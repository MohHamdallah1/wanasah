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


if __name__ == "__main__":
    unittest.main()
