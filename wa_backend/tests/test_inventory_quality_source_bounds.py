import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "QualitySourceBoundTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
from sqlalchemy import literal
from sqlalchemy.dialects import postgresql

from domains.inventory_quality_source_bounds import first_quality_source_limit_excess


class _Result:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _Session:
    def __init__(self, row):
        self.row = row
        self.sql = ""

    async def execute(self, statement):
        self.sql = str(
            statement.compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        return _Result(self.row)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "row,expected",
    [
        (None, None),
        (SimpleNamespace(batch_id=11, source_count=501), (11, 501)),
    ],
)
async def test_source_limit_preflight_is_one_set_based_grouped_query(row, expected):
    db = _Session(row)
    result = await first_quality_source_limit_excess(
        db,
        company_id=3,
        product_variant_id=8,
        batch_ids=[12, 11, 11],
        readable_location_filter=literal(True),
    )
    assert result == expected
    normalized = " ".join(db.sql.split())
    assert "count(distinct(inventory_locations.id))" in normalized
    assert "inventory_balances.company_id = 3" in normalized
    assert "inventory_balances.product_variant_id = 8" in normalized
    assert "inventory_balances.batch_id IN (11, 12)" in normalized
    assert "GROUP BY inventory_balances.batch_id" in normalized
    assert "HAVING count(distinct(inventory_locations.id)) > 500" in normalized
    assert "LIMIT 1" in normalized


def test_quality_reads_preflight_before_detail_materialization_and_map_terminal_limits():
    source = (Path(__file__).parents[1] / "api" / "warehouse" / "live_stock.py").read_text(
        encoding="utf-8"
    )
    whole_start = source.index("async def get_whole_product_quality_issue_sources(")
    batch_start = source.index("async def get_batch_stock_sources(")
    whole = source[whole_start:batch_start]
    batch = source[batch_start:]

    assert whole.index("first_quality_source_limit_excess(") < whole.index(
        "variant_reservation_owner_projection("
    )
    assert batch.index("first_quality_source_limit_excess(") < batch.index(
        "reservation_owner_projection("
    )
    assert "except InventoryRuleError as exc:" in whole
    assert "except InventoryRuleError as exc:" in batch
    assert "raise HTTPException(status_code=409, detail=exc.as_detail()) from exc" in whole
    assert "raise HTTPException(status_code=409, detail=exc.as_detail()) from exc" in batch
