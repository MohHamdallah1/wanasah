import os
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "WholeProductLegacyFifoTestSecretAa123456")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest

from domains.inventory_costing.service import (
    CostingError,
    LEGACY_FIFO_STATE_BRIDGE_BASIS,
    _consume_fifo_outbound_cost,
)
from services import (
    InventoryMutationError,
    InventoryRuleError,
    _normalize_inventory_movement_spec,
)


def _status_spec(reference_type="QUALITY_HANDLING_STAGE"):
    return {
        "product_variant_id": 7,
        "batch_id": 11,
        "quantity": "1",
        "movement_kind": "STATUS_CHANGE",
        "reference_type": reference_type,
        "reference_id": "QSTG-1",
        "idempotency_key": "QSTG-K1",
        "source_location_id": 5,
        "destination_location_id": 5,
        "source_stock_status": "AVAILABLE",
        "destination_stock_status": "DISPOSAL_PENDING",
        "transfer_header_id": 41,
    }


def _layer(qty="1000", value="210"):
    return SimpleNamespace(
        remaining_quantity=Decimal(qty),
        remaining_value=Decimal(value),
        version=1,
        updated_at=None,
    )


def test_qstg_disposal_transition_is_scoped_but_allowed():
    normalized = _normalize_inventory_movement_spec(_status_spec())
    assert normalized["destination_stock_status"] == "DISPOSAL_PENDING"

    with pytest.raises(InventoryRuleError) as caught:
        _normalize_inventory_movement_spec(
            _status_spec("UNRELATED_STATUS_CHANGE")
        )
    assert caught.value.code == "STOCK_STATUS_TRANSITION_BLOCKED"

    invalid_qstg = _status_spec()
    invalid_qstg["reference_id"] = "NOT-QSTG"
    invalid_qstg["idempotency_key"] = "QSTG-K2"
    with pytest.raises(InventoryRuleError) as invalid_reference:
        _normalize_inventory_movement_spec(invalid_qstg)
    assert invalid_reference.value.code == "STOCK_STATUS_TRANSITION_BLOCKED"


def test_legacy_fifo_bridge_flag_is_terminal_internal_only():
    spec = {
        "product_variant_id": 7,
        "batch_id": 11,
        "quantity": "1",
        "movement_kind": "PHYSICAL",
        "reference_type": "FINAL_DISPOSAL",
        "reference_id": "REQ-1",
        "idempotency_key": "TERM-K1",
        "source_location_id": 5,
        "destination_location_id": None,
        "source_stock_status": "DISPOSAL_PENDING",
        "destination_stock_status": None,
        "transfer_header_id": 41,
        "allow_legacy_fifo_state_bridge": True,
    }
    normalized = _normalize_inventory_movement_spec(spec)
    assert normalized["allow_legacy_fifo_state_bridge"] is True

    with pytest.raises(InventoryMutationError):
        _normalize_inventory_movement_spec({**spec, "reference_type": "SALE"})


def test_legacy_fifo_bridge_closes_residual_before_real_layers():
    layer = _layer()
    total, basis, consumed = _consume_fifo_outbound_cost(
        quantity=Decimal("5100"),
        before_quantity=Decimal("6100"),
        before_value=Decimal("720"),
        layers=[layer],
        allow_legacy_state_bridge=True,
    )
    assert total == Decimal("510.000000")
    assert basis == LEGACY_FIFO_STATE_BRIDGE_BASIS
    assert consumed == []
    assert layer.remaining_quantity == Decimal("1000")
    assert layer.remaining_value == Decimal("210")

    total2, basis2, consumed2 = _consume_fifo_outbound_cost(
        quantity=Decimal("1000"),
        before_quantity=Decimal("1000"),
        before_value=Decimal("210"),
        layers=[layer],
        allow_legacy_state_bridge=False,
    )
    assert total2 == Decimal("210.000000")
    assert basis2 == "FIFO_LAYER"
    assert consumed2[0][1] == Decimal("1000")
    assert layer.remaining_quantity == Decimal("0")
    assert layer.remaining_value == Decimal("0.000000")


def test_unlayered_legacy_fifo_fails_closed_without_terminal_bridge():
    with pytest.raises(CostingError) as caught:
        _consume_fifo_outbound_cost(
            quantity=Decimal("1"),
            before_quantity=Decimal("6100"),
            before_value=Decimal("720"),
            layers=[_layer()],
            allow_legacy_state_bridge=False,
        )
    assert caught.value.code == "FIFO_LEGACY_STATE_UNLAYERED"


def test_layer_overflow_still_fails_closed():
    with pytest.raises(CostingError) as caught:
        _consume_fifo_outbound_cost(
            quantity=Decimal("1"),
            before_quantity=Decimal("10"),
            before_value=Decimal("5"),
            layers=[_layer(qty="11", value="5")],
            allow_legacy_state_bridge=True,
        )
    assert caught.value.code == "FIFO_COST_STATE_LAYER_OVERFLOW"


def test_whole_product_opts_in_but_terminal_defaults_remain_strict():
    root = Path(__file__).resolve().parents[1]
    whole = (
        root / "api" / "warehouse" / "whole_product_quality.py"
    ).read_text(encoding="utf-8")
    disposal = (
        root / "domains" / "inventory_terminal_quality.py"
    ).read_text(encoding="utf-8")
    vendor = (
        root / "domains" / "inventory_terminal_vendor.py"
    ).read_text(encoding="utf-8")

    assert whole.count("allow_legacy_fifo_state_bridge=True") == 2
    assert "allow_legacy_fifo_state_bridge: bool = False" in disposal
    assert "allow_legacy_fifo_state_bridge: bool = False" in vendor


def test_migration_expands_basis_with_fixed_physical_constraint_name():
    root = Path(__file__).resolve().parents[1]
    migration = (
        root
        / "alembic"
        / "versions"
        / "b8e4d7a91c52_legacy_fifo_state_bridge.py"
    ).read_text(encoding="utf-8")

    assert 'down_revision = "a4c9e7d2f631"' in migration
    assert "LEGACY_FIFO_STATE_BRIDGE" in migration
    assert "op.f(_CONSTRAINT)" in migration
    assert "Cannot downgrade: legacy FIFO bridge cost evidence exists" in migration
