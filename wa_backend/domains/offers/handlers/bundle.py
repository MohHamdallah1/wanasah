from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import BasketLine, CatalogPrice, OfferCandidate, ZERO, money
from domains.offers.handlers.common import (
    allocate_discount,
    application_limit,
    discount_limit,
    proposal,
)


def bundle(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[int, Decimal],
    catalog_prices: Mapping[int, CatalogPrice],
):
    component_ids = {
        row.product_variant_id
        for row in candidate.products
        if row.role == "BUNDLE_COMPONENT"
    }
    if len(component_ids) < 2:
        raise ValueError("Bundle requires at least two component variants.")

    line_by_variant = {line.product_variant_id: line for line in lines}
    if not component_ids.issubset(line_by_variant):
        return None

    required = Decimal(str(candidate.payload["bundle_quantity"]))
    applications = min(
        int(line_by_variant[variant_id].quantity // required)
        for variant_id in component_ids
    )
    applications = application_limit(candidate, applications)
    if applications <= 0:
        return None

    basis_by_line: dict[int, Decimal] = {}
    for variant_id in sorted(component_ids):
        line = line_by_variant[variant_id]
        current = money(current_amounts[line.line_id])
        if current <= ZERO or line.quantity <= ZERO:
            return None
        unit_current = current / line.quantity
        eligible_qty = required * Decimal(applications)
        basis_by_line[line.line_id] = money(unit_current * eligible_qty)

    basis_total = money(sum(basis_by_line.values(), ZERO))
    if basis_total <= ZERO:
        return None

    reward_type = str(candidate.payload["reward_type"])
    reward_value = Decimal(str(candidate.payload["reward_value"]))

    if reward_type == "PERCENTAGE_DISCOUNT":
        requested = money(basis_total * reward_value / Decimal("100"))
    elif reward_type == "FIXED_DISCOUNT":
        requested = money(reward_value * Decimal(applications))
    elif reward_type == "FIXED_PRICE":
        target = money(reward_value * Decimal(applications))
        requested = money(max(ZERO, basis_total - target))
    else:
        raise ValueError(f"Unsupported bundle reward type: {reward_type}")

    total = discount_limit(candidate, requested, basis_total)
    line_by_id = {line.line_id: line for line in lines}
    adjustments = allocate_discount(total, basis_by_line, line_by_id)
    return proposal(
        candidate,
        adjustments=adjustments,
        application_count=applications,
        metadata={
            "bundle_quantity_per_component": str(required),
            "reward_type": reward_type,
            "reward_value": str(reward_value),
        },
        catalog_prices=catalog_prices,
    )
