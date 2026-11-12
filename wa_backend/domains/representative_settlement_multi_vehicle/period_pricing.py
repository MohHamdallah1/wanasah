"""Bounded shortage-price seam over frozen canonical period contexts.

Pricing resolves each publication using its existing authority. If one vehicle
has genuinely different applicable locked prices and no finer provenance, the
backend requests review instead of selecting an initial/last route or asking
the receiver to choose a price. No price, valuation or COGS ledger is written.
"""
from decimal import Decimal, InvalidOperation

from sqlalchemy import and_, select

from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.pricing.core import PricingError
from domains.pricing.resolver import resolve_prices_bulk
from models import DispatchRoute, InventoryLocation, ProductVariant, RouteCommercialContext

from .contracts import MAX_PERIODS, CustodyRejected
from .inventory_integration import canonical_session
from .resolution import session_responsibilities


def unambiguous_shortage_prices(prices_by_context, variant_ids):
    result = {}
    for variant_id in variant_ids:
        prices = {prices[variant_id] for prices in prices_by_context if variant_id in prices}
        if len(prices) != 1 or len(prices_by_context) == 0 or any(
                variant_id not in prices for prices in prices_by_context):
            raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED")
        price = prices.pop()
        try:
            if (not price.is_finite() or price < 0 or price > Decimal("999999999.999")
                    or price.quantize(Decimal(".001")) != price):
                raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED")
        except InvalidOperation:
            raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED") from None
        result[variant_id] = price
    return result


async def resolve_canonical_shortage_prices(db, *, company_id, work_session_id,
                                            vehicle_location_id, variant_ids):
    _, vehicles = await session_responsibilities(
        db, company_id=company_id, session_id=work_session_id, lock_session=True,
    )
    vehicle = next((v for v in vehicles if v.location_id == vehicle_location_id), None)
    if vehicle is None:
        raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND")
    # Include every applicable period. Missing contexts cannot disappear through
    # an inner join or a last-route lookup. Repeated A periods may share context.
    period = DispatchRouteExecutionPeriod
    records = (await db.execute(select(period.id, RouteCommercialContext, InventoryLocation.branch_id).select_from(period)
        .join(RouteCommercialContext, and_(
            RouteCommercialContext.company_id == period.company_id,
            RouteCommercialContext.id == period.commercial_context_id,
            RouteCommercialContext.dispatch_route_id == period.route_id,
        )).join(DispatchRoute, and_(DispatchRoute.company_id == period.company_id,
                                   DispatchRoute.id == period.route_id))
        .join(InventoryLocation, and_(InventoryLocation.company_id == period.company_id,
                                     InventoryLocation.id == DispatchRoute.source_location_id))
        .where(period.company_id == company_id, period.id.in_(vehicle.period_ids))
        .order_by(period.id).limit(MAX_PERIODS + 1))).all()
    if {r[0] for r in records} != set(vehicle.period_ids):
        raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED")
    variant_ids = sorted(set(variant_ids))
    variants = dict((await db.execute(select(ProductVariant.id, ProductVariant.base_uom_id).where(
        ProductVariant.company_id == company_id, ProductVariant.id.in_(variant_ids),
    ))).all())
    if set(variants) != set(variant_ids):
        raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED")
    contexts = {}
    for _, context, branch_id in records:
        contexts[(context.id, branch_id)] = context
    if len(contexts) > 16 or len({c.transaction_currency_code for c in contexts.values()}) != 1:
        raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED")
    prices_by_context = []
    for (_, branch_id), context in contexts.items():
        if (context.pricing_locked_at is None or not context.price_publication_revision
                or not context.assignment_revision or not context.transaction_currency_code):
            raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED")
        resolved = await resolve_prices_bulk(
            db, company_id=company_id, pairs=list(variants.items()), customer_id=None,
            branch_id=branch_id, as_of=context.pricing_locked_at,
            publication_revision_ceiling=int(context.price_publication_revision),
            assignment_revision_ceiling=int(context.assignment_revision),
        )
        prices = {}
        for variant_id, uom_id in variants.items():
            price = resolved[(variant_id, uom_id)]
            if str(price.currency_code).upper() != str(context.transaction_currency_code).upper():
                raise CustodyRejected("SHORTAGE_PERIOD_PRICE_REVIEW_REQUIRED")
            prices[variant_id] = Decimal(price.amount)
        prices_by_context.append(prices)
    return unambiguous_shortage_prices(prices_by_context, variant_ids)


async def resolve_recon_shortage_prices(db, *, company_id, work_session_id,
                                       vehicle_location_id, variant_ids):
    """Direct-caller seam proposed to LEAD; historical price rule is unchanged."""
    if not await canonical_session(db, company_id=company_id, session_id=work_session_id):
        from domains.pricing.driver_authority import resolve_work_session_pack_prices_bulk
        return await resolve_work_session_pack_prices_bulk(
            db, company_id=company_id, work_session_id=work_session_id, variant_ids=variant_ids,
        )
    try:
        return await resolve_canonical_shortage_prices(
            db, company_id=company_id, work_session_id=work_session_id,
            vehicle_location_id=vehicle_location_id, variant_ids=variant_ids,
        )
    except CustodyRejected as exc:
        raise PricingError(exc.code, exc.code, status_code=409, context=exc.context) from exc
