from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import (
    BasketLine,
    CatalogPrice,
    ComponentKey,
    OfferCandidate,
    Reward,
    ZERO,
    money,
)
from domains.offers.handlers.common import (
    allocate_discount,
    component_key,
    discount_limit,
    proposal,
    reward_limit,
)


def quantity_tiers(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[
        ComponentKey,
        Decimal,
    ],
    catalog_prices: Mapping[
        tuple[int, int],
        CatalogPrice,
    ],
):
    if (
        len(candidate.product_targets)
        != 1
    ):
        raise ValueError(
            "Quantity-tier offer must target exactly one product variant/UOM."
        )
    target = candidate.product_targets[0]
    if target.uom_id is None:
        raise ValueError(
            "Quantity-tier target UOM is missing."
        )
    line = next(
        (
            row
            for row in lines
            if int(
                row.product_variant_id
            )
            == int(
                target.product_variant_id
            )
        ),
        None,
    )
    if line is None:
        return None

    target_uom = int(target.uom_id)
    component = line.component(
        target_uom
    )
    if component is None:
        return None
    quantity = component.quantity

    selected = None
    for tier in candidate.payload[
        "tiers"
    ]:
        minimum = Decimal(
            str(
                tier[
                    "minimum_quantity"
                ]
            )
        )
        if quantity >= minimum:
            selected = tier
        else:
            break
    if selected is None:
        return None

    key = component_key(
        line,
        component,
    )
    basis_amount = money(
        current_amounts[key]
    )
    basis = (
        {key: basis_amount}
        if basis_amount > ZERO
        else {}
    )
    identities = {
        key: (
            int(
                line.product_variant_id
            ),
            int(component.uom_id),
        )
    }
    available = money(
        sum(basis.values(), ZERO)
    )
    reward_type = str(
        selected["reward_type"]
    )
    reward_value = Decimal(
        str(
            selected["reward_value"]
        )
    )

    adjustments = ()
    rewards = ()
    if (
        reward_type
        == "PERCENTAGE_DISCOUNT"
    ):
        requested = money(
            available
            * reward_value
            / Decimal("100")
        )
        total = discount_limit(
            candidate,
            requested,
            available,
        )
        adjustments = (
            allocate_discount(
                total,
                basis,
                identities,
            )
        )
    elif (
        reward_type
        == "FIXED_DISCOUNT"
    ):
        total = discount_limit(
            candidate,
            money(reward_value),
            available,
        )
        adjustments = (
            allocate_discount(
                total,
                basis,
                identities,
            )
        )
    elif (
        reward_type
        == "FREE_QUANTITY"
    ):
        qty = reward_limit(
            candidate,
            reward_value,
        )
        if qty > ZERO:
            rewards = (
                Reward(
                    product_variant_id=int(
                        line.product_variant_id
                    ),
                    uom_id=target_uom,
                    quantity=qty,
                ),
            )
    else:
        raise ValueError(
            "Unsupported quantity-tier "
            f"reward type: {reward_type}"
        )

    return proposal(
        candidate,
        adjustments=adjustments,
        rewards=rewards,
        metadata={
            "target_uom_id": (
                target_uom
            ),
            "minimum_quantity": str(
                selected[
                    "minimum_quantity"
                ]
            ),
            "reward_type": (
                reward_type
            ),
            "reward_value": str(
                reward_value
            ),
        },
        catalog_prices=catalog_prices,
    )
