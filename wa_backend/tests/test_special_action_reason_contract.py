import os
from decimal import Decimal

os.environ.setdefault("SECRET_KEY", "SpecialActionReasonContractSecretKeyAa1234567890")
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
            "DISPOSAL": 30,
        },
        purpose_access={
            "QUARANTINE": True,
            "RECALL_RETURN": True,
            "DISPOSAL": True,
        },
        terminal_evidence={},
    )
    values.update(overrides)
    return inventory_quality_action_availability(**values)


def reason(result, purpose):
    return next(
        item["reason_code"]
        for item in result["special_actions"]
        if item["purpose"] == purpose
    )


def test_batch_actions_expose_server_derived_unavailability_reasons():
    assert reason(matrix(), "QUARANTINE") == "ALLOWED"
    assert reason(matrix(), "RETURN_TO_VENDOR") == "STATE_RESTRICTION"
    assert reason(matrix(special_destinations={}), "RECALL_RETURN") == "NO_CONFIGURED_DESTINATION"
    assert reason(
        matrix(source_location_id=20),
        "QUARANTINE",
    ) == "ALREADY_AT_DESTINATION"
    assert reason(matrix(can_send=False), "DISPOSAL") == "SOURCE_CANNOT_SEND"
    assert reason(
        matrix(
            purpose_access={
                "QUARANTINE": False,
                "RECALL_RETURN": True,
                "DISPOSAL": True,
            }
        ),
        "QUARANTINE",
    ) == "PERMISSION_REQUIRED"
    assert reason(matrix(movable_quantity=Decimal("0")), "DISPOSAL") == "NO_MOVABLE_QUANTITY"


def test_allowed_purposes_remains_compatibility_projection_of_action_options():
    for result in (
        matrix(),
        matrix(can_send=False),
        matrix(movable_quantity=Decimal("0")),
        matrix(source_location_id=20),
    ):
        assert result["allowed_purposes"] == [
            item["purpose"]
            for item in result["special_actions"]
            if item["allowed"]
        ]
