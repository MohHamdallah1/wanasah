from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.offers.contracts import BasketLine, CatalogPrice
from domains.offers.core import OfferError
from domains.offers.eligibility import resolve_offer_candidates
from domains.offers.engine import calculate_offers
from domains.offers.schemas import PreviewRequest
from domains.pricing.core import (
    current_assignment_revision_ceiling,
    current_publication_revision_ceiling,
)
from domains.pricing.resolver import resolve_prices_bulk
from models import ProductVariant
from quantity import QuantityError, canonical_quantity, validate_variant_quantity


def _aware(value: datetime | None) -> datetime:
    result = value or datetime.now(timezone.utc)
    if result.tzinfo is None or result.utcoffset() is None:
        raise OfferError(
            "OFFER_AS_OF_TIMEZONE_REQUIRED",
            "Preview time must include a UTC offset.",
            status_code=422,
        )
    return result.astimezone(timezone.utc)


async def _variants(
    db: AsyncSession,
    *,
    company_id: int,
    ids: set[int],
) -> dict[int, ProductVariant]:
    if not ids:
        return {}
    rows = list(
        (
            await db.scalars(
                select(ProductVariant).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(ids),
                )
            )
        ).all()
    )
    result = {int(row.id): row for row in rows}
    missing = sorted(ids - result.keys())
    if missing:
        raise OfferError(
            "OFFER_PRODUCT_NOT_FOUND",
            "One or more products are not available inside this company.",
            status_code=404,
            context={"product_variant_ids": missing},
        )
    return result


def _decimal(value: Decimal) -> str:
    return format(value, ".6f")


async def preview_offer_basket(
    db: AsyncSession,
    *,
    company_id: int,
    payload: PreviewRequest,
) -> dict[str, Any]:
    when = _aware(payload.as_of)
    basket_ids = {int(line.product_variant_id) for line in payload.lines}
    variant_map = await _variants(db, company_id=company_id, ids=basket_ids)

    canonical_quantities: dict[int, Decimal] = {}
    pairs: list[tuple[int, int]] = []
    try:
        for line in payload.lines:
            variant = variant_map[int(line.product_variant_id)]
            canonical_quantities[int(line.product_variant_id)] = validate_variant_quantity(
                line.quantity,
                quantity_scale=int(variant.quantity_scale),
                quantity_step=variant.quantity_step,
                field_name=f"quantity[{variant.id}]",
            )
            pairs.append((int(variant.id), int(variant.base_uom_id)))
    except QuantityError as exc:
        raise OfferError("OFFER_QUANTITY_INVALID", str(exc), status_code=422) from exc

    publication_ceiling = await current_publication_revision_ceiling(db, company_id)
    assignment_ceiling = await current_assignment_revision_ceiling(db, company_id)
    price_rows = await resolve_prices_bulk(
        db,
        company_id=company_id,
        pairs=pairs,
        customer_id=payload.customer_id,
        branch_id=payload.branch_id,
        as_of=when,
        publication_revision_ceiling=publication_ceiling,
        assignment_revision_ceiling=assignment_ceiling,
    )
    currencies = {row.currency_code for row in price_rows.values()}
    if len(currencies) != 1:
        raise OfferError(
            "OFFER_PREVIEW_CURRENCY_CONFLICT",
            "Preview basket resolved to more than one transaction currency.",
        )
    currency = next(iter(currencies))

    candidates, offer_ceiling = await resolve_offer_candidates(
        db,
        company_id=company_id,
        as_of=when,
        currency_code=currency,
        customer_id=payload.customer_id,
        branch_id=payload.branch_id,
        channel_code=payload.channel_code,
        revision_ceiling=payload.offer_revision_ceiling,
    )

    role_ids = {
        product.product_variant_id
        for candidate in candidates
        for product in candidate.products
    }
    all_ids = basket_ids | role_ids
    all_variants = await _variants(db, company_id=company_id, ids=all_ids)
    all_pairs = {
        (variant_id, int(all_variants[variant_id].base_uom_id))
        for variant_id in all_ids
    }
    missing_pairs = all_pairs - set(price_rows)
    if missing_pairs:
        extra = await resolve_prices_bulk(
            db,
            company_id=company_id,
            pairs=sorted(missing_pairs),
            customer_id=payload.customer_id,
            branch_id=payload.branch_id,
            as_of=when,
            publication_revision_ceiling=publication_ceiling,
            assignment_revision_ceiling=assignment_ceiling,
        )
        price_rows.update(extra)

    catalog_prices = {
        variant_id: CatalogPrice(
            product_variant_id=variant_id,
            base_uom_id=int(all_variants[variant_id].base_uom_id),
            unit_price=price_rows[(variant_id, int(all_variants[variant_id].base_uom_id))].amount,
            price_entry_id=price_rows[(variant_id, int(all_variants[variant_id].base_uom_id))].price_entry_id,
        )
        for variant_id in all_ids
    }
    basket_lines = [
        BasketLine(
            line_id=index,
            product_variant_id=int(line.product_variant_id),
            base_uom_id=int(variant_map[int(line.product_variant_id)].base_uom_id),
            quantity=canonical_quantities[int(line.product_variant_id)],
            unit_price=catalog_prices[int(line.product_variant_id)].unit_price,
            price_entry_id=catalog_prices[int(line.product_variant_id)].price_entry_id,
        )
        for index, line in enumerate(payload.lines, start=1)
    ]

    result = calculate_offers(
        lines=basket_lines,
        candidates=candidates,
        catalog_prices=catalog_prices,
        calculated_at=when,
    )
    return {
        "calculated_at": result.calculated_at.isoformat(),
        "currency_code": currency,
        "price_publication_revision_ceiling": int(publication_ceiling),
        "assignment_revision_ceiling": int(assignment_ceiling),
        "offer_revision_ceiling": int(offer_ceiling),
        "gross_amount": _decimal(result.gross_amount),
        "discount_amount": _decimal(result.discount_amount),
        "net_amount": _decimal(result.net_amount),
        "lines": [
            {
                "line_id": line.line_id,
                "product_variant_id": line.product_variant_id,
                "base_uom_id": line.base_uom_id,
                "quantity": canonical_quantity(line.quantity),
                "unit_price": _decimal(line.unit_price),
                "price_entry_id": line.price_entry_id,
                "gross_amount": _decimal(line.gross_amount),
                "net_amount": _decimal(result.line_net_amounts[line.line_id]),
            }
            for line in basket_lines
        ],
        "adjustments": [
            {
                "sequence": row.sequence,
                "offer_version_id": row.offer_version_id,
                "offer_definition_id": row.offer_definition_id,
                "offer_revision": row.offer_revision,
                "offer_type": row.offer_type,
                "line_id": row.line_id,
                "product_variant_id": row.product_variant_id,
                "basis_amount": _decimal(row.basis_amount),
                "discount_amount": _decimal(row.discount_amount),
            }
            for row in result.adjustments
        ],
        "free_goods": [
            {
                "sequence": row.sequence,
                "offer_version_id": row.offer_version_id,
                "offer_definition_id": row.offer_definition_id,
                "offer_revision": row.offer_revision,
                "offer_type": row.offer_type,
                "product_variant_id": row.product_variant_id,
                "base_uom_id": row.base_uom_id,
                "quantity": canonical_quantity(row.quantity),
            }
            for row in result.rewards
        ],
        "applied_offers": [
            {
                "sequence": row.sequence,
                "offer_version_id": row.offer_version_id,
                "offer_definition_id": row.offer_definition_id,
                "offer_revision": row.offer_revision,
                "offer_type": row.offer_type,
                "priority": row.priority,
                "stacking_mode": row.stacking_mode,
                "application_count": row.application_count,
                "discount_amount": _decimal(row.discount_amount),
                "reward_value": _decimal(row.reward_value),
                "benefit_amount": _decimal(row.benefit_amount),
                "metadata": dict(row.metadata),
            }
            for row in result.applied_offers
        ],
    }
