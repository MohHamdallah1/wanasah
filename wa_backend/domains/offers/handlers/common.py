from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import (
    BasketLine,
    CatalogPrice,
    MONEY_QUANT,
    OfferCandidate,
    OfferProposal,
    RequestedAdjustment,
    Reward,
    ZERO,
    money,
)


def caps(candidate: OfferCandidate) -> Mapping:
    value = candidate.payload.get("caps")
    return value if isinstance(value, Mapping) else {}


def application_limit(candidate: OfferCandidate, applications: int) -> int:
    configured = caps(candidate).get("max_applications_per_document")
    if configured is None:
        return max(0, applications)
    return min(max(0, applications), int(configured))


def reward_limit(candidate: OfferCandidate, quantity: Decimal) -> Decimal:
    configured = caps(candidate).get("max_reward_quantity")
    if configured is None:
        return money(quantity)
    return money(min(quantity, Decimal(str(configured))))


def discount_limit(candidate: OfferCandidate, amount: Decimal, available: Decimal) -> Decimal:
    limited = min(max(ZERO, money(amount)), max(ZERO, money(available)))
    configured = caps(candidate).get("max_discount_amount")
    if configured is not None:
        limited = min(limited, money(Decimal(str(configured))))
    return money(limited)


def target_lines(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
) -> tuple[BasketLine, ...]:
    if candidate.product_scope_variant_ids:
        return tuple(
            line for line in lines
            if line.product_variant_id in candidate.product_scope_variant_ids
        )
    return tuple(lines)


def allocate_discount(
    total_discount: Decimal,
    basis_by_line: Mapping[int, Decimal],
    line_by_id: Mapping[int, BasketLine],
) -> tuple[RequestedAdjustment, ...]:
    positive = {
        int(line_id): money(value)
        for line_id, value in basis_by_line.items()
        if money(value) > ZERO
    }
    basis_total = money(sum(positive.values(), ZERO))
    total = min(money(total_discount), basis_total)
    if total <= ZERO or basis_total <= ZERO:
        return ()

    remaining_discount = total
    remaining_basis = basis_total
    result: list[RequestedAdjustment] = []
    ordered_ids = sorted(positive)

    for index, line_id in enumerate(ordered_ids):
        basis = positive[line_id]
        if index == len(ordered_ids) - 1:
            amount = min(basis, remaining_discount)
        else:
            raw = (
                remaining_discount * basis / remaining_basis
                if remaining_basis > ZERO
                else ZERO
            )
            amount = min(basis, money(raw))
        amount = money(amount)
        if amount > ZERO:
            line = line_by_id[line_id]
            result.append(
                RequestedAdjustment(
                    line_id=line_id,
                    product_variant_id=line.product_variant_id,
                    basis_amount=basis,
                    discount_amount=amount,
                )
            )
            remaining_discount = money(remaining_discount - amount)
        remaining_basis = money(remaining_basis - basis)

    if remaining_discount > ZERO:
        # Six-decimal proportional rounding can leave at most a tiny residue.
        # Allocate it deterministically without exceeding the line basis.
        for index in range(len(result) - 1, -1, -1):
            row = result[index]
            room = money(row.basis_amount - row.discount_amount)
            if room <= ZERO:
                continue
            add = min(room, remaining_discount)
            result[index] = RequestedAdjustment(
                line_id=row.line_id,
                product_variant_id=row.product_variant_id,
                basis_amount=row.basis_amount,
                discount_amount=money(row.discount_amount + add),
            )
            remaining_discount = money(remaining_discount - add)
            if remaining_discount <= ZERO:
                break

    if remaining_discount > ZERO:
        raise ValueError("Offer discount allocation invariant failed.")
    return tuple(result)


def proposal(
    candidate: OfferCandidate,
    *,
    adjustments: Sequence[RequestedAdjustment] = (),
    rewards: Sequence[Reward] = (),
    application_count: int = 1,
    metadata: Mapping | None = None,
    catalog_prices: Mapping[int, CatalogPrice],
) -> OfferProposal | None:
    discount = money(
        sum((row.discount_amount for row in adjustments), ZERO)
    )
    reward_value = ZERO
    for reward in rewards:
        price = catalog_prices.get(reward.product_variant_id)
        if price is None:
            raise ValueError(
                f"Missing price for reward product {reward.product_variant_id}."
            )
        if int(price.base_uom_id) != int(reward.base_uom_id):
            raise ValueError("Reward UOM does not match its canonical base UOM.")
        reward_value = money(
            reward_value + money(reward.quantity * price.unit_price)
        )

    benefit = money(discount + reward_value)
    if benefit <= ZERO:
        return None
    return OfferProposal(
        candidate=candidate,
        adjustments=tuple(adjustments),
        rewards=tuple(rewards),
        application_count=int(application_count),
        metadata=dict(metadata or {}),
        benefit_amount=benefit,
    )
