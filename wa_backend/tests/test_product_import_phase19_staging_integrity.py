"""Fail-closed V1 Product Import staging guards for short database writes."""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from domains.simple_products.imports.application import (
    staging_service,
)
from domains.simple_products.imports.domain import (
    ProductImportTerminalError,
)
from domains.simple_products.imports.infrastructure.parsers import (
    ParsedRow,
)
from domains.simple_products.imports.infrastructure.repository import (
    insert_staged_rows,
)


class StageIntegrityTests(unittest.IsolatedAsyncioTestCase):
    async def test_staging_uses_bounded_single_statement_batches(
        self,
    ) -> None:
        db = AsyncMock()
        result = await insert_staged_rows(
            db,
            company_id=38,
            job_id=uuid4(),
            rows=(
                ParsedRow(
                    row_number=2 + index,
                    raw={"Product": f"Item {index}"},
                )
                for index in range(1_200)
            ),
            batch_size=500,
            max_rows=50_000,
        )

        self.assertEqual(result, 1_200)
        self.assertEqual(db.execute.await_count, 3)
        self.assertTrue(
            all(
                len(call.args) == 1
                for call in db.execute.await_args_list
            ),
            "Do not pass executemany parameter lists to asyncpg.",
        )
        self.assertEqual(
            [
                len(call.args[0]._multi_values[0])
                for call in db.execute.await_args_list
            ],
            [500, 500, 200],
        )

    async def test_staging_batch_trace_contains_only_safe_numeric_progress(self) -> None:
        db = AsyncMock()
        job_id = uuid4()
        with self.assertLogs("wanasah_logger", level="INFO") as logs:
            result = await insert_staged_rows(
                db,
                company_id=38,
                job_id=job_id,
                rows=(
                    ParsedRow(row_number=2 + index, raw={
                        "Name": "PRIVATE CUSTOMER PRODUCT DO NOT LOG",
                    })
                    for index in range(3)
                ),
                batch_size=2,
                max_rows=50_000,
            )
        self.assertEqual(result, 3)
        combined = "\n".join(logs.output)
        self.assertEqual(combined.count("PRODUCT_IMPORT_STAGING_BATCH_BEGIN"), 2)
        self.assertEqual(combined.count("phase=STAGING_SQL"), 2)
        self.assertEqual(combined.count("outcome=returned"), 2)
        self.assertIn("batch_index=2 candidate_rows=1", combined)
        self.assertIn("first_source_row=4 last_source_row=4", combined)
        self.assertNotIn("PRIVATE CUSTOMER PRODUCT", combined)

    async def test_staging_failed_insert_has_interrupted_marker_without_source_data(self) -> None:
        db = AsyncMock()
        db.execute.side_effect = RuntimeError("PRIVATE CUSTOMER PRODUCT")
        with self.assertLogs("wanasah_logger", level="INFO") as logs:
            with self.assertRaises(RuntimeError):
                await insert_staged_rows(
                    db,
                    company_id=38,
                    job_id=uuid4(),
                    rows=[ParsedRow(row_number=14, raw={
                        "Name": "PRIVATE CUSTOMER PRODUCT",
                    })],
                    batch_size=500,
                    max_rows=50_000,
                )
        combined = "\n".join(logs.output)
        self.assertIn("PRODUCT_IMPORT_STAGING_BATCH_BEGIN", combined)
        self.assertIn("first_source_row=14 last_source_row=14", combined)
        self.assertIn("phase=STAGING_SQL outcome=interrupted", combined)
        self.assertNotIn("PRIVATE CUSTOMER PRODUCT", combined)

    async def _run_with_persisted_count(
        self,
        *,
        persisted: int,
    ) -> tuple[AsyncMock, AsyncMock]:
        db = AsyncMock()
        insert = AsyncMock(return_value=1_000)
        count = AsyncMock(return_value=persisted)

        with (
            patch.object(
                staging_service,
                "open_tenant_session",
                new=AsyncMock(return_value=(object(), db)),
            ),
            patch.object(
                staging_service,
                "close_tenant_session",
                new=AsyncMock(),
            ),
            patch.object(
                staging_service,
                "delete_job_rows",
                new=AsyncMock(),
            ),
            patch.object(
                staging_service,
                "insert_staged_rows",
                new=insert,
            ),
            patch.object(
                staging_service,
                "count_job_rows",
                new=count,
            ),
            patch.object(
                staging_service,
                "load_job",
                new=AsyncMock(return_value=None),
            ),
        ):
            with self.assertRaises(
                (ProductImportTerminalError, ValueError),
            ) as failure:
                await staging_service.stage_source(
                    company_id=38,
                    job_id=uuid4(),
                    headers=["Product"],
                    rows=iter(()),
                    suggestions={"name": "Product"},
                )
            if persisted != 1_000:
                self.assertIsInstance(
                    failure.exception,
                    ProductImportTerminalError,
                )
                self.assertIn(
                    "Staging row-count mismatch",
                    str(failure.exception),
                )
                db.commit.assert_not_awaited()
                db.rollback.assert_awaited_once()
            else:
                # The mocked job is absent only after the stage count
                # check: a complete staging count can advance to job load.
                self.assertIsInstance(
                    failure.exception,
                    ValueError,
                )

            self.assertEqual(
                insert.await_args.kwargs["batch_size"],
                500,
            )
            count.assert_awaited_once()
            self.assertEqual(
                count.await_args.kwargs["status"],
                "STAGED",
            )
            return insert, count

    async def test_short_insert_rolls_back_before_source_release(
        self,
    ) -> None:
        await self._run_with_persisted_count(
            persisted=937,
        )

    async def test_complete_insert_advances_past_count_gate(
        self,
    ) -> None:
        await self._run_with_persisted_count(
            persisted=1_000,
        )



class StagingRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_deadline_aborts_transport_before_driver_cancel_wait(self):
        import asyncio
        from types import SimpleNamespace
        from domains.simple_products.imports.infrastructure import staging_io
        from domains.simple_products.imports.domain.errors import (
            ProductImportStagingTimeoutError, classify_import_error,
        )
        released = asyncio.Event()
        order = []
        class Driver:
            def terminate(self):
                order.append("terminate")
                released.set()
        guard = staging_io.StagingIOGuard(company_id=38, job_id=uuid4())
        async def stalled():
            staging_io._capture_staging_connection(
                SimpleNamespace(driver_connection=Driver()), SimpleNamespace(info={}), None,
            )
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                order.append("cancel_wait")
                await released.wait()  # Models an unresponsive cancel channel.
                raise
        with patch.object(staging_io, "STAGING_IO_TIMEOUT_SECONDS", 0.02):
            with self.assertRaises(ProductImportStagingTimeoutError) as failure:
                await asyncio.wait_for(guard.run(stalled(), operation="staging_batch"), timeout=1)
        self.assertEqual(order, ["terminate", "cancel_wait"])
        self.assertTrue(classify_import_error(failure.exception).retryable)
        self.assertEqual(classify_import_error(failure.exception).code, "PRODUCT_IMPORT_STAGING_TIMEOUT")


    async def test_terminate_failure_still_cancels_task_without_logging_private_driver_error(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import Mock
        from domains.simple_products.imports.infrastructure import staging_io
        from domains.simple_products.imports.domain.errors import ProductImportStagingTimeoutError

        guard = staging_io.StagingIOGuard(company_id=38, job_id=uuid4())
        private_message = "PRIVATE CUSTOMER SQL AND BARCODE"
        driver = Mock()
        driver.terminate.side_effect = RuntimeError(private_message)
        stopped = asyncio.Event()

        async def stalled():
            staging_io._capture_staging_connection(
                SimpleNamespace(driver_connection=driver),
                SimpleNamespace(info={}),
                None,
            )
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        with (
            patch.object(staging_io, "STAGING_IO_TIMEOUT_SECONDS", 0.02),
            self.assertLogs("wanasah_logger", level="WARNING") as logs,
        ):
            with self.assertRaises(ProductImportStagingTimeoutError):
                await asyncio.wait_for(
                    guard.run(stalled(), operation="staging_batch"),
                    timeout=1,
                )

        self.assertTrue(stopped.is_set(), "Failed terminate must not orphan a running task.")
        driver.terminate.assert_called_once()
        output = "\n".join(logs.output)
        self.assertIn("PRODUCT_IMPORT_STAGING_IO_TERMINATE_FAILED", output)
        self.assertIn("PRODUCT_IMPORT_STAGING_IO_ABORT", output)
        self.assertNotIn(private_message, output)

    async def test_returned_connection_cannot_be_aborted_after_another_tenant_borrows_it(self):
        from types import SimpleNamespace
        from unittest.mock import Mock
        from domains.simple_products.imports.infrastructure import staging_io
        record = SimpleNamespace(info={})
        driver = Mock()
        dbapi = SimpleNamespace(driver_connection=driver)
        first = staging_io.StagingIOGuard(company_id=38, job_id=uuid4())
        second = staging_io.StagingIOGuard(company_id=99, job_id=uuid4())
        async def checkout():
            staging_io._capture_staging_connection(dbapi, record, None)
        await first.run(checkout(), operation="tenant_setup")
        staging_io._release_staging_connection(dbapi, record)
        await second.run(checkout(), operation="tenant_setup")
        first.abort(operation="late_cancel")
        driver.terminate.assert_not_called()
        self.assertIsNone(first.driver_connection)
        self.assertIs(second.driver_connection, driver)
        staging_io._release_staging_connection(dbapi, record)

    async def test_setup_capture_is_scoped_and_releases_tenant_context(self):
        import asyncio
        from types import SimpleNamespace
        from unittest.mock import Mock
        from context import tenant_context
        from domains.simple_products.imports.infrastructure import repository, staging_io
        baseline = tenant_context.get()
        from database import on_checkout
        listeners = list(staging_io.engine.sync_engine.pool.dispatch.checkout)
        self.assertLess(listeners.index(staging_io._capture_staging_connection), listeners.index(on_checkout))
        guard = staging_io.StagingIOGuard(company_id=38, job_id=uuid4())
        driver = Mock()
        db = AsyncMock()
        async def setup(*args, **kwargs):
            self.assertEqual(tenant_context.get(), 38)
            staging_io._capture_staging_connection(SimpleNamespace(driver_connection=driver), SimpleNamespace(info={}), None)
            await asyncio.Event().wait()
        db.execute.side_effect = setup
        with patch.object(repository, "AsyncSessionLocal", return_value=db), \
             patch.object(staging_io, "STAGING_IO_TIMEOUT_SECONDS", 0.02):
            with self.assertRaises(TimeoutError):
                await repository.open_tenant_session(38, io_guard=guard)
        driver.terminate.assert_called_once()
        db.invalidate.assert_awaited_once()
        self.assertEqual(tenant_context.get(), baseline)
        # Non-staging checkout does not attach another tenant's connection.
        staging_io._capture_staging_connection(SimpleNamespace(driver_connection=object()), SimpleNamespace(info={}), None)
        self.assertIs(guard.driver_connection, driver)
        late_driver = Mock()
        async def late_checkout():
            staging_io._capture_staging_connection(SimpleNamespace(driver_connection=late_driver), SimpleNamespace(info={}), None)
        with self.assertRaises(TimeoutError):
            await guard.run(late_checkout(), operation="late_cleanup", cleanup=True)
        late_driver.terminate.assert_called_once()

    async def _interrupted_source(self, *, cancel=False, stuck_rollback=False):
        import asyncio
        import hashlib
        from types import SimpleNamespace
        from unittest.mock import Mock
        from context import tenant_context
        from domains.simple_products.imports.application import source_service
        from domains.simple_products.imports.infrastructure import staging_io
        from domains.simple_products.imports.domain.errors import ProductImportStagingTimeoutError
        payload = b"Product,Price\nFirst,1\nSecond,2\n"
        job_id, source_id = uuid4(), uuid4()
        context = source_service.ProductImportSourceContext(
            source_id=source_id, source_size=len(payload),
            source_sha256=hashlib.sha256(payload).hexdigest(), source_cleared=False,
            file_name="synthetic.csv", status="PARSING",
        )
        store = AsyncMock()
        store.read_verified_bytes.return_value = payload
        db = AsyncMock()
        driver = Mock()
        blocked = asyncio.Event()
        calls = 0
        buffers = []
        actual_spool = source_service.spool_stage_rows
        async def spool(*args, **kwargs):
            buffered = await actual_spool(*args, **kwargs)
            buffers.append(buffered)
            return buffered
        async def open_session(*args, **kwargs):
            return tenant_context.set(38), db
        async def execute(*args, **kwargs):
            nonlocal calls
            calls += 1
            staging_io._capture_staging_connection(SimpleNamespace(driver_connection=driver), SimpleNamespace(info={}), None)
            if calls == 2:
                blocked.set()
                await asyncio.Event().wait()
        db.execute.side_effect = execute
        if stuck_rollback:
            async def rollback():
                await asyncio.Event().wait()
            db.rollback.side_effect = rollback
        baseline = tenant_context.get()
        with patch.object(source_service, "_load_source_context", AsyncMock(return_value=context)), \
             patch.object(source_service, "set_job_status", AsyncMock(return_value="PARSING")), \
             patch.object(source_service, "spool_stage_rows", spool), \
             patch.object(staging_service, "open_tenant_session", open_session), \
             patch.object(staging_service, "delete_job_rows", AsyncMock()), \
             patch.object(staging_service, "count_job_rows", AsyncMock()) as count, \
             patch.object(staging_service, "STAGE_BATCH", 1), \
             patch.object(staging_io, "STAGING_IO_TIMEOUT_SECONDS", 0.05), \
             patch.object(staging_io, "STAGING_CLEANUP_TIMEOUT_SECONDS", 0.02), \
             self.assertLogs("wanasah_logger", level="INFO") as logs:
            task = asyncio.create_task(source_service.prepare_import_source(
                company_id=38, job_id=job_id, source_store=store,
            ))
            if cancel:
                await asyncio.wait_for(blocked.wait(), timeout=1)
                task.cancel()
            with self.assertRaises(asyncio.CancelledError if cancel else ProductImportStagingTimeoutError):
                await asyncio.wait_for(task, timeout=1)
        self.assertEqual(calls, 2)  # One earlier batch returned, no batch committed.
        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()
        db.invalidate.assert_awaited_once()
        count.assert_not_awaited()
        driver.terminate.assert_called_once()
        store.delete_source_bytes.assert_not_awaited()
        self.assertTrue(buffers[0].stream.closed)
        self.assertEqual(tenant_context.get(), baseline)
        combined = "\n".join(logs.output)
        self.assertIn("batch_index=2 candidate_rows=1", combined)
        self.assertIn("phase=STAGING_SQL outcome=interrupted", combined)
        self.assertNotIn("First", combined)
        self.assertNotIn("Second", combined)

    async def test_staging_timeout_and_stuck_rollback_retain_source(self):
        await self._interrupted_source(stuck_rollback=True)

    async def test_task_cancellation_rolls_back_without_clearing_source(self):
        await self._interrupted_source(cancel=True)

    async def test_lost_commit_response_resumes_durable_state_without_restaging(self):
        import asyncio
        from unittest.mock import Mock
        from domains.simple_products.imports.application import source_service
        from domains.simple_products.imports.infrastructure import staging_io
        from domains.simple_products.imports.domain.errors import ProductImportStagingTimeoutError
        guard = staging_io.StagingIOGuard(company_id=38, job_id=uuid4())
        guard.driver_connection = Mock()
        durable = {"status": "PARSING"}
        async def lost_commit_response():
            durable["status"] = "VALIDATING"  # Commit succeeded before response loss.
            await asyncio.Event().wait()
        with patch.object(staging_io, "STAGING_IO_TIMEOUT_SECONDS", 0.02):
            with self.assertRaises(ProductImportStagingTimeoutError):
                await guard.run(lost_commit_response(), operation="commit_staging")
        context = source_service.ProductImportSourceContext(
            source_id=uuid4(), source_size=10, source_sha256="a" * 64,
            source_cleared=False, file_name="synthetic.csv", status=durable["status"],
        )
        store = AsyncMock()
        with patch.object(source_service, "_load_source_context", AsyncMock(return_value=context)), \
             patch.object(source_service, "_runtime_state", AsyncMock(return_value=("VALIDATING", True))), \
             patch.object(source_service, "_mark_source_cleaned", AsyncMock()) as marker, \
             patch.object(source_service, "stage_source", AsyncMock(side_effect=AssertionError("must not restage"))) as stage:
            result = await source_service.prepare_import_source(
                company_id=38, job_id=guard.job_id, source_store=store,
            )
        self.assertEqual(result, "VALIDATING")
        stage.assert_not_awaited()
        store.read_verified_bytes.assert_not_awaited()
        store.delete_source_bytes.assert_awaited_once()
        marker.assert_awaited_once()

if __name__ == "__main__":
    unittest.main()
