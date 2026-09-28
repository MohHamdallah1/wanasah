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


class StageIntegrityTests(unittest.IsolatedAsyncioTestCase):
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
