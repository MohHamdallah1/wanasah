from __future__ import annotations

from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.offers.core import OfferError
from domains.offers.eligibility import current_offer_revision_ceiling
from domains.sales_calculation.policy import (
    CommercialPolicyError,
    resolve_commercial_rounding_policy,
)
from domains.taxation.core import TaxError, current_tax_revision_ceiling
from models import (
    Company,
    DispatchRoute,
    PriceBookAssignment,
    PriceBookEntry,
    PricePublication,
    RouteCommercialContext,
)

from .core import PricingError, acquire_pricing_company_lock, utc_now


async def _read_lock_snapshot(
    db: AsyncSession,
    *,
    company_id: int,
    locked_at,
) -> tuple[str, int, int, int | None]:
    """Read pricing revision ceilings in one PostgreSQL statement."""
    publication_ceiling = (
        select(func.max(PricePublication.revision))
        .where(
            PricePublication.company_id == int(company_id),
            PricePublication.status.in_(("PUBLISHED", "SUPERSEDED")),
            PricePublication.published_at.is_not(None),
            PricePublication.published_at <= locked_at,
        )
        .scalar_subquery()
    )
    assignment_ceiling = (
        select(func.max(PriceBookAssignment.revision))
        .where(PriceBookAssignment.company_id == int(company_id))
        .scalar_subquery()
    )
    usable_chain = (
        select(PriceBookAssignment.id)
        .join(
            PriceBookEntry,
            and_(
                PriceBookEntry.company_id == PriceBookAssignment.company_id,
                PriceBookEntry.price_book_id == PriceBookAssignment.price_book_id,
            ),
        )
        .join(
            PricePublication,
            and_(
                PricePublication.company_id == PriceBookEntry.company_id,
                PricePublication.id == PriceBookEntry.publication_id,
                PricePublication.price_book_id == PriceBookEntry.price_book_id,
            ),
        )
        .where(
            PriceBookAssignment.company_id == int(company_id),
            PriceBookAssignment.effectivity.contains(locked_at),
            PriceBookEntry.is_published.is_(True),
            PriceBookEntry.effectivity.contains(locked_at),
            PricePublication.status.in_(("PUBLISHED", "SUPERSEDED")),
            PricePublication.published_at.is_not(None),
            PricePublication.published_at <= locked_at,
        )
        .order_by(
            PriceBookAssignment.revision.desc(),
            PricePublication.revision.desc(),
            PriceBookEntry.id.asc(),
        )
        .limit(1)
        .scalar_subquery()
    )

    row = (
        await db.execute(
            select(
                Company.currency_code,
                publication_ceiling.label("publication_revision"),
                assignment_ceiling.label("assignment_revision"),
                usable_chain.label("usable_assignment_id"),
            ).where(Company.id == int(company_id))
        )
    ).one_or_none()
    if row is None:
        raise PricingError(
            "TENANT_NOT_FOUND",
            "الشركة غير موجودة.",
            status_code=404,
        )

    currency = str(row.currency_code or "").strip().upper()
    publication_revision = int(row.publication_revision or 0)
    assignment_revision = int(row.assignment_revision or 0)
    usable_assignment_id = (
        int(row.usable_assignment_id)
        if row.usable_assignment_id is not None
        else None
    )

    if not currency:
        raise PricingError(
            "COMMERCIAL_CURRENCY_INVALID",
            "عملة الشركة غير صالحة لإنشاء السياق التجاري.",
        )

    if (
        publication_revision <= 0
        or assignment_revision <= 0
        or usable_assignment_id is None
    ):
        raise PricingError(
            "PRICE_NOT_RESOLVED",
            "لا يمكن إطلاق خط السير قبل وجود Pricing Publication وAssignment فعالين وقابلين للحل.",
            context={
                "price_publication_revision": publication_revision,
                "assignment_revision": assignment_revision,
            },
        )

    return (
        currency,
        publication_revision,
        assignment_revision,
        usable_assignment_id,
    )


def _require_complete_context(
    context: RouteCommercialContext,
) -> RouteCommercialContext:
    values = {
        "offer_revision_ceiling": context.offer_ruleset_version,
        "tax_revision_ceiling": context.tax_ruleset_version,
        "rounding_policy_version": context.rounding_policy_version,
        "tenant_policy_revision": context.tenant_policy_revision,
    }
    if (
        values["offer_revision_ceiling"] is None
        or int(values["offer_revision_ceiling"]) < 0
        or values["tax_revision_ceiling"] is None
        or int(values["tax_revision_ceiling"]) <= 0
        or values["rounding_policy_version"] is None
        or int(values["rounding_policy_version"]) <= 0
        or values["tenant_policy_revision"] is None
        or int(values["tenant_policy_revision"]) <= 0
    ):
        raise PricingError(
            "COMMERCIAL_CONTEXT_INCOMPLETE",
            "السياق التجاري للمسار ناقص ولا يجوز استخدامه للبيع.",
            context={
                "commercial_context_id": int(context.id),
                **values,
            },
        )
    return context


async def lock_route_commercial_context(
    db: AsyncSession,
    *,
    company_id: int,
    dispatch_route_id: int,
) -> RouteCommercialContext:
    """Atomically lock price, offer, tax and rounding authorities once."""
    company_id = int(company_id)
    dispatch_route_id = int(dispatch_route_id)

    # Shared tenant lock root. Pricing writes, offer/tax publication and the
    # rounding-policy publisher all serialize against the Company row.
    await acquire_pricing_company_lock(db, company_id)

    route_exists = await db.scalar(
        select(DispatchRoute.id).where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.id == dispatch_route_id,
        )
    )
    if route_exists is None:
        raise PricingError(
            "COMMERCIAL_ROUTE_NOT_FOUND",
            "خط السير غير موجود داخل الشركة.",
            status_code=404,
            context={"dispatch_route_id": dispatch_route_id},
        )

    existing = await db.scalar(
        select(RouteCommercialContext).where(
            RouteCommercialContext.company_id == company_id,
            RouteCommercialContext.dispatch_route_id == dispatch_route_id,
        )
    )
    if existing is not None:
        return _require_complete_context(existing)

    locked_at = utc_now()
    (
        currency,
        publication_revision,
        assignment_revision,
        _usable_assignment_id,
    ) = await _read_lock_snapshot(
        db,
        company_id=company_id,
        locked_at=locked_at,
    )

    try:
        offer_revision = await current_offer_revision_ceiling(
            db,
            company_id=company_id,
            as_of=locked_at,
        )
    except OfferError as exc:
        raise PricingError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc

    try:
        tax_revision = await current_tax_revision_ceiling(
            db,
            company_id,
            as_of=locked_at,
        )
    except TaxError as exc:
        raise PricingError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc
    if int(tax_revision) <= 0:
        raise PricingError(
            "TAX_CONFIGURATION_REQUIRED",
            "لا يمكن إطلاق خط السير قبل نشر إعداد ضريبي صالح. استخدم مكوناً بنسبة 0 عند عدم وجود ضريبة فعلية.",
            context={"tax_revision_ceiling": int(tax_revision)},
        )

    try:
        rounding = await resolve_commercial_rounding_policy(
            db,
            company_id=company_id,
            as_of=locked_at,
            expected_currency_code=currency,
        )
    except CommercialPolicyError as exc:
        raise PricingError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc

    context = RouteCommercialContext(
        company_id=company_id,
        dispatch_route_id=dispatch_route_id,
        pricing_locked_at=locked_at,
        price_publication_revision=publication_revision,
        assignment_revision=assignment_revision,
        offer_ruleset_version=int(offer_revision),
        tax_ruleset_version=int(tax_revision),
        transaction_currency_code=currency,
        functional_currency_code=currency,
        rounding_policy_version=int(rounding.rounding_policy.version),
        tenant_policy_revision=int(rounding.policy_revision),
    )
    db.add(context)
    await db.flush()
    return _require_complete_context(context)


async def require_route_commercial_context(
    db: AsyncSession,
    *,
    company_id: int,
    dispatch_route_id: int,
) -> RouteCommercialContext:
    context = await db.scalar(
        select(RouteCommercialContext).where(
            RouteCommercialContext.company_id == int(company_id),
            RouteCommercialContext.dispatch_route_id == int(dispatch_route_id),
        )
    )
    if context is None:
        raise PricingError(
            "COMMERCIAL_CONTEXT_REQUIRED",
            "خط السير لا يملك سياقاً تجارياً مقفلاً. يجب إطلاقه ضمن السلطة التجارية قبل بدء البيع.",
            context={"dispatch_route_id": int(dispatch_route_id)},
        )
    return _require_complete_context(context)


def commercial_context_payload(
    context: RouteCommercialContext,
) -> dict[str, Any]:
    checked = _require_complete_context(context)
    return {
        "commercial_context_id": int(checked.id),
        "pricing_locked_at": checked.pricing_locked_at.isoformat(),
        "price_publication_revision": int(checked.price_publication_revision),
        "assignment_revision": int(checked.assignment_revision),
        "offer_ruleset_version": int(checked.offer_ruleset_version),
        "tax_ruleset_version": int(checked.tax_ruleset_version),
        "transaction_currency_code": checked.transaction_currency_code,
        "functional_currency_code": checked.functional_currency_code,
        "rounding_policy_version": int(checked.rounding_policy_version),
        "tenant_policy_revision": int(checked.tenant_policy_revision),
    }
