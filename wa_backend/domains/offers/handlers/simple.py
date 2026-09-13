from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import (
    BasketLine,
    CatalogPrice,
    ComponentKey,
    OfferCandidate,
    ZERO,
    money,
)
from domains.offers.handlers.common import (
    allocate_discount,
    component_key,
    discount_limit,
    proposal,
    target_components,
)


def _basis(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[
        ComponentKey,
        Decimal,
    ],
):
    targets = target_components(
        candidate,
        lines,
    )
    basis = {
        component_key(
            line,
            component,
        ): money(
            current_amounts[
                component_key(
                    line,
                    component,
                )
            ]
        )
        for line, component in targets
        if money(
            current_amounts[
                component_key(
                    line,
                    component,
                )
            ]
        ) > ZERO
    }
    identities = {
        component_key(
            line,
            component,
        ): (
            int(line.product_variant_id),
            int(component.uom_id),
        )
        for line, component in targets
    }
    return basis, identities


def percentage_discount(
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
    basis, identities = _basis(
        candidate,
        lines,
        current_amounts,
    )
    available = money(
        sum(basis.values(), ZERO)
    )
    if available <= ZERO:
        return None
    percentage = Decimal(
        str(candidate.payload["percentage"])
    )
    requested = money(
        available
        * percentage
        / Decimal("100")
    )
    total = discount_limit(
        candidate,
        requested,
        available,
    )
    adjustments = allocate_discount(
        total,
        basis,
        identities,
    )
    return proposal(
        candidate,
        adjustments=adjustments,
        metadata={
            "percentage": str(
                percentage
            )
        },
        catalog_prices=catalog_prices,
    )


def fixed_discount(
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
    basis, identities = _basis(
        candidate,
        lines,
        current_amounts,
    )
    available = money(
        sum(basis.values(), ZERO)
    )
    if available <= ZERO:
        return None
    configured = money(
        Decimal(
            str(
                candidate.payload["amount"]
            )
        )
    )
    total = discount_limit(
        candidate,
        configured,
        available,
    )
    adjustments = allocate_discount(
        total,
        basis,
        identities,
    )
    return proposal(
        candidate,
        adjustments=adjustments,
        metadata={
            "configured_amount": str(
                configured
            )
        },
        catalog_prices=catalog_prices,
    )
