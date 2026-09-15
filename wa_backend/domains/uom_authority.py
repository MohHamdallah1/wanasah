from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProductUomConversion, ProductVariant
from quantity import (
    QUANTITY_MAX,
    QUANTITY_SCALE,
    QuantityError,
    parse_quantity,
    validate_variant_quantity,
)


class UomAuthorityError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        context: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.context = dict(context or {})


def _positive_fraction(value: Decimal) -> Fraction:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise UomAuthorityError(
            "UOM_CONVERSION_RATIO_INVALID",
            "UOM conversion ratios must be positive finite Decimals.",
        )
    return Fraction(value)


def _decimal_exact(
    value: Fraction,
    *,
    scale: int,
    field_name: str,
) -> Decimal:
    if type(scale) is not int or not 0 <= scale <= QUANTITY_SCALE:
        raise UomAuthorityError(
            "UOM_TARGET_SCALE_INVALID",
            "Target quantity scale is invalid.",
            context={"scale": scale},
        )
    scaled = value * (10 ** scale)
    if scaled.denominator != 1:
        raise UomAuthorityError(
            "UOM_CONVERSION_PRECISION_LOSS",
            "UOM conversion cannot be represented exactly at the product quantity scale.",
            context={"field": field_name, "scale": scale},
        )
    result = Decimal(scaled.numerator).scaleb(-scale)
    if abs(result) > QUANTITY_MAX:
        raise UomAuthorityError(
            "UOM_CONVERSION_OVERFLOW",
            "Converted quantity exceeds NUMERIC(20,6) capacity.",
            context={"field": field_name},
        )
    return result


@dataclass(frozen=True)
class VariantUomAuthority:
    product_variant_id: int
    base_uom_id: int
    quantity_scale: int
    quantity_step: Decimal
    factors_to_base: dict[int, Fraction]

    def factor_to_base(self, uom_id: int) -> Fraction:
        key = int(uom_id)
        factor = self.factors_to_base.get(key)
        if factor is None:
            raise UomAuthorityError(
                "UOM_NOT_REACHABLE",
                "Selected UOM is not connected to the product base UOM.",
                context={
                    "product_variant_id": self.product_variant_id,
                    "uom_id": key,
                    "base_uom_id": self.base_uom_id,
                },
            )
        return factor

    def to_base(
        self,
        quantity: Decimal,
        *,
        uom_id: int,
        field_name: str = "quantity",
        validate_step: bool = False,
    ) -> Decimal:
        try:
            parsed = parse_quantity(
                quantity,
                field_name,
            )
        except QuantityError as exc:
            raise UomAuthorityError(
                "UOM_QUANTITY_INVALID",
                str(exc),
                context={
                    "product_variant_id": self.product_variant_id,
                    "uom_id": int(uom_id),
                    "field": field_name,
                },
            ) from exc
        converted = _decimal_exact(
            Fraction(parsed) * self.factor_to_base(uom_id),
            scale=self.quantity_scale,
            field_name=field_name,
        )
        if validate_step:
            try:
                return validate_variant_quantity(
                    converted,
                    quantity_scale=self.quantity_scale,
                    quantity_step=self.quantity_step,
                    field_name=field_name,
                )
            except QuantityError as exc:
                raise UomAuthorityError(
                    "UOM_CONVERTED_QUANTITY_INVALID",
                    str(exc),
                    context={
                        "product_variant_id": self.product_variant_id,
                        "uom_id": int(uom_id),
                    },
                ) from exc
        return converted

    def validate_canonical_total(
        self,
        quantity: Decimal,
        *,
        field_name: str = "quantity",
    ) -> Decimal:
        try:
            return validate_variant_quantity(
                quantity,
                quantity_scale=self.quantity_scale,
                quantity_step=self.quantity_step,
                field_name=field_name,
            )
        except QuantityError as exc:
            raise UomAuthorityError(
                "UOM_CANONICAL_QUANTITY_INVALID",
                str(exc),
                context={"product_variant_id": self.product_variant_id},
            ) from exc


def _build_authority(
    variant: ProductVariant,
    conversions: list[ProductUomConversion],
) -> VariantUomAuthority:
    base = int(variant.base_uom_id)
    factors: dict[int, Fraction] = {base: Fraction(1, 1)}
    adjacency: dict[int, list[tuple[int, Fraction]]] = {}

    for row in conversions:
        source = int(row.from_uom_id)
        target = int(row.to_uom_id)
        # Canonical contract:
        #   from_quantity * numerator / denominator == to_quantity
        ratio = (
            _positive_fraction(Decimal(row.numerator))
            / _positive_fraction(Decimal(row.denominator))
        )
        adjacency.setdefault(source, []).append((target, ratio))
        adjacency.setdefault(target, []).append(
            (source, Fraction(1, 1) / ratio)
        )

    # factors[uom] means canonical-base quantity represented by one unit of uom.
    # For target_qty = source_qty * ratio:
    # base_per_target = base_per_source / ratio.
    queue = [base]
    while queue:
        current = queue.pop(0)
        current_to_base = factors[current]
        for neighbor, current_to_neighbor in adjacency.get(current, ()):
            proposed = current_to_base / current_to_neighbor
            existing = factors.get(neighbor)
            if existing is None:
                factors[neighbor] = proposed
                queue.append(neighbor)
            elif existing != proposed:
                raise UomAuthorityError(
                    "UOM_CONVERSION_GRAPH_AMBIGUOUS",
                    "UOM conversion graph contains conflicting exact conversion paths.",
                    context={
                        "product_variant_id": int(variant.id),
                        "uom_id": neighbor,
                    },
                )

    return VariantUomAuthority(
        product_variant_id=int(variant.id),
        base_uom_id=base,
        quantity_scale=int(variant.quantity_scale),
        quantity_step=Decimal(variant.quantity_step),
        factors_to_base=factors,
    )


async def load_variant_uom_authorities(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: Iterable[int],
) -> dict[int, VariantUomAuthority]:
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return {}
    if any(value <= 0 for value in ids):
        raise UomAuthorityError(
            "UOM_VARIANT_ID_INVALID",
            "Product variant IDs must be positive.",
        )

    variants = list(
        (
            await db.scalars(
                select(ProductVariant).where(
                    ProductVariant.company_id == int(company_id),
                    ProductVariant.id.in_(ids),
                )
            )
        ).all()
    )
    variant_map = {int(row.id): row for row in variants}
    missing = sorted(set(ids) - set(variant_map))
    if missing:
        raise UomAuthorityError(
            "UOM_VARIANT_NOT_FOUND",
            "One or more product variants are not available inside this company.",
            context={"product_variant_ids": missing},
        )

    conversions = list(
        (
            await db.scalars(
                select(ProductUomConversion)
                .where(
                    ProductUomConversion.company_id == int(company_id),
                    ProductUomConversion.product_variant_id.in_(ids),
                )
                .order_by(
                    ProductUomConversion.product_variant_id,
                    ProductUomConversion.id,
                )
            )
        ).all()
    )
    by_variant: dict[int, list[ProductUomConversion]] = {
        variant_id: [] for variant_id in ids
    }
    for row in conversions:
        by_variant[int(row.product_variant_id)].append(row)

    return {
        variant_id: _build_authority(
            variant_map[variant_id],
            by_variant[variant_id],
        )
        for variant_id in ids
    }
