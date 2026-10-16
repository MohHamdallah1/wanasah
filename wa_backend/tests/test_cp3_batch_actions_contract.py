from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from domains.batch_actions import (
    STATUS_CHANGE_DESTINATIONS,
    status_change_availability,
)


ROOT = Path(__file__).resolve().parents[1]


def test_cp3_stock_status_matrix_is_backend_only_and_frozen():
    assert STATUS_CHANGE_DESTINATIONS == {
        "AVAILABLE": ("QUARANTINED", "BLOCKED", "RECALLED"),
        "QUARANTINED": ("AVAILABLE", "BLOCKED", "RECALLED"),
        "BLOCKED": ("RECALLED",),
        "RECALLED": (),
        "DAMAGED": (),
        "DISPOSAL_PENDING": (),
    }


def test_cp3_status_availability_uses_free_quantity_permission_and_sellability():
    actions = status_change_availability(
        "AVAILABLE",
        eligible_quantity=Decimal("2.500001"),
        can_change=True,
        batch_sellable=True,
    )
    assert [action["destination_status"] for action in actions] == [
        "QUARANTINED",
        "BLOCKED",
        "RECALLED",
    ]
    assert all(action["allowed"] for action in actions)
    assert all(action["eligible_quantity"] == Decimal("2.500001") for action in actions)

    denied = status_change_availability(
        "AVAILABLE",
        eligible_quantity=Decimal("2.500001"),
        can_change=False,
        batch_sellable=True,
    )
    assert {action["reason_code"] for action in denied} == {"PERMISSION_REQUIRED"}

    empty = status_change_availability(
        "BLOCKED",
        eligible_quantity=Decimal("0"),
        can_change=True,
        batch_sellable=True,
    )
    assert empty == [
        {
            "destination_status": "RECALLED",
            "allowed": False,
            "eligible_quantity": Decimal("0"),
            "reason_code": "NO_ELIGIBLE_QUANTITY",
        }
    ]


def test_cp3_quarantine_release_is_server_sellability_gated():
    blocked = status_change_availability(
        "QUARANTINED",
        eligible_quantity=Decimal("4"),
        can_change=True,
        batch_sellable=False,
    )
    release = next(
        action for action in blocked if action["destination_status"] == "AVAILABLE"
    )
    assert release == {
        "destination_status": "AVAILABLE",
        "allowed": False,
        "eligible_quantity": Decimal("4"),
        "reason_code": "BATCH_NOT_SELLABLE",
    }
    assert all(
        action["allowed"]
        for action in blocked
        if action["destination_status"] in {"BLOCKED", "RECALLED"}
    )


def test_cp3_source_detail_is_exact_location_capability_and_reservation_bound():
    source = (ROOT / "api" / "warehouse" / "live_stock_source_detail.py").read_text(
        encoding="utf-8"
    )
    assert 'access.allows(\n                    "inventory.status_change",\n                    location_id=location_id,' in source
    assert "InventoryBalance.location_id == location_id" in source
    assert "ProductBatch.company_id == company_id" in source
    assert "movable = on_hand - reserved" in source
    assert "status_change_availability(" in source
    assert "batch_metadata_is_sellable(" in source
    assert "base_uom_id" in source
    assert "quantity_scale" in source
    assert "quantity_step" in source


def test_cp3_does_not_move_mutation_authority_into_read_route():
    source = (ROOT / "api" / "warehouse" / "live_stock_source_detail.py").read_text(
        encoding="utf-8"
    )
    for forbidden in (
        "apply_inventory_movement(",
        "begin_idempotent_operation(",
        "complete_idempotent_operation(",
        "change_product_batch_disposition(",
    ):
        assert forbidden not in source
