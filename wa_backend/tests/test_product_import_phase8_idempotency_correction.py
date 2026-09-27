from __future__ import annotations

import asyncio
import csv
from io import StringIO
import os
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import psycopg
from dotenv import load_dotenv
from psycopg.errors import CheckViolation
from sqlalchemy.engine import make_url

from database import engine
from domains.simple_products.imports.application.correction_service import (
    CORRECTION_IDENTITY_HEADER,
    build_correction_artifact,
    parse_correction_payload,
)
from domains.simple_products.imports.application.validation_service import (
    validation_outcome,
)
from domains.simple_products.imports.application.execution_service import (
    _batch_request_hash,
    _batch_request_id,
    _execute_rows_once,
)
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    RowStatus,
)
from domains.simple_products.imports.infrastructure.correction_repository import (
    apply_correction_and_requeue,
)


load_dotenv()


def _run_async(coro):
    with asyncio.Runner(
        loop_factory=
            asyncio.SelectorEventLoop
    ) as runner:
        return runner.run(
            coro
        )


def _owner_dsn() -> str:
    raw = (
        os.getenv("DATABASE_URL_MIGRATION")
        or os.getenv("DATABASE_URL")
    )
    if not raw:
        raise RuntimeError(
            "Database URL is required for Phase 8 integration tests."
        )
    return (
        make_url(raw)
        .set(drivername="postgresql")
        .render_as_string(
            hide_password=False
        )
    )


def _normalized(
    name: str,
) -> dict[str, object]:
    return {
        "name": name,
        "family_name": None,
        "package_uom_code": None,
        "units_per_package": 1,
        "package_price": None,
        "unit_price": "1.000",
        "unit_barcode": None,
        "package_barcode": None,
        "lot_control_mode": "NONE",
        "expiry_control_mode": "NONE",
    }


def _fake_row(
    *,
    identity: UUID,
    row_number: int,
    name: str,
):
    return SimpleNamespace(
        row_identity=identity,
        row_number=row_number,
        normalized_data=_normalized(
            name
        ),
        status=RowStatus.VALID.value,
        product_variant_id=None,
        error_code=None,
        error_message=None,
        version=1,
    )


class Phase8CorrectionContractTests(
    unittest.TestCase
):
    def test_prior_imported_success_keeps_correction_terminal_as_completed_with_errors(
        self,
    ) -> None:
        self.assertEqual(
            validation_outcome(
                0,
                2,
                imported_count=3,
                import_failed_count=0,
            ),
            (
                JobStatus.COMPLETED_WITH_ERRORS.value,
                False,
            ),
        )

    def test_correction_parser_allows_reserved_metadata_beyond_100_source_columns(
        self,
    ) -> None:
        source_headers = [
            f"Column {index}"
            for index in range(
                1,
                101,
            )
        ]
        identity = uuid4()
        output = StringIO(
            newline=""
        )
        writer = csv.writer(
            output
        )
        writer.writerow(
            [
                "__wanasah_row_identity",
                "__wanasah_original_row",
                "__wanasah_error_code",
                "__wanasah_error_field",
                "__wanasah_error_message",
                *source_headers,
            ]
        )
        writer.writerow(
            [
                str(
                    identity
                ),
                "2",
                "BAD_ROW",
                "",
                "Bad row",
                *[
                    f"value-{index}"
                    for index
                    in range(
                        1,
                        101,
                    )
                ],
            ]
        )

        patches = parse_correction_payload(
            file_name=
                "correction.csv",
            payload=(
                "\ufeff"
                + output.getvalue()
            ).encode(
                "utf-8"
            ),
            source_headers=
                source_headers,
        )

        self.assertEqual(
            len(
                patches
            ),
            1,
        )
        self.assertEqual(
            patches[0].row_identity,
            identity,
        )
        self.assertEqual(
            len(
                patches[0].raw_data
            ),
            100,
        )


class Phase8ExecutionIdempotencyTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_crash_replay_uses_durable_idempotency_result_without_duplicate_create(
        self,
    ) -> None:
        job_id = uuid4()
        identity = uuid4()
        row = _fake_row(
            identity=identity,
            row_number=2,
            name="Tea",
        )

        begin = AsyncMock(
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
                                777,
                        }
                    ]
                },
            )
        )
        create = AsyncMock()

        with (
            patch(
                "domains.simple_products.imports.application.execution_service.begin_idempotent_operation",
                begin,
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
                    company_id=7,
                ),
                job_id=job_id,
                rows=[
                    row
                ],
            )

        create.assert_not_awaited()
        self.assertEqual(
            row.status,
            RowStatus.IMPORTED.value,
        )
        self.assertEqual(
            row.product_variant_id,
            777,
        )

    async def test_duplicate_queue_delivery_replays_same_row_identity_and_creates_once(
        self,
    ) -> None:
        job_id = uuid4()
        identity = uuid4()
        stored: dict[
            str,
            object
        ] = {}

        async def begin(
            *_args,
            **_kwargs,
        ):
            replay = stored.get(
                "response"
            )
            return (
                SimpleNamespace(),
                replay,
            )

        def complete(
            _record,
            response,
        ) -> None:
            stored[
                "response"
            ] = dict(
                response
            )

        create = AsyncMock(
            return_value=[
                (
                    SimpleNamespace(
                        id=901
                    ),
                    object(),
                )
            ]
        )

        first = _fake_row(
            identity=identity,
            row_number=2,
            name="Tea",
        )
        second = _fake_row(
            identity=identity,
            row_number=999,
            name="Tea",
        )

        with (
            patch(
                "domains.simple_products.imports.application.execution_service.begin_idempotent_operation",
                begin,
            ),
            patch(
                "domains.simple_products.imports.application.execution_service.complete_idempotent_operation",
                complete,
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
                    company_id=7,
                ),
                job_id=job_id,
                rows=[
                    first
                ],
            )
            await _execute_rows_once(
                object(),
                actor=SimpleNamespace(
                    id=1,
                    company_id=7,
                ),
                job_id=job_id,
                rows=[
                    second
                ],
            )

        self.assertEqual(
            create.await_count,
            1,
        )
        self.assertEqual(
            second.status,
            RowStatus.IMPORTED.value,
        )
        self.assertEqual(
            second.product_variant_id,
            901,
        )

    def test_request_identity_depends_on_job_and_immutable_row_identity_not_row_number(
        self,
    ) -> None:
        job_id = uuid4()
        identity = uuid4()
        first = _fake_row(
            identity=identity,
            row_number=2,
            name="Tea",
        )
        same_identity = _fake_row(
            identity=identity,
            row_number=50_001,
            name="Tea",
        )

        self.assertEqual(
            _batch_request_id(
                job_id,
                [
                    first
                ],
            ),
            _batch_request_id(
                job_id,
                [
                    same_identity
                ],
            ),
        )
        self.assertEqual(
            _batch_request_hash(
                [
                    first
                ]
            ),
            _batch_request_hash(
                [
                    same_identity
                ]
            ),
        )


class Phase8CorrectionIntegrationTests(
    unittest.TestCase
):
    def setUp(self) -> None:
        self.owner_dsn = (
            _owner_dsn()
        )
        self.job_id = uuid4()
        self.imported_guard_job_id = (
            uuid4()
        )
        self.request_ids: list[
            UUID
        ] = []

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            fixture = conn.execute(
                """
                SELECT
                    variants.company_id,
                    drivers.id
                FROM product_variants AS variants
                JOIN drivers
                  ON drivers.company_id = variants.company_id
                 AND drivers.is_active IS TRUE
                ORDER BY variants.id
                LIMIT 1
                """
            ).fetchone()
            if fixture is None:
                self.fail(
                    "Phase 8 integration test requires one Product variant and active driver."
                )

            (
                self.company_id,
                self.driver_id,
            ) = map(
                int,
                fixture,
            )

            for job_id in (
                self.job_id,
                self.imported_guard_job_id,
            ):
                conn.execute(
                    """
                    INSERT INTO product_import_jobs (
                        id,
                        company_id,
                        request_id,
                        created_by,
                        file_name,
                        content_type,
                        source_payload,
                        source_sha256,
                        file_size,
                        status,
                        detected_headers,
                        suggested_mapping,
                        column_mapping,
                        default_lot_control_mode,
                        default_expiry_control_mode,
                        error_summary,
                        total_rows,
                        processed_rows,
                        valid_rows,
                        failed_rows,
                        version
                    )
                    VALUES (
                        %s,%s,%s,%s,
                        'phase8.csv',
                        'text/csv',
                        NULL,
                        %s,
                        1,
                        'COMPLETED_WITH_ERRORS',
                        '["Product","Unit Price"]'::jsonb,
                        '{}'::jsonb,
                        '{"name":"Product","unit_price":"Unit Price"}'::jsonb,
                        'NONE',
                        'NONE',
                        '{}'::jsonb,
                        3,1,2,1,1
                    )
                    """,
                    (
                        job_id,
                        self.company_id,
                        uuid4(),
                        self.driver_id,
                        uuid4().hex.ljust(
                            64,
                            "0",
                        )[:64],
                    ),
                )

                conn.execute(
                    """
                    INSERT INTO product_import_rows (
                        company_id,
                        job_id,
                        row_number,
                        raw_data,
                        normalized_data,
                        status,
                        error_code,
                        error_message,
                        version
                    )
                    VALUES
                    (
                        %s,%s,2,
                        '{"Product":"Already","Unit Price":"1.000"}'::jsonb,
                        '{}'::jsonb,
                        'IMPORTED',
                        NULL,NULL,1
                    ),
                    (
                        %s,%s,3,
                        '{"Product":"","Unit Price":"2.000"}'::jsonb,
                        '{}'::jsonb,
                        'INVALID',
                        'IMPORT_NAME_REQUIRED',
                        'Product name is required.',
                        1
                    ),
                    (
                        %s,%s,4,
                        '{"Product":"Conflict","Unit Price":"3.000"}'::jsonb,
                        '{}'::jsonb,
                        'IMPORT_FAILED',
                        'IMPORT_BARCODE_CONFLICT',
                        'Barcode is already active.',
                        1
                    )
                    """,
                    (
                        self.company_id,
                        job_id,
                        self.company_id,
                        job_id,
                        self.company_id,
                        job_id,
                    ),
                )

        self.addCleanup(
            self._cleanup
        )

    def _cleanup(self) -> None:
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            conn.execute(
                """
                DELETE FROM operation_idempotency
                WHERE company_id = %s
                  AND operation = 'PRODUCT_IMPORT_CORRECTION'
                  AND request_id = ANY(%s)
                """,
                (
                    self.company_id,
                    [
                        str(
                            request_id
                        )
                        for request_id
                        in self.request_ids
                    ]
                    or [
                        str(
                            uuid4()
                        )
                    ],
                ),
            )
            conn.execute(
                """
                DELETE FROM product_import_jobs
                WHERE company_id = %s
                  AND id = ANY(%s)
                """,
                (
                    self.company_id,
                    [
                        self.job_id,
                        self.imported_guard_job_id,
                    ],
                ),
            )

    def _identities(
        self,
        job_id: UUID,
    ) -> dict[int, UUID]:
        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            return {
                int(
                    row_number
                ):
                    UUID(
                        str(
                            identity
                        )
                    )
                for (
                    row_number,
                    identity,
                )
                in conn.execute(
                    """
                    SELECT
                        row_number,
                        row_identity
                    FROM product_import_rows
                    WHERE company_id = %s
                      AND job_id = %s
                    ORDER BY row_number
                    """,
                    (
                        self.company_id,
                        job_id,
                    ),
                ).fetchall()
            }

    async def _build_artifact(
        self,
        file_format: str,
    ):
        try:
            return await build_correction_artifact(
                company_id=
                    self.company_id,
                job_id=
                    self.job_id,
                file_format=
                    file_format,
            )
        finally:
            await engine.dispose()

    def test_correction_artifacts_include_only_failed_rows_with_stable_identity_in_csv_and_xlsx(
        self,
    ) -> None:
        identities = self._identities(
            self.job_id
        )
        expected = {
            identities[3],
            identities[4],
        }

        for file_format in (
            "csv",
            "xlsx",
        ):
            artifact = _run_async(
                self._build_artifact(
                    file_format
                )
            )
            self.assertEqual(
                artifact.row_count,
                2,
            )
            patches = (
                parse_correction_payload(
                    file_name=
                        artifact.file_name,
                    payload=
                        artifact.payload,
                    source_headers=[
                        "Product",
                        "Unit Price",
                    ],
                )
            )
            self.assertEqual(
                {
                    patch.row_identity
                    for patch
                    in patches
                },
                expected,
            )

    def test_database_rejects_row_identity_mutation(
        self,
    ) -> None:
        identity = self._identities(
            self.job_id
        )[3]
        with psycopg.connect(
            self.owner_dsn,
            autocommit=True,
        ) as conn:
            with self.assertRaises(
                CheckViolation
            ):
                with conn.transaction():
                    conn.execute(
                        """
                        UPDATE product_import_rows
                        SET row_identity = %s
                        WHERE company_id = %s
                          AND job_id = %s
                          AND row_identity = %s
                        """,
                        (
                            uuid4(),
                            self.company_id,
                            self.job_id,
                            identity,
                        ),
                    )

    def test_correction_rejects_attempt_to_modify_imported_row(
        self,
    ) -> None:
        identities = self._identities(
            self.imported_guard_job_id
        )
        request_id = uuid4()
        self.request_ids.append(
            request_id
        )

        async def noop_defer(
            *_args,
            **_kwargs,
        ) -> None:
            return None

        async def scenario():
            with patch(
                "domains.simple_products.imports.infrastructure.correction_repository.defer_import_on_connection",
                noop_defer,
            ):
                return await apply_correction_and_requeue(
                    company_id=
                        self.company_id,
                    actor_id=
                        self.driver_id,
                    job_id=
                        self.imported_guard_job_id,
                    request_id=
                        request_id,
                    request_hash=
                        "a"
                        * 64,
                    corrections=[
                        {
                            "row_identity":
                                identities[
                                    2
                                ],
                            "raw_data": {
                                "Product":
                                    "Tampered",
                                "Unit Price":
                                    "9.000",
                            },
                        }
                    ],
                )

        with self.assertRaisesRegex(
            ValueError,
            "already imported",
        ):
            _run_async(
                scenario()
            )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            raw = conn.execute(
                """
                SELECT raw_data->>'Product'
                FROM product_import_rows
                WHERE company_id = %s
                  AND job_id = %s
                  AND row_number = 2
                """,
                (
                    self.company_id,
                    self.imported_guard_job_id,
                ),
            ).fetchone()[0]
        self.assertEqual(
            raw,
            "Already",
        )

    def test_correction_updates_only_failed_rows_same_job_and_duplicate_client_retry_replays(
        self,
    ) -> None:
        identities = self._identities(
            self.job_id
        )
        request_id = uuid4()
        self.request_ids.append(
            request_id
        )

        corrections = [
            {
                "row_identity":
                    identities[3],
                "raw_data": {
                    "Product":
                        "Corrected A",
                    "Unit Price":
                        "2.000",
                },
            },
            {
                "row_identity":
                    identities[4],
                "raw_data": {
                    "Product":
                        "Corrected B",
                    "Unit Price":
                        "3.000",
                },
            },
        ]

        async def noop_defer(
            *_args,
            **_kwargs,
        ) -> None:
            return None

        async def apply_once():
            with patch(
                "domains.simple_products.imports.infrastructure.correction_repository.defer_import_on_connection",
                noop_defer,
            ):
                return await apply_correction_and_requeue(
                    company_id=
                        self.company_id,
                    actor_id=
                        self.driver_id,
                    job_id=
                        self.job_id,
                    request_id=
                        request_id,
                    request_hash=
                        "b"
                        * 64,
                    corrections=
                        corrections,
                )

        first = _run_async(
            apply_once()
        )
        self.assertFalse(
            first[
                "replayed"
            ]
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            before_replay = conn.execute(
                """
                SELECT
                    row_number,
                    row_identity,
                    status,
                    version,
                    raw_data->>'Product'
                FROM product_import_rows
                WHERE company_id = %s
                  AND job_id = %s
                ORDER BY row_number
                """,
                (
                    self.company_id,
                    self.job_id,
                ),
            ).fetchall()
            job_status = conn.execute(
                """
                SELECT status
                FROM product_import_jobs
                WHERE company_id = %s
                  AND id = %s
                """,
                (
                    self.company_id,
                    self.job_id,
                ),
            ).fetchone()[0]

        self.assertEqual(
            str(
                job_status
            ),
            JobStatus.VALIDATING.value,
        )
        self.assertEqual(
            str(
                before_replay[0][2]
            ),
            RowStatus.IMPORTED.value,
        )
        self.assertEqual(
            [
                str(
                    before_replay[
                        index
                    ][2]
                )
                for index in (
                    1,
                    2,
                )
            ],
            [
                RowStatus.STAGED.value,
                RowStatus.STAGED.value,
            ],
        )
        self.assertEqual(
            UUID(
                str(
                    before_replay[
                        1
                    ][1]
                )
            ),
            identities[3],
        )
        self.assertEqual(
            UUID(
                str(
                    before_replay[
                        2
                    ][1]
                )
            ),
            identities[4],
        )

        replay = _run_async(
            apply_once()
        )
        self.assertTrue(
            replay[
                "replayed"
            ]
        )

        with psycopg.connect(
            self.owner_dsn
        ) as conn:
            after_replay = conn.execute(
                """
                SELECT
                    row_number,
                    row_identity,
                    status,
                    version,
                    raw_data->>'Product'
                FROM product_import_rows
                WHERE company_id = %s
                  AND job_id = %s
                ORDER BY row_number
                """,
                (
                    self.company_id,
                    self.job_id,
                ),
            ).fetchall()

        self.assertEqual(
            after_replay,
            before_replay,
        )


if __name__ == "__main__":
    unittest.main()
