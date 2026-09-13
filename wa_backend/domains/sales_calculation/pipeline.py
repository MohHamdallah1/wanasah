from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import BasketLine, OfferEngineResult
from domains.sales_calculation.contracts import (
    CalculatedLine,
    CalculationTotals,
    CommercialCalculation,
    RoundedTaxComponent,
    RoundingPolicy,
)
from domains.sales_calculation.core import (
    CalculationError,
    MONEY_MAX,
    normalize_currency_code,
)
from domains.sales_calculation.rounding import (
    reconcile_components,
    round_currency,
    validate_rounding_policy,
)
from domains.taxation.calculator import calculate_tax
from domains.taxation.core import TaxError
from domains.taxation.contracts import TaxResolution


ZERO = Decimal("0")


def _ensure_capacity(value: Decimal, field: str) -> None:
    if not value.is_finite() or abs(value) > MONEY_MAX:
        raise CalculationError(
            "CALCULATION_AMOUNT_OVERFLOW",
            f"{field} exceeds NUMERIC(20,6) monetary capacity.",
            context={"field": field},
        )


def calculate_document(
    *,
    basket_lines: Sequence[BasketLine],
    offer_result: OfferEngineResult,
    tax_resolutions: Mapping[int, TaxResolution],
    transaction_currency_code: str,
    rounding_policy: RoundingPolicy,
    price_publication_revisions: Mapping[int, int],
    assignment_revisions: Mapping[int, int],
    price_publication_revision_ceiling: int,
    assignment_revision_ceiling: int,
    offer_revision_ceiling: int,
    tax_revision_ceiling: int,
) -> CommercialCalculation:
    policy = validate_rounding_policy(rounding_policy)
    currency = normalize_currency_code(transaction_currency_code)
    if currency != policy.currency_code:
        raise CalculationError(
            "ROUNDING_POLICY_CURRENCY_MISMATCH",
            "Rounding policy currency does not match transaction currency.",
            context={
                "transaction_currency_code": currency,
                "rounding_policy_currency_code": policy.currency_code,
            },
        )

    ceilings = {
        "price_publication_revision_ceiling": price_publication_revision_ceiling,
        "assignment_revision_ceiling": assignment_revision_ceiling,
        "offer_revision_ceiling": offer_revision_ceiling,
        "tax_revision_ceiling": tax_revision_ceiling,
    }
    if (
        not isinstance(price_publication_revision_ceiling, int)
        or price_publication_revision_ceiling <= 0
        or not isinstance(assignment_revision_ceiling, int)
        or assignment_revision_ceiling <= 0
        or not isinstance(offer_revision_ceiling, int)
        or offer_revision_ceiling < 0
        or not isinstance(tax_revision_ceiling, int)
        or tax_revision_ceiling <= 0
    ):
        raise CalculationError(
            "COMMERCIAL_REVISION_CEILING_INVALID",
            "Commercial revision ceilings are invalid.",
            status_code=422,
            context=ceilings,
        )

    ordered_lines = sorted(basket_lines, key=lambda row: row.line_id)
    line_ids = [row.line_id for row in ordered_lines]
    product_ids = [row.product_variant_id for row in ordered_lines]
    if not ordered_lines:
        raise CalculationError(
            "CALCULATION_EMPTY_DOCUMENT",
            "A commercial calculation requires at least one line.",
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
    if any(
        not isinstance(value, int) or isinstance(value, bool) or value <= 0
        for value in (*line_ids, *product_ids)
    ):
        raise CalculationError(
            "CALCULATION_INPUT_INVALID",
            "Line and product identifiers must be positive integers.",
            status_code=422,
        )
    for line in ordered_lines:
        if (
            not isinstance(line.quantity, Decimal)
            or not line.quantity.is_finite()
            or not isinstance(line.unit_price, Decimal)
            or not line.unit_price.is_finite()
            or line.base_uom_id <= 0
            or line.price_entry_id <= 0
        ):
            raise CalculationError(
                "CALCULATION_LINE_INVALID",
                "Calculation line contains invalid structural or decimal evidence.",
                status_code=422,
                context={"line_id": line.line_id},
            )

    if set(offer_result.line_net_amounts) != set(line_ids):
        raise CalculationError(
            "CALCULATION_OFFER_RESULT_MISMATCH",
            "Offer result lines do not match calculation lines.",
        )
    expected_offer_gross = sum((line.gross_amount for line in ordered_lines), ZERO)
    expected_offer_net = sum(
        (offer_result.line_net_amounts[line_id] for line_id in line_ids),
        ZERO,
    )
    adjustment_discount = sum(
        (row.discount_amount for row in offer_result.adjustments),
        ZERO,
    )
    if (
        offer_result.gross_amount != expected_offer_gross
        or offer_result.net_amount != expected_offer_net
        or offer_result.discount_amount != expected_offer_gross - expected_offer_net
        or adjustment_discount != offer_result.discount_amount
    ):
        raise CalculationError(
            "CALCULATION_OFFER_RESULT_MISMATCH",
            "Offer engine summary/evidence does not reconcile with calculation lines.",
        )

    missing_tax = sorted(set(product_ids) - set(tax_resolutions))
    foreign_tax = sorted(set(tax_resolutions) - set(product_ids))
    if missing_tax or foreign_tax:
        raise CalculationError(
            "CALCULATION_TAX_RESULT_MISMATCH",
            "Tax resolutions do not match calculation products.",
            context={"missing": missing_tax, "unexpected": foreign_tax},
        )

    if (
        set(price_publication_revisions) != set(product_ids)
        or set(assignment_revisions) != set(product_ids)
    ):
        raise CalculationError(
            "CALCULATION_PRICE_EVIDENCE_MISMATCH",
            "Price revision evidence does not match calculation products.",
        )

    valid_line_ids = set(line_ids)
    for evidence in (*offer_result.adjustments, *offer_result.rewards, *offer_result.applied_offers):
        revision = int(evidence.offer_revision)
        if revision <= 0 or revision > offer_revision_ceiling:
            raise CalculationError(
                "CALCULATION_OFFER_REVISION_OUT_OF_LOCK",
                "Applied offer evidence exceeds the locked offer revision ceiling.",
                context={"offer_revision": revision, "offer_revision_ceiling": offer_revision_ceiling},
            )
    for adjustment in offer_result.adjustments:
        if int(adjustment.line_id) not in valid_line_ids:
            raise CalculationError(
                "CALCULATION_OFFER_RESULT_MISMATCH",
                "Offer adjustment refers to an unknown calculation line.",
                context={"line_id": int(adjustment.line_id)},
            )

    # Free-goods rewards remain typed evidence with zero consideration here.
    # We do not invent a deemed tax base. A jurisdiction needing deemed-value
    # taxation requires an explicit future typed tax rule, never a silent fallback.
    if (
        offer_result.calculated_at.tzinfo is None
        or offer_result.calculated_at.utcoffset() is None
    ):
        raise CalculationError(
            "CALCULATION_CONTEXT_TIME_MISMATCH",
            "Offer engine calculation timestamp must include a UTC offset.",
        )

    calculated_lines: list[CalculatedLine] = []
    raw_document_final = ZERO

    for line in ordered_lines:
        if line.quantity <= 0 or line.unit_price < 0:
            raise CalculationError(
                "CALCULATION_LINE_INVALID",
                "Line quantity must be positive and price must be non-negative.",
                status_code=422,
                context={"line_id": line.line_id},
            )

        publication_revision = int(price_publication_revisions[line.product_variant_id])
        assignment_revision = int(assignment_revisions[line.product_variant_id])
        if publication_revision <= 0 or publication_revision > price_publication_revision_ceiling:
            raise CalculationError(
                "CALCULATION_PRICE_REVISION_OUT_OF_LOCK",
                "Selected price revision exceeds the locked publication ceiling.",
                context={
                    "line_id": line.line_id,
                    "price_publication_revision": publication_revision,
                    "price_publication_revision_ceiling": price_publication_revision_ceiling,
                },
            )
        if assignment_revision <= 0 or assignment_revision > assignment_revision_ceiling:
            raise CalculationError(
                "CALCULATION_ASSIGNMENT_REVISION_OUT_OF_LOCK",
                "Selected price assignment revision exceeds the locked assignment ceiling.",
                context={
                    "line_id": line.line_id,
                    "assignment_revision": assignment_revision,
                    "assignment_revision_ceiling": assignment_revision_ceiling,
                },
            )

        tax_resolution = tax_resolutions[line.product_variant_id]
        if tax_resolution.product_variant_id != line.product_variant_id:
            raise CalculationError(
                "CALCULATION_TAX_RESULT_MISMATCH",
                "Tax resolution product does not match the calculation line.",
                context={"line_id": line.line_id},
            )
        if tax_resolution.resolved_at != offer_result.calculated_at:
            raise CalculationError(
                "CALCULATION_CONTEXT_TIME_MISMATCH",
                "Tax and offer authorities were not resolved at the same commercial timestamp.",
                context={"line_id": line.line_id},
            )
        if tax_resolution.tax_revision <= 0 or tax_resolution.tax_revision > tax_revision_ceiling:
            raise CalculationError(
                "CALCULATION_TAX_REVISION_OUT_OF_LOCK",
                "Resolved tax revision exceeds the locked tax ceiling.",
                context={
                    "line_id": line.line_id,
                    "tax_revision": tax_resolution.tax_revision,
                    "tax_revision_ceiling": tax_revision_ceiling,
                },
            )

        gross_raw = line.gross_amount
        post_offer_raw = offer_result.line_net_amounts[line.line_id]
        if post_offer_raw < ZERO or post_offer_raw > gross_raw:
            raise CalculationError(
                "CALCULATION_OFFER_RESULT_INVALID",
                "Offer-adjusted amount must be between zero and gross amount.",
                context={"line_id": line.line_id},
            )
        discount_raw = gross_raw - post_offer_raw

        try:
            tax_calc = calculate_tax(post_offer_raw, tax_resolution)
        except TaxError as exc:
            raise CalculationError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                context=exc.context,
            ) from exc
        raw_document_final += tax_calc.total_amount

        gross = round_currency(gross_raw, policy)
        post_offer = round_currency(post_offer_raw, policy)
        discount = gross - post_offer
        taxable = round_currency(tax_calc.taxable_base, policy)
        final = round_currency(tax_calc.total_amount, policy)
        tax_amount = final - taxable
        if min(gross, post_offer, discount, taxable, tax_amount, final) < ZERO:
            raise CalculationError(
                "CALCULATION_NEGATIVE_AMOUNT",
                "Rounding produced a negative commercial amount.",
                context={"line_id": line.line_id},
            )

        component_amounts = reconcile_components(
            raw_amounts=tuple(item.tax_amount for item in tax_calc.components),
            target_total=tax_amount,
            policy=policy,
        )
        rounded_components = tuple(
            RoundedTaxComponent(
                tax_component_id=item.component_id,
                component_code=item.component_code,
                name=item.name,
                sequence=item.sequence,
                rate=item.rate,
                basis_mode=item.basis_mode,
                reporting_code=item.reporting_code,
                unrounded_basis_amount=item.basis_amount,
                unrounded_tax_amount=item.tax_amount,
                tax_amount=component_amounts[index],
            )
            for index, item in enumerate(tax_calc.components)
        )

        if sum((item.tax_amount for item in rounded_components), ZERO) != tax_amount:
            raise CalculationError(
                "CALCULATION_TAX_RECONCILIATION_FAILED",
                "Rounded component taxes do not equal rounded line tax.",
                context={"line_id": line.line_id},
            )
        if gross - discount != post_offer:
            raise CalculationError(
                "CALCULATION_LINE_RECONCILIATION_FAILED",
                "Rounded gross minus discount does not equal post-offer amount.",
                context={"line_id": line.line_id},
            )
        if taxable + tax_amount != final:
            raise CalculationError(
                "CALCULATION_LINE_RECONCILIATION_FAILED",
                "Rounded taxable amount plus tax does not equal line final amount.",
                context={"line_id": line.line_id},
            )

        for field, value in (
            ("gross_amount", gross),
            ("discount_amount", discount),
            ("post_offer_amount", post_offer),
            ("taxable_amount", taxable),
            ("tax_amount", tax_amount),
            ("final_amount", final),
        ):
            _ensure_capacity(value, field)

        calculated_lines.append(
            CalculatedLine(
                line_id=int(line.line_id),
                product_variant_id=int(line.product_variant_id),
                base_uom_id=int(line.base_uom_id),
                quantity=line.quantity,
                price_entry_id=int(line.price_entry_id),
                price_publication_revision=publication_revision,
                assignment_revision=assignment_revision,
                unit_price=line.unit_price,
                gross_amount=gross,
                discount_amount=discount,
                post_offer_amount=post_offer,
                taxable_amount=taxable,
                tax_amount=tax_amount,
                final_amount=final,
                unrounded_final_amount=tax_calc.total_amount,
                tax_rule_set_id=tax_resolution.tax_rule_set_id,
                tax_rule_set_version_id=tax_resolution.tax_rule_set_version_id,
                tax_revision=tax_resolution.tax_revision,
                tax_price_mode=tax_resolution.price_mode,
                tax_components=rounded_components,
            )
        )

    gross_total = sum((row.gross_amount for row in calculated_lines), ZERO)
    discount_total = sum((row.discount_amount for row in calculated_lines), ZERO)
    post_offer_total = sum((row.post_offer_amount for row in calculated_lines), ZERO)
    taxable_total = sum((row.taxable_amount for row in calculated_lines), ZERO)
    tax_total = sum((row.tax_amount for row in calculated_lines), ZERO)
    line_total = sum((row.final_amount for row in calculated_lines), ZERO)

    if gross_total - discount_total != post_offer_total:
        raise CalculationError(
            "CALCULATION_HEADER_RECONCILIATION_FAILED",
            "Header gross minus discount does not equal post-offer amount.",
        )
    if taxable_total + tax_total != line_total:
        raise CalculationError(
            "CALCULATION_HEADER_RECONCILIATION_FAILED",
            "Header taxable amount plus tax does not equal sum of rounded lines.",
        )

    desired_document_total = round_currency(raw_document_final, policy)
    rounding_adjustment = desired_document_total - line_total
    final_total = line_total + rounding_adjustment

    for field, value in (
        ("gross_amount", gross_total),
        ("discount_amount", discount_total),
        ("post_offer_amount", post_offer_total),
        ("taxable_amount", taxable_total),
        ("tax_amount", tax_total),
        ("line_total_amount", line_total),
        ("rounding_adjustment", rounding_adjustment),
        ("final_amount", final_total),
    ):
        _ensure_capacity(value, field)

    if line_total + rounding_adjustment != final_total:
        raise CalculationError(
            "CALCULATION_HEADER_RECONCILIATION_FAILED",
            "Header rounding adjustment failed to reconcile final amount.",
        )

    return CommercialCalculation(
        calculated_at=offer_result.calculated_at,
        transaction_currency_code=currency,
        rounding_policy=policy,
        price_publication_revision_ceiling=price_publication_revision_ceiling,
        assignment_revision_ceiling=assignment_revision_ceiling,
        offer_revision_ceiling=offer_revision_ceiling,
        tax_revision_ceiling=tax_revision_ceiling,
        lines=tuple(calculated_lines),
        totals=CalculationTotals(
            gross_amount=gross_total,
            discount_amount=discount_total,
            post_offer_amount=post_offer_total,
            taxable_amount=taxable_total,
            tax_amount=tax_total,
            line_total_amount=line_total,
            rounding_adjustment=rounding_adjustment,
            final_amount=final_total,
        ),
        adjustments=offer_result.adjustments,
        rewards=offer_result.rewards,
        applied_offers=offer_result.applied_offers,
        tax_resolutions=dict(tax_resolutions),
    )
