"""Exact vehicle-scoped Stocktake scope and human count-sheet projection."""
from sqlalchemy import and_, select

from models import ProductVariant, StocktakeLine, StocktakeSession
from services import acquire_inventory_location_guard

from .activation import require_m04_schema
from .application import require_capability
from .contracts import MAX_LINES, CustodyRejected
from .inventory_integration import lock_canonical_recon_vehicles
from .resolution import session_responsibilities
from .review_evidence import recount_line_key


async def variance_scope(db, *, access, session_id, vehicle_id, capability, lock):
    await require_m04_schema(db)
    await require_capability(access, "settlement.read" if capability == "stocktake.review" else "settlement.execute")
    work, vehicles = await session_responsibilities(
        db, company_id=access.company_id, session_id=session_id, lock_session=lock,
    )
    vehicle = next((v for v in vehicles if v.vehicle_id == vehicle_id), None)
    if vehicle is None:
        raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND", status=404)
    await require_capability(access, "inventory.read", vehicle.location_id)
    await require_capability(access, capability, vehicle.location_id)
    if lock:
        await lock_canonical_recon_vehicles(db, company_id=access.company_id, session_id=session_id)
        await acquire_inventory_location_guard(db, access.company_id, vehicle.location_id, exclusive=True)
    query = select(StocktakeSession).where(
        StocktakeSession.company_id == access.company_id, StocktakeSession.related_work_session_id == session_id,
        StocktakeSession.location_id == vehicle.location_id, StocktakeSession.stocktake_type == "VEHICLE_RECON",
        StocktakeSession.status != "CANCELLED",
    ).limit(2).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    recons = (await db.scalars(query)).all()
    if len(recons) != 1:
        raise CustodyRejected("NO_SETTLEMENT_VARIANCE_TO_REVIEW")
    return work, vehicle, recons[0]


async def internal_count_rows(db, *, recon, vehicle):
    found = (await db.execute(select(
        StocktakeLine.product_variant_id, StocktakeLine.batch_id, StocktakeLine.stock_status,
        ProductVariant.base_uom_id,
    ).join(ProductVariant, and_(ProductVariant.company_id == StocktakeLine.company_id,
                               ProductVariant.id == StocktakeLine.product_variant_id)).where(
        StocktakeLine.company_id == recon.company_id, StocktakeLine.stocktake_session_id == recon.id,
    ).order_by(StocktakeLine.id).limit(MAX_LINES + 1))).mappings().all()
    if len(found) > MAX_LINES:
        raise CustodyRejected("SETTLEMENT_CUSTODY_TOO_LARGE")
    return {recount_line_key(recon=recon, vehicle=vehicle, row=r): r for r in found}
