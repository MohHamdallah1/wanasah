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
)
from domains.offers.handlers.common import (
    application_limit,
    proposal,
)


def _role_rows(
    candidate: OfferCandidate,
    role: str,
):
    return tuple(
        row
        for row in candidate.products
        if row.role == role
    )


def _free_reward(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    catalog_prices: Mapping[
        tuple[int, int],
        CatalogPrice,
    ],
    *,
    qualifying_quantity: Decimal,
):
    qualifying = _role_rows(
        candidate,
        "QUALIFYING",
    )
    rewards = _role_rows(
        candidate,
        "REWARD",
    )
    if not qualifying or not rewards:
        raise ValueError(
            "Cross-product offer configuration is not canonical."
        )

    qualifying_uoms = {
        int(row.uom_id)
        for row in qualifying
    }
    if len(qualifying_uoms) != 1:
        raise ValueError(
            "Qualifying pool must use one explicit UOM."
        )
    qualifying_uom = next(
        iter(qualifying_uoms)
    )

    line_by_variant = {
        int(line.product_variant_id): line
        for line in lines
    }
    purchased = ZERO
    for row in qualifying:
        line = line_by_variant.get(
            int(row.product_variant_id)
        )
        if line is not None:
            purchased += (
                line.quantity_for_uom(
                    qualifying_uom
                )
            )

    applications = int(
        purchased
        // qualifying_quantity
    )
    applications = application_limit(
        candidate,
        applications,
    )
    if applications <= 0:
        return None

    reward_rows: list[Reward] = []
    for row in sorted(
        rewards,
        key=lambda item: (
            item.product_variant_id,
            item.uom_id,
        ),
    ):
        if (
            row.quantity_per_application
            is None
        ):
            raise ValueError(
                "Reward quantity is missing."
            )
        quantity = (
            Decimal(
                row.quantity_per_application
            )
            * Decimal(applications)
        )
        if quantity <= ZERO:
            continue
        reward_rows.append(
            Reward(
                product_variant_id=int(
                    row.product_variant_id
                ),
                uom_id=int(row.uom_id),
                quantity=quantity,
            )
        )

    if not reward_rows:
        return None

    return proposal(
        candidate,
        rewards=tuple(reward_rows),
        application_count=applications,
        metadata={
            "qualifying_uom_id": (
                qualifying_uom
            ),
            "qualifying_quantity": str(
                qualifying_quantity
            ),
            "reward_count": len(
                reward_rows
            ),
        },
        catalog_prices=catalog_prices,
    )


def buy_x_get_y(
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
    del current_amounts
    return _free_reward(
        candidate,
        lines,
        catalog_prices,
        qualifying_quantity=Decimal(
            str(
                candidate.payload[
                    "buy_quantity"
                ]
            )
        ),
    )


def free_goods(
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
    del current_amounts
    return _free_reward(
        candidate,
        lines,
        catalog_prices,
        qualifying_quantity=Decimal(
            str(
                candidate.payload[
                    "qualifying_quantity"
                ]
            )
        ),
    )
