"""Compile PostgreSQL statements with a fake session; never connect to a DB."""
from decimal import Decimal
import os
import re
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "TerminalBoundTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
from sqlalchemy.dialects import postgresql

from domains.inventory_terminal_provenance import (
    allocate_terminal_origin_quantity,
    read_terminal_origin_availability_for_batches,
)
from services import InventoryRuleError


class FakeSession:
    def __init__(self, origins):
        self.origins = origins
        self.sql = []
        self.materialized = 0

    def compile(self, statement):
        sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
        self.sql.append(sql)
        return sql

    async def execute(self, statement):
        sql = self.compile(statement)
        rows = self.origins if "reference_number" in sql or "destination_location_id IN" in sql else []
        match = re.search(r"\bLIMIT (\d+)", sql)
        if match:
            rows = rows[:int(match[1])]
        self.materialized = max(self.materialized, len(rows))
        return SimpleNamespace(all=lambda: rows)

    async def scalar(self, statement):
        sql = self.compile(statement)
        assert "count(*)" in sql and "LIMIT" not in sql
        assert "inventory_transfer_headers.company_id = 2" in sql
        assert "inventory_transfer_lines.product_variant_id = 8" in sql
        return len(self.origins)


async def read(db, allocation):
    if allocation:
        return await allocate_terminal_origin_quantity(
            db, company_id=2, transfer_purpose="DISPOSAL", destination_location_id=7,
            product_variant_id=8, batch_id=9, terminal_reference_type="FINAL_DISPOSAL",
            requested_quantity=Decimal("1"),
        )
    return await read_terminal_origin_availability_for_batches(
        db, company_id=2, destination_location_ids=[7], product_variant_id=8, batch_ids=[9],
    )


def origins(count):
    return [SimpleNamespace(header_id=index + 1, reference_number=f"T-{index + 1}",
        destination_location_id=7, transfer_purpose="DISPOSAL", batch_id=9,
        quantity=Decimal("1")) for index in range(count)]


@pytest.mark.asyncio
@pytest.mark.parametrize("allocation,capacity", [(True, 500), (False, 10_000)])
async def test_capacity_is_sql_bounded_without_extra_success_queries(allocation, capacity):
    db = FakeSession(origins(capacity))
    result = await read(db, allocation)
    assert len(db.sql) == (3 if allocation else 2)
    assert any(f"LIMIT {capacity + 1}" in sql for sql in db.sql)
    assert db.materialized == capacity
    if allocation:
        assert [(item.transfer_header_id, item.quantity) for item in result] == [(1, Decimal("1"))]
    else:
        assert result == {("DISPOSAL", 9, 7): Decimal(capacity)}


@pytest.mark.asyncio
@pytest.mark.parametrize("allocation,capacity", [(True, 500), (False, 10_000)])
async def test_overflow_materializes_only_sentinel_and_preserves_exact_error_count(allocation, capacity):
    db = FakeSession(origins(capacity + 37))
    with pytest.raises(InventoryRuleError) as exc:
        await read(db, allocation)
    assert exc.value.code == "TERMINAL_ORIGIN_EVIDENCE_LIMIT"
    assert exc.value.context == {"origin_document_count": capacity + 37}
    assert db.materialized == capacity + 1
    assert len(db.sql) == (3 if allocation else 2)
    assert "count(*)" in db.sql[-1]
    # No partial allocation/consumption read is reached on overflow.
    assert not any("inventory_movements" in sql for sql in db.sql)
