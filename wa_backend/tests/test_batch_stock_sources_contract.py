import pytest
from pydantic import ValidationError

from schemas import WarehouseBatchStockSourcesResponse


def payload():
    return {
        "batch_id": 41,
        "product_variant_id": 118,
        "batch_number": "LOT-41",
        "production_date": "2026-09-01",
        "expiry_date": "2027-09-01",
        "disposition": "QUARANTINED",
        "disposition_reason": "Expiry concern",
        "disposition_revision": 3,
        "days_to_expiry": 332,
        "base_uom_id": 7,
        "base_uom_code": "EA",
        "operational_hold": "NONE",
        "sources": [
            {
                "location_id": 901,
                "location_name": "Vehicle 12",
                "location_type": "VEHICLE",
                "can_send": True,
                "statuses": [
                    {
                        "stock_status": "QUARANTINED",
                        "on_hand_quantity": "12.000000",
                        "reserved_quantity": "2.000000",
                        "movable_quantity": "10.000000",
                        "terminal_actions": [
                            {
                                "action": "CONFIRM_VENDOR_HANDOVER",
                                "allowed": True,
                                "eligible_quantity": "4.000000",
                                "reason_code": "ALLOWED",
                            }
                        ],
                        "reservation_evidence": {
                            "coverage": "UNRESOLVED",
                            "reason": "OWNER_EVIDENCE_UNAVAILABLE",
                            "owners": [],
                            "unattributed_quantity": "2.000000",
                            "owners_truncated": False,
                        },
                    }
                ],
            }
        ],
    }


def test_stock_sources_contract_supports_vehicle_only_batch_action_context():
    result = WarehouseBatchStockSourcesResponse.model_validate(payload())

    assert result.batch_id == 41
    assert result.batch_number == "LOT-41"
    assert result.disposition == "QUARANTINED"
    assert result.disposition_revision == 3
    assert result.base_uom_code == "EA"
    assert len(result.sources) == 1
    assert result.sources[0].location_type == "VEHICLE"
    action = result.sources[0].statuses[0].terminal_actions[0]
    assert action.action == "CONFIRM_VENDOR_HANDOVER"
    assert action.allowed is True
    assert action.eligible_quantity == 4


def test_stock_sources_contract_rejects_invalid_action_revision():
    invalid = payload()
    invalid["disposition_revision"] = 0

    with pytest.raises(ValidationError):
        WarehouseBatchStockSourcesResponse.model_validate(invalid)
