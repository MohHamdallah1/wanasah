from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from domains.simple_products.imports.application import validation_service
from domains.simple_products.imports.application.state_machine import (
    JobStatus,
    RowStatus,
)
from domains.simple_products.imports.domain.normalization import (
    normalize_raw_row as real_normalize_raw_row,
)


class FakeDb:
    def __init__(
        self,
        state,
    ) -> None:
        self.state = state

    async def commit(
        self,
    ) -> None:
        self.state.commits += 1

    async def rollback(
        self,
    ) -> None:
        self.state.rollbacks += 1


class ValidationState:
    def __init__(
        self,
    ) -> None:
        self.job_id = uuid4()
        self.job = SimpleNamespace(
            id=self.job_id,
            company_id=7,
            status=JobStatus.VALIDATING.value,
            detected_headers=[
                "Product",
                "Unit Price",
            ],
            column_mapping={
                "name": "Product",
                "unit_price": "Unit Price",
            },
            default_lot_control_mode="NONE",
            default_expiry_control_mode="OPTIONAL",
            total_rows=4,
            processed_rows=0,
            valid_rows=0,
            failed_rows=0,
            error_summary={},
            version=1,
            updated_at=None,
        )
        self.rows = [
            SimpleNamespace(
                id=1,
                row_number=2,
                raw_data={
                    "Product": "Tea",
                    "Unit Price": "1.00",
                },
                normalized_data={},
                status=RowStatus.STAGED.value,
                error_code=None,
                error_message=None,
                version=1,
            ),
            SimpleNamespace(
                id=2,
                row_number=3,
                raw_data={
                    "Product": "",
                    "Unit Price": "2.00",
                },
                normalized_data={},
                status=RowStatus.STAGED.value,
                error_code=None,
                error_message=None,
                version=1,
            ),
            SimpleNamespace(
                id=3,
                row_number=4,
                raw_data={
                    "Product": "Coffee",
                    "Unit Price": "3.00",
                },
                normalized_data={},
                status=RowStatus.STAGED.value,
                error_code=None,
                error_message=None,
                version=1,
            ),
            SimpleNamespace(
                id=4,
                row_number=5,
                raw_data={
                    "Product": "Juice",
                    "Unit Price": "4.00",
                },
                normalized_data={},
                status=RowStatus.STAGED.value,
                error_code=None,
                error_message=None,
                version=1,
            ),
        ]
        self.commits = 0
        self.rollbacks = 0
        self.crash_enabled = True
        self.crashed = False
        self.normalized_row_numbers: list[
            int
        ] = []

    async def open_session(
        self,
        _company_id: int,
    ):
        return (
            object(),
            FakeDb(self),
        )

    async def close_session(
        self,
        _token,
        _db,
    ) -> None:
        return None

    async def load_job(
        self,
        _db,
        *,
        company_id: int,
        job_id,
        for_update: bool = False,
    ):
        self.assert_tenant(
            company_id
        )
        if job_id != self.job_id:
            return None
        return self.job

    async def fetch_batch(
        self,
        _db,
        *,
        company_id: int,
        job_id,
        after_row_number: int,
        limit: int,
    ):
        self.assert_tenant(
            company_id
        )
        if (
            self.crash_enabled
            and not self.crashed
            and self.commits >= 1
        ):
            self.crashed = True
            raise RuntimeError(
                "simulated worker crash"
            )

        return [
            row
            for row in self.rows
            if (
                row.status
                == RowStatus.STAGED.value
                and row.row_number
                > after_row_number
            )
        ][
            :limit
        ]

    async def counts(
        self,
        _db,
        *,
        company_id: int,
        job_id,
    ):
        self.assert_tenant(
            company_id
        )
        return (
            sum(
                row.status
                == RowStatus.VALID.value
                for row in self.rows
            ),
            sum(
                row.status
                == RowStatus.INVALID.value
                for row in self.rows
            ),
            sum(
                row.status
                == RowStatus.STAGED.value
                for row in self.rows
            ),
        )

    async def count_status(
        self,
        _db,
        *,
        company_id: int,
        job_id,
        status: str,
    ) -> int:
        self.assert_tenant(
            company_id
        )
        return sum(
            row.status == status
            for row in self.rows
        )

    async def finalize_barcodes(
        self,
        _db,
        *,
        company_id: int,
        job_id,
    ) -> int:
        self.assert_tenant(
            company_id
        )
        return 0

    def normalize(
        self,
        raw,
        mapping,
        *,
        default_lot_control_mode,
        default_expiry_control_mode,
    ):
        product = str(
            raw.get("Product")
            or ""
        )
        row = next(
            row
            for row in self.rows
            if (
                row.raw_data
                is raw
                or row.raw_data
                == raw
            )
        )
        self.normalized_row_numbers.append(
            int(row.row_number)
        )
        return real_normalize_raw_row(
            raw,
            mapping,
            default_lot_control_mode=
                default_lot_control_mode,
            default_expiry_control_mode=
                default_expiry_control_mode,
        )

    def assert_tenant(
        self,
        company_id: int,
    ) -> None:
        if int(company_id) != 7:
            raise AssertionError(
                "tenant boundary changed"
            )


class Phase5ValidationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_crash_resume_skips_already_finalized_rows(
        self,
    ) -> None:
        state = ValidationState()

        with (
            patch.object(
                validation_service,
                "VALIDATION_BATCH_SIZE",
                2,
            ),
            patch.object(
                validation_service,
                "open_tenant_session",
                state.open_session,
            ),
            patch.object(
                validation_service,
                "close_tenant_session",
                state.close_session,
            ),
            patch.object(
                validation_service,
                "load_job",
                state.load_job,
            ),
            patch.object(
                validation_service,
                "fetch_validation_batch",
                state.fetch_batch,
            ),
            patch.object(
                validation_service,
                "count_validation_outcomes",
                state.counts,
            ),
            patch.object(
                validation_service,
                "count_job_rows",
                state.count_status,
            ),
            patch.object(
                validation_service,
                "rebuild_job_barcode_staging",
                state.finalize_barcodes,
            ),
            patch.object(
                validation_service,
                "invalidate_internal_duplicate_barcodes",
                state.finalize_barcodes,
            ),
            patch.object(
                validation_service,
                "invalidate_external_barcode_conflicts",
                state.finalize_barcodes,
            ),
            patch.object(
                validation_service,
                "normalize_raw_row",
                state.normalize,
            ),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "simulated worker crash",
            ):
                await validation_service.validate_rows(
                    company_id=7,
                    job_id=state.job_id,
                )

            first_versions = [
                state.rows[0].version,
                state.rows[1].version,
            ]
            first_normalization = list(
                state.normalized_row_numbers
            )

            self.assertEqual(
                [
                    row.status
                    for row in state.rows
                ],
                [
                    RowStatus.VALID.value,
                    RowStatus.INVALID.value,
                    RowStatus.STAGED.value,
                    RowStatus.STAGED.value,
                ],
            )
            self.assertEqual(
                (
                    state.job.valid_rows,
                    state.job.failed_rows,
                ),
                (1, 1),
            )

            state.crash_enabled = False
            result = (
                await validation_service.validate_rows(
                    company_id=7,
                    job_id=state.job_id,
                )
            )

        self.assertTrue(result)
        self.assertEqual(
            state.job.status,
            JobStatus.IMPORTING.value,
        )
        self.assertEqual(
            (
                state.job.valid_rows,
                state.job.failed_rows,
            ),
            (3, 1),
        )
        self.assertEqual(
            [
                state.rows[0].version,
                state.rows[1].version,
            ],
            first_versions,
        )
        self.assertEqual(
            first_normalization,
            [2, 3],
        )
        self.assertEqual(
            state.normalized_row_numbers,
            [2, 3, 4, 5],
        )

    def test_validation_helper_rejects_unbounded_batch(
        self,
    ) -> None:
        rows = [
            SimpleNamespace(
                id=index,
                raw_data={},
            )
            for index in range(
                validation_service
                .VALIDATION_BATCH_SIZE
                + 1
            )
        ]
        with self.assertRaisesRegex(
            ValueError,
            "bounded validation limit",
        ):
            validation_service.collect_row_validation(
                rows,
                mapping={},
                default_lot_control_mode="NONE",
                default_expiry_control_mode="NONE",
            )


if __name__ == "__main__":
    unittest.main()
