"""Backend-owned canonical base quantity contract for Dispatch Route Launch."""
from __future__ import annotations

from decimal import Decimal
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.uom_authority import UomAuthorityError, VariantUomAuthority, load_variant_uom_authorities
from models import InventoryBalance, ProductBatch, ProductVariant, UOM
from quantity import canonical_quantity
from services import InventoryMutationError, allocate_fefo_inventory_batch


def canonical_route_delta(*, current: Decimal, target: Decimal, authority: VariantUomAuthority) -> Decimal:
    """No carton multiplication: the current and target are both in the canonical base unit."""
    if target != 0:
        authority.validate_canonical_total(target, field_name="inventory_base")
    return target - current


def canonical_adjustment_target(
    *, current: Decimal, pending: Decimal, delta: Decimal, authority: VariantUomAuthority,
) -> Decimal:
    """An in-route delta extends current custody plus already-pending handshakes."""
    authority.validate_canonical_total(abs(delta), field_name="delta_base")
    target = current + pending + delta
    if current + pending < 0 or target < 0:
        raise UomAuthorityError("DISPATCH_ADJUSTMENT_NEGATIVE", "Resulting load cannot be negative.")
    if target:
        authority.validate_canonical_total(target, field_name="target_base_quantity")
    return target


async def route_vehicle_base_totals(db: AsyncSession, *, company_id: int, location_id: int, all_statuses: bool = False):
    rows = (await db.execute(
        select(InventoryBalance.product_variant_id,
               func.sum(InventoryBalance.on_hand_quantity),
               func.sum(InventoryBalance.reserved_quantity))
        .where(InventoryBalance.company_id == company_id,
               InventoryBalance.location_id == location_id,
               True if all_statuses else InventoryBalance.stock_status == "AVAILABLE",
               or_(InventoryBalance.on_hand_quantity > 0, InventoryBalance.reserved_quantity > 0))
        .group_by(InventoryBalance.product_variant_id)
        .order_by(InventoryBalance.product_variant_id.asc())
    )).all()
    return {int(pid): (Decimal(on_hand or 0), Decimal(reserved or 0))
            for pid, on_hand, reserved in rows}


async def allocate_route_base_batches(
    db: AsyncSession, *, company_id: int, location_id: int,
    product_variant_id: int, quantity: Decimal, as_of_date, require_sellable: bool,
):
    if quantity <= 0:
        return []
    if require_sellable:
        allocations = await allocate_fefo_inventory_batch(
            db, company_id=company_id, location_id=location_id,
            requests={product_variant_id: quantity},
            as_of_date=as_of_date, require_full=True,
        )
        return [(int(batch_id), Decimal(qty))
                for batch_id, qty in allocations.get(product_variant_id, [])]

    rows = (await db.execute(
        select(InventoryBalance.batch_id,
               InventoryBalance.on_hand_quantity,
               InventoryBalance.reserved_quantity)
        .join(ProductBatch, and_(
            ProductBatch.company_id == InventoryBalance.company_id,
            ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
            ProductBatch.id == InventoryBalance.batch_id))
        .where(InventoryBalance.company_id == company_id,
               InventoryBalance.location_id == location_id,
               InventoryBalance.product_variant_id == product_variant_id,
               InventoryBalance.stock_status == "AVAILABLE",
               InventoryBalance.on_hand_quantity > InventoryBalance.reserved_quantity)
        .order_by(ProductBatch.expiry_date.asc(), ProductBatch.id.asc(), InventoryBalance.id.asc())
        .with_for_update()
    )).all()
    remaining = quantity
    result = []
    for batch_id, on_hand, reserved in rows:
        free = Decimal(on_hand or 0) - Decimal(reserved or 0)
        if free <= 0:
            continue
        take = min(free, remaining)
        result.append((int(batch_id), take))
        remaining -= take
        if remaining == 0:
            break
    if remaining:
        raise InventoryMutationError(f"Insufficient vehicle stock for product {product_variant_id}.")
    return result


async def allocate_route_return_batches(db, *, company_id, location_id, product_variant_id, quantity):
    """Deterministic free custody allocation, retaining each source stock bucket."""
    rows = (await db.execute(select(
        InventoryBalance.batch_id, InventoryBalance.stock_status,
        InventoryBalance.on_hand_quantity, InventoryBalance.reserved_quantity,
    ).join(ProductBatch, and_(
        ProductBatch.company_id == InventoryBalance.company_id,
        ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
        ProductBatch.id == InventoryBalance.batch_id))
      .where(InventoryBalance.company_id == company_id, InventoryBalance.location_id == location_id,
             InventoryBalance.product_variant_id == product_variant_id,
             InventoryBalance.on_hand_quantity > InventoryBalance.reserved_quantity)
      .order_by(ProductBatch.expiry_date.asc(), ProductBatch.id.asc(), InventoryBalance.stock_status.asc(),
                InventoryBalance.id.asc()).with_for_update())).all()
    remaining, allocations = quantity, []
    for batch_id, status, on_hand, reserved in rows:
        take = min(Decimal(on_hand) - Decimal(reserved), remaining)
        if take > 0:
            allocations.append(dict(product_variant_id=product_variant_id, batch_id=int(batch_id),
                                   quantity=take, stock_status=str(status)))
            remaining -= take
        if not remaining:
            break
    if remaining:
        raise InventoryMutationError("Insufficient free vehicle custody for this return.")
    return allocations


async def route_load_uom_metadata(db: AsyncSession, *, company_id: int, variant_ids):
    """Exact base UOM plus one uniquely reachable commercial UOM when available."""
    ids = sorted({int(v) for v in variant_ids})
    if not ids:
        return {}
    rows = (await db.execute(
        select(ProductVariant.id, ProductVariant.base_uom_id,
               ProductVariant.quantity_scale, ProductVariant.quantity_step,
               UOM.name, UOM.code)
        .join(UOM, UOM.id == ProductVariant.base_uom_id)
        .where(ProductVariant.company_id == company_id, ProductVariant.id.in_(ids))
        .order_by(ProductVariant.id.asc())
    )).all()
    if len(rows) != len(ids):
        raise UomAuthorityError("UOM_VARIANT_NOT_FOUND", "Product/base UOM not found in company.")
    authorities = await load_variant_uom_authorities(db, company_id=company_id, variant_ids=ids)
    commercial = {}
    for pid in ids:
        authority = authorities[pid]
        candidates = [(uom_id, factor) for uom_id, factor in authority.factors_to_base.items()
                      if uom_id != authority.base_uom_id and factor > 1 and factor.denominator == 1]
        if len(candidates) == 1:
            commercial[pid] = candidates[0]
    candidate_ids = sorted({candidate[0] for candidate in commercial.values()})
    names = dict((await db.execute(select(UOM.id, UOM.name).where(
        UOM.id.in_(candidate_ids)))).all()) if candidate_ids else {}
    result = {}
    for pid, base_id, scale, step, name, code in rows:
        candidate = commercial.get(int(pid))
        display = candidate if candidate and candidate[0] in names else None
        result[int(pid)] = {
            "base_uom_id": int(base_id),
            "base_uom_code": str(code),
            "base_uom_name": str(name),
            "quantity_scale": int(scale),
            "quantity_step": canonical_quantity(step),
            "display_uom_name": str(names[display[0]]) if display else None,
            "display_factor_to_base": str(display[1].numerator) if display else None,
        }
    return result
