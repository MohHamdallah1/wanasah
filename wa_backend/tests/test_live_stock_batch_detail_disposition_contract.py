from __future__ import annotations

from datetime import date
from decimal import Decimal
import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "Checkpoint1BatchDetailSecretABC123456789xyz")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@127.0.0.1:5432/wanasah_unit")

import pytest
from sqlalchemy import true

from api.warehouse import live_stock
from services import allowed_batch_disposition_targets
from domains.product_tracking import build_internal_no_lot_batch_number
from schemas import WarehouseInventoryBatchItem


class _Result:
    def __init__(self, rows):
        self._rows = list(rows)

    def one_or_none(self):
        if not self._rows:
            return None
        if len(self._rows) != 1:
            raise AssertionError("expected one row")
        return self._rows[0]

    def all(self):
        return list(self._rows)


class _DB:
    def __init__(self, results):
        self._results = list(results)
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        if not self._results:
            raise AssertionError("unexpected execute call")
        return self._results.pop(0)


class _Access:
    company_id = 77

    def allows(self, code, location_id):
        assert code == "inventory.read"
        assert location_id == 5
        return true()


def _batch_row(*, disposition: str, batch_number: str, production_date, expiry_date):
    return SimpleNamespace(
        batch_id=99,
        batch_number=batch_number,
        production_date=production_date,
        expiry_date=expiry_date,
        disposition=disposition,
        disposition_revision=3,
        disposition_reason=None,
        on_hand_total=Decimal("10"),
        reserved_total=Decimal("2"),
        sellable_on_hand=Decimal("10"),
        sellable_reserved=Decimal("2"),
        expiry_unavailable_quantity=Decimal("0"),
        quarantined_quantity=Decimal("0"),
        blocked_quantity=Decimal("0"),
        recalled_quantity=Decimal("0"),
        damaged_quantity=Decimal("0"),
        disposal_pending_quantity=Decimal("0"),
    )


async def _produce(*, disposition: str, batch_number: str, production_date, expiry_date):
    db = _DB(
        [
            _Result([SimpleNamespace(location_type="WAREHOUSE", is_active=True, can_read=True)]),
            _Result([SimpleNamespace(variant_id=44, currency_code="JOD", as_of_date=date(2026, 10, 16))]),
            _Result([SimpleNamespace(batch_id=99, expiry_date=expiry_date)]),
            _Result([
                _batch_row(
                    disposition=disposition,
                    batch_number=batch_number,
                    production_date=production_date,
                    expiry_date=expiry_date,
                )
            ]),
            _Result([]),
        ]
    )
    response = await live_stock.get_warehouse_inventory_batches(
        product_variant_id=44,
        location_id=5,
        cursor=None,
        limit=100,
        db=db,
        access=_Access(),
    )
    return response, db


def test_schema_declares_bounded_allowed_disposition_targets():
    field = WarehouseInventoryBatchItem.model_fields["allowed_disposition_targets"]
    metadata = field.metadata
    max_lengths = [item.max_length for item in metadata if hasattr(item, "max_length")]
    assert max_lengths == [3]


@pytest.mark.asyncio
@pytest.mark.parametrize("disposition", ["RELEASED", "QUARANTINED", "BLOCKED", "RECALLED"])
async def test_batch_detail_emits_canonical_allowed_disposition_targets(disposition):
    response, _ = await _produce(
        disposition=disposition,
        batch_number=f"REAL-{disposition}",
        production_date=date(2026, 1, 2),
        expiry_date=date(2030, 3, 4),
    )
    assert response["has_more"] is False
    assert response["next_cursor"] is None
    assert len(response["batches"]) == 1
    item = response["batches"][0]
    assert item["batch_id"] == 99
    assert item["batch_number"] == f"REAL-{disposition}"
    assert item["production_date"] == date(2026, 1, 2)
    assert item["expiry_date"] == date(2030, 3, 4)
    assert item["disposition"] == disposition
    assert item["disposition_revision"] == 3
    assert item["allowed_disposition_targets"] == list(
        allowed_batch_disposition_targets(disposition)
    )


@pytest.mark.asyncio
async def test_batch_detail_masks_anonymous_lot_preserves_null_dates_and_batch_id():
    internal = build_internal_no_lot_batch_number(
        request_id=__import__("uuid").UUID("00000000-0000-0000-0000-000000000321"),
        production_date=None,
        expiry_date=None,
    )
    response, _ = await _produce(
        disposition="RELEASED",
        batch_number=internal,
        production_date=None,
        expiry_date=None,
    )
    item = response["batches"][0]
    assert item["batch_id"] == 99
    assert item["batch_number"] is None
    assert item["production_date"] is None
    assert item["expiry_date"] is None
    assert item["allowed_disposition_targets"] == list(
        allowed_batch_disposition_targets("RELEASED")
    )
    assert internal not in repr(response)


@pytest.mark.asyncio
async def test_batch_detail_keeps_existing_pagination_and_ordering_contract():
    _, db = await _produce(
        disposition="RELEASED",
        batch_number="REAL-LOT-ORDER",
        production_date=None,
        expiry_date=date(2030, 1, 1),
    )
    assert len(db.statements) == 5
    candidate_sql = str(db.statements[2])
    aggregate_sql = str(db.statements[3])
    expected = "product_batches.expiry_date ASC NULLS LAST, product_batches.id ASC"
    assert expected in candidate_sql
    assert expected in aggregate_sql
