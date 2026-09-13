from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import (
    BasketLine,
    CatalogPrice,
    OfferCandidate,
    Reward,
    ZERO,
    money,
)
from domains.offers.handlers.common import (
    allocate_discount,
    discount_limit,
    proposal,
    reward_limit,
    target_lines,
)


def quantity_tiers(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[int, Decimal],
    catalog_prices: Mapping[int, CatalogPrice],
):
    targets = target_lines(candidate, lines)
    if not targets:
        return None
    variant_ids = {line.product_variant_id for line in targets}
    if len(variant_ids) != 1:
        raise ValueError("Quantity-tier offer must target exactly one product variant.")

    quantity = sum((line.quantity for line in targets), ZERO)
    tiers = candidate.payload["tiers"]
    selected = None
    for tier in tiers:
        minimum = Decimal(str(tier["minimum_quantity"]))
        if quantity >= minimum:
            selected = tier
        else:
            break
    if selected is None:
        return None

    line_by_id = {line.line_id: line for line in lines}
    basis = {
        line.line_id: money(current_amounts[line.line_id])
        for line in targets
        if money(current_amounts[line.line_id]) > ZERO
    }
    available = money(sum(basis.values(), ZERO))
    reward_type = str(selected["reward_type"])
    reward_value = Decimal(str(selected["reward_value"]))

    adjustments = ()
    rewards = ()
    if reward_type == "PERCENTAGE_DISCOUNT":
        requested = money(available * reward_value / Decimal("100"))
        total = discount_limit(candidate, requested, available)
        adjustments = allocate_discount(total, basis, line_by_id)
    elif reward_type == "FIXED_DISCOUNT":
        total = discount_limit(candidate, money(reward_value), available)
        adjustments = allocate_discount(total, basis, line_by_id)
    elif reward_type == "FREE_QUANTITY":
        target = targets[0]
        qty = reward_limit(candidate, reward_value)
        if qty > ZERO:
            rewards = (
                Reward(
                    product_variant_id=target.product_variant_id,
                    base_uom_id=target.base_uom_id,
                    quantity=qty,
                ),
            )
    else:
        raise ValueError(f"Unsupported quantity-tier reward type: {reward_type}")

    return proposal(
        candidate,
        adjustments=adjustments,
        rewards=rewards,
        metadata={
            "minimum_quantity": str(selected["minimum_quantity"]),
            "reward_type": reward_type,
            "reward_value": str(reward_value),
        },
        catalog_prices=catalog_prices,
    )
