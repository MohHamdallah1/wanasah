"""Authenticated FIELD physical VEHICLE stock; independent of any route/session.

The current signed VehicleCustodyEpoch, never a DispatchRoute assignment,
authorizes one canonical location. A changing custody or physical snapshot
invalidates the signed pagination cursor; unknown is never rendered as zero.
"""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import and_, func, or_, select

from models import InventoryBalance, ProductVariant, UOM
from domains.auth_sessions.context import FieldRequestContext
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.dispatch.route_execution.custody.snapshot import read_vehicle_state
from domains.dispatch.route_execution.custody.proofs import CustodyRejected
from quantity import QUANTITY_MAX, canonical_quantity

from .contracts import FieldContractError
from .tokens import open_reference, owner_binding, require_binding, seal_reference

_PURPOSE = "FIELD_VEHICLE_STOCK_CURSOR"
_NON_SELLABLE = frozenset(
    {"QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING"}
)
_ALLOWED = _NON_SELLABLE | {"AVAILABLE"}


async def _authorized_vehicle(db, *, context: FieldRequestContext):
    """At most one currently signed FIELD vehicle; no user-supplied vehicle ID.

    Never enumerate other representatives' vehicles or silently select among
    multiple independently accepted vehicles. Auth/capability are enforced by
    the caller's FIELD-only dependencies before this query executes.
    """
    epochs = (await db.scalars(
        select(VehicleCustodyEpoch).where(
            VehicleCustodyEpoch.company_id == context.company_id,
            VehicleCustodyEpoch.custodian_principal_id == context.principal_id,
            VehicleCustodyEpoch.field_representative_id == context.representative_id,
            VehicleCustodyEpoch.custodian_kind == "FIELD_REPRESENTATIVE",
            VehicleCustodyEpoch.state == "ACCEPTED",
            VehicleCustodyEpoch.ended_at.is_(None),
        ).order_by(VehicleCustodyEpoch.id.desc()).limit(2)
    )).all()
    if not epochs:
        raise FieldContractError(
            "FIELD_VEHICLE_CUSTODY_NOT_ACCEPTED",
            "No signed, current vehicle custody belongs to this FIELD identity.",
            status_code=403,
        )
    if len(epochs) != 1:
        raise FieldContractError(
            "FIELD_VEHICLE_CUSTODY_AMBIGUOUS",
            "Several accepted vehicles require an explicit authorized choice.",
            status_code=409,
        )
    epoch = epochs[0]
    try:
        state = await read_vehicle_state(
            db, int(context.company_id), int(epoch.vehicle_id),
        )
    except CustodyRejected as exc:
        raise FieldContractError(
            exc.code, "Current vehicle stock cannot be verified.",
            status_code=exc.status,
        ) from exc
    if (
        state.epoch is None
        or int(state.epoch.id) != int(epoch.id)
        or state.epoch.state != "ACCEPTED"
        or state.epoch.custodian_kind != "FIELD_REPRESENTATIVE"
        or state.epoch.custodian_principal_id != context.principal_id
        or state.epoch.field_representative_id != context.representative_id
        or state.location_id != int(epoch.vehicle_location_id)
    ):
        raise FieldContractError(
            "FIELD_VEHICLE_CUSTODY_STALE",
            "Signed custody or the canonical physical vehicle location changed.",
            status_code=409,
        )
    # A positive but unsupported/negative physical balance is not a verified
    # empty stock list. Check the entire BOUNDED signed snapshot before paging.
    for line in state.lines:
        try:
            amount = Decimal(line["on_hand"])
        except (ValueError, TypeError, ArithmeticError) as exc:
            raise FieldContractError(
                "FIELD_VEHICLE_STOCK_INVALID", "Invalid physical stock evidence.",
            ) from exc
        if not amount.is_finite() or amount < 0 or amount > QUANTITY_MAX:
            raise FieldContractError(
                "FIELD_VEHICLE_STOCK_INVALID", "Invalid physical stock evidence.",
            )
        if amount > 0 and line["status"] not in _ALLOWED:
            raise FieldContractError(
                "FIELD_VEHICLE_STOCK_STATUS_UNSUPPORTED",
                "Physical vehicle stock has an unsupported status.",
            )
    return epoch, state


async def read_current_vehicle_stock(
    db, *, context: FieldRequestContext, driver_id: int,
    limit: int = 100, cursor: str | None = None,
) -> dict:
    """One paginated vehicle snapshot, two distinct categories and no cost data."""
    if type(limit) is not int or not 1 <= limit <= 200:
        raise FieldContractError(
            "FIELD_VEHICLE_STOCK_PAGE_INVALID",
            "Invalid vehicle stock page size.", status_code=422,
        )
    epoch, state = await _authorized_vehicle(db, context=context)
    binding = {
        **owner_binding(context, driver_id),
        "vehicle": int(epoch.vehicle_id),
        "location": int(state.location_id),
        "epoch": int(epoch.id),
        "revision": int(epoch.context_revision),
        "snapshot": state.stock_snapshot,
    }
    after = None
    if cursor is not None:
        value = open_reference(_PURPOSE, cursor)
        require_binding(value, binding)
        after = value.get("after")
        if (
            not isinstance(after, list) or len(after) != 2
            or type(after[0]) is not int or after[0] <= 0
            or type(after[1]) is not str or after[1] not in _ALLOWED
        ):
            raise FieldContractError(
                "FIELD_VEHICLE_STOCK_PAGE_INVALID",
                "Invalid vehicle stock cursor.", status_code=422,
            )
    query = (
        select(
            InventoryBalance.product_variant_id,
            ProductVariant.name, InventoryBalance.stock_status,
            UOM.code, ProductVariant.packs_per_carton,
            func.sum(InventoryBalance.on_hand_quantity),
        )
        .outerjoin(ProductVariant, and_(
            ProductVariant.company_id == InventoryBalance.company_id,
            ProductVariant.id == InventoryBalance.product_variant_id,
        ))
        .outerjoin(UOM, UOM.id == ProductVariant.base_uom_id)
        .where(
            InventoryBalance.company_id == context.company_id,
            InventoryBalance.location_id == state.location_id,
            InventoryBalance.on_hand_quantity > 0,
        )
    )
    if after is not None:
        query = query.where(or_(
            InventoryBalance.product_variant_id > after[0],
            and_(
                InventoryBalance.product_variant_id == after[0],
                InventoryBalance.stock_status > after[1],
            ),
        ))
    rows = (await db.execute(
        query.group_by(
            InventoryBalance.product_variant_id,
            ProductVariant.name, InventoryBalance.stock_status,
            UOM.code, ProductVariant.packs_per_carton,
        ).order_by(
            InventoryBalance.product_variant_id,
            InventoryBalance.stock_status,
        ).limit(limit + 1)
    )).all()
    sellable, non_sellable = [], []
    for variant_id, name, status, uom, packs, amount in rows[:limit]:
        if not name or not uom or status not in _ALLOWED:
            raise FieldContractError(
                "FIELD_VEHICLE_STOCK_METADATA_INVALID",
                "Physical vehicle inventory has invalid product metadata.",
            )
        quantity = Decimal(amount)
        if not quantity.is_finite() or not 0 < quantity <= QUANTITY_MAX:
            raise FieldContractError(
                "FIELD_VEHICLE_STOCK_INVALID",
                "Physical vehicle inventory has invalid quantity evidence.",
            )
        line = {
            "product_variant_id": int(variant_id),
            "product_name": name,
            "stock_status": status,
            "uom_code": uom,
            "quantity": canonical_quantity(quantity),
        }
        if status == "AVAILABLE":
            # Commercial UOM is metadata, never an inferred physical count.
            if packs is None or int(packs) <= 0:
                raise FieldContractError(
                    "FIELD_VEHICLE_STOCK_UOM_INVALID",
                    "Commercial unit mapping is unavailable.",
                )
            line["packs_per_carton"] = int(packs)
            sellable.append(line)
        else:
            non_sellable.append(line)
    next_cursor = None
    if len(rows) > limit:
        variant_id, _name, status, *_rest = rows[limit - 1]
        next_cursor = seal_reference(_PURPOSE, {
            **binding, "after": [int(variant_id), str(status)],
        })
    return {
        "status": "VERIFIED",
        "source": "INVENTORY_BALANCE",
        "vehicle_id": int(epoch.vehicle_id),
        "vehicle_location_id": int(state.location_id),
        "custody_epoch_id": int(epoch.id),
        "context_revision": int(epoch.context_revision),
        "stock_snapshot": state.stock_snapshot,
        "sellable_items": sellable,
        "non_sellable_items": non_sellable,
        "next_cursor": next_cursor,
    }
