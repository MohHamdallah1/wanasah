"""Tenant/assignment reads for FIELD prerequisites; operational IDs are locators."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import and_, or_, select
from models import DispatchRoute, Shop, ShortageRequest, Visit, WorkSession
from domains.auth_sessions.context import FieldRequestContext
from domains.vehicles import resolve_vehicle_custody_location_id
from domains.taxation.core import TaxError, jurisdiction_chain, require_active_jurisdictions
from .contracts import FieldContractError


@dataclass(frozen=True)
class FieldWork:
    session: WorkSession
    route: DispatchRoute
    vehicle_location_id: int


async def owned_visit(db, *, context: FieldRequestContext, driver_id: int, visit_id: int):
    row = (await db.execute(
        select(Visit, Shop).join(Shop, and_(
            Shop.company_id == Visit.company_id, Shop.id == Visit.shop_id,
        )).where(
            Visit.company_id == context.company_id, Visit.id == visit_id,
            Visit.driver_id == driver_id, Shop.company_id == context.company_id,
        )
    )).one_or_none()
    if row is None:
        raise FieldContractError("FIELD_VISIT_NOT_FOUND", "Visit is unavailable.", status_code=404)
    return row


async def active_work(db, *, context: FieldRequestContext, driver_id: int) -> FieldWork:
    session = (await db.execute(select(WorkSession).where(
        WorkSession.company_id == context.company_id,
        WorkSession.driver_id == driver_id, WorkSession.end_time.is_(None),
    ).order_by(WorkSession.id.desc()).limit(1))).scalar_one_or_none()
    if session is None:
        raise FieldContractError("FIELD_SESSION_REQUIRED", "Start the assigned work session.", status_code=403)
    if session.is_settled or session.inventory_reconciled_at is not None:
        raise FieldContractError("FIELD_SESSION_SEALED", "This custody session is sealed.")
    route = (await db.execute(select(DispatchRoute).where(
        DispatchRoute.company_id == context.company_id,
        DispatchRoute.driver_id == driver_id,
        DispatchRoute.work_session_id == session.id,
    ).order_by(DispatchRoute.id.asc()).limit(1))).scalar_one_or_none()
    if route is None or route.vehicle_id is None:
        raise FieldContractError("FIELD_ROUTE_REQUIRED", "The session has no assigned vehicle route.")
    location_id = await resolve_vehicle_custody_location_id(
        db, company_id=context.company_id, vehicle_id=int(route.vehicle_id),
        require_active=True,
    )
    return FieldWork(session, route, int(location_id))


async def assigned_visit(db, *, context, driver_id: int, visit_id: int):
    visit, shop = await owned_visit(db, context=context, driver_id=driver_id, visit_id=visit_id)
    work = await active_work(db, context=context, driver_id=driver_id)
    if (visit.status == "Cancelled" or shop.is_archived
            or visit.work_session_id not in (None, work.session.id)):
        raise FieldContractError("FIELD_VISIT_UNAVAILABLE", "The visit is not available in this session.")
    if shop.zone_id != work.route.zone_id and not visit.is_emergency:
        shortage = (await db.execute(select(ShortageRequest.id).where(
            ShortageRequest.company_id == context.company_id,
            ShortageRequest.shop_id == shop.id, ShortageRequest.status == "pending",
            or_(ShortageRequest.driver_id.is_(None), ShortageRequest.driver_id == driver_id),
        ).limit(1))).scalar_one_or_none()
        if shortage is None:
            raise FieldContractError("FIELD_VISIT_OUTSIDE_ASSIGNMENT", "Visit is outside assigned work.", status_code=403)
    return visit, shop, work


def pending_shop_commercial_state() -> dict:
    # No geographic/default inference: Backoffice edits the existing Shop
    # jurisdiction through canonical tax authority, then FIELD refreshes this read.
    return {
        "status": "ACTION_REQUIRED", "sale_ready": False,
        "code": "SHOP_TAX_JURISDICTION_REQUIRED",
        "required_action": "BACKOFFICE_SET_SHOP_TAX_JURISDICTION",
    }


async def shop_commercial_state(db, *, company_id: int, shop) -> dict:
    if shop.tax_jurisdiction_id is None:
        return pending_shop_commercial_state()
    try:
        chain = await jurisdiction_chain(
            db, company_id=company_id, jurisdiction_id=int(shop.tax_jurisdiction_id),
        )
        await require_active_jurisdictions(
            db, company_id=company_id, jurisdiction_ids=chain,
        )
    except TaxError:
        return {
            **pending_shop_commercial_state(),
            "code": "SHOP_TAX_JURISDICTION_REVIEW_REQUIRED",
        }
    return {"status": "READY", "sale_ready": True, "code": None, "required_action": None}
