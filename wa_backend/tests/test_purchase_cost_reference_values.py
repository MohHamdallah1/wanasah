"""Exact-money contract and dependency boundary checks without database writes."""
import ast
from decimal import Decimal
from fractions import Fraction
from pathlib import Path

import pytest

from domains.inventory_costing.purchase_reference.errors import PurchaseReferenceError
from domains.inventory_costing.purchase_reference.values import amount_value, convert_exact


@pytest.mark.parametrize("value", [None, True, 1.2, "NaN", "Infinity", "-1", "1.0000001", "100000000000000"])
def test_invalid_amount_fails_closed(value):
    with pytest.raises(ValueError):
        amount_value(value)


def test_exact_purchase_uom_conversion_and_zero():
    assert convert_exact(Decimal("24"), source_factor=Fraction(12), target_factor=Fraction(1)) == Decimal("2")
    assert convert_exact(Decimal("2"), source_factor=Fraction(1), target_factor=Fraction(12)) == Decimal("24")
    assert amount_value("0") == Decimal("0.000000")
    with pytest.raises(PurchaseReferenceError) as error:
        convert_exact(Decimal("1"), source_factor=Fraction(3), target_factor=Fraction(1))
    assert error.value.code == "PURCHASE_REFERENCE_PRECISION_LOSS"


def test_no_financial_mutation_or_transport_dependencies_in_application_service():
    path = Path(__file__).parents[1] / "domains/inventory_costing/purchase_reference/service.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not imports & {"services", "domains.pricing.publishing", "domains.inventory_costing.service", "fastapi"}
    calls = {node.func.attr for node in ast.walk(tree)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls & {"commit", "rollback"}
