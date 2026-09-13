from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping


MONEY_QUANT = Decimal("0.000001")
ZERO = Decimal("0.000000")


def money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError("Offer monetary value must be finite.")
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BasketLine:
    line_id: int
    product_variant_id: int
    base_uom_id: int
    quantity: Decimal
    unit_price: Decimal
    price_entry_id: int

    @property
    def gross_amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)


@dataclass(frozen=True)
class CatalogPrice:
    product_variant_id: int
    base_uom_id: int
    unit_price: Decimal
    price_entry_id: int


@dataclass(frozen=True)
class OfferProductRef:
    role: str
    product_variant_id: int


@dataclass(frozen=True)
class OfferCandidate:
    version_id: int
    definition_id: int
    revision: int
    offer_type: str
    priority: int
    stacking_mode: str
    payload: Mapping[str, Any]
    product_scope_variant_ids: frozenset[int]
    products: tuple[OfferProductRef, ...]


@dataclass(frozen=True)
class RequestedAdjustment:
    line_id: int
    product_variant_id: int
    basis_amount: Decimal
    discount_amount: Decimal


@dataclass(frozen=True)
class Reward:
    product_variant_id: int
    base_uom_id: int
    quantity: Decimal


@dataclass(frozen=True)
class OfferProposal:
    candidate: OfferCandidate
    adjustments: tuple[RequestedAdjustment, ...]
    rewards: tuple[Reward, ...]
    application_count: int
    metadata: Mapping[str, Any]
    benefit_amount: Decimal


@dataclass(frozen=True)
class AppliedAdjustment:
    sequence: int
    offer_version_id: int
    offer_definition_id: int
    offer_revision: int
    offer_type: str
    line_id: int
    product_variant_id: int
    basis_amount: Decimal
    discount_amount: Decimal


@dataclass(frozen=True)
class AppliedReward:
    sequence: int
    offer_version_id: int
    offer_definition_id: int
    offer_revision: int
    offer_type: str
    product_variant_id: int
    base_uom_id: int
    quantity: Decimal


@dataclass(frozen=True)
class AppliedOffer:
    sequence: int
    offer_version_id: int
    offer_definition_id: int
    offer_revision: int
    offer_type: str
    priority: int
    stacking_mode: str
    application_count: int
    discount_amount: Decimal
    reward_value: Decimal
    benefit_amount: Decimal
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class OfferEngineResult:
    calculated_at: datetime
    gross_amount: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    line_net_amounts: Mapping[int, Decimal]
    adjustments: tuple[AppliedAdjustment, ...]
    rewards: tuple[AppliedReward, ...]
    applied_offers: tuple[AppliedOffer, ...]
