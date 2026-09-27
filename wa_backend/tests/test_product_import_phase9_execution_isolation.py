from __future__ import annotations

import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy.exc import (
    IntegrityError,
    OperationalError,
)

from domains.simple_products.imports.application.execution_service import (
    _execute_rows_best_effort,
)
from domains.simple_products.imports.application.state_machine import (
    RowStatus,
    transition_row,
)
from domains.simple_products.imports.domain.errors import (
    ImportErrorKind,
    ImportFailureScope,
    classify_import_error,
)


class _ConstraintViolation(
    Exception
):
    constraint_name = (
        "uq_active_product_barcode"
    )


class _FakeNestedDb:
    @asynccontextmanager
    async def begin_nested(
        self,
    ):
        yield


def _rows(
    count: int,
):
    return [
        SimpleNamespace(
            row_identity=uuid4(),
            row_number=index + 2,
            status=
                RowStatus.VALID.value,
            version=1,
            normalized_data={
                "name":
                    f"P{index}",
            },
            product_variant_id=None,
            error_code=None,
            error_message=None,
        )
        for index in range(
            count
        )
    ]


class Phase9ExecutionIsolationTests(
    unittest.IsolatedAsyncioTestCase
):
    async def test_one_constraint_failure_in_100_rows_imports_other_99(
        self,
    ) -> None:
        rows = _rows(
            100
        )
        bad_identity = (
            rows[
                61
            ].row_identity
        )

        async def execute(
            _db,
            *,
            actor,
            job_id,
            rows,
        ) -> None:
            if any(
                row.row_identity
                == bad_identity
                for row in rows
            ):
                raise IntegrityError(
                    "INSERT product_barcodes",
                    {},
                    _ConstraintViolation(
                        "duplicate barcode"
                    ),
                )

            for row in rows:
                transition_row(
                    row,
                    RowStatus.IMPORTED,
                    product_variant_id=
                        int(
                            row.row_number
                        )
                        + 100_000,
                    error_code=None,
                    error_message=None,
                )

        with patch(
            "domains.simple_products.imports.application.execution_service._execute_rows_once",
            execute,
        ):
            (
                imported,
                failed,
            ) = (
                await _execute_rows_best_effort(
                    _FakeNestedDb(),
                    actor=
                        SimpleNamespace(
                            id=1,
                            company_id=1,
                        ),
                    job_id=
                        uuid4(),
                    rows=rows,
                )
            )

        self.assertEqual(
            imported,
            99,
        )
        self.assertEqual(
            failed,
            1,
        )
        self.assertEqual(
            sum(
                row.status
                == RowStatus.IMPORTED.value
                for row in rows
            ),
            99,
        )
        bad = rows[
            61
        ]
        self.assertEqual(
            bad.status,
            RowStatus.IMPORT_FAILED.value,
        )
        self.assertEqual(
            bad.error_code,
            "IMPORT_BARCODE_CONFLICT",
        )

    async def test_database_outage_is_not_converted_into_100_row_errors(
        self,
    ) -> None:
        rows = _rows(
            100
        )

        async def outage(
            _db,
            *,
            actor,
            job_id,
            rows,
        ) -> None:
            raise OperationalError(
                "INSERT products",
                {},
                ConnectionError(
                    "database unavailable"
                ),
            )

        with patch(
            "domains.simple_products.imports.application.execution_service._execute_rows_once",
            outage,
        ):
            with self.assertRaises(
                OperationalError
            ) as raised:
                await _execute_rows_best_effort(
                    _FakeNestedDb(),
                    actor=
                        SimpleNamespace(
                            id=1,
                            company_id=1,
                        ),
                    job_id=
                        uuid4(),
                    rows=rows,
                )

        classification = (
            classify_import_error(
                raised.exception
            )
        )
        self.assertIs(
            classification.kind,
            ImportErrorKind.TRANSIENT_SYSTEM,
        )
        self.assertIs(
            classification.scope,
            ImportFailureScope.JOB,
        )
        self.assertTrue(
            classification.retryable
        )
        self.assertEqual(
            {
                row.status
                for row in rows
            },
            {
                RowStatus.VALID.value
            },
        )
        self.assertTrue(
            all(
                row.error_code
                is None
                for row in rows
            )
        )


if __name__ == "__main__":
    unittest.main()
