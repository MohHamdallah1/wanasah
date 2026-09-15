from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import (
    BasketLine,
    BasketPriceComponent,
    CatalogPrice,
    ComponentKey,
    OfferCandidate,
    OfferProposal,
    RequestedAdjustment,
    Reward,
    ZERO,
    money,
)
from domains.offers.core import OfferError
from quantity import QuantityError, parse_quantity


def caps(candidate: OfferCandidate) -> Mapping:
    value = candidate.payload.get("caps")
    return value if isinstance(value, Mapping) else {}


def application_limit(
    candidate: OfferCandidate,
    applications: int,
) -> int:
    configured = caps(candidate).get(
        "max_applications_per_document"
    )
    if configured is None:
        return max(0, applications)
    return min(
        max(0, applications),
        int(configured),
    )


def _reward_quantity(
    candidate: OfferCandidate,
    quantity: Decimal,
) -> Decimal:
    try:
        return parse_quantity(
            quantity,
            "reward_quantity",
        )
    except QuantityError as exc:
        raise OfferError(
            "OFFER_REWARD_QUANTITY_INVALID",
            "Calculated reward quantity exceeds the exact NUMERIC(20,6) contract.",
            status_code=422,
            context={
                "offer_version_id": int(
                    candidate.version_id
                ),
            },
        ) from exc


def reward_limit(
    candidate: OfferCandidate,
    quantity: Decimal,
) -> Decimal:
    configured = caps(candidate).get(
        "max_reward_quantity"
    )
    limited = (
        quantity
        if configured is None
        else min(
            quantity,
            Decimal(str(configured)),
        )
    )
    return _reward_quantity(
        candidate,
        limited,
    )


def discount_limit(
    candidate: OfferCandidate,
    amount: Decimal,
    available: Decimal,
) -> Decimal:
    limited = min(
        max(ZERO, money(amount)),
        max(ZERO, money(available)),
    )
    configured = caps(candidate).get(
        "max_discount_amount"
    )
    if configured is not None:
        limited = min(
            limited,
            money(Decimal(str(configured))),
        )
    return money(limited)


def component_key(
    line: BasketLine,
    component: BasketPriceComponent,
) -> ComponentKey:
    return (
        int(line.line_id),
        int(component.uom_id),
    )


def target_components(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
) -> tuple[
    tuple[BasketLine, BasketPriceComponent],
    ...,
]:
    if not candidate.product_targets:
        return tuple(
            (line, component)
            for line in lines
            for component in line.price_components
        )

    targets_by_variant: dict[
        int,
        list[int | None],
    ] = {}
    for target in candidate.product_targets:
        targets_by_variant.setdefault(
            int(target.product_variant_id),
            [],
        ).append(target.uom_id)

    result: list[
        tuple[BasketLine, BasketPriceComponent]
    ] = []
    for line in lines:
        target_uoms = targets_by_variant.get(
            int(line.product_variant_id)
        )
        if not target_uoms:
            continue
        if any(
            value is None
            for value in target_uoms
        ):
            result.extend(
                (line, component)
                for component in line.price_components
            )
            continue
        allowed = {
            int(value)
            for value in target_uoms
            if value is not None
        }
        result.extend(
            (line, component)
            for component in line.price_components
            if int(component.uom_id) in allowed
        )
    return tuple(result)


def allocate_discount(
    total_discount: Decimal,
    basis_by_component: Mapping[
        ComponentKey,
        Decimal,
    ],
    identity_by_component: Mapping[
        ComponentKey,
        tuple[int, int],
    ],
) -> tuple[RequestedAdjustment, ...]:
    positive = {
        (
            int(key[0]),
            int(key[1]),
        ): money(value)
        for key, value
        in basis_by_component.items()
        if money(value) > ZERO
    }
    basis_total = money(
        sum(positive.values(), ZERO)
    )
    total = min(
        money(total_discount),
        basis_total,
    )
    if (
        total <= ZERO
        or basis_total <= ZERO
    ):
        return ()

    remaining_discount = total
    remaining_basis = basis_total
    result: list[
        RequestedAdjustment
    ] = []
    ordered_keys = sorted(positive)

    for index, key in enumerate(
        ordered_keys
    ):
        basis = positive[key]
        if index == len(ordered_keys) - 1:
            amount = min(
                basis,
                remaining_discount,
            )
        else:
            raw = (
                remaining_discount
                * basis
                / remaining_basis
                if remaining_basis > ZERO
                else ZERO
            )
            amount = min(
                basis,
                money(raw),
            )
        amount = money(amount)
        if amount > ZERO:
            (
                product_variant_id,
                uom_id,
            ) = identity_by_component[key]
            result.append(
                RequestedAdjustment(
                    line_id=key[0],
                    product_variant_id=int(
                        product_variant_id
                    ),
                    uom_id=int(uom_id),
                    basis_amount=basis,
                    discount_amount=amount,
                )
            )
            remaining_discount = money(
                remaining_discount - amount
            )
        remaining_basis = money(
            remaining_basis - basis
        )

    if remaining_discount > ZERO:
        for index in range(
            len(result) - 1,
            -1,
            -1,
        ):
            row = result[index]
            room = money(
                row.basis_amount
                - row.discount_amount
            )
            if room <= ZERO:
                continue
            add = min(
                room,
                remaining_discount,
            )
            result[index] = (
                RequestedAdjustment(
                    line_id=row.line_id,
                    product_variant_id=(
                        row.product_variant_id
                    ),
                    uom_id=row.uom_id,
                    basis_amount=row.basis_amount,
                    discount_amount=money(
                        row.discount_amount + add
                    ),
                )
            )
            remaining_discount = money(
                remaining_discount - add
            )
            if remaining_discount <= ZERO:
                break

    if remaining_discount > ZERO:
        raise ValueError(
            "Offer discount allocation invariant failed."
        )
    return tuple(result)


def proposal(
    candidate: OfferCandidate,
    *,
    adjustments: Sequence[
        RequestedAdjustment
    ] = (),
    rewards: Sequence[Reward] = (),
    application_count: int = 1,
    metadata: Mapping | None = None,
    catalog_prices: Mapping[
        tuple[int, int],
        CatalogPrice,
    ],
) -> OfferProposal | None:
    discount = money(
        sum(
            (
                row.discount_amount
                for row in adjustments
            ),
            ZERO,
        )
    )
    reward_value = ZERO
    for reward in rewards:
        _reward_quantity(
            candidate,
            reward.quantity,
        )
        key = (
            int(reward.product_variant_id),
            int(reward.uom_id),
        )
        price = catalog_prices.get(key)
        if price is None:
            raise OfferError(
                "OFFER_REWARD_PRICE_REQUIRED",
                "Reward product/UOM price is required for deterministic offer comparison.",
                context={
                    "product_variant_id": int(
                        reward.product_variant_id
                    ),
                    "uom_id": int(
                        reward.uom_id
                    ),
                },
            )
        reward_value = money(
            reward_value
            + money(
                reward.quantity
                * price.unit_price
            )
        )

    benefit = money(
        discount + reward_value
    )
    if benefit <= ZERO:
        return None
    return OfferProposal(
        candidate=candidate,
        adjustments=tuple(adjustments),
        rewards=tuple(rewards),
        application_count=int(
            application_count
        ),
        metadata=dict(metadata or {}),
        benefit_amount=benefit,
    )
