from __future__ import annotations

from dataclasses import replace
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from domains.taxation.contracts import (
    TaxCalculation,
    TaxComponentCalculation,
    TaxResolution,
)
from domains.taxation.core import TaxError


HUNDRED = Decimal("100")
MONEY_MAX = Decimal("99999999999999.999999")
CALCULATION_PRECISION = 60


def _amount(value: Any) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise TaxError(
            "TAX_AMOUNT_INVALID",
            "Tax calculation amount is invalid.",
            status_code=422,
        ) from exc
    if not result.is_finite() or result < 0:
        raise TaxError(
            "TAX_AMOUNT_INVALID",
            "Tax calculation amount must be finite and non-negative.",
            status_code=422,
        )
    if result > MONEY_MAX:
        raise TaxError(
            "TAX_AMOUNT_INVALID",
            "Tax calculation amount exceeds NUMERIC(20,6) capacity.",
            status_code=422,
        )
    return result


def _component_amounts(
    taxable_base: Decimal,
    resolution: TaxResolution,
) -> tuple[TaxComponentCalculation, ...]:
    prior_tax = Decimal("0")
    rows: list[TaxComponentCalculation] = []
    for component in resolution.components:
        if component.rate < 0 or not component.rate.is_finite():
            raise TaxError(
                "TAX_CONFIGURATION_INVALID",
                "Published tax component has an invalid rate.",
                context={"tax_component_id": component.component_id},
            )
        if component.basis_mode == "TAXABLE_BASE":
            basis = taxable_base
        elif component.basis_mode == "TAXABLE_BASE_PLUS_PRIOR_TAX":
            basis = taxable_base + prior_tax
        else:
            raise TaxError(
                "TAX_CONFIGURATION_INVALID",
                "Published tax component has an invalid basis mode.",
                context={"tax_component_id": component.component_id},
            )

        # Stored tax rates are percentage points: 5.00000000 means 5%.
        tax_amount = basis * (component.rate / HUNDRED)
        rows.append(
            TaxComponentCalculation(
                component_id=component.component_id,
                component_code=component.component_code,
                name=component.name,
                sequence=component.sequence,
                rate=component.rate,
                basis_mode=component.basis_mode,
                reporting_code=component.reporting_code,
                basis_amount=basis,
                tax_amount=tax_amount,
            )
        )
        prior_tax += tax_amount
    return tuple(rows)


def calculate_tax(
    amount: Any,
    resolution: TaxResolution,
) -> TaxCalculation:
    input_amount = _amount(amount)
    if not resolution.components:
        raise TaxError(
            "TAX_CONFIGURATION_INVALID",
            "Resolved tax rule contains no tax components.",
            context={"tax_rule_set_version_id": resolution.tax_rule_set_version_id},
        )

    sequences = [component.sequence for component in resolution.components]
    if sequences != list(range(1, len(resolution.components) + 1)):
        raise TaxError(
            "TAX_CONFIGURATION_INVALID",
            "Resolved tax component sequence must be contiguous and start at 1.",
            context={
                "tax_rule_set_version_id": resolution.tax_rule_set_version_id,
                "sequences": sequences,
            },
        )
    if resolution.components[0].basis_mode != "TAXABLE_BASE":
        raise TaxError(
            "TAX_CONFIGURATION_INVALID",
            "The first resolved tax component must use TAXABLE_BASE.",
            context={"tax_rule_set_version_id": resolution.tax_rule_set_version_id},
        )

    with localcontext() as ctx:
        # Computational precision only. Currency rounding belongs to Stage 6E.
        ctx.prec = CALCULATION_PRECISION

        if resolution.price_mode == "EXCLUSIVE":
            taxable_base = input_amount
            components = _component_amounts(taxable_base, resolution)
            tax_amount = sum(
                (row.tax_amount for row in components),
                Decimal("0"),
            )
            total_amount = taxable_base + tax_amount

        elif resolution.price_mode == "INCLUSIVE":
            prior_factor = Decimal("0")
            for component in resolution.components:
                if component.basis_mode == "TAXABLE_BASE":
                    basis_factor = Decimal("1")
                elif component.basis_mode == "TAXABLE_BASE_PLUS_PRIOR_TAX":
                    basis_factor = Decimal("1") + prior_factor
                else:
                    raise TaxError(
                        "TAX_CONFIGURATION_INVALID",
                        "Published tax component has an invalid basis mode.",
                        context={"tax_component_id": component.component_id},
                    )
                prior_factor += basis_factor * (component.rate / HUNDRED)

            divisor = Decimal("1") + prior_factor
            if divisor <= 0:
                raise TaxError(
                    "TAX_CONFIGURATION_INVALID",
                    "Inclusive tax divisor is invalid.",
                    context={"tax_rule_set_version_id": resolution.tax_rule_set_version_id},
                )

            taxable_base = input_amount / divisor
            components = _component_amounts(taxable_base, resolution)
            target_tax = input_amount - taxable_base
            calculated_tax = sum(
                (row.tax_amount for row in components),
                Decimal("0"),
            )

            # Decimal division can be repeating. Reconcile only the representation
            # residue at working precision; this is not currency rounding.
            residue = target_tax - calculated_tax
            if residue and components:
                last = components[-1]
                components = components[:-1] + (
                    replace(last, tax_amount=last.tax_amount + residue),
                )

            tax_amount = target_tax
            total_amount = input_amount

        else:
            raise TaxError(
                "TAX_CONFIGURATION_INVALID",
                "Resolved tax rule has an invalid price mode.",
                context={
                    "tax_rule_set_version_id": resolution.tax_rule_set_version_id,
                    "price_mode": resolution.price_mode,
                },
            )

        if taxable_base > MONEY_MAX or tax_amount > MONEY_MAX or total_amount > MONEY_MAX:
            raise TaxError(
                "TAX_AMOUNT_OVERFLOW",
                "Tax calculation exceeds NUMERIC(20,6) monetary capacity.",
                context={
                    "tax_rule_set_version_id": resolution.tax_rule_set_version_id,
                },
            )

    return TaxCalculation(
        input_amount=input_amount,
        price_mode=resolution.price_mode,
        taxable_base=taxable_base,
        tax_amount=tax_amount,
        total_amount=total_amount,
        components=components,
    )
