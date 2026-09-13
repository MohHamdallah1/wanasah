from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Mapping


MONEY_QUANT = Decimal("0.000001")
ZERO = Decimal("0.000000")
ComponentKey = tuple[int, int]


def money(value: Decimal) -> Decimal:
    if not isinstance(value, Decimal):
        value = Decimal(str(value))
    if not value.is_finite():
        raise ValueError("Offer monetary value must be finite.")
    return value.quantize(MONEY_QUANT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class BasketPriceComponent:
    uom_id: int
    quantity: Decimal
    base_quantity: Decimal
    unit_price: Decimal
    price_entry_id: int

    @property
    def gross_amount(self) -> Decimal:
        return money(self.quantity * self.unit_price)


@dataclass(frozen=True)
class BasketLine:
    line_id: int
    product_variant_id: int
    base_uom_id: int
    quantity: Decimal
    price_components: tuple[BasketPriceComponent, ...]

    @property
    def gross_amount(self) -> Decimal:
        return money(
            sum(
                (component.gross_amount for component in self.price_components),
                ZERO,
            )
        )

    def component(self, uom_id: int) -> BasketPriceComponent | None:
        target = int(uom_id)
        for component in self.price_components:
            if int(component.uom_id) == target:
                return component
        return None

    def quantity_for_uom(self, uom_id: int) -> Decimal:
        component = self.component(uom_id)
        return component.quantity if component is not None else ZERO

    def _single_price_component(self) -> BasketPriceComponent:
        if len(self.price_components) != 1:
            raise ValueError(
                "Mixed-UOM line has no single authoritative unit price."
            )
        return self.price_components[0]

    @property
    def unit_price(self) -> Decimal:
        return self._single_price_component().unit_price

    @property
    def price_entry_id(self) -> int:
        return self._single_price_component().price_entry_id


@dataclass(frozen=True)
class CatalogPrice:
    product_variant_id: int
    uom_id: int
    unit_price: Decimal
    price_entry_id: int


@dataclass(frozen=True)
class ProductTargetRef:
    product_variant_id: int
    uom_id: int | None


@dataclass(frozen=True)
class OfferProductRef:
    role: str
    product_variant_id: int
    uom_id: int
    quantity_per_application: Decimal | None


@dataclass(frozen=True)
class OfferCandidate:
    version_id: int
    definition_id: int
    revision: int
    offer_type: str
    priority: int
    stacking_mode: str
    payload: Mapping[str, Any]
    product_targets: tuple[ProductTargetRef, ...]
    products: tuple[OfferProductRef, ...]


@dataclass(frozen=True)
class RequestedAdjustment:
    line_id: int
    product_variant_id: int
    uom_id: int
    basis_amount: Decimal
    discount_amount: Decimal


@dataclass(frozen=True)
class Reward:
    product_variant_id: int
    uom_id: int
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
    uom_id: int
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
    uom_id: int
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
