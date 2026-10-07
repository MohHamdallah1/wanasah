"""Executable ownership contract for the new V1 authority."""
import ast
from pathlib import Path

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
