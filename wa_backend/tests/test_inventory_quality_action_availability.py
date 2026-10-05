import os
from decimal import Decimal

os.environ.setdefault("SECRET_KEY", "QualityAvailabilityTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

from services import inventory_quality_action_availability


def matrix(**overrides):
    values = dict(
        lifecycle_status="ACTIVE",
        operational_hold="RECALL",
        batch_disposition="RELEASED",
        source_status="AVAILABLE",
        metadata_sellable=True,
        movable_quantity=Decimal("8"),
        source_location_id=10,
        can_send=True,
        can_confirm_disposal=False,
        can_confirm_vendor_return=False,
        special_destinations={
            "QUARANTINE": 20,
            "RECALL_RETURN": 20,
            "RETURN_TO_VENDOR": 40,
            "DISPOSAL": 30,
        },
        purpose_access={
            "QUARANTINE": True,
            "RECALL_RETURN": True,
            "RETURN_TO_VENDOR": True,
            "DISPOSAL": True,
        },
        terminal_evidence={},
    )
    values.update(overrides)
    return inventory_quality_action_availability(**values)


def test_allowed_purposes_are_derived_from_the_same_special_action_matrix():
    result = matrix()
    assert result["allowed_purposes"] == [
        item["purpose"] for item in result["special_actions"] if item["allowed"]
    ]
    reasons = {item["purpose"]: item["reason_code"] for item in result["special_actions"]}
    assert reasons["RETURN_TO_VENDOR"] == "ALLOWED"
    assert reasons["RECALL_RETURN"] == "ALLOWED"
    assert reasons["QUARANTINE"] == "STATE_RESTRICTION"
    assert reasons["DISPOSAL"] == "ALLOWED"


def test_special_action_reason_is_server_derived_for_missing_policy_and_source_permission():
    missing = matrix(special_destinations={})
    by_purpose = {item["purpose"]: item for item in missing["special_actions"]}
    assert by_purpose["RECALL_RETURN"]["reason_code"] == "NO_CONFIGURED_DESTINATION"
    no_send = matrix(can_send=False)
    by_purpose = {item["purpose"]: item for item in no_send["special_actions"]}
    assert by_purpose["DISPOSAL"]["reason_code"] == "SOURCE_CANNOT_SEND"
    assert no_send["allowed_purposes"] == []


def test_disposal_terminal_eligibility_is_capped_by_free_stock_and_origin_evidence():
    result = matrix(
        source_status="DISPOSAL_PENDING",
        operational_hold="NONE",
        batch_disposition="BLOCKED",
        can_confirm_disposal=True,
        terminal_evidence={"DISPOSAL": Decimal("3")},
    )
    disposal = next(item for item in result["terminal_actions"] if item["action"] == "CONFIRM_DISPOSAL")
    assert disposal == {
        "action": "CONFIRM_DISPOSAL",
        "allowed": True,
        "eligible_quantity": "3",
        "reason_code": "ALLOWED",
    }


def test_vendor_terminal_eligibility_requires_evidence_permission_and_staging_state():
    result = matrix(
        source_status="QUARANTINED",
        operational_hold="NONE",
        batch_disposition="QUARANTINED",
        can_confirm_vendor_return=True,
        terminal_evidence={"RETURN_TO_VENDOR": Decimal("12")},
    )
    vendor = next(item for item in result["terminal_actions"] if item["action"] == "CONFIRM_VENDOR_HANDOVER")
    assert vendor["allowed"] is True
    assert vendor["eligible_quantity"] == "8"
    denied = matrix(
        source_status="QUARANTINED",
        operational_hold="NONE",
        batch_disposition="QUARANTINED",
        can_confirm_vendor_return=False,
        terminal_evidence={"RETURN_TO_VENDOR": Decimal("4")},
    )
    vendor = next(item for item in denied["terminal_actions"] if item["action"] == "CONFIRM_VENDOR_HANDOVER")
    assert vendor["allowed"] is False
    assert vendor["reason_code"] == "PERMISSION_REQUIRED"
    assert vendor["eligible_quantity"] == "0"


def test_both_inventory_read_surfaces_use_the_same_backend_action_helper():
    from pathlib import Path
    api = (Path(__file__).parents[1] / "api" / "warehouse" / "live_stock.py").read_text(encoding="utf-8")
    assert api.count("inventory_quality_action_availability(") == 2
    whole = api[api.index("async def get_whole_product_quality_issue_sources("):api.index("async def get_batch_stock_sources(")]
    batch = api[api.index("async def get_batch_stock_sources("):]
    assert "read_terminal_origin_availability_for_batches(" in whole
    assert "read_terminal_origin_availability(" in batch
    assert "special_actions = []" not in whole
    assert "special_actions = []" not in batch
