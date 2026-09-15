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
    ComponentKey,
    OfferEngineResult,
    OfferProposal,
    RequestedAdjustment,
    ZERO,
    money,
)
from domains.offers.core import OfferError
from domains.offers.handlers import HANDLERS


def _evaluate(
    candidate,
    lines: Sequence[BasketLine],
    current_amounts: Mapping[
        ComponentKey,
        Decimal,
    ],
    catalog_prices: Mapping[
        tuple[int, int],
        CatalogPrice,
    ],
) -> OfferProposal | None:
    handler = HANDLERS.get(
        candidate.offer_type
    )
    if handler is None:
        raise OfferError(
            "OFFER_HANDLER_MISSING",
            "No calculation handler exists for a published offer type.",
            context={
                "offer_type": (
                    candidate.offer_type
                ),
                "offer_version_id": (
                    candidate.version_id
                ),
            },
        )
    try:
        return handler(
            candidate,
            lines,
            current_amounts,
            catalog_prices,
        )
    except OfferError:
        raise
    except (
        ValueError,
        KeyError,
        ArithmeticError,
    ) as exc:
        raise OfferError(
            "OFFER_CALCULATION_INVALID",
            str(exc),
            context={
                "offer_version_id": (
                    candidate.version_id
                ),
                "offer_type": (
                    candidate.offer_type
                ),
            },
        ) from exc


def _reward_value(
    proposal: OfferProposal,
    catalog_prices: Mapping[
        tuple[int, int],
        CatalogPrice,
    ],
) -> Decimal:
    total = ZERO
    for reward in proposal.rewards:
        key = (
            int(
                reward.product_variant_id
            ),
            int(reward.uom_id),
        )
        price = catalog_prices.get(key)
        if price is None:
            raise OfferError(
                "OFFER_REWARD_PRICE_REQUIRED",
                "Reward product/UOM price is required for deterministic offer comparison.",
                context={
                    "product_variant_id": (
                        reward.product_variant_id
                    ),
                    "uom_id": (
                        reward.uom_id
                    ),
                },
            )
        total = money(
            total
            + money(
                reward.quantity
                * price.unit_price
            )
        )
    return total


def _exclusive_winner(
    proposals: list[OfferProposal],
) -> OfferProposal:
    best_benefit = max(
        row.benefit_amount
        for row in proposals
    )
    winners = [
        row
        for row in proposals
        if row.benefit_amount
        == best_benefit
    ]
    if len(winners) != 1:
        raise OfferError(
            "OFFER_PRECEDENCE_CONFLICT",
            "Multiple exclusive offers have the same priority and customer benefit.",
            context={
                "priority": (
                    winners[0]
                    .candidate.priority
                ),
                "offer_version_ids": sorted(
                    row.candidate.version_id
                    for row in winners
                ),
                "benefit_amount": str(
                    best_benefit
                ),
            },
        )
    return winners[0]


def _scale_component_rows(
    *,
    available: Decimal,
    rows: list[
        tuple[
            int,
            RequestedAdjustment,
        ]
    ],
) -> dict[int, Decimal]:
    requested = {
        int(offer_id): money(
            row.discount_amount
        )
        for offer_id, row in rows
        if money(
            row.discount_amount
        ) > ZERO
    }
    requested_total = money(
        sum(
            requested.values(),
            ZERO,
        )
    )
    available = money(
        max(
            ZERO,
            available,
        )
    )
    if (
        requested_total
        <= available
    ):
        return requested
    if (
        available <= ZERO
        or requested_total <= ZERO
    ):
        return {}

    remaining_amount = available
    remaining_basis = requested_total
    result: dict[
        int,
        Decimal,
    ] = {}
    ordered = sorted(requested)

    for index, offer_id in enumerate(
        ordered
    ):
        basis = requested[offer_id]
        if index == len(ordered) - 1:
            amount = min(
                basis,
                remaining_amount,
            )
        else:
            amount = min(
                basis,
                money(
                    remaining_amount
                    * basis
                    / remaining_basis
                ),
            )
        amount = money(amount)
        if amount > ZERO:
            result[offer_id] = amount
            remaining_amount = money(
                remaining_amount
                - amount
            )
        remaining_basis = money(
            remaining_basis - basis
        )

    if remaining_amount > ZERO:
        for offer_id in reversed(
            ordered
        ):
            current = result.get(
                offer_id,
                ZERO,
            )
            room = money(
                requested[offer_id]
                - current
            )
            if room <= ZERO:
                continue
            add = min(
                room,
                remaining_amount,
            )
            result[offer_id] = money(
                current + add
            )
            remaining_amount = money(
                remaining_amount - add
            )
            if remaining_amount <= ZERO:
                break

    if remaining_amount > ZERO:
        raise ValueError(
            "Stackable offer allocation invariant failed."
        )
    return result


def _scale_stackable_adjustments(
    proposals: Sequence[
        OfferProposal
    ],
    current_amounts: Mapping[
        ComponentKey,
        Decimal,
    ],
) -> dict[
    tuple[int, int, int],
    RequestedAdjustment,
]:
    by_component: dict[
        ComponentKey,
        list[
            tuple[
                int,
                RequestedAdjustment,
            ]
        ],
    ] = defaultdict(list)

    for proposal in proposals:
        for adjustment in (
            proposal.adjustments
        ):
            key = (
                int(
                    adjustment.line_id
                ),
                int(
                    adjustment.uom_id
                ),
            )
            by_component[
                key
            ].append(
                (
                    int(
                        proposal.candidate
                        .version_id
                    ),
                    adjustment,
                )
            )

    actual: dict[
        tuple[int, int, int],
        RequestedAdjustment,
    ] = {}
    for key, rows in (
        by_component.items()
    ):
        allocations = (
            _scale_component_rows(
                available=money(
                    current_amounts[key]
                ),
                rows=rows,
            )
        )
        for offer_id, requested in rows:
            amount = money(
                allocations.get(
                    offer_id,
                    ZERO,
                )
            )
            if amount <= ZERO:
                continue
            actual[
                (
                    offer_id,
                    key[0],
                    key[1],
                )
            ] = RequestedAdjustment(
                line_id=(
                    requested.line_id
                ),
                product_variant_id=(
                    requested
                    .product_variant_id
                ),
                uom_id=(
                    requested.uom_id
                ),
                basis_amount=(
                    requested.basis_amount
                ),
                discount_amount=amount,
            )
    return actual


def _validate_line(
    line: BasketLine,
) -> None:
    if (
        not isinstance(
            line.line_id,
            int,
        )
        or isinstance(
            line.line_id,
            bool,
        )
        or line.line_id <= 0
        or not isinstance(
            line.product_variant_id,
            int,
        )
        or isinstance(
            line.product_variant_id,
            bool,
        )
        or line.product_variant_id <= 0
        or not isinstance(
            line.base_uom_id,
            int,
        )
        or isinstance(
            line.base_uom_id,
            bool,
        )
        or line.base_uom_id <= 0
        or not isinstance(
            line.quantity,
            Decimal,
        )
        or not line.quantity.is_finite()
        or line.quantity <= ZERO
        or not line.price_components
    ):
        raise OfferError(
            "OFFER_BASKET_INVALID",
            "Basket line contains invalid mixed-UOM evidence.",
            status_code=422,
            context={
                "line_id": (
                    line.line_id
                )
            },
        )

    uoms = [
        int(component.uom_id)
        for component
        in line.price_components
    ]
    if len(uoms) != len(set(uoms)):
        raise OfferError(
            "OFFER_BASKET_DUPLICATE_UOM",
            "One logical product line cannot repeat the same sold UOM.",
            status_code=422,
            context={
                "line_id": (
                    line.line_id
                )
            },
        )

    base_total = ZERO
    for component in (
        line.price_components
    ):
        if (
            not isinstance(
                component.uom_id,
                int,
            )
            or isinstance(
                component.uom_id,
                bool,
            )
            or component.uom_id <= 0
            or not isinstance(
                component.price_entry_id,
                int,
            )
            or isinstance(
                component.price_entry_id,
                bool,
            )
            or component.price_entry_id <= 0
            or not isinstance(
                component.price_publication_revision,
                int,
            )
            or isinstance(
                component.price_publication_revision,
                bool,
            )
            or component.price_publication_revision <= 0
            or not isinstance(
                component.assignment_revision,
                int,
            )
            or isinstance(
                component.assignment_revision,
                bool,
            )
            or component.assignment_revision <= 0
            or not isinstance(
                component.quantity,
                Decimal,
            )
            or not component.quantity.is_finite()
            or component.quantity <= ZERO
            or not isinstance(
                component.base_quantity,
                Decimal,
            )
            or not component.base_quantity.is_finite()
            or component.base_quantity <= ZERO
            or not isinstance(
                component.unit_price,
                Decimal,
            )
            or not component.unit_price.is_finite()
            or component.unit_price < ZERO
        ):
            raise OfferError(
                "OFFER_BASKET_INVALID",
                "Basket price component is invalid.",
                status_code=422,
                context={
                    "line_id": (
                        line.line_id
                    ),
                    "uom_id": (
                        component.uom_id
                    ),
                },
            )
        base_total += (
            component.base_quantity
        )

    if base_total != line.quantity:
        raise OfferError(
            "OFFER_BASKET_QUANTITY_MISMATCH",
            "Mixed-UOM components do not reconcile to canonical line quantity.",
            status_code=422,
            context={
                "line_id": (
                    line.line_id
                )
            },
        )


def calculate_offers(
    *,
    lines: Sequence[BasketLine],
    candidates: Sequence,
    catalog_prices: Mapping[
        tuple[int, int],
        CatalogPrice,
    ],
    calculated_at: (
        datetime | None
    ) = None,
) -> OfferEngineResult:
    if not lines:
        return OfferEngineResult(
            calculated_at=(
                calculated_at
                or datetime.now(
                    timezone.utc
                )
            ),
            gross_amount=ZERO,
            discount_amount=ZERO,
            net_amount=ZERO,
            line_net_amounts={},
            adjustments=(),
            rewards=(),
            applied_offers=(),
        )

    line_ids = [
        line.line_id
        for line in lines
    ]
    variants = [
        line.product_variant_id
        for line in lines
    ]
    if (
        len(line_ids)
        != len(set(line_ids))
    ):
        raise OfferError(
            "OFFER_BASKET_DUPLICATE_LINE",
            "Basket line IDs must be unique.",
            status_code=422,
        )
    if (
        len(variants)
        != len(set(variants))
    ):
        raise OfferError(
            "OFFER_BASKET_DUPLICATE_VARIANT",
            "Offer engine requires one logical basket line per product variant.",
            status_code=422,
        )
    for line in lines:
        _validate_line(line)

    line_by_id = {
        int(line.line_id): line
        for line in lines
    }
    try:
        current: dict[
            ComponentKey,
            Decimal,
        ] = {
            (
                int(line.line_id),
                int(component.uom_id),
            ): component.gross_amount
            for line in lines
            for component
            in line.price_components
        }
        gross = money(
            sum(
                current.values(),
                ZERO,
            )
        )
    except (
        ValueError,
        ArithmeticError,
    ) as exc:
        raise OfferError(
            "OFFER_MONETARY_OVERFLOW",
            "Basket monetary evidence exceeds the exact NUMERIC(20,6) contract.",
            status_code=422,
        ) from exc

    by_priority: dict[
        int,
        list,
    ] = defaultdict(list)
    for candidate in candidates:
        by_priority[
            int(candidate.priority)
        ].append(candidate)

    applied_adjustments: list[
        AppliedAdjustment
    ] = []
    applied_rewards: list[
        AppliedReward
    ] = []
    applied_offers: list[
        AppliedOffer
    ] = []
    sequence = 0

    for priority in sorted(
        by_priority,
        reverse=True,
    ):
        snapshot = dict(current)
        proposals = [
            proposal
            for proposal in (
                _evaluate(
                    candidate,
                    lines,
                    snapshot,
                    catalog_prices,
                )
                for candidate
                in by_priority[
                    priority
                ]
            )
            if proposal is not None
        ]
        if not proposals:
            continue

        exclusive = [
            row
            for row in proposals
            if row.candidate
            .stacking_mode
            == "EXCLUSIVE"
        ]
        if exclusive:
            chosen = (
                _exclusive_winner(
                    exclusive
                )
            )
            proposals_to_apply = [
                chosen
            ]
            actual_map = {
                (
                    int(
                        chosen.candidate
                        .version_id
                    ),
                    int(row.line_id),
                    int(row.uom_id),
                ): row
                for row
                in chosen.adjustments
            }
            stop_after_group = True
        else:
            proposals_to_apply = [
                row
                for row in proposals
                if row.candidate
                .stacking_mode
                == "STACKABLE"
            ]
            actual_map = (
                _scale_stackable_adjustments(
                    proposals_to_apply,
                    snapshot,
                )
            )
            stop_after_group = False

        for proposal_row in sorted(
            proposals_to_apply,
            key=lambda row: (
                row.candidate.revision,
                row.candidate.version_id,
            ),
        ):
            sequence += 1
            actual_discount = ZERO
            for requested in (
                proposal_row.adjustments
            ):
                map_key = (
                    int(
                        proposal_row
                        .candidate.version_id
                    ),
                    int(
                        requested.line_id
                    ),
                    int(
                        requested.uom_id
                    ),
                )
                actual = actual_map.get(
                    map_key
                )
                if (
                    actual is None
                    or actual
                    .discount_amount
                    <= ZERO
                ):
                    continue

                current_key = (
                    int(
                        actual.line_id
                    ),
                    int(
                        actual.uom_id
                    ),
                )
                current[current_key] = money(
                    current[current_key]
                    - actual
                    .discount_amount
                )
                actual_discount = money(
                    actual_discount
                    + actual
                    .discount_amount
                )
                applied_adjustments.append(
                    AppliedAdjustment(
                        sequence=sequence,
                        offer_version_id=(
                            proposal_row
                            .candidate
                            .version_id
                        ),
                        offer_definition_id=(
                            proposal_row
                            .candidate
                            .definition_id
                        ),
                        offer_revision=(
                            proposal_row
                            .candidate
                            .revision
                        ),
                        offer_type=(
                            proposal_row
                            .candidate
                            .offer_type
                        ),
                        line_id=(
                            actual.line_id
                        ),
                        product_variant_id=(
                            actual
                            .product_variant_id
                        ),
                        uom_id=(
                            actual.uom_id
                        ),
                        basis_amount=(
                            actual
                            .basis_amount
                        ),
                        discount_amount=(
                            actual
                            .discount_amount
                        ),
                    )
                )

            reward_value = (
                _reward_value(
                    proposal_row,
                    catalog_prices,
                )
            )
            for reward in (
                proposal_row.rewards
            ):
                applied_rewards.append(
                    AppliedReward(
                        sequence=sequence,
                        offer_version_id=(
                            proposal_row
                            .candidate
                            .version_id
                        ),
                        offer_definition_id=(
                            proposal_row
                            .candidate
                            .definition_id
                        ),
                        offer_revision=(
                            proposal_row
                            .candidate
                            .revision
                        ),
                        offer_type=(
                            proposal_row
                            .candidate
                            .offer_type
                        ),
                        product_variant_id=(
                            reward
                            .product_variant_id
                        ),
                        uom_id=(
                            reward.uom_id
                        ),
                        quantity=(
                            reward.quantity
                        ),
                    )
                )

            applied_offers.append(
                AppliedOffer(
                    sequence=sequence,
                    offer_version_id=(
                        proposal_row
                        .candidate.version_id
                    ),
                    offer_definition_id=(
                        proposal_row
                        .candidate.definition_id
                    ),
                    offer_revision=(
                        proposal_row
                        .candidate.revision
                    ),
                    offer_type=(
                        proposal_row
                        .candidate.offer_type
                    ),
                    priority=(
                        proposal_row
                        .candidate.priority
                    ),
                    stacking_mode=(
                        proposal_row
                        .candidate
                        .stacking_mode
                    ),
                    application_count=(
                        proposal_row
                        .application_count
                    ),
                    discount_amount=(
                        actual_discount
                    ),
                    reward_value=(
                        reward_value
                    ),
                    benefit_amount=money(
                        actual_discount
                        + reward_value
                    ),
                    metadata=dict(
                        proposal_row
                        .metadata
                    ),
                )
            )

        if stop_after_group:
            break

    line_net_amounts = {
        line_id: money(
            sum(
                (
                    amount
                    for (
                        candidate_line_id,
                        _uom_id,
                    ), amount
                    in current.items()
                    if candidate_line_id
                    == line_id
                ),
                ZERO,
            )
        )
        for line_id in line_by_id
    }
    discount = money(
        gross
        - money(
            sum(
                line_net_amounts
                .values(),
                ZERO,
            )
        )
    )
    net = money(
        gross - discount
    )
    if (
        any(
            value < ZERO
            for value
            in current.values()
        )
        or net < ZERO
    ):
        raise OfferError(
            "OFFER_NEGATIVE_NET",
            "Offer engine produced an invalid negative net amount.",
        )

    return OfferEngineResult(
        calculated_at=(
            calculated_at
            or datetime.now(
                timezone.utc
            )
        ),
        gross_amount=gross,
        discount_amount=discount,
        net_amount=net,
        line_net_amounts=(
            line_net_amounts
        ),
        adjustments=tuple(
            applied_adjustments
        ),
        rewards=tuple(
            applied_rewards
        ),
        applied_offers=tuple(
            applied_offers
        ),
    )
