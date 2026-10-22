from fastapi import HTTPException

from api.warehouse.inbound import _require_new_receipt_reference


def test_new_inbound_receipt_requires_invoice_or_supplier_reference():
    for value in (None, "", "   ", "بدون فاتورة"):
        try:
            _require_new_receipt_reference(value)
        except HTTPException as exc:
            assert exc.status_code == 422
            assert exc.detail["code"] == "INBOUND_REFERENCE_REQUIRED"
        else:
            raise AssertionError(f"{value!r} should be rejected")


def test_new_inbound_receipt_reference_is_trimmed_and_preserved():
    assert _require_new_receipt_reference("  INV-2026-77  ") == "INV-2026-77"
