from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import BasketLine, OfferEngineResult, money
from domains.sales_calculation.contracts import (
    CalculatedLine,
    CalculatedPriceComponent,
    CalculatedReward,
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
    calculated_rewards: Sequence[CalculatedReward],
    tax_resolutions: Mapping[int, TaxResolution],
    transaction_currency_code: str,
    rounding_policy: RoundingPolicy,
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
            "Calculation requires one logical line per product variant.",
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
            or line.quantity <= ZERO
            or line.base_uom_id <= 0
            or not line.price_components
        ):
            raise CalculationError(
                "CALCULATION_LINE_INVALID",
                "Calculation line contains invalid mixed-UOM evidence.",
                status_code=422,
                context={"line_id": line.line_id},
            )

        uoms = [int(row.uom_id) for row in line.price_components]
        if len(uoms) != len(set(uoms)):
            raise CalculationError(
                "CALCULATION_PRICE_COMPONENT_DUPLICATE_UOM",
                "A logical product line cannot repeat a price UOM.",
                status_code=422,
                context={"line_id": line.line_id},
            )

        base_total = ZERO
        for component in line.price_components:
            if (
                int(component.uom_id) <= 0
                or int(component.price_entry_id) <= 0
                or int(component.price_publication_revision) <= 0
                or int(component.price_publication_revision)
                > price_publication_revision_ceiling
                or int(component.assignment_revision) <= 0
                or int(component.assignment_revision)
                > assignment_revision_ceiling
                or not component.quantity.is_finite()
                or component.quantity <= ZERO
                or not component.base_quantity.is_finite()
                or component.base_quantity <= ZERO
                or not component.unit_price.is_finite()
                or component.unit_price < ZERO
            ):
                raise CalculationError(
                    "CALCULATION_PRICE_COMPONENT_INVALID",
                    "Price component contains invalid or out-of-lock evidence.",
                    status_code=422,
                    context={
                        "line_id": line.line_id,
                        "uom_id": component.uom_id,
                    },
                )
            base_total += component.base_quantity
        if base_total != line.quantity:
            raise CalculationError(
                "CALCULATION_PRICE_COMPONENT_RECONCILIATION_FAILED",
                "Price component base quantities do not equal canonical line quantity.",
                context={"line_id": line.line_id},
            )

    if set(offer_result.line_net_amounts) != set(line_ids):
        raise CalculationError(
            "CALCULATION_OFFER_RESULT_MISMATCH",
            "Offer result lines do not match calculation lines.",
        )
    expected_offer_gross = sum(
        (line.gross_amount for line in ordered_lines),
        ZERO,
    )
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
        or offer_result.discount_amount
        != expected_offer_gross - expected_offer_net
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

    valid_line_ids = set(line_ids)
    for evidence in (
        *offer_result.adjustments,
        *offer_result.rewards,
        *offer_result.applied_offers,
    ):
        revision = int(evidence.offer_revision)
        if revision <= 0 or revision > offer_revision_ceiling:
            raise CalculationError(
                "CALCULATION_OFFER_REVISION_OUT_OF_LOCK",
                "Applied offer evidence exceeds the locked offer revision ceiling.",
                context={
                    "offer_revision": revision,
                    "offer_revision_ceiling": offer_revision_ceiling,
                },
            )
    for adjustment in offer_result.adjustments:
        if int(adjustment.line_id) not in valid_line_ids:
            raise CalculationError(
                "CALCULATION_OFFER_RESULT_MISMATCH",
                "Offer adjustment refers to an unknown calculation line.",
                context={"line_id": int(adjustment.line_id)},
            )

    if (
        offer_result.calculated_at.tzinfo is None
        or offer_result.calculated_at.utcoffset() is None
    ):
        raise CalculationError(
            "CALCULATION_CONTEXT_TIME_MISMATCH",
            "Offer engine calculation timestamp must include a UTC offset.",
        )

    raw_reward_identity = [
        (
            int(row.sequence),
            int(row.offer_version_id),
            int(row.offer_definition_id),
            int(row.offer_revision),
            str(row.offer_type),
            int(row.product_variant_id),
            int(row.uom_id),
            row.quantity,
        )
        for row in offer_result.rewards
    ]
    calculated_reward_identity = [
        (
            int(row.sequence),
            int(row.offer_version_id),
            int(row.offer_definition_id),
            int(row.offer_revision),
            str(row.offer_type),
            int(row.product_variant_id),
            int(row.uom_id),
            row.quantity,
        )
        for row in calculated_rewards
    ]
    if raw_reward_identity != calculated_reward_identity:
        raise CalculationError(
            "CALCULATION_REWARD_EVIDENCE_MISMATCH",
            "Typed reward evidence does not match the applied offer rewards.",
        )

    reward_value_by_sequence: dict[int, Decimal] = {}
    seen_reward_keys: set[tuple[int, int, int]] = set()
    for reward in calculated_rewards:
        key = (
            int(reward.sequence),
            int(reward.product_variant_id),
            int(reward.uom_id),
        )
        if key in seen_reward_keys:
            raise CalculationError(
                "CALCULATION_REWARD_EVIDENCE_DUPLICATE",
                "Typed reward evidence repeats the same offer/product/UOM.",
                context={
                    "offer_sequence": key[0],
                    "product_variant_id": key[1],
                    "uom_id": key[2],
                },
            )
        seen_reward_keys.add(key)
        if (
            reward.sequence <= 0
            or reward.product_variant_id <= 0
            or reward.uom_id <= 0
            or reward.price_entry_id <= 0
            or reward.offer_revision <= 0
            or reward.offer_revision > offer_revision_ceiling
            or reward.price_publication_revision <= 0
            or reward.price_publication_revision
            > price_publication_revision_ceiling
            or reward.assignment_revision <= 0
            or reward.assignment_revision > assignment_revision_ceiling
            or not reward.quantity.is_finite()
            or reward.quantity <= ZERO
            or not reward.base_quantity.is_finite()
            or reward.base_quantity <= ZERO
            or not reward.unit_price.is_finite()
            or reward.unit_price < ZERO
            or not reward.reward_value.is_finite()
            or reward.reward_value < ZERO
            or reward.reward_value
            != money(reward.quantity * reward.unit_price)
        ):
            raise CalculationError(
                "CALCULATION_REWARD_EVIDENCE_INVALID",
                "Typed reward evidence contains invalid or out-of-lock values.",
                context={
                    "offer_sequence": int(reward.sequence),
                    "product_variant_id": int(reward.product_variant_id),
                    "uom_id": int(reward.uom_id),
                },
            )
        reward_value_by_sequence[reward.sequence] = money(
            reward_value_by_sequence.get(reward.sequence, ZERO)
            + reward.reward_value
        )

    for applied in offer_result.applied_offers:
        expected = money(applied.reward_value)
        actual = reward_value_by_sequence.get(int(applied.sequence), money(ZERO))
        if expected != actual:
            raise CalculationError(
                "CALCULATION_REWARD_RECONCILIATION_FAILED",
                "Typed reward values do not reconcile to applied offer evidence.",
                context={
                    "offer_sequence": int(applied.sequence),
                    "expected_reward_value": str(expected),
                    "actual_reward_value": str(actual),
                },
            )

    calculated_lines: list[CalculatedLine] = []
    raw_document_final = ZERO

    for line in ordered_lines:
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
        if (
            tax_resolution.tax_revision <= 0
            or tax_resolution.tax_revision > tax_revision_ceiling
        ):
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
            raw_amounts=tuple(
                item.tax_amount for item in tax_calc.components
            ),
            target_total=tax_amount,
            policy=policy,
        )
        rounded_tax_components = tuple(
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

        if (
            sum(
                (item.tax_amount for item in rounded_tax_components),
                ZERO,
            )
            != tax_amount
        ):
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

        calculated_price_components = tuple(
            CalculatedPriceComponent(
                sequence=index,
                uom_id=int(component.uom_id),
                quantity=component.quantity,
                base_quantity=component.base_quantity,
                price_entry_id=int(component.price_entry_id),
                price_publication_revision=int(
                    component.price_publication_revision
                ),
                assignment_revision=int(component.assignment_revision),
                unit_price=component.unit_price,
                gross_amount=component.gross_amount,
            )
            for index, component in enumerate(
                line.price_components,
                start=1,
            )
        )
        if (
            sum(
                (row.gross_amount for row in calculated_price_components),
                ZERO,
            )
            != gross_raw
        ):
            raise CalculationError(
                "CALCULATION_PRICE_COMPONENT_RECONCILIATION_FAILED",
                "Calculated price components do not reconcile to raw line gross.",
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
                price_components=calculated_price_components,
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
                tax_components=rounded_tax_components,
            )
        )

    gross_total = sum(
        (row.gross_amount for row in calculated_lines),
        ZERO,
    )
    discount_total = sum(
        (row.discount_amount for row in calculated_lines),
        ZERO,
    )
    post_offer_total = sum(
        (row.post_offer_amount for row in calculated_lines),
        ZERO,
    )
    taxable_total = sum(
        (row.taxable_amount for row in calculated_lines),
        ZERO,
    )
    tax_total = sum(
        (row.tax_amount for row in calculated_lines),
        ZERO,
    )
    line_total = sum(
        (row.final_amount for row in calculated_lines),
        ZERO,
    )

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

    desired_document_total = round_currency(
        raw_document_final,
        policy,
    )
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
        rewards=tuple(calculated_rewards),
        applied_offers=offer_result.applied_offers,
        tax_resolutions=tax_resolutions,
    )
