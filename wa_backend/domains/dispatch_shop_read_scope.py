"""D06 owner-approved company Shop masters and independent sensitive finance reads.

A warehouse is a *route's stock source*, never a Shop's permanent owner.
An ordinary warehouse-scoped dispatch.read sees only Shop rows with an actual
Visit bound to an active, currently authorized route; a Shop's Zone alone is
not a warehouse/assignment grant. Never infer a join from Zone->Warehouse.
"""
from __future__ import annotations

from sqlalchemy import and_, or_, select
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from dispatch_access import route_filter
from models import DispatchRoute, Shop, Visit, Zone


async def company_shop_directory(access: BackofficeCapabilityAccess) -> bool:
    """Only a COMPANY role's dispatch.read grants entire Shop/Zone directory."""
    return bool(await access.db.scalar(select(access.allows("dispatch.read"))))


async def can_read_shop_financials(access: BackofficeCapabilityAccess) -> bool:
    """A separate COMPANY-ONLY permission; no dispatch/settlement inheritance."""
    return bool(await access.db.scalar(select(access.allows("shop.financial.read"))))


def assigned_shop_filter(access: BackofficeCapabilityAccess):
    """Correlated existence of a genuine Visit on a currently readable ACTIVE route.

    Requires canonical route source-warehouse AND vehicle-custody visibility.
    Driver, company, Route, Zone/emergency and WorkSession bindings must agree.
    A Zone match by itself never confers Shop access.
    """
    return (
        select(1)
        .select_from(Visit)
        .join(
            DispatchRoute,
            and_(
                DispatchRoute.company_id == Visit.company_id,
                DispatchRoute.driver_id == Visit.driver_id,
                DispatchRoute.status == "active",
                or_(DispatchRoute.zone_id == Shop.zone_id,
                    Visit.is_emergency.is_(True)),
                or_(Visit.work_session_id.is_(None),
                    DispatchRoute.work_session_id == Visit.work_session_id),
            ),
        )
        .where(
            Visit.company_id == access.company_id,
            Visit.shop_id == Shop.id,
            Shop.company_id == access.company_id,
            route_filter(access, "dispatch.read"),
        )
        .exists()
    )


def visible_shop_filter(access: BackofficeCapabilityAccess, *, company_directory: bool):
    if company_directory:
        return Shop.company_id == access.company_id
    return and_(
        Shop.company_id == access.company_id,
        assigned_shop_filter(access),
    )


def visible_zone_filter(access: BackofficeCapabilityAccess, *, company_directory: bool):
    if company_directory:
        return Zone.company_id == access.company_id
    # A route-owned Zone can be named even if no Visit has yet been attached,
    # but its unassigned Shop directory stays invisible.
    routed = (
        select(DispatchRoute.zone_id)
        .where(
            DispatchRoute.company_id == access.company_id,
            DispatchRoute.status == "active",
            route_filter(access, "dispatch.read"),
        )
    )
    return and_(
        Zone.company_id == access.company_id,
        Zone.id.in_(routed),
    )


def project_shop(shop: Shop, *, finances: bool) -> dict:
    """Explicit null + redaction marker, never the false financial value zero."""
    return {
        "id": str(shop.id),
        "name": shop.name,
        "owner": shop.contact_person.strip() if shop.contact_person else "",
        "phone": shop.phone_number or "",
        "mapLink": shop.location_link or "",
        "zoneId": str(shop.zone_id) if shop.zone_id else "",
        "taxJurisdictionId": int(shop.tax_jurisdiction_id) if shop.tax_jurisdiction_id is not None else None,
        "initialDebt": shop.current_balance if finances else None,
        "maxDebtLimit": shop.max_debt_limit if finances else None,
        "financeRedacted": not finances,
        "sequence": shop.sequence if shop.sequence is not None else 999,
        "archived": bool(shop.is_archived),
    }
