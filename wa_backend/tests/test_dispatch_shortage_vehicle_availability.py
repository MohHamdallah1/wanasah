"""#1057: bounded read-only signed custody calculations; unknown is not zero."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from api.dispatch_shortage_availability import _sellable_by_variant, _unknown


def _line(variant, batch, on_hand, reserved="0", status="AVAILABLE"):
    return {
        "variant_id": variant, "batch_id": batch, "status": status,
        "on_hand": on_hand, "reserved": reserved,
    }


def test_sellable_quote_subtracts_reservations_expiry_and_non_sellable():
    today = date(2026, 11, 19)
    batches = {
        1: (10, today + timedelta(days=2), "RELEASED"),
        2: (10, today - timedelta(days=1), "RELEASED"),
        3: (10, today + timedelta(days=2), "RECALLED"),
        4: (11, None, "RELEASED"),
        5: (11, today, "RELEASED"),
    }
    lines = [
        _line(10, 1, "15", "3"),
        _line(10, 2, "8"),
        _line(10, 3, "6"),
        _line(10, 1, "5", status="DAMAGED"),
        _line(11, 4, "3.5", "1.5"),
        _line(11, 5, "2"),
    ]
    result = _sellable_by_variant(
        lines=lines, batches=batches, today=today, product_ids={10, 11, 12},
    )
    assert result == {10: Decimal(12), 11: Decimal(4), 12: Decimal(0)}


@pytest.mark.parametrize("line,batches", [
    (_line(10, 1, "2", "3"), {1: (10, None, "RELEASED")}),
    (_line(10, 1, "-1"), {1: (10, None, "RELEASED")}),
    (_line(10, 1, "NaN"), {1: (10, None, "RELEASED")}),
    (_line(10, 1, "Infinity"), {1: (10, None, "RELEASED")}),
    (_line(10, 1, "1"), {}),
    (_line(10, 1, "1"), {1: (11, None, "RELEASED")}),
])
def test_unverifiable_physical_evidence_never_becomes_zero(line, batches):
    assert _sellable_by_variant(
        lines=[line], batches=batches, today=date(2026, 11, 19), product_ids={10},
    ) is None


def test_unknown_custody_has_no_misleading_zero_quantities():
    assert _unknown("NO_ACCEPTED_VEHICLE_CUSTODY") == {
        "status": "UNKNOWN", "reason": "NO_ACCEPTED_VEHICLE_CUSTODY", "items": [],
    }
