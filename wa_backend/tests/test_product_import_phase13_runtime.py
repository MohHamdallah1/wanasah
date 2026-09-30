from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from domains.simple_products.imports.application.cancellation_service import (
    cancel_import_job,
)
from domains.simple_products.imports.application.execution_service import (
    _execute_rows_once,
)
from domains.simple_products.imports.application.source_service import (
    ProductImportSourceContext,
    prepare_import_source,
)
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    ProductImportStateTransitionError,
    transition_job,
)
from domains.simple_products.imports.application.worker import (
    run_product_import_job,
)
from domains.simple_products.imports.domain.admission import (
    ProductImportAdmissionPolicy,
)
from domains.simple_products.imports.infrastructure.admission_repository import (
    _ACTIVE_JOB_STATUSES,
)
from domains.simple_products.imports.infrastructure.queue import (
    defer_import_on_connection,
    process_product_import,
)
from domains.simple_products.imports.infrastructure.realtime_manager import (
    ProductImportConnectionManager,
)
from domains.simple_products.imports.infrastructure.realtime_relay import (
    ProductImportEventRelay,
    _parse_event,
)
from workers.recovery import (
    recover_safe_stalled_jobs,
)


class _FakeWebSocket:
    def __init__(self) -> None:
        self.accepted = False
        self.closed_code: int | None = None
        self.sent: list[dict[str, object]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def close(
        self,
        *,
        code: int,
    ) -> None:
        self.closed_code = int(code)

    async def send_json(
        self,
        payload: dict[str, object],
    ) -> None:
        self.sent.append(
            dict(
                payload
            )
        )


class Phase13StateAndBackpressureTests(
    unittest.TestCase
):
    def test_all_active_states_can_cancel_and_cancelled_is_terminal(
        self,
    ) -> None:
        active = (
            JobStatus.QUEUED,
            JobStatus.PARSING,
            JobStatus.NEEDS_MAPPING,
            JobStatus.VALIDATING,
            JobStatus.IMPORTING,
            JobStatus.RETRYING,
        )
        for state in active:
            with self.subTest(
                state=state.value
            ):
                job = SimpleNamespace(
                    status=state.value,
                    version=1,
                    updated_at=None,
                )
                transition_job(
                    job,
                    JobStatus.CANCELLED,
                )
                self.assertEqual(
                    job.status,
                    JobStatus.CANCELLED.value,
                )

        cancelled = SimpleNamespace(
            status=JobStatus.CANCELLED.value,
            version=1,
            updated_at=None,
        )
        with self.assertRaises(
            ProductImportStateTransitionError
        ):
            transition_job(
                cancelled,
                JobStatus.IMPORTING,
            )

    def test_active_import_backpressure_counts_all_nonterminal_work(
        self,
    ) -> None:
        self.assertEqual(
            set(
                _ACTIVE_JOB_STATUSES
            ),
            {
                "QUEUED",
                "PARSING",
                "NEEDS_MAPPING",
                "VALIDATING",
                "IMPORTING",
                "RETRYING",
            },
        )
        self.assertGreater(
            ProductImportAdmissionPolicy().max_active_jobs_per_tenant,
            0,
        )


class Phase13CancellationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_cancel_takes_job_row_lock_and_commits_terminal_state(
        self,
    ) -> None:
        job = SimpleNamespace(
            status=JobStatus.IMPORTING.value,
            version=7,
            updated_at=None,
            finished_at=None,
            error_summary={},
        )
        db = SimpleNamespace(
            commit=AsyncMock(),
            rollback=AsyncMock(),
        )
        token = object()
        load_job = AsyncMock(
            return_value=job
        )
        with (
            patch(
                "domains.simple_products.imports.application.cancellation_service.open_tenant_session",
                AsyncMock(
                    return_value=(
                        token,
                        db,
                    )
                ),
            ),
            patch(
                "domains.simple_products.imports.application.cancellation_service.load_job",
                load_job,
            ),
            patch(
                "domains.simple_products.imports.application.cancellation_service.close_tenant_session",
                AsyncMock(),
            ),
        ):
            status = await cancel_import_job(
                company_id=9,
                job_id=uuid4(),
            )

        self.assertEqual(
            status,
            JobStatus.CANCELLED.value,
        )
        self.assertEqual(
            job.status,
            JobStatus.CANCELLED.value,
        )
        self.assertEqual(
            job.error_summary[
                "code"
            ],
            "PRODUCT_IMPORT_CANCELLED",
        )
        db.commit.assert_awaited_once()
        load_job.assert_awaited_once()
        self.assertTrue(
            load_job.await_args.kwargs[
                "for_update"
            ]
        )


    async def test_cancelled_queued_delivery_releases_retained_source(
        self,
    ) -> None:
        source_id = uuid4()
        job_id = uuid4()
        store = SimpleNamespace(
            delete_source_bytes=
                AsyncMock()
        )
        with (
            patch(
                "domains.simple_products.imports.application.source_service._load_source_context",
                AsyncMock(
                    return_value=
                        ProductImportSourceContext(
                                        source_id=source_id,
                            source_size=128,
                            source_sha256="a" * 64,
                            source_cleared=False,
                            file_name="products.csv",
                            status=
                                JobStatus.CANCELLED.value,
                        )
                ),
            ),
            patch(
                "domains.simple_products.imports.application.source_service._mark_source_cleaned",
                AsyncMock(),
            ) as mark_cleaned,
        ):
            status = await prepare_import_source(
                company_id=11,
                job_id=job_id,
                source_store=store,
            )

        self.assertEqual(
            status,
            JobStatus.CANCELLED.value,
        )
        store.delete_source_bytes.assert_awaited_once_with(
            company_id=11,
            source_id=source_id,
        )
        mark_cleaned.assert_awaited_once_with(
            company_id=11,
            job_id=job_id,
        )


class Phase13QueueSerializationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_company_scoped_execution_lock_is_retained(
        self,
    ) -> None:
        deferred = AsyncMock()
        configured = SimpleNamespace(
            defer_async=deferred
        )
        connection = object()
        with patch.object(
            process_product_import,
            "configure",
            return_value=configured,
        ) as configure:
            job_id = uuid4()
            await defer_import_on_connection(
                connection,
                company_id=17,
                job_id=job_id,
            )

        configure.assert_called_once_with(
            connection=connection,
            lock="product-import:17",
            queueing_lock=f"product-import-job:{job_id}",
        )
        deferred.assert_awaited_once_with(
            company_id=17,
            job_id=str(
                job_id
            ),
        )


class Phase13RealtimeTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_connection_broadcast_is_exact_job_scoped(
        self,
    ) -> None:
        manager = (
            ProductImportConnectionManager()
        )
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        first_job = uuid4()
        second_job = uuid4()

        self.assertTrue(
            await manager.connect(
                first,
                company_id=7,
                job_id=first_job,
            )
        )
        self.assertTrue(
            await manager.connect(
                second,
                company_id=7,
                job_id=second_job,
            )
        )

        payload = {
            "event":
                "PRODUCT_IMPORT_PROGRESS",
            "job_id":
                str(
                    first_job
                ),
        }
        await manager.broadcast(
            payload,
            company_id=7,
            job_id=first_job,
        )

        self.assertEqual(
            first.sent,
            [
                payload
            ],
        )
        self.assertEqual(
            second.sent,
            [],
        )

    async def test_connection_backpressure_fails_closed(
        self,
    ) -> None:
        manager = (
            ProductImportConnectionManager()
        )
        first = _FakeWebSocket()
        second = _FakeWebSocket()
        job_id = uuid4()

        with patch(
            "domains.simple_products.imports.infrastructure.realtime_manager.MAX_JOB_CONNECTIONS",
            1,
        ):
            self.assertTrue(
                await manager.connect(
                    first,
                    company_id=7,
                    job_id=job_id,
                )
            )
            self.assertFalse(
                await manager.connect(
                    second,
                    company_id=7,
                    job_id=job_id,
                )
            )

        self.assertEqual(
            second.closed_code,
            1013,
        )

    async def test_progress_relay_coalesces_to_latest_job_version(
        self,
    ) -> None:
        relay = (
            ProductImportEventRelay()
        )
        job_id = uuid4()

        def payload(
            version: int,
        ) -> str:
            return (
                "{"
                f'"event":"PRODUCT_IMPORT_PROGRESS",'
                f'"company_id":4,'
                f'"job_id":"{job_id}",'
                f'"status":"IMPORTING",'
                f'"version":{version},'
                '"total_rows":10,'
                f'"processed_rows":{version},'
                '"valid_rows":10,'
                '"failed_rows":0'
                "}"
            )

        relay._queue.put_nowait(
            payload(
                2
            )
        )
        broadcast = AsyncMock()
        with (
            patch(
                "domains.simple_products.imports.infrastructure.realtime_relay.asyncio.sleep",
                AsyncMock(),
            ),
            patch(
                "domains.simple_products.imports.infrastructure.realtime_relay.product_import_connection_manager.broadcast",
                broadcast,
            ),
        ):
            await relay._flush_batch(
                payload(
                    1
                )
            )

        broadcast.assert_awaited_once()
        outbound = (
            broadcast.await_args.args[
                0
            ]
        )
        self.assertEqual(
            outbound[
                "version"
            ],
            2,
        )
        self.assertEqual(
            outbound[
                "processed_rows"
            ],
            2,
        )

    def test_progress_parser_rejects_missing_tenant_job_scope(
        self,
    ) -> None:
        self.assertIsNone(
            _parse_event(
                '{"event":"PRODUCT_IMPORT_PROGRESS","job_id":"'
                + str(
                    uuid4()
                )
                + '"}'
            )
        )


class Phase13RecoveryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_stalled_product_import_delivery_is_retried(
        self,
    ) -> None:
        stalled = SimpleNamespace(
            id=44,
            task_name=
                "wanasah.process_product_import",
            queueing_lock=None,
        )
        manager = SimpleNamespace(
            prune_stalled_workers=AsyncMock(
                return_value=[
                    3
                ]
            ),
            get_stalled_jobs=AsyncMock(
                return_value=[
                    stalled
                ]
            ),
            retry_job=AsyncMock(),
            finish_job_by_id_async=AsyncMock(),
        )
        result = await recover_safe_stalled_jobs(
            SimpleNamespace(
                job_manager=
                    manager
            ),
            allowlist={
                "wanasah.process_product_import"
            },
            seconds_since_heartbeat=
                30,
        )

        self.assertEqual(
            result[
                "retried"
            ],
            1,
        )
        manager.retry_job.assert_awaited_once_with(
            stalled
        )

    async def test_worker_restart_resumes_durable_importing_state(
        self,
    ) -> None:
        execute = AsyncMock()
        validate = AsyncMock()
        with (
            patch(
                "domains.simple_products.imports.application.worker.prepare_import_source",
                AsyncMock(
                    return_value=
                        JobStatus.IMPORTING.value
                ),
            ),
            patch(
                "domains.simple_products.imports.application.worker.validate_rows",
                validate,
            ),
            patch(
                "domains.simple_products.imports.application.worker.execute_import",
                execute,
            ),
        ):
            job_id = uuid4()
            await run_product_import_job(
                company_id=5,
                job_id=job_id,
                source_store=
                    SimpleNamespace(),
            )

        validate.assert_not_awaited()
        execute.assert_awaited_once_with(
            company_id=5,
            job_id=job_id,
        )


class Phase13DuplicateDeliveryTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_duplicate_delivery_replays_durable_row_result_without_create(
        self,
    ) -> None:
        identity = uuid4()
        row = SimpleNamespace(
            row_identity=identity,
            row_number=2,
            normalized_data={
                "name": "Tea",
                "family_name": None,
                "package_uom_code": None,
                "units_per_package": 1,
                "package_price": None,
                "unit_price": "1.000",
                "unit_barcode": None,
                "package_barcode": None,
                "lot_control_mode": "NONE",
                "expiry_control_mode": "NONE",
            },
            status="VALID",
            product_variant_id=None,
            error_code=None,
            error_message=None,
            version=1,
        )
        create = AsyncMock()
        with (
            patch(
                "domains.simple_products.imports.application.execution_service.begin_idempotent_operation",
                AsyncMock(
                    return_value=(
                        SimpleNamespace(),
                        {
                            "rows": [
                                {
                                    "row_identity":
                                        str(
                                            identity
                                        ),
                                    "product_variant_id":
                                        501,
                                }
                            ]
                        },
                    )
                ),
            ),
            patch(
                "domains.simple_products.imports.application.execution_service.create_products_and_prices",
                create,
            ),
        ):
            await _execute_rows_once(
                object(),
                actor=SimpleNamespace(
                    id=1,
                    company_id=8,
                ),
                job_id=uuid4(),
                rows=[
                    row
                ],
            )

        create.assert_not_awaited()
        self.assertEqual(
            row.product_variant_id,
            501,
        )
        self.assertEqual(
            row.status,
            "IMPORTED",
        )


if __name__ == "__main__":
    unittest.main()
