from __future__ import annotations

from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import BasketLine, CatalogPrice, OfferCandidate, ZERO, money
from domains.offers.handlers.common import (
    allocate_discount,
    discount_limit,
    proposal,
    target_lines,
)


def percentage_discount(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[int, Decimal],
    catalog_prices: Mapping[int, CatalogPrice],
):
    targets = target_lines(candidate, lines)
    line_by_id = {line.line_id: line for line in lines}
    basis = {
        line.line_id: money(current_amounts[line.line_id])
        for line in targets
        if money(current_amounts[line.line_id]) > ZERO
    }
    available = money(sum(basis.values(), ZERO))
    if available <= ZERO:
        return None
    percentage = Decimal(str(candidate.payload["percentage"]))
    requested = money(available * percentage / Decimal("100"))
    total = discount_limit(candidate, requested, available)
    adjustments = allocate_discount(total, basis, line_by_id)
    return proposal(
        candidate,
        adjustments=adjustments,
        metadata={"percentage": str(percentage)},
        catalog_prices=catalog_prices,
    )


def fixed_discount(
    candidate: OfferCandidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[int, Decimal],
    catalog_prices: Mapping[int, CatalogPrice],
):
    targets = target_lines(candidate, lines)
    line_by_id = {line.line_id: line for line in lines}
    basis = {
        line.line_id: money(current_amounts[line.line_id])
        for line in targets
        if money(current_amounts[line.line_id]) > ZERO
    }
    available = money(sum(basis.values(), ZERO))
    if available <= ZERO:
        return None
    configured = money(Decimal(str(candidate.payload["amount"])))
    total = discount_limit(candidate, configured, available)
    adjustments = allocate_discount(total, basis, line_by_id)
    return proposal(
        candidate,
        adjustments=adjustments,
        metadata={"configured_amount": str(configured)},
        catalog_prices=catalog_prices,
    )
