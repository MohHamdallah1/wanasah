from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api import inventory_stock_policy
from api.warehouse import batch_index, stock_policy_read
from domains.authorization.capabilities import PERMISSIONS
from domains.inventory_rules import batch_metadata_is_sellable
from domains.inventory_stock_policy.read import (
    InventoryStockPolicyReadNotFound,
    read_effective_shelf_life_policy,
)


ROOT = Path(__file__).parents[1]


class _ScalarResult:
    def __init__(self, row):
        self.row = row

    def one_or_none(self):
        return self.row


class _ReadDb:
    def __init__(self, *, warehouse=1, assignment=1, policy=None):
        self.scalar = AsyncMock(side_effect=[warehouse, assignment])
        self.execute = AsyncMock(return_value=_ScalarResult(policy))


@pytest.mark.asyncio
async def test_effective_shelf_life_read_is_exact_and_read_only():
    db = _ReadDb(
        policy=SimpleNamespace(
            id=90,
            minimum_remaining_shelf_life_days=12,
        )
    )
    result = await read_effective_shelf_life_policy(
        db,
        company_id=7,
        location_id=11,
        product_variant_id=13,
    )
    assert result.location_id == 11
    assert result.product_variant_id == 13
    assert result.minimum_remaining_shelf_life_days == 12
    assert result.requirement_applies is True
    assert result.source == "EXACT_ACTIVE_POLICY"

    sql = "\n".join(
        str(call.args[0].compile(compile_kwargs={"literal_binds": True}))
        for call in db.scalar.await_args_list
    )
    sql += "\n" + str(
        db.execute.await_args.args[0].compile(compile_kwargs={"literal_binds": True})
    )
    assert "inventory_locations.company_id = 7" in sql
    assert "inventory_locations.id = 11" in sql
    assert "product_locations.company_id = 7" in sql
    assert "product_locations.location_id = 11" in sql
    assert "product_locations.product_variant_id = 13" in sql
    assert "inventory_stock_policies.company_id = 7" in sql
    assert "inventory_stock_policies.location_id = 11" in sql
    assert "inventory_stock_policies.product_variant_id = 13" in sql
    assert "inventory_stock_policies.is_active IS true" in sql

    no_policy = _ReadDb(policy=None)
    result = await read_effective_shelf_life_policy(
        no_policy,
        company_id=7,
        location_id=11,
        product_variant_id=13,
    )
    assert result.minimum_remaining_shelf_life_days == 0
    assert result.requirement_applies is False
    assert result.source == "NO_ACTIVE_POLICY"

    for warehouse, assignment in ((None, 1), (1, None)):
        with pytest.raises(InventoryStockPolicyReadNotFound):
            await read_effective_shelf_life_policy(
                _ReadDb(warehouse=warehouse, assignment=assignment),
                company_id=7,
                location_id=11,
                product_variant_id=13,
            )


def test_v1_has_no_shelf_life_write_authority_and_no_cost_read_capability():
    assert "cost.read" not in PERMISSIONS
    assert not any("shelf" in code for code in PERMISSIONS)
    assert "minimum_remaining_shelf_life_days" not in inventory_stock_policy.MinimumStockUpdateRequest.model_fields
    assert "minimum_remaining_shelf_life_days" not in inventory_stock_policy.BulkMinimumStockRequest.model_fields

    route = next(
        item
        for item in stock_policy_read.router.routes
        if item.path == "/warehouse/inventory/stock-policy/effective"
    )
    assert route.methods == {"GET"}


def test_authoritative_sellability_boundaries_and_warning_separation():
    today = date(2026, 10, 16)
    common = dict(
        as_of_date=today,
        expiry_control_mode="REQUIRED",
        production_date=today - timedelta(days=1),
        is_active=True,
        disposition="RELEASED",
    )
    assert batch_metadata_is_sellable(
        **common,
        expiry_date=today + timedelta(days=10),
        minimum_remaining_shelf_life_days=10,
    ) is True
    assert batch_metadata_is_sellable(
        **common,
        expiry_date=today + timedelta(days=9),
        minimum_remaining_shelf_life_days=10,
    ) is False
    assert batch_metadata_is_sellable(
        **common,
        expiry_date=today,
        minimum_remaining_shelf_life_days=0,
    ) is True
    assert batch_metadata_is_sellable(
        **common,
        expiry_date=today - timedelta(days=1),
        minimum_remaining_shelf_life_days=0,
    ) is False

    warning = batch_index._expiry_filter(
        expiry_state="EXPIRING_SOON",
        as_of_date=today,
        expiry_warning_days=30,
    )
    assert "minimum_remaining_shelf_life_days" not in str(warning)
    assert "expiry_warning_days" not in str(batch_index._batch_index_query_parts)


def test_cost_visibility_v1_is_frozen_to_existing_server_surfaces():
    live_schema = (ROOT / "schemas.py").read_text(encoding="utf-8")
    live_api = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    batch_api = (ROOT / "api" / "warehouse" / "batch_index.py").read_text(encoding="utf-8")
    ledger_api = (ROOT / "api" / "warehouse" / "ledger.py").read_text(encoding="utf-8")
    ledger_read = (ROOT / "domains" / "ledger" / "read.py").read_text(encoding="utf-8")
    inbound_api = (ROOT / "api" / "warehouse" / "inbound.py").read_text(encoding="utf-8")

    # Frozen V1 rule: inventory.read exposes the server-computed Live Stock cost evidence.
    assert "average_cost_display" in live_schema
    assert "last_purchase_cost" in live_schema
    assert "InventoryCostEvent" in live_api
    assert "inventory.read" in live_api

    # Dedicated Batches intentionally exposes no cost evidence at all.
    assert "InventoryCostEvent" not in batch_api
    for forbidden in ("input_unit_cost", "total_cost", "average_cost_after", "last_purchase_cost"):
        assert forbidden not in batch_api

    # Ledger cost evidence is server-computed and gated by the existing ledger.read capability.
    assert 'access.require("ledger.read"' in ledger_api
    for field in ("input_unit_cost", "total_cost", "average_cost_after"):
        assert field in ledger_read

    # Inbound owns submitted acquisition-cost evidence; it does not establish a read capability.
    assert "unit_cost" in inbound_api
    assert "InventoryCostEvent" in inbound_api or "record_purchase" in inbound_api
    assert "cost.read" not in live_api + batch_api + ledger_api + inbound_api
