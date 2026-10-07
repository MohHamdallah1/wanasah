"""Executable ownership contract for the new V1 authority."""
import ast
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from domains.suppliers.contracts import SupplierCreate, SupplierUpdate, SupplierView

ROOT = Path(__file__).resolve().parents[1]


def test_inventory_consumes_only_public_supplier_contracts():
    consumers = [ROOT / "api/warehouse/inbound.py", ROOT / "api/warehouse/whole_product_quality.py",
                 ROOT / "domains/inventory_supplier_evidence.py"]
    for path in consumers:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("domains.suppliers"):
                assert node.module in {"domains.suppliers.public", "domains.suppliers.contracts"}, path


def test_supplier_storage_and_commands_are_transport_independent():
    for name in ("models", "repository", "application", "contracts", "errors"):
        source = (ROOT / f"domains/suppliers/{name}.py").read_text(encoding="utf-8")
        assert "from fastapi" not in source
        assert "InventoryMovement(" not in source and "InventoryBalance(" not in source


def test_supplier_is_never_a_global_product_attribute():
    tree = ast.parse((ROOT / "models.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name in {"Product", "ProductVariant"}:
            assert "supplier_id" not in ast.unparse(node)

def test_supplier_writes_require_phone_and_primary_address_but_legacy_views_remain_readable():
    valid = dict(name="Supplier", phone="0790000000", address="Main address")
    assert SupplierCreate(request_id=uuid4(), **valid).phone == "0790000000"
    assert SupplierUpdate(request_id=uuid4(), expected_version=1, **valid).address == "Main address"
    with pytest.raises(ValidationError):
        SupplierCreate(request_id=uuid4(), name="Supplier", address="Main address")
    with pytest.raises(ValidationError):
        SupplierCreate(request_id=uuid4(), name="Supplier", phone="0790000000")
    with pytest.raises(ValidationError):
        SupplierCreate(request_id=uuid4(), name="Supplier", phone="   ", address="Main address")
    legacy = SupplierView(
        id=1, name="Legacy supplier", phone=None, address=None, is_active=True, version=1,
        created_at="2026-10-07T00:00:00Z", updated_at="2026-10-07T00:00:00Z",
    )
    assert legacy.phone is None and legacy.address is None
