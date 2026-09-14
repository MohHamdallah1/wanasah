from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from typing import Optional, Sequence

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.uom_authority import UomAuthorityError, load_variant_uom_authorities
from models import DispatchRoute, InventoryLocation, ProductVariant

from .context import require_route_commercial_context
from .core import PricingError
from .resolver import PriceResolution, resolve_prices_bulk


_DISPLAY_MONEY_QUANT = Decimal("0.001")
_DISPLAY_MONEY_MAX = Decimal("999999999.999")


@dataclass(frozen=True)
class DriverDisplayPrice:
    product_variant_id: int
    pack_uom_id: int
    carton_uom_id: int
    packs_per_carton: int
    price_per_pack: Decimal
    price_per_carton: Decimal
    pack_resolution: PriceResolution
    carton_resolution: PriceResolution


def _display_money_12_3(value: Decimal, field_name: str) -> Decimal:
    """Preserve the existing mobile response precision without silent rounding."""
    try:
        amount = Decimal(value)
        quantized = amount.quantize(_DISPLAY_MONEY_QUANT)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PricingError(
            "DRIVER_DISPLAY_PRICE_PRECISION_UNSUPPORTED",
            f"{field_name} is not representable by the current driver display contract.",
        ) from exc

    if (
        not amount.is_finite()
        or amount < 0
        or amount > _DISPLAY_MONEY_MAX
        or quantized != amount
    ):
        raise PricingError(
            "DRIVER_DISPLAY_PRICE_PRECISION_UNSUPPORTED",
            f"{field_name} must be a non-negative value with at most 3 decimal places.",
            context={"amount": str(value)},
        )
    return quantized


def _carton_uom_id(
    *,
    product_variant_id: int,
    base_uom_id: int,
    packs_per_carton: int,
    factors_to_base: dict[int, Fraction],
) -> int:
    if packs_per_carton <= 0:
        raise PricingError(
            "DRIVER_DISPLAY_PACKAGING_INVALID",
            "packs_per_carton must be positive for driver display pricing.",
            context={"product_variant_id": int(product_variant_id)},
        )
    if packs_per_carton == 1:
        return int(base_uom_id)

    target = Fraction(int(packs_per_carton), 1)
    candidates = sorted(
        int(uom_id)
        for uom_id, factor in factors_to_base.items()
        if int(uom_id) != int(base_uom_id) and factor == target
    )
    if not candidates:
        raise PricingError(
            "DRIVER_DISPLAY_CARTON_UOM_UNRESOLVED",
            "No explicit UOM resolves exactly to one carton for this product.",
            context={
                "product_variant_id": int(product_variant_id),
                "base_uom_id": int(base_uom_id),
                "packs_per_carton": int(packs_per_carton),
            },
        )
    if len(candidates) != 1:
        raise PricingError(
            "DRIVER_DISPLAY_CARTON_UOM_AMBIGUOUS",
            "More than one UOM resolves exactly to one carton for this product.",
            context={
                "product_variant_id": int(product_variant_id),
                "candidate_uom_ids": candidates,
            },
        )
    return candidates[0]


async def resolve_driver_display_prices_bulk(
    db: AsyncSession,
    *,
    company_id: int,
    dispatch_route_id: int,
    variant_ids: Sequence[int],
    customer_id: Optional[int] = None,
    expected_commercial_context_id: Optional[int] = None,
) -> dict[int, DriverDisplayPrice]:
    normalized = sorted({int(value) for value in variant_ids})
    if not normalized:
        return {}
    if int(company_id) <= 0 or int(dispatch_route_id) <= 0 or any(
        value <= 0 for value in normalized
    ):
        raise PricingError(
            "DRIVER_DISPLAY_PRICE_INPUT_INVALID",
            "Driver display pricing requires positive tenant, route and variant identifiers.",
            status_code=422,
        )

    route = (
        await db.execute(
            select(
                DispatchRoute.id,
                InventoryLocation.branch_id,
            )
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == DispatchRoute.company_id,
                    InventoryLocation.id == DispatchRoute.source_location_id,
                ),
            )
            .where(
                DispatchRoute.company_id == int(company_id),
                DispatchRoute.id == int(dispatch_route_id),
                InventoryLocation.company_id == int(company_id),
            )
        )
    ).one_or_none()
    if route is None:
        raise PricingError(
            "COMMERCIAL_ROUTE_NOT_FOUND",
            "The route or its source inventory location is missing from this company.",
            status_code=404,
            context={"dispatch_route_id": int(dispatch_route_id)},
        )

    context = await require_route_commercial_context(
        db,
        company_id=int(company_id),
        dispatch_route_id=int(dispatch_route_id),
    )
    if (
        expected_commercial_context_id is not None
        and int(context.id) != int(expected_commercial_context_id)
    ):
        raise PricingError(
            "COMMERCIAL_CONTEXT_LOCKED",
            "Work session and dispatch route do not reference the same locked commercial context.",
            context={
                "dispatch_route_id": int(dispatch_route_id),
                "route_commercial_context_id": int(context.id),
                "work_session_commercial_context_id": int(
                    expected_commercial_context_id
                ),
            },
        )

    variant_rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.packs_per_carton,
            )
            .where(
                ProductVariant.company_id == int(company_id),
                ProductVariant.id.in_(normalized),
            )
            .order_by(ProductVariant.id.asc())
        )
    ).all()
    packs_by_variant = {
        int(row.id): int(row.packs_per_carton or 0)
        for row in variant_rows
    }
    missing = sorted(set(normalized) - set(packs_by_variant))
    if missing:
        raise PricingError(
            "PRICE_VARIANT_NOT_FOUND",
            "One or more product variants are missing from this company.",
            status_code=404,
            context={"product_variant_ids": missing},
        )

    try:
        authorities = await load_variant_uom_authorities(
            db,
            company_id=int(company_id),
            variant_ids=normalized,
        )
    except UomAuthorityError as exc:
        raise PricingError(
            exc.code,
            exc.message,
            status_code=422,
            context=exc.context,
        ) from exc

    contracts: dict[int, tuple[int, int, int]] = {}
    pairs: list[tuple[int, int]] = []
    for variant_id in normalized:
        authority = authorities[variant_id]
        base_uom_id = int(authority.base_uom_id)
        packs_per_carton = int(packs_by_variant[variant_id])
        carton_uom_id = _carton_uom_id(
            product_variant_id=variant_id,
            base_uom_id=base_uom_id,
            packs_per_carton=packs_per_carton,
            factors_to_base=authority.factors_to_base,
        )
        contracts[variant_id] = (
            base_uom_id,
            carton_uom_id,
            packs_per_carton,
        )
        pairs.append((variant_id, base_uom_id))
        pairs.append((variant_id, carton_uom_id))

    branch_id = int(route.branch_id) if route.branch_id is not None else None
    resolutions = await resolve_prices_bulk(
        db,
        company_id=int(company_id),
        pairs=pairs,
        customer_id=(int(customer_id) if customer_id is not None else None),
        branch_id=branch_id,
        as_of=context.pricing_locked_at,
        publication_revision_ceiling=int(context.price_publication_revision),
        assignment_revision_ceiling=int(context.assignment_revision),
    )

    transaction_currency = str(context.transaction_currency_code or "").upper()
    if not transaction_currency:
        raise PricingError(
            "COMMERCIAL_CURRENCY_MISMATCH",
            "Locked route context is missing its transaction currency.",
        )

    result: dict[int, DriverDisplayPrice] = {}
    for variant_id in normalized:
        pack_uom_id, carton_uom_id, packs_per_carton = contracts[variant_id]
        pack_resolution = resolutions[(variant_id, pack_uom_id)]
        carton_resolution = resolutions[(variant_id, carton_uom_id)]
        if (
            str(pack_resolution.currency_code).upper() != transaction_currency
            or str(carton_resolution.currency_code).upper() != transaction_currency
        ):
            raise PricingError(
                "COMMERCIAL_CURRENCY_MISMATCH",
                "Published display price currency does not match the locked route context.",
                context={
                    "product_variant_id": variant_id,
                    "transaction_currency_code": transaction_currency,
                },
            )

        result[variant_id] = DriverDisplayPrice(
            product_variant_id=variant_id,
            pack_uom_id=pack_uom_id,
            carton_uom_id=carton_uom_id,
            packs_per_carton=packs_per_carton,
            price_per_pack=_display_money_12_3(
                pack_resolution.amount,
                "price_per_pack",
            ),
            price_per_carton=_display_money_12_3(
                carton_resolution.amount,
                "price_per_carton",
            ),
            pack_resolution=pack_resolution,
            carton_resolution=carton_resolution,
        )

    return result
