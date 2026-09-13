from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.offers.contracts import (
    BasketLine,
    BasketPriceComponent,
    CatalogPrice,
)
from domains.offers.core import OfferError
from domains.offers.eligibility import resolve_offer_candidates
from domains.offers.engine import calculate_offers
from domains.pricing.core import PricingError
from domains.pricing.resolver import resolve_prices_bulk
from domains.sales_calculation.contracts import (
    CalculationInputLine,
    CommercialCalculation,
    RoundingPolicy,
)
from domains.sales_calculation.core import CalculationError, require_aware_datetime
from domains.sales_calculation.pipeline import calculate_document
from domains.sales_calculation.rounding import validate_rounding_policy
from domains.taxation.core import TaxError
from domains.taxation.resolver import resolve_tax_rules_bulk
from models import ProductVariant
from quantity import QuantityError, validate_variant_quantity


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
                    ProductVariant.company_id == int(company_id),
                    ProductVariant.id.in_(sorted(ids)),
                )
            )
        ).all()
    )
    result = {int(row.id): row for row in rows}
    missing = sorted(ids - set(result))
    if missing:
        raise CalculationError(
            "CALCULATION_PRODUCT_NOT_FOUND",
            "One or more product variants are not available inside this company.",
            status_code=404,
            context={"product_variant_ids": missing},
        )
    return result


def _validate_lock(
    *,
    publication_revision_ceiling: int,
    assignment_revision_ceiling: int,
    offer_revision_ceiling: int,
    tax_revision_ceiling: int,
) -> None:
    if (
        not isinstance(publication_revision_ceiling, int)
        or publication_revision_ceiling <= 0
        or not isinstance(assignment_revision_ceiling, int)
        or assignment_revision_ceiling <= 0
        or not isinstance(offer_revision_ceiling, int)
        or offer_revision_ceiling < 0
        or not isinstance(tax_revision_ceiling, int)
        or tax_revision_ceiling <= 0
    ):
        raise CalculationError(
            "COMMERCIAL_CONTEXT_LOCK_INVALID",
            "Calculation requires explicit valid commercial revision ceilings.",
            status_code=422,
        )


async def resolve_and_calculate_document(
    db: AsyncSession,
    *,
    company_id: int,
    lines: Sequence[CalculationInputLine],
    customer_id: int | None,
    branch_id: int | None,
    channel_code: str | None,
    jurisdiction_id: int,
    document_type_code: str,
    as_of: datetime,
    rounding_policy: RoundingPolicy,
    price_publication_revision_ceiling: int,
    assignment_revision_ceiling: int,
    offer_revision_ceiling: int,
    tax_revision_ceiling: int,
) -> CommercialCalculation:
    when = require_aware_datetime(as_of, "as_of")
    policy = validate_rounding_policy(rounding_policy)
    _validate_lock(
        publication_revision_ceiling=price_publication_revision_ceiling,
        assignment_revision_ceiling=assignment_revision_ceiling,
        offer_revision_ceiling=offer_revision_ceiling,
        tax_revision_ceiling=tax_revision_ceiling,
    )

    ordered_inputs = sorted(lines, key=lambda row: row.line_id)
    if not ordered_inputs:
        raise CalculationError(
            "CALCULATION_EMPTY_DOCUMENT",
            "A commercial calculation requires at least one line.",
            status_code=422,
        )
    line_ids = [int(row.line_id) for row in ordered_inputs]
    product_ids = [int(row.product_variant_id) for row in ordered_inputs]
    if any(value <= 0 for value in line_ids + product_ids):
        raise CalculationError(
            "CALCULATION_INPUT_INVALID",
            "Line and product identifiers must be positive.",
            status_code=422,
        )
    if len(line_ids) != len(set(line_ids)):
        raise CalculationError(
            "CALCULATION_DUPLICATE_LINE",
            "Calculation line IDs must be unique.",
            status_code=422,
        )
    if len(product_ids) != len(set(product_ids)):
        raise CalculationError(
            "CALCULATION_DUPLICATE_VARIANT",
            "Calculation requires one canonical line per product variant.",
            status_code=422,
        )

    variant_map = await _variants(
        db,
        company_id=company_id,
        ids=set(product_ids),
    )
    canonical_quantities: dict[int, Decimal] = {}
    price_pairs: list[tuple[int, int]] = []
    try:
        for row in ordered_inputs:
            variant = variant_map[int(row.product_variant_id)]
            canonical_quantities[int(row.product_variant_id)] = validate_variant_quantity(
                row.quantity,
                quantity_scale=int(variant.quantity_scale),
                quantity_step=variant.quantity_step,
                field_name=f"quantity[{variant.id}]",
            )
            price_pairs.append((int(variant.id), int(variant.base_uom_id)))
    except QuantityError as exc:
        raise CalculationError(
            "CALCULATION_QUANTITY_INVALID",
            str(exc),
            status_code=422,
        ) from exc

    try:
        price_rows = await resolve_prices_bulk(
            db,
            company_id=company_id,
            pairs=price_pairs,
            customer_id=customer_id,
            branch_id=branch_id,
            as_of=when,
            publication_revision_ceiling=price_publication_revision_ceiling,
            assignment_revision_ceiling=assignment_revision_ceiling,
        )
    except PricingError as exc:
        raise CalculationError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc

    currencies = {str(row.currency_code).upper() for row in price_rows.values()}
    if len(currencies) != 1:
        raise CalculationError(
            "CALCULATION_CURRENCY_CONFLICT",
            "Base prices resolve to more than one transaction currency.",
        )
    currency = next(iter(currencies))
    if currency != policy.currency_code:
        raise CalculationError(
            "ROUNDING_POLICY_CURRENCY_MISMATCH",
            "Locked rounding policy does not match resolved transaction currency.",
            context={
                "transaction_currency_code": currency,
                "rounding_policy_currency_code": policy.currency_code,
            },
        )

    try:
        offer_candidates, used_offer_ceiling = await resolve_offer_candidates(
            db,
            company_id=company_id,
            as_of=when,
            currency_code=currency,
            customer_id=customer_id,
            branch_id=branch_id,
            channel_code=channel_code,
            revision_ceiling=offer_revision_ceiling,
        )
    except OfferError as exc:
        raise CalculationError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc
    if int(used_offer_ceiling) != int(offer_revision_ceiling):
        raise CalculationError(
            "CALCULATION_OFFER_CEILING_MISMATCH",
            "Offer resolver did not honor the locked offer revision ceiling.",
        )

    reward_pairs = {
        (
            int(product.product_variant_id),
            int(product.uom_id),
        )
        for candidate in offer_candidates
        for product in candidate.products
        if product.role == "REWARD"
    }
    all_product_ids = set(product_ids) | {
        variant_id
        for variant_id, _uom_id in reward_pairs
    }
    await _variants(
        db,
        company_id=company_id,
        ids=all_product_ids,
    )

    missing_pairs = reward_pairs - set(price_rows)
    if missing_pairs:
        try:
            reward_prices = await resolve_prices_bulk(
                db,
                company_id=company_id,
                pairs=sorted(missing_pairs),
                customer_id=customer_id,
                branch_id=branch_id,
                as_of=when,
                publication_revision_ceiling=price_publication_revision_ceiling,
                assignment_revision_ceiling=assignment_revision_ceiling,
            )
        except PricingError as exc:
            raise CalculationError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                context=exc.context,
            ) from exc
        price_rows.update(reward_prices)

    resolved_currencies = {
        str(row.currency_code).upper()
        for row in price_rows.values()
    }
    if resolved_currencies != {currency}:
        raise CalculationError(
            "CALCULATION_CURRENCY_CONFLICT",
            "Reward/base price evidence does not share one transaction currency.",
        )
    for pair, price in price_rows.items():
        if (
            int(price.price_publication_revision) <= 0
            or int(price.price_publication_revision)
            > int(price_publication_revision_ceiling)
        ):
            raise CalculationError(
                "CALCULATION_PRICE_REVISION_OUT_OF_LOCK",
                "Price resolver returned a revision newer than the locked ceiling.",
                context={"pair": list(pair)},
            )
        if (
            int(price.assignment_revision) <= 0
            or int(price.assignment_revision)
            > int(assignment_revision_ceiling)
        ):
            raise CalculationError(
                "CALCULATION_ASSIGNMENT_REVISION_OUT_OF_LOCK",
                "Price resolver returned an assignment newer than the locked ceiling.",
                context={"pair": list(pair)},
            )
        if price.resolved_at != when:
            raise CalculationError(
                "CALCULATION_CONTEXT_TIME_MISMATCH",
                "Price authority was not resolved at the locked commercial timestamp.",
                context={"pair": list(pair)},
            )

    catalog_prices = {
        pair: CatalogPrice(
            product_variant_id=int(pair[0]),
            uom_id=int(pair[1]),
            unit_price=price.amount,
            price_entry_id=int(price.price_entry_id),
        )
        for pair, price in price_rows.items()
    }
    basket_lines = []
    for row in ordered_inputs:
        variant_id = int(row.product_variant_id)
        variant = variant_map[variant_id]
        base_uom_id = int(variant.base_uom_id)
        pair = (variant_id, base_uom_id)
        price = price_rows[pair]
        canonical_quantity = canonical_quantities[
            variant_id
        ]
        basket_lines.append(
            BasketLine(
                line_id=int(row.line_id),
                product_variant_id=variant_id,
                base_uom_id=base_uom_id,
                quantity=canonical_quantity,
                price_components=(
                    BasketPriceComponent(
                        uom_id=base_uom_id,
                        quantity=canonical_quantity,
                        base_quantity=canonical_quantity,
                        unit_price=price.amount,
                        price_entry_id=int(
                            price.price_entry_id
                        ),
                    ),
                ),
            )
        )

    if any(
        int(candidate.revision) <= 0
        or int(candidate.revision) > int(offer_revision_ceiling)
        for candidate in offer_candidates
    ):
        raise CalculationError(
            "CALCULATION_OFFER_REVISION_OUT_OF_LOCK",
            "Offer resolver returned a candidate newer than the locked ceiling.",
        )

    try:
        offer_result = calculate_offers(
            lines=basket_lines,
            candidates=offer_candidates,
            catalog_prices=catalog_prices,
            calculated_at=when,
        )
    except OfferError as exc:
        raise CalculationError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc

    try:
        tax_resolutions, used_tax_ceiling = await resolve_tax_rules_bulk(
            db,
            company_id=company_id,
            product_variant_ids=product_ids,
            jurisdiction_id=jurisdiction_id,
            customer_id=customer_id,
            document_type_code=document_type_code,
            as_of=when,
            revision_ceiling=tax_revision_ceiling,
        )
    except TaxError as exc:
        raise CalculationError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc
    if int(used_tax_ceiling) != int(tax_revision_ceiling):
        raise CalculationError(
            "CALCULATION_TAX_CEILING_MISMATCH",
            "Tax resolver did not honor the locked tax revision ceiling.",
        )

    publication_revisions: dict[int, int] = {}
    assignment_revisions: dict[int, int] = {}
    for product_id in product_ids:
        pair = (product_id, int(variant_map[product_id].base_uom_id))
        price = price_rows[pair]
        publication_revisions[product_id] = int(price.price_publication_revision)
        assignment_revisions[product_id] = int(price.assignment_revision)

    return calculate_document(
        basket_lines=basket_lines,
        offer_result=offer_result,
        tax_resolutions=tax_resolutions,
        transaction_currency_code=currency,
        rounding_policy=policy,
        price_publication_revisions=publication_revisions,
        assignment_revisions=assignment_revisions,
        price_publication_revision_ceiling=price_publication_revision_ceiling,
        assignment_revision_ceiling=assignment_revision_ceiling,
        offer_revision_ceiling=offer_revision_ceiling,
        tax_revision_ceiling=tax_revision_ceiling,
    )
