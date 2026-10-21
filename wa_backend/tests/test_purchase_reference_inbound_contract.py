"""Historical transport compatibility and order-independent business selection."""
import ast
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest

from api.warehouse._shared import _stable_request_hash
from domains.inventory_costing.purchase_reference.public import PurchaseReferenceError
from domains.inventory_costing.purchase_reference.inbound import (
    receipt_hash_arguments, select_reference_pairs,
)
from schemas import InboundPurchaseReferenceSelection, UpgradedInboundRequest


def payload(**changes):
    body = dict(request_id=UUID("11111111-1111-4111-8111-111111111111"), supplier_id=3,
                location_id=4, items=[
                    dict(product_variant_id=7, quantity="1", uom_id=1, unit_cost="2"),
                    dict(product_variant_id=7, quantity="1", uom_id=2, unit_cost="24"),
                ])
    body.update(changes)
    return UpgradedInboundRequest(**body)


@pytest.mark.parametrize("supplier", [None, 3])
def test_historical_request_hash_remains_byte_compatible(supplier):
    request = payload(supplier_id=supplier)
    old_body = request.model_dump(mode="json", exclude={"purchase_reference_selections"})
    old = SimpleNamespace(model_dump=lambda **kw: {
        key: value for key, value in old_body.items() if key not in kw["exclude"]
    })
    legacy = _stable_request_hash(old, exclude_fields={"supplier_id"} if supplier is None else None)
    assert _stable_request_hash(request, **receipt_hash_arguments(request)) == legacy
    assert _stable_request_hash(request.model_copy(update={"items": list(reversed(request.items))}),
                                **receipt_hash_arguments(request)) == legacy
    assert _stable_request_hash(payload(supplier_id=supplier, purchase_reference_selections=[]),
                                **receipt_hash_arguments(request)) == legacy


def test_selection_is_canonical_and_cannot_rely_on_item_or_selection_order():
    a = dict(product_variant_id=7, uom_id=2, unit_cost="24")
    b = dict(product_variant_id=8, uom_id=1, unit_cost="3")
    request = payload(purchase_reference_selections=[a, b])
    reversed_request = payload(items=list(reversed(request.items)),
                               purchase_reference_selections=[b, a])
    assert _stable_request_hash(request, **receipt_hash_arguments(request)) == _stable_request_hash(
        reversed_request, **receipt_hash_arguments(reversed_request))
    assert _stable_request_hash(request, **receipt_hash_arguments(request)) != _stable_request_hash(
        payload(), **receipt_hash_arguments(payload()))
    pairs = {7: {(1, Decimal("2")), (2, Decimal("24"))}}
    with pytest.raises(PurchaseReferenceError) as error:
        select_reference_pairs(pairs, None)
    assert error.value.code == "INBOUND_REFERENCE_SELECTION_REQUIRED"
    chosen = InboundPurchaseReferenceSelection(**a)
    assert select_reference_pairs(pairs, [chosen]) == {7: (2, Decimal("24"))}
    with pytest.raises(PurchaseReferenceError):
        select_reference_pairs(pairs, [chosen, chosen])
    with pytest.raises(PurchaseReferenceError):
        select_reference_pairs(pairs, [InboundPurchaseReferenceSelection(
            product_variant_id=7, uom_id=2, unit_cost="25")])


def test_receipt_guard_and_transaction_ownership_are_explicit():
    root = Path(__file__).parents[1]
    source = (root / "api/warehouse/inbound.py").read_text(encoding="utf-8")
    receipt = source[source.index("async def warehouse_inbound("):]
    assert receipt.index("if replay_response is not None") < receipt.index("await begin_receipt_reference")
    assert receipt.index("await begin_receipt_reference") < receipt.index("await select_active_supplier")
    assert receipt.index("await write_receipt_references") < receipt.index("complete_idempotent_operation")
    assert receipt.count("await db.commit()") == 1
    domain = ast.parse((root / "domains/inventory_costing/purchase_reference/inbound.py").read_text(encoding="utf-8"))
    calls = {node.func.attr for node in ast.walk(domain)
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
    assert not calls & {"commit", "rollback"}
