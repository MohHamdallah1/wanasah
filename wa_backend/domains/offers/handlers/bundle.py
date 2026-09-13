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
    application_limit,
    component_key,
    discount_limit,
    proposal,
)


def bundle(
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
    terms = tuple(
        row
        for row in candidate.products
        if row.role
        == "BUNDLE_COMPONENT"
    )
    if len(terms) < 2:
        raise ValueError(
            "Bundle requires at least two component rows."
        )

    line_by_variant = {
        int(line.product_variant_id): line
        for line in lines
    }
    applications_by_component: list[
        int
    ] = []
    selected: list[tuple] = []

    for term in terms:
        if (
            term.quantity_per_application
            is None
        ):
            raise ValueError(
                "Bundle component quantity is missing."
            )
        line = line_by_variant.get(
            int(term.product_variant_id)
        )
        if line is None:
            return None
        component = line.component(
            int(term.uom_id)
        )
        if component is None:
            return None
        sold = component.quantity
        required = Decimal(
            term.quantity_per_application
        )
        applications_by_component.append(
            int(sold // required)
        )
        selected.append(
            (
                term,
                line,
                component,
                sold,
                required,
            )
        )

    applications = application_limit(
        candidate,
        min(
            applications_by_component
        ),
    )
    if applications <= 0:
        return None

    basis_by_component: dict[
        ComponentKey,
        Decimal,
    ] = {}
    identities: dict[
        ComponentKey,
        tuple[int, int],
    ] = {}
    for (
        _term,
        line,
        component,
        sold,
        required,
    ) in selected:
        key = component_key(
            line,
            component,
        )
        current = money(
            current_amounts[key]
        )
        if (
            current <= ZERO
            or sold <= ZERO
        ):
            return None
        eligible_quantity = (
            required
            * Decimal(applications)
        )
        basis = money(
            current
            * eligible_quantity
            / sold
        )
        if basis <= ZERO:
            return None
        basis_by_component[key] = money(
            basis_by_component.get(
                key,
                ZERO,
            )
            + basis
        )
        identities[key] = (
            int(
                line.product_variant_id
            ),
            int(component.uom_id),
        )

    basis_total = money(
        sum(
            basis_by_component.values(),
            ZERO,
        )
    )
    if basis_total <= ZERO:
        return None

    reward_type = str(
        candidate.payload[
            "reward_type"
        ]
    )
    reward_value = Decimal(
        str(
            candidate.payload[
                "reward_value"
            ]
        )
    )

    if (
        reward_type
        == "PERCENTAGE_DISCOUNT"
    ):
        requested = money(
            basis_total
            * reward_value
            / Decimal("100")
        )
    elif (
        reward_type
        == "FIXED_DISCOUNT"
    ):
        requested = money(
            reward_value
            * Decimal(applications)
        )
    elif reward_type == "FIXED_PRICE":
        target = money(
            reward_value
            * Decimal(applications)
        )
        requested = money(
            max(
                ZERO,
                basis_total - target,
            )
        )
    else:
        raise ValueError(
            "Unsupported bundle reward "
            f"type: {reward_type}"
        )

    total = discount_limit(
        candidate,
        requested,
        basis_total,
    )
    adjustments = allocate_discount(
        total,
        basis_by_component,
        identities,
    )
    return proposal(
        candidate,
        adjustments=adjustments,
        application_count=applications,
        metadata={
            "component_count": len(
                terms
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
