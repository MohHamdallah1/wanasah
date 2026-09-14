from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Mapping

from domains.offers.contracts import AppliedAdjustment, AppliedOffer, AppliedReward
from domains.taxation.contracts import TaxResolution


@dataclass(frozen=True)
class RoundingPolicy:
    version: int
    currency_code: str
    precision: int
    mode: str


@dataclass(frozen=True)
class CalculationInputComponent:
    uom_id: int
    quantity: Decimal


@dataclass(frozen=True)
class CalculationInputLine:
    line_id: int
    product_variant_id: int
    components: tuple[CalculationInputComponent, ...]


@dataclass(frozen=True)
class CalculatedPriceComponent:
    sequence: int
    uom_id: int
    quantity: Decimal
    base_quantity: Decimal
    price_entry_id: int
    price_publication_revision: int
    assignment_revision: int
    unit_price: Decimal
    gross_amount: Decimal


@dataclass(frozen=True)
class RoundedTaxComponent:
    tax_component_id: int
    component_code: str
    name: str
    sequence: int
    rate: Decimal
    basis_mode: str
    reporting_code: str | None
    unrounded_basis_amount: Decimal
    unrounded_tax_amount: Decimal
    tax_amount: Decimal


@dataclass(frozen=True)
class CalculatedLine:
    line_id: int
    product_variant_id: int
    base_uom_id: int
    quantity: Decimal
    price_components: tuple[CalculatedPriceComponent, ...]
    gross_amount: Decimal
    discount_amount: Decimal
    post_offer_amount: Decimal
    taxable_amount: Decimal
    tax_amount: Decimal
    final_amount: Decimal
    unrounded_final_amount: Decimal
    tax_rule_set_id: int
    tax_rule_set_version_id: int
    tax_revision: int
    tax_price_mode: str
    tax_components: tuple[RoundedTaxComponent, ...]


@dataclass(frozen=True)
class CalculationTotals:
    gross_amount: Decimal
    discount_amount: Decimal
    post_offer_amount: Decimal
    taxable_amount: Decimal
    tax_amount: Decimal
    line_total_amount: Decimal
    rounding_adjustment: Decimal
    final_amount: Decimal


@dataclass(frozen=True)
class CommercialCalculation:
    calculated_at: datetime
    transaction_currency_code: str
    rounding_policy: RoundingPolicy
    price_publication_revision_ceiling: int
    assignment_revision_ceiling: int
    offer_revision_ceiling: int
    tax_revision_ceiling: int
    lines: tuple[CalculatedLine, ...]
    totals: CalculationTotals
    adjustments: tuple[AppliedAdjustment, ...]
    rewards: tuple[AppliedReward, ...]
    applied_offers: tuple[AppliedOffer, ...]
    tax_resolutions: Mapping[int, TaxResolution]
