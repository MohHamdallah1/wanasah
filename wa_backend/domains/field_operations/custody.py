"""Bounded current non-sellable vehicle custody from InventoryBalance only."""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import and_, func, or_, select

from models import InventoryBalance, ProductVariant, UOM
from quantity import QUANTITY_MAX, canonical_quantity
from .contracts import FieldContractError
from .context import active_work
from .tokens import open_reference, owner_binding, require_binding, seal_reference

_PURPOSE = "FIELD_CUSTODY_CURSOR"
_STATUSES = ("QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING")


async def read_custody(db, *, context, driver_id, limit=100, cursor=None):
    if type(limit) is not int or not 1 <= limit <= 200:
        raise FieldContractError("FIELD_CUSTODY_PAGE_INVALID", "Invalid page size.", status_code=422)
    work = await active_work(db, context=context, driver_id=driver_id)
    binding = {**owner_binding(context, driver_id),
               "session": work.session.id, "location": work.vehicle_location_id}
    after = None
    if cursor:
        value = open_reference(_PURPOSE, cursor)
        require_binding(value, binding)
        after = value.get("after")
        if (not isinstance(after, list) or len(after) != 2 or type(after[0]) is not int
                or after[0] <= 0 or after[1] not in _STATUSES):
            raise FieldContractError("FIELD_CUSTODY_PAGE_INVALID", "Invalid page cursor.", status_code=422)
    query = select(
        InventoryBalance.product_variant_id, ProductVariant.name,
        InventoryBalance.stock_status, UOM.code,
        func.sum(InventoryBalance.on_hand_quantity),
    ).join(ProductVariant, and_(
        ProductVariant.company_id == InventoryBalance.company_id,
        ProductVariant.id == InventoryBalance.product_variant_id,
    )).join(UOM, UOM.id == ProductVariant.base_uom_id).where(
        InventoryBalance.company_id == context.company_id,
        InventoryBalance.location_id == work.vehicle_location_id,
        InventoryBalance.stock_status.in_(_STATUSES),
        InventoryBalance.on_hand_quantity > 0,
        ProductVariant.company_id == context.company_id,
    )
    if after is not None:
        query = query.where(or_(
            InventoryBalance.product_variant_id > after[0],
            and_(InventoryBalance.product_variant_id == after[0],
                 InventoryBalance.stock_status > after[1]),
        ))
    rows = (await db.execute(query.group_by(
        InventoryBalance.product_variant_id, ProductVariant.name,
        InventoryBalance.stock_status, UOM.code,
    ).order_by(InventoryBalance.product_variant_id, InventoryBalance.stock_status).limit(limit + 1))).all()
    result = []
    for variant_id, name, status, uom, amount in rows[:limit]:
        quantity = Decimal(amount)
        if not quantity.is_finite() or not 0 < quantity <= QUANTITY_MAX:
            raise FieldContractError("FIELD_CUSTODY_QUANTITY_INVALID", "Custody quantity is invalid.")
        result.append({
            "product_variant_id": variant_id, "product_name": name,
            "stock_status": status, "uom_code": uom,
            "quantity": canonical_quantity(quantity),
        })
    next_cursor = None
    if len(rows) > limit:
        last = result[-1]
        next_cursor = seal_reference(_PURPOSE, {
            **binding, "after": [last["product_variant_id"], last["stock_status"]],
        })
    return {"session_id": work.session.id, "items": result, "next_cursor": next_cursor}
