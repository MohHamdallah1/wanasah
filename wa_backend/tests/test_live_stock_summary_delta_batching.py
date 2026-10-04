import os

os.environ.setdefault("SECRET_KEY", "LiveStockSummaryBatchTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
from sqlalchemy.dialects import postgresql

from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    _apply_warehouse_summary_deltas,
)


class _Result:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount


class _Session:
    def __init__(self, rowcount: int):
        self.rowcount = rowcount
        self.sql: list[str] = []
        self.flushes = 0

    async def execute(self, statement):
        self.sql.append(
            str(
                statement.compile(
                    dialect=postgresql.dialect(),
                    compile_kwargs={"literal_binds": True},
                )
            )
        )
        return _Result(self.rowcount)

    async def flush(self):
        self.flushes += 1


@pytest.mark.asyncio
async def test_summary_deltas_are_applied_in_one_set_based_update():
    db = _Session(rowcount=2)
    await _apply_warehouse_summary_deltas(
        db,
        company_id=7,
        summary_deltas={
            11: [1, 0, 1],
            12: [0, -1, 0],
            13: [0, 0, 0],
        },
    )

    assert len(db.sql) == 1
    normalized = " ".join(db.sql[0].split())
    assert normalized.startswith("UPDATE inventory_live_stock_warehouse_summaries")
    assert "FROM (VALUES (11, 1, 0, 1), (12, 0, -1, 0)) AS live_stock_summary_delta" in normalized
    assert "inventory_live_stock_warehouse_summaries.company_id = 7" in normalized
    assert db.flushes == 1


@pytest.mark.asyncio
async def test_summary_delta_batch_preserves_missing_summary_invariant():
    db = _Session(rowcount=1)
    with pytest.raises(LiveStockProjectionError):
        await _apply_warehouse_summary_deltas(
            db,
            company_id=7,
            summary_deltas={11: [1, 0, 0], 12: [0, 1, 0]},
        )
    assert len(db.sql) == 1
    assert db.flushes == 0


@pytest.mark.asyncio
async def test_zero_summary_deltas_skip_update_but_preserve_flush_boundary():
    db = _Session(rowcount=0)
    await _apply_warehouse_summary_deltas(
        db,
        company_id=7,
        summary_deltas={11: [0, 0, 0]},
    )
    assert db.sql == []
    assert db.flushes == 1
