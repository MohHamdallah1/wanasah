"""Pending Visit lifecycle shared by single and grouped Dispatch shortages.

The shortage itself is removable only while pending. A pending emergency Visit is
retained as historical evidence: remove its emergency flag when an active route
still owns its zone, otherwise cancel the pending Visit (never hard-delete it).
"""
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import DispatchRoute, ShortageRequest, Visit


def ensure_shortage_pending_visit(
    db: AsyncSession, *, company_id: int, driver_id: int, shop,
    operational_date, existing: Visit | None,
) -> Visit:
    """Attach an eligible shortage to the one locked Pending owner Visit."""
    if existing is None:
        existing = Visit(
            company_id=company_id,
            driver_id=driver_id,
            shop_id=int(shop.id),
            operational_date=operational_date,
            status="Pending",
            sequence=shop.sequence if shop.sequence is not None else 999,
            is_emergency=True,
        )
        db.add(existing)
    else:
        existing.is_emergency = True
    return existing


async def settle_shortage_pending_visit(
    db: AsyncSession, *, company_id: int, shop, driver_id: int,
) -> None:
    """Preserve the existing DELETE /dispatch/shortages/{id} Visit semantics.

    Caller owns the transaction, has locked the Zone and Shop, and holds the
    company/shop advisory lock. Only call after deleted rows have been flushed.
    """
    shop_id = int(shop.id)
    remaining = int((await db.execute(
        select(func.count(ShortageRequest.id)).filter(
            ShortageRequest.company_id == company_id,
            ShortageRequest.shop_id == shop_id,
            ShortageRequest.driver_id == driver_id,
            ShortageRequest.status == "pending",
        )
    )).scalar() or 0)
    if remaining:
        return

    pending_emergency = (await db.execute(
        select(Visit).filter(
            Visit.company_id == company_id,
            Visit.shop_id == shop_id,
            Visit.driver_id == driver_id,
            Visit.status == "Pending",
            Visit.is_emergency.is_(True),
        ).order_by(Visit.id.asc()).with_for_update()
    )).scalars().all()
    active_route = (await db.execute(
        select(DispatchRoute).filter(
            DispatchRoute.company_id == company_id,
            DispatchRoute.driver_id == driver_id,
            DispatchRoute.status == "active",
        ).order_by(DispatchRoute.id.asc()).limit(1)
    )).scalars().first()
    for visit in pending_emergency:
        if active_route is not None and int(active_route.zone_id) == int(shop.zone_id or 0):
            visit.is_emergency = False
        else:
            visit.status = "Cancelled"
            visit.is_emergency = False
            visit.work_session_id = None
