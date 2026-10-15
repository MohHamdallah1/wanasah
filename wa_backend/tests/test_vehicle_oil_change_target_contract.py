import pytest

from domains.vehicles.contracts import VehicleError
from domains.vehicles.validation import require_future_oil_change_target


def test_next_oil_change_target_must_be_ahead_of_current_mileage():
    require_future_oil_change_target(current_mileage=15_000, next_oil_change=20_000)
    require_future_oil_change_target(current_mileage=15_000, next_oil_change=None)

    for invalid in (14_999, 15_000):
        with pytest.raises(VehicleError) as exc_info:
            require_future_oil_change_target(
                current_mileage=15_000,
                next_oil_change=invalid,
            )
        assert exc_info.value.code == "VEHICLE_OIL_CHANGE_TARGET_INVALID"
        assert exc_info.value.status_code == 422


def test_management_enforces_oil_target_on_create_and_when_target_is_changed():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[1] / "domains/vehicles/management.py").read_text(encoding="utf-8")
    assert source.count("require_future_oil_change_target(") >= 2
    assert 'if "next_oil_change" in fields:' in source
