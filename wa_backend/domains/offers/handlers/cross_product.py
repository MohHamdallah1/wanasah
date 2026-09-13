from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import (
    BasketLine,
    CatalogPrice,
    OfferCandidate,
    Reward,
    ZERO,
)
from domains.offers.handlers.common import application_limit, proposal, reward_limit


def _role_ids(candidate: OfferCandidate, role: str) -> tuple[int, ...]:
    return tuple(
        row.product_variant_id for row in candidate.products if row.role == role
    )


def _free_reward(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    catalog_prices: Mapping[int, CatalogPrice],
    *,
    qualifying_quantity: Decimal,
    reward_quantity: Decimal,
):
    qualifying_ids = set(_role_ids(candidate, "QUALIFYING"))
    reward_ids = _role_ids(candidate, "REWARD")
    if not qualifying_ids or len(reward_ids) != 1:
        raise ValueError("Cross-product offer configuration is not canonical.")

    qualifying_lines = [
        line for line in lines if line.product_variant_id in qualifying_ids
    ]
    if not qualifying_lines:
        return None

    # Aggregating quantities from multiple qualifying variants is valid only when
    # those variants share the same canonical UOM. Never add cartons to pieces.
    uom_ids = {line.base_uom_id for line in qualifying_lines}
    if len(uom_ids) != 1:
        raise ValueError(
            "Qualifying products use different base UOMs and cannot share one quantity threshold."
        )

    purchased = sum((line.quantity for line in qualifying_lines), ZERO)
    applications = int(purchased // qualifying_quantity)
    applications = application_limit(candidate, applications)
    if applications <= 0:
        return None

    reward_id = int(reward_ids[0])
    reward_price = catalog_prices.get(reward_id)
    if reward_price is None:
        raise ValueError(f"Missing canonical price for reward product {reward_id}.")

    quantity = reward_limit(
        candidate, reward_quantity * Decimal(applications)
    )
    if quantity <= ZERO:
        return None

    return proposal(
        candidate,
        rewards=(
            Reward(
                product_variant_id=reward_id,
                base_uom_id=reward_price.base_uom_id,
                quantity=quantity,
            ),
        ),
        application_count=applications,
        metadata={
            "qualifying_quantity": str(qualifying_quantity),
            "reward_quantity_per_application": str(reward_quantity),
        },
        catalog_prices=catalog_prices,
    )


def buy_x_get_y(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[int, Decimal],
    catalog_prices: Mapping[int, CatalogPrice],
):
    del current_amounts
    return _free_reward(
        candidate,
        lines,
        catalog_prices,
        qualifying_quantity=Decimal(str(candidate.payload["buy_quantity"])),
        reward_quantity=Decimal(str(candidate.payload["get_quantity"])),
    )


def free_goods(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[int, Decimal],
    catalog_prices: Mapping[int, CatalogPrice],
):
    del current_amounts
    return _free_reward(
        candidate,
        lines,
        catalog_prices,
        qualifying_quantity=Decimal(str(candidate.payload["qualifying_quantity"])),
        reward_quantity=Decimal(str(candidate.payload["free_quantity"])),
    )
