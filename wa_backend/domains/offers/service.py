from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from domains.offers.contracts import (
    BasketLine,
    BasketPriceComponent,
    CatalogPrice,
)
from domains.offers.core import OfferError
from domains.offers.eligibility import resolve_offer_candidates
from domains.offers.engine import calculate_offers
from domains.offers.schemas import PreviewRequest
from domains.pricing.core import (
    PricingError,
    current_assignment_revision_ceiling,
    current_publication_revision_ceiling,
)
from domains.pricing.resolver import resolve_prices_bulk
from domains.uom_authority import (
    UomAuthorityError,
    load_variant_uom_authorities,
)
from quantity import canonical_quantity


def _aware(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise OfferError(
            "OFFER_AS_OF_TIMEZONE_REQUIRED",
            "Preview time must include a UTC offset.",
            status_code=422,
        )
    return result.astimezone(timezone.utc)


def _decimal(value: Decimal) -> str:
    return format(value, ".6f")


def _uom_error(exc: UomAuthorityError) -> OfferError:
    return OfferError(
        exc.code,
        exc.message,
        status_code=422,
        context=exc.context,
    )


async def preview_offer_basket(
    db: AsyncSession,
    *,
    company_id: int,
    payload: PreviewRequest,
) -> dict[str, Any]:
    when = _aware(payload.as_of)
    basket_ids = {
        int(line.product_variant_id)
        for line in payload.lines
    }
    try:
        basket_authorities = await load_variant_uom_authorities(
            db,
            company_id=company_id,
            variant_ids=basket_ids,
        )
    except UomAuthorityError as exc:
        raise _uom_error(exc) from exc

    requested_pairs: set[tuple[int, int]] = set()
    component_base_quantities: dict[
        tuple[int, int],
        Decimal,
    ] = {}
    canonical_totals: dict[int, Decimal] = {}

    try:
        for line in payload.lines:
            variant_id = int(line.product_variant_id)
            authority = basket_authorities[variant_id]
            total = Decimal("0")
            for component in line.components:
                uom_id = int(component.uom_id)
                pair = (variant_id, uom_id)
                base_quantity = authority.to_base(
                    component.quantity,
                    uom_id=uom_id,
                    field_name=(
                        f"quantity[{variant_id}:{uom_id}]"
                    ),
                )
                component_base_quantities[pair] = (
                    base_quantity
                )
                total += base_quantity
                requested_pairs.add(pair)
            canonical_totals[variant_id] = (
                authority.validate_canonical_total(
                    total,
                    field_name=(
                        f"canonical_quantity[{variant_id}]"
                    ),
                )
            )
    except UomAuthorityError as exc:
        raise _uom_error(exc) from exc

    publication_ceiling = (
        await current_publication_revision_ceiling(
            db,
            company_id,
        )
    )
    assignment_ceiling = (
        await current_assignment_revision_ceiling(
            db,
            company_id,
        )
    )
    try:
        price_rows = await resolve_prices_bulk(
            db,
            company_id=company_id,
            pairs=sorted(requested_pairs),
            customer_id=payload.customer_id,
            branch_id=payload.branch_id,
            as_of=when,
            publication_revision_ceiling=(
                publication_ceiling
            ),
            assignment_revision_ceiling=(
                assignment_ceiling
            ),
        )
    except PricingError as exc:
        raise OfferError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc

    currencies = {
        str(row.currency_code).upper()
        for row in price_rows.values()
    }
    if len(currencies) != 1:
        raise OfferError(
            "OFFER_PREVIEW_CURRENCY_CONFLICT",
            "Preview basket resolved to more than one transaction currency.",
        )
    currency = next(iter(currencies))

    candidates, offer_ceiling = (
        await resolve_offer_candidates(
            db,
            company_id=company_id,
            as_of=when,
            currency_code=currency,
            customer_id=payload.customer_id,
            branch_id=payload.branch_id,
            channel_code=payload.channel_code,
            revision_ceiling=(
                payload.offer_revision_ceiling
            ),
        )
    )

    reward_pairs = {
        (
            int(product.product_variant_id),
            int(product.uom_id),
        )
        for candidate in candidates
        for product in candidate.products
        if product.role == "REWARD"
    }
    all_variant_ids = basket_ids | {
        variant_id
        for variant_id, _uom_id in reward_pairs
    }
    try:
        all_authorities = await load_variant_uom_authorities(
            db,
            company_id=company_id,
            variant_ids=all_variant_ids,
        )
        for variant_id, uom_id in reward_pairs:
            all_authorities[
                variant_id
            ].factor_to_base(uom_id)
    except UomAuthorityError as exc:
        raise _uom_error(exc) from exc

    missing_pairs = reward_pairs - set(price_rows)
    if missing_pairs:
        try:
            extra = await resolve_prices_bulk(
                db,
                company_id=company_id,
                pairs=sorted(missing_pairs),
                customer_id=payload.customer_id,
                branch_id=payload.branch_id,
                as_of=when,
                publication_revision_ceiling=(
                    publication_ceiling
                ),
                assignment_revision_ceiling=(
                    assignment_ceiling
                ),
            )
        except PricingError as exc:
            raise OfferError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                context=exc.context,
            ) from exc
        price_rows.update(extra)

    resolved_currencies = {
        str(row.currency_code).upper()
        for row in price_rows.values()
    }
    if resolved_currencies != {currency}:
        raise OfferError(
            "OFFER_PREVIEW_CURRENCY_CONFLICT",
            "Preview and reward prices must share one transaction currency.",
        )

    for pair, price in price_rows.items():
        if (
            int(price.price_publication_revision) <= 0
            or int(price.price_publication_revision)
            > int(publication_ceiling)
            or int(price.assignment_revision) <= 0
            or int(price.assignment_revision)
            > int(assignment_ceiling)
            or price.resolved_at != when
        ):
            raise OfferError(
                "OFFER_PREVIEW_PRICE_EVIDENCE_INVALID",
                "Resolved preview price evidence exceeds the locked preview authority.",
                context={"pair": list(pair)},
            )

    catalog_prices = {
        pair: CatalogPrice(
            product_variant_id=int(pair[0]),
            uom_id=int(pair[1]),
            unit_price=price.amount,
            price_entry_id=int(price.price_entry_id),
            price_publication_revision=int(
                price.price_publication_revision
            ),
            assignment_revision=int(price.assignment_revision),
        )
        for pair, price in price_rows.items()
    }

    basket_lines: list[BasketLine] = []
    for index, line in enumerate(
        payload.lines,
        start=1,
    ):
        variant_id = int(line.product_variant_id)
        authority = basket_authorities[variant_id]
        components: list[BasketPriceComponent] = []
        for component in line.components:
            uom_id = int(component.uom_id)
            pair = (variant_id, uom_id)
            price = price_rows[pair]
            components.append(
                BasketPriceComponent(
                    uom_id=uom_id,
                    quantity=component.quantity,
                    base_quantity=(
                        component_base_quantities[pair]
                    ),
                    unit_price=price.amount,
                    price_entry_id=int(
                        price.price_entry_id
                    ),
                    price_publication_revision=int(
                        price.price_publication_revision
                    ),
                    assignment_revision=int(
                        price.assignment_revision
                    ),
                )
            )
        basket_lines.append(
            BasketLine(
                line_id=index,
                product_variant_id=variant_id,
                base_uom_id=int(
                    authority.base_uom_id
                ),
                quantity=canonical_totals[
                    variant_id
                ],
                price_components=tuple(
                    sorted(
                        components,
                        key=lambda row: row.uom_id,
                    )
                ),
            )
        )

    result = calculate_offers(
        lines=basket_lines,
        candidates=candidates,
        catalog_prices=catalog_prices,
        calculated_at=when,
    )
    return {
        "calculated_at": (
            result.calculated_at.isoformat()
        ),
        "currency_code": currency,
        "price_publication_revision_ceiling": int(
            publication_ceiling
        ),
        "assignment_revision_ceiling": int(
            assignment_ceiling
        ),
        "offer_revision_ceiling": int(
            offer_ceiling
        ),
        "gross_amount": _decimal(
            result.gross_amount
        ),
        "discount_amount": _decimal(
            result.discount_amount
        ),
        "net_amount": _decimal(
            result.net_amount
        ),
        "lines": [
            {
                "line_id": line.line_id,
                "product_variant_id": (
                    line.product_variant_id
                ),
                "base_uom_id": line.base_uom_id,
                "canonical_quantity": (
                    canonical_quantity(
                        line.quantity
                    )
                ),
                "gross_amount": _decimal(
                    line.gross_amount
                ),
                "net_amount": _decimal(
                    result.line_net_amounts[
                        line.line_id
                    ]
                ),
                "price_components": [
                    {
                        "uom_id": component.uom_id,
                        "quantity": (
                            canonical_quantity(
                                component.quantity
                            )
                        ),
                        "base_quantity": (
                            canonical_quantity(
                                component.base_quantity
                            )
                        ),
                        "unit_price": _decimal(
                            component.unit_price
                        ),
                        "price_entry_id": (
                            component.price_entry_id
                        ),
                        "gross_amount": _decimal(
                            component.gross_amount
                        ),
                    }
                    for component
                    in line.price_components
                ],
            }
            for line in basket_lines
        ],
        "adjustments": [
            {
                "sequence": row.sequence,
                "offer_version_id": (
                    row.offer_version_id
                ),
                "offer_definition_id": (
                    row.offer_definition_id
                ),
                "offer_revision": (
                    row.offer_revision
                ),
                "offer_type": row.offer_type,
                "line_id": row.line_id,
                "product_variant_id": (
                    row.product_variant_id
                ),
                "uom_id": row.uom_id,
                "basis_amount": _decimal(
                    row.basis_amount
                ),
                "discount_amount": _decimal(
                    row.discount_amount
                ),
            }
            for row in result.adjustments
        ],
        "free_goods": [
            {
                "sequence": row.sequence,
                "offer_version_id": (
                    row.offer_version_id
                ),
                "offer_definition_id": (
                    row.offer_definition_id
                ),
                "offer_revision": (
                    row.offer_revision
                ),
                "offer_type": row.offer_type,
                "product_variant_id": (
                    row.product_variant_id
                ),
                "uom_id": row.uom_id,
                "quantity": canonical_quantity(
                    row.quantity
                ),
            }
            for row in result.rewards
        ],
        "applied_offers": [
            {
                "sequence": row.sequence,
                "offer_version_id": (
                    row.offer_version_id
                ),
                "offer_definition_id": (
                    row.offer_definition_id
                ),
                "offer_revision": (
                    row.offer_revision
                ),
                "offer_type": row.offer_type,
                "priority": row.priority,
                "stacking_mode": (
                    row.stacking_mode
                ),
                "application_count": (
                    row.application_count
                ),
                "discount_amount": _decimal(
                    row.discount_amount
                ),
                "reward_value": _decimal(
                    row.reward_value
                ),
                "benefit_amount": _decimal(
                    row.benefit_amount
                ),
                "metadata": dict(row.metadata),
            }
            for row in result.applied_offers
        ],
    }
