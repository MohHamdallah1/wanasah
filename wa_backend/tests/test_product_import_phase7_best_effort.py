from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from domains.simple_products.imports.api.router import (
    _job_payload,
)
from domains.simple_products.imports.application.execution_service import (
    _execute_rows_best_effort,
    completion_outcome,
)
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    RowStatus,
    transition_row,
)
from domains.simple_products.imports.application.validation_service import (
    collect_row_validation,
    validation_outcome,
)
from domains.simple_products.imports.domain.normalization import (
    normalize_raw_row,
)
from domains.simple_products.imports.infrastructure.parsers import (
    open_source,
)
from domains.simple_products.imports.infrastructure.repository import (
    ProductImportProgress,
)
from domains.simple_products.service import (
    SimpleProductError,
)


def _large_csv_payload() -> bytes:
    chunks = [
        b"Product,Unit Price\n"
    ]
    for index in range(
        49_999
    ):
        chunks.append(
            (
                f"P{index},1.000\n"
            ).encode("utf-8")
        )
    chunks.append(
        b",1.000\n"
    )
    return b"".join(chunks)


class Phase7OutcomeTests(
    unittest.TestCase
):
    def test_49999_valid_plus_one_invalid_file_completes_with_errors(
        self,
    ) -> None:
        valid = 0
        invalid = 0

        with open_source(
            "products.csv",
            _large_csv_payload(),
        ) as source:
            for parsed in source.rows:
                try:
                    normalize_raw_row(
                        parsed.raw,
                        {
                            "name":
                                "Product",
                            "unit_price":
                                "Unit Price",
                        },
                        default_lot_control_mode=
                            "NONE",
                        default_expiry_control_mode=
                            "NONE",
                    )
                    valid += 1
                except SimpleProductError:
                    invalid += 1

        self.assertEqual(
            valid,
            49_999,
        )
        self.assertEqual(
            invalid,
            1,
        )
        self.assertEqual(
            validation_outcome(
                valid,
                invalid,
            ),
            (
                JobStatus.IMPORTING.value,
                True,
            ),
        )

        progress = ProductImportProgress(
            total_rows=50_000,
            imported_rows=49_999,
            invalid_rows=1,
            import_failed_rows=0,
            pending_rows=0,
        )
        self.assertIs(
            completion_outcome(
                progress
            ),
            JobStatus.COMPLETED_WITH_ERRORS,
        )

    def test_mixed_tracking_package_and_price_errors_do_not_block_valid_row(
        self,
    ) -> None:
        rows = [
            SimpleNamespace(
                id=1,
                raw_data={
                    "Product": "Good",
                    "Package": "CARTON",
                    "Units": "12",
                    "Price": "1.000",
                    "Lot": "NONE",
                },
            ),
            SimpleNamespace(
                id=2,
                raw_data={
                    "Product": "Bad tracking",
                    "Package": "CARTON",
                    "Units": "12",
                    "Price": "1.000",
                    "Lot": "NOT_A_MODE",
                },
            ),
            SimpleNamespace(
                id=3,
                raw_data={
                    "Product": "Bad package",
                    "Package": "CARTON",
                    "Units": "1",
                    "Price": "1.000",
                    "Lot": "NONE",
                },
            ),
            SimpleNamespace(
                id=4,
                raw_data={
                    "Product": "Bad price",
                    "Package": "CARTON",
                    "Units": "12",
                    "Price": "not-a-price",
                    "Lot": "NONE",
                },
            ),
        ]

        normalized, errors = (
            collect_row_validation(
                rows,
                mapping={
                    "name": "Product",
                    "package_uom":
                        "Package",
                    "units_per_package":
                        "Units",
                    "unit_price":
                        "Price",
                    "lot_control_mode":
                        "Lot",
                },
                default_lot_control_mode=
                    "NONE",
                default_expiry_control_mode=
                    "NONE",
            )
        )

        self.assertEqual(
            set(normalized),
            {1},
        )
        self.assertEqual(
            set(errors),
            {
                2,
                3,
                4,
            },
        )
        self.assertEqual(
            validation_outcome(
                1,
                3,
            ),
            (
                JobStatus.IMPORTING.value,
                True,
            ),
        )

    def test_zero_valid_rows_stops_at_validation_failed(
        self,
    ) -> None:
        self.assertEqual(
            validation_outcome(
                0,
                12,
            ),
            (
                JobStatus.VALIDATION_FAILED.value,
                False,
            ),
        )

    def test_clean_execution_finishes_completed(
        self,
    ) -> None:
        self.assertIs(
            completion_outcome(
                ProductImportProgress(
                    total_rows=3,
                    imported_rows=3,
                    invalid_rows=0,
                    import_failed_rows=0,
                    pending_rows=0,
                )
            ),
            JobStatus.COMPLETED,
        )

    def test_import_failed_row_finishes_completed_with_errors(
        self,
    ) -> None:
        self.assertIs(
            completion_outcome(
                ProductImportProgress(
                    total_rows=3,
                    imported_rows=2,
                    invalid_rows=0,
                    import_failed_rows=1,
                    pending_rows=0,
                )
            ),
            JobStatus.COMPLETED_WITH_ERRORS,
        )


class _FakeNestedDb:
    @asynccontextmanager
    async def begin_nested(
        self,
    ):
        yield


class Phase7PayloadTests(
    unittest.TestCase
):
    def test_public_payload_exposes_explicit_outcome_counters(
        self,
    ) -> None:
        job = SimpleNamespace(
            id=uuid4(),
            status=
                JobStatus.COMPLETED_WITH_ERRORS.value,
            file_name="products.csv",
            total_rows=5,
            processed_rows=3,
            valid_rows=4,
            failed_rows=1,
            detected_headers=[],
            suggested_mapping={},
            column_mapping={},
            default_lot_control_mode="NONE",
            default_expiry_control_mode="NONE",
            error_summary={},
            created_at=None,
            started_at=None,
            finished_at=None,
        )
        payload = _job_payload(
            job,
            ProductImportProgress(
                total_rows=5,
                imported_rows=3,
                invalid_rows=1,
                import_failed_rows=1,
                pending_rows=0,
            ),
        )

        self.assertEqual(
            payload[
                "imported_rows"
            ],
            3,
        )
        self.assertEqual(
            payload[
                "invalid_rows"
            ],
            1,
        )
        self.assertEqual(
            payload[
                "import_failed_rows"
            ],
            1,
        )
        self.assertEqual(
            payload[
                "pending_rows"
            ],
            0,
        )


class Phase7ExecutionIsolationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_deterministic_bad_row_does_not_block_unrelated_valid_rows(
        self,
    ) -> None:
        rows = [
            SimpleNamespace(
                row_number=index,
                status=RowStatus.VALID.value,
                version=1,
                normalized_data={
                    "name":
                        (
                            "Bad"
                            if index == 3
                            else f"P{index}"
                        )
                },
                product_variant_id=None,
                error_code=None,
                error_message=None,
            )
            for index in range(
                1,
                6
            )
        ]

        async def fake_execute_once(
            _db,
            *,
            actor,
            job_id,
            rows,
        ) -> None:
            if any(
                row.normalized_data[
                    "name"
                ]
                == "Bad"
                for row in rows
            ):
                raise SimpleProductError(
                    "SIMPLE_PRODUCT_ROW_REJECTED",
                    "Rejected row.",
                    status_code=422,
                )

            for row in rows:
                transition_row(
                    row,
                    RowStatus.IMPORTED,
                    product_variant_id=
                        row.row_number
                        + 10_000,
                    error_code=None,
                    error_message=None,
                )

        with patch(
            "domains.simple_products.imports.application.execution_service._execute_rows_once",
            fake_execute_once,
        ):
            imported, failed = (
                await _execute_rows_best_effort(
                    _FakeNestedDb(),
                    actor=SimpleNamespace(
                        id=1,
                        company_id=1,
                    ),
                    job_id=uuid4(),
                    rows=rows,
                )
            )

        self.assertEqual(
            imported,
            4,
        )
        self.assertEqual(
            failed,
            1,
        )
        self.assertEqual(
            [
                row.status
                for row in rows
            ],
            [
                RowStatus.IMPORTED.value,
                RowStatus.IMPORTED.value,
                RowStatus.IMPORT_FAILED.value,
                RowStatus.IMPORTED.value,
                RowStatus.IMPORTED.value,
            ],
        )
        self.assertEqual(
            rows[2].error_code,
            "SIMPLE_PRODUCT_ROW_REJECTED",
        )

    async def test_system_failure_propagates_without_reclassifying_rows(
        self,
    ) -> None:
        rows = [
            SimpleNamespace(
                row_number=1,
                status=RowStatus.VALID.value,
                version=1,
                normalized_data={
                    "name": "P1",
                },
                product_variant_id=None,
                error_code=None,
                error_message=None,
            )
        ]

        async def crash(
            _db,
            *,
            actor,
            job_id,
            rows,
        ) -> None:
            raise RuntimeError(
                "database unavailable"
            )

        with patch(
            "domains.simple_products.imports.application.execution_service._execute_rows_once",
            crash,
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "database unavailable",
            ):
                await _execute_rows_best_effort(
                    _FakeNestedDb(),
                    actor=SimpleNamespace(
                        id=1,
                        company_id=1,
                    ),
                    job_id=uuid4(),
                    rows=rows,
                )

        self.assertEqual(
            rows[0].status,
            RowStatus.VALID.value,
        )
        self.assertIsNone(
            rows[0].error_code
        )


if __name__ == "__main__":
    unittest.main()
