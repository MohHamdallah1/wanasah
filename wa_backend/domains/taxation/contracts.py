from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal


@dataclass(frozen=True)
class TaxComponentSnapshot:
    component_id: int
    component_code: str
    name: str
    sequence: int
    rate: Decimal
    basis_mode: str
    reporting_code: str | None


@dataclass(frozen=True)
class TaxResolution:
    product_variant_id: int
    tax_rule_set_id: int
    tax_rule_set_version_id: int
    tax_revision: int
    definition_version: int
    priority: int
    price_mode: str
    scope_types: tuple[str, ...]
    matched_jurisdiction_id: int | None
    jurisdiction_distance: int | None
    components: tuple[TaxComponentSnapshot, ...]
    resolved_at: datetime


@dataclass(frozen=True)
class TaxComponentCalculation:
    component_id: int
    component_code: str
    name: str
    sequence: int
    rate: Decimal
    basis_mode: str
    reporting_code: str | None
    basis_amount: Decimal
    tax_amount: Decimal


@dataclass(frozen=True)
class TaxCalculation:
    input_amount: Decimal
    price_mode: str
    taxable_base: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    components: tuple[TaxComponentCalculation, ...]
