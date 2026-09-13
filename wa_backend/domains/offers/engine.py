from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import Mapping, Sequence

from domains.offers.contracts import (
    AppliedAdjustment,
    AppliedOffer,
    AppliedReward,
    BasketLine,
    CatalogPrice,
    OfferEngineResult,
    OfferProposal,
    RequestedAdjustment,
    ZERO,
    money,
)
from domains.offers.core import OfferError
from domains.offers.handlers import HANDLERS
from domains.offers.handlers.common import allocate_discount


def _evaluate(
    candidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[int, Decimal],
    catalog_prices: Mapping[int, CatalogPrice],
) -> OfferProposal | None:
    handler = HANDLERS.get(candidate.offer_type)
    if handler is None:
        raise OfferError(
            "OFFER_HANDLER_MISSING",
            "No calculation handler exists for a published offer type.",
            context={"offer_type": candidate.offer_type, "offer_version_id": candidate.version_id},
        )
    try:
        return handler(candidate, lines, current_amounts, catalog_prices)
    except OfferError:
        raise
    except (ValueError, KeyError, ArithmeticError) as exc:
        raise OfferError(
            "OFFER_CALCULATION_INVALID",
            str(exc),
            context={"offer_version_id": candidate.version_id, "offer_type": candidate.offer_type},
        ) from exc


def _reward_value(proposal: OfferProposal, catalog_prices: Mapping[int, CatalogPrice]) -> Decimal:
    total = ZERO
    for reward in proposal.rewards:
        price = catalog_prices.get(reward.product_variant_id)
        if price is None:
            raise OfferError(
                "OFFER_REWARD_PRICE_REQUIRED",
                "Reward product price is required for deterministic offer comparison.",
                context={"product_variant_id": reward.product_variant_id},
            )
        total = money(total + money(reward.quantity * price.unit_price))
    return total


def _exclusive_winner(
    proposals: list[OfferProposal],
) -> OfferProposal:
    best_benefit = max(row.benefit_amount for row in proposals)
    winners = [row for row in proposals if row.benefit_amount == best_benefit]
    if len(winners) != 1:
        raise OfferError(
            "OFFER_PRECEDENCE_CONFLICT",
            "Multiple exclusive offers have the same priority and customer benefit.",
            context={
                "priority": winners[0].candidate.priority,
                "offer_version_ids": sorted(row.candidate.version_id for row in winners),
                "benefit_amount": str(best_benefit),
            },
        )
    return winners[0]


def _scale_stackable_adjustments(
    proposals: Sequence[OfferProposal],
    current_amounts: Mapping[int, Decimal],
    line_by_id: Mapping[int, BasketLine],
) -> dict[tuple[int, int], RequestedAdjustment]:
    by_line: dict[int, list[tuple[int, RequestedAdjustment]]] = defaultdict(list)
    for proposal in proposals:
        for adjustment in proposal.adjustments:
            by_line[adjustment.line_id].append(
                (proposal.candidate.version_id, adjustment)
            )

    actual: dict[tuple[int, int], RequestedAdjustment] = {}
    for line_id, rows in by_line.items():
        available = money(current_amounts[line_id])
        requested_total = money(
            sum((row.discount_amount for _, row in rows), ZERO)
        )
        if requested_total <= available:
            for offer_id, row in rows:
                actual[(offer_id, line_id)] = row
            continue

        synthetic_basis = {
            offer_id: row.discount_amount for offer_id, row in rows
        }
        # Use synthetic BasketLine keys only as deterministic allocation identities.
        pseudo_lines = {
            offer_id: BasketLine(
                line_id=offer_id,
                product_variant_id=line_by_id[line_id].product_variant_id,
                base_uom_id=line_by_id[line_id].base_uom_id,
                quantity=Decimal("1"),
                unit_price=Decimal("0"),
                price_entry_id=0,
            )
            for offer_id, _ in rows
        }
        allocations = allocate_discount(
            available, synthetic_basis, pseudo_lines
        )
        allocation_map = {
            row.line_id: row.discount_amount for row in allocations
        }
        for offer_id, requested in rows:
            amount = money(allocation_map.get(offer_id, ZERO))
            if amount <= ZERO:
                continue
            actual[(offer_id, line_id)] = RequestedAdjustment(
                line_id=line_id,
                product_variant_id=requested.product_variant_id,
                basis_amount=requested.basis_amount,
                discount_amount=amount,
            )
    return actual


def calculate_offers(
    *,
    lines: Sequence[BasketLine],
    candidates: Sequence,
    catalog_prices: Mapping[int, CatalogPrice],
    calculated_at: datetime | None = None,
) -> OfferEngineResult:
    if not lines:
        return OfferEngineResult(
            calculated_at=(calculated_at or datetime.now(timezone.utc)),
            gross_amount=ZERO,
            discount_amount=ZERO,
            net_amount=ZERO,
            line_net_amounts={},
            adjustments=(),
            rewards=(),
            applied_offers=(),
        )

    line_ids = [line.line_id for line in lines]
    variants = [line.product_variant_id for line in lines]
    if len(line_ids) != len(set(line_ids)):
        raise OfferError("OFFER_BASKET_DUPLICATE_LINE", "Basket line IDs must be unique.", status_code=422)
    if len(variants) != len(set(variants)):
        raise OfferError(
            "OFFER_BASKET_DUPLICATE_VARIANT",
            "Offer engine requires one canonical basket line per product variant.",
            status_code=422,
        )
    if any(line.quantity <= ZERO or line.unit_price < ZERO for line in lines):
        raise OfferError("OFFER_BASKET_INVALID", "Basket quantities/prices are invalid.", status_code=422)

    line_by_id = {line.line_id: line for line in lines}
    current = {line.line_id: line.gross_amount for line in lines}
    gross = money(sum(current.values(), ZERO))

    by_priority: dict[int, list] = defaultdict(list)
    for candidate in candidates:
        by_priority[int(candidate.priority)].append(candidate)

    applied_adjustments: list[AppliedAdjustment] = []
    applied_rewards: list[AppliedReward] = []
    applied_offers: list[AppliedOffer] = []
    sequence = 0

    for priority in sorted(by_priority, reverse=True):
        snapshot = dict(current)
        proposals = [
            proposal
            for proposal in (
                _evaluate(candidate, lines, snapshot, catalog_prices)
                for candidate in by_priority[priority]
            )
            if proposal is not None
        ]
        if not proposals:
            continue

        exclusive = [
            row for row in proposals
            if row.candidate.stacking_mode == "EXCLUSIVE"
        ]
        if exclusive:
            chosen = _exclusive_winner(exclusive)
            proposals_to_apply = [chosen]
            actual_map = {
                (chosen.candidate.version_id, row.line_id): row
                for row in chosen.adjustments
            }
            stop_after_group = True
        else:
            proposals_to_apply = [
                row for row in proposals
                if row.candidate.stacking_mode == "STACKABLE"
            ]
            actual_map = _scale_stackable_adjustments(
                proposals_to_apply, snapshot, line_by_id
            )
            stop_after_group = False

        # Same-priority STACKABLE offers are calculated from the same snapshot,
        # then clipped proportionally per line. Their result is independent of DB row order.
        for proposal_row in sorted(
            proposals_to_apply,
            key=lambda row: (row.candidate.revision, row.candidate.version_id),
        ):
            sequence += 1
            actual_discount = ZERO
            for requested in proposal_row.adjustments:
                actual = actual_map.get(
                    (proposal_row.candidate.version_id, requested.line_id)
                )
                if actual is None or actual.discount_amount <= ZERO:
                    continue
                current[actual.line_id] = money(
                    current[actual.line_id] - actual.discount_amount
                )
                actual_discount = money(
                    actual_discount + actual.discount_amount
                )
                applied_adjustments.append(
                    AppliedAdjustment(
                        sequence=sequence,
                        offer_version_id=proposal_row.candidate.version_id,
                        offer_definition_id=proposal_row.candidate.definition_id,
                        offer_revision=proposal_row.candidate.revision,
                        offer_type=proposal_row.candidate.offer_type,
                        line_id=actual.line_id,
                        product_variant_id=actual.product_variant_id,
                        basis_amount=actual.basis_amount,
                        discount_amount=actual.discount_amount,
                    )
                )

            reward_value = _reward_value(proposal_row, catalog_prices)
            for reward in proposal_row.rewards:
                applied_rewards.append(
                    AppliedReward(
                        sequence=sequence,
                        offer_version_id=proposal_row.candidate.version_id,
                        offer_definition_id=proposal_row.candidate.definition_id,
                        offer_revision=proposal_row.candidate.revision,
                        offer_type=proposal_row.candidate.offer_type,
                        product_variant_id=reward.product_variant_id,
                        base_uom_id=reward.base_uom_id,
                        quantity=reward.quantity,
                    )
                )

            applied_offers.append(
                AppliedOffer(
                    sequence=sequence,
                    offer_version_id=proposal_row.candidate.version_id,
                    offer_definition_id=proposal_row.candidate.definition_id,
                    offer_revision=proposal_row.candidate.revision,
                    offer_type=proposal_row.candidate.offer_type,
                    priority=proposal_row.candidate.priority,
                    stacking_mode=proposal_row.candidate.stacking_mode,
                    application_count=proposal_row.application_count,
                    discount_amount=actual_discount,
                    reward_value=reward_value,
                    benefit_amount=money(actual_discount + reward_value),
                    metadata=dict(proposal_row.metadata),
                )
            )

        if stop_after_group:
            break

    discount = money(gross - money(sum(current.values(), ZERO)))
    net = money(gross - discount)
    if any(value < ZERO for value in current.values()) or net < ZERO:
        raise OfferError("OFFER_NEGATIVE_NET", "Offer engine produced an invalid negative net amount.")

    return OfferEngineResult(
        calculated_at=(calculated_at or datetime.now(timezone.utc)),
        gross_amount=gross,
        discount_amount=discount,
        net_amount=net,
        line_net_amounts={key: money(value) for key, value in current.items()},
        adjustments=tuple(applied_adjustments),
        rewards=tuple(applied_rewards),
        applied_offers=tuple(applied_offers),
    )
