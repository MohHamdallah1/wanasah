from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api import inventory_stock_policy
from api.warehouse import batch_index
from domains.authorization.capabilities import PERMISSIONS
from domains.inventory_rules import batch_metadata_is_sellable
from domains.inventory_stock_policy.read import (
    InventoryStockPolicyReadNotFound,
    read_effective_shelf_life_policy,
)


ROOT = Path(__file__).parents[1]
REPO = ROOT.parent


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
    for request_model in (
        inventory_stock_policy.MinimumStockUpdateRequest,
        inventory_stock_policy.BulkMinimumStockBase,
        inventory_stock_policy.BulkMinimumStockApplyRequest,
    ):
        assert "minimum_remaining_shelf_life_days" not in request_model.model_fields

    route = next(
        item
        for item in inventory_stock_policy.router.routes
        if item.path == "/warehouse/inventory/stock-policy/effective"
    )
    assert route.methods == {"GET"}
    assert route.response_model is inventory_stock_policy.EffectiveShelfLifePolicyResponse

    read_source = (
        ROOT / "domains" / "inventory_stock_policy" / "read.py"
    ).read_text(encoding="utf-8")
    assert "float(" not in read_source
    assert "minimum_remaining_shelf_life_days" in read_source


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
    schemas = (ROOT / "schemas.py").read_text(encoding="utf-8")
    live_api = (ROOT / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    batch_api = (ROOT / "api" / "warehouse" / "batch_index.py").read_text(encoding="utf-8")
    ledger_api = (ROOT / "api" / "warehouse" / "ledger.py").read_text(encoding="utf-8")
    ledger_read = (ROOT / "domains" / "ledger" / "read.py").read_text(encoding="utf-8")
    inbound_api = (ROOT / "api" / "warehouse" / "inbound.py").read_text(encoding="utf-8")
    batch_contract = (
        REPO / "dashboard" / "src" / "pages" / "inventory" / "batches" / "batchIndexContracts.ts"
    ).read_text(encoding="utf-8")

    # Frozen V1: inventory.read exposes server-computed Live Stock valuation and
    # purchase evidence. The legacy product-batch detail also carries server purchase
    # evidence; React does not create a new cost permission or derive a hidden value.
    assert "average_cost_display" in schemas
    assert "last_purchase_cost" in schemas
    assert "latest_purchase_cost" in schemas
    assert "InventoryCostEvent" in live_api
    assert "inventory.read" in live_api

    # The CP2 Batches primary index is deliberately non-cost-bearing. Cost data is
    # absent from the backend/query contract, not merely hidden by Dashboard CSS.
    assert "InventoryCostEvent" not in batch_api
    for forbidden in (
        "input_unit_cost",
        "total_cost",
        "average_cost_after",
        "last_purchase_cost",
        "latest_purchase_cost",
    ):
        assert forbidden not in batch_api
        assert forbidden not in batch_contract

    # Ledger retains its existing explicit read authority and server-generated cost evidence.
    assert 'access.require("ledger.read"' in ledger_api
    for field in ("input_unit_cost", "total_cost", "average_cost_after"):
        assert field in ledger_read

    # Inbound owns submitted acquisition-cost evidence under its existing write path;
    # it delegates financial posting to the authoritative costing service and does not
    # establish a read capability or a second valuation formula.
    assert "unit_cost" in inbound_api
    assert "build_purchase_cost_input" in inbound_api
    assert "activate_costing_for_first_receipt" in inbound_api
    assert "cost.read" not in live_api + batch_api + ledger_api + inbound_api
