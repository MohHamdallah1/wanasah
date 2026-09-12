from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import (
    DispatchRoute,
    InventoryLocation,
    ProductUomConversion,
    ProductVariant,
    WorkSession,
)

from .context import require_route_commercial_context
from .core import PricingError
from .resolver import PriceResolution, resolve_prices_bulk


_MONEY_QUANT = Decimal("0.001")
_MONEY_MAX = Decimal("999999999.999")


@dataclass(frozen=True)
class LegacyDriverPrice:
    product_variant_id: int
    pack_uom_id: int
    carton_uom_id: int
    packs_per_carton: int
    price_per_pack: Decimal
    price_per_carton: Decimal
    pack_resolution: PriceResolution
    carton_resolution: PriceResolution


def _legacy_money_12_3(value: Decimal, field_name: str) -> Decimal:
    try:
        amount = Decimal(value)
        quantized = amount.quantize(_MONEY_QUANT)
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise PricingError(
            "PRICE_PRECISION_UNSUPPORTED",
            f"{field_name} غير صالح لعقد البيع الحالي Numeric(12,3).",
        ) from exc

    if (
        not amount.is_finite()
        or amount < 0
        or amount > _MONEY_MAX
        or quantized != amount
    ):
        raise PricingError(
            "PRICE_PRECISION_UNSUPPORTED",
            f"{field_name} يجب أن يكون غير سالب وقابلاً للتمثيل بدقة 3 منازل.",
            context={"amount": str(value)},
        )
    return quantized


async def _route_context_and_branch(
    db: AsyncSession,
    *,
    company_id: int,
    dispatch_route_id: int,
    expected_commercial_context_id: Optional[int],
):
    route = (
        await db.execute(
            select(
                DispatchRoute.id,
                DispatchRoute.source_location_id,
            ).where(
                DispatchRoute.company_id == int(company_id),
                DispatchRoute.id == int(dispatch_route_id),
            )
        )
    ).one_or_none()
    if route is None:
        raise PricingError(
            "COMMERCIAL_ROUTE_NOT_FOUND",
            "خط السير غير موجود داخل الشركة.",
            status_code=404,
            context={"dispatch_route_id": int(dispatch_route_id)},
        )

    context = await require_route_commercial_context(
        db,
        company_id=company_id,
        dispatch_route_id=dispatch_route_id,
    )
    if (
        expected_commercial_context_id is not None
        and int(context.id) != int(expected_commercial_context_id)
    ):
        raise PricingError(
            "COMMERCIAL_CONTEXT_LOCKED",
            "جلسة العمل وخط السير لا يشيران إلى نفس السياق التجاري المقفل.",
            context={
                "dispatch_route_id": int(dispatch_route_id),
                "route_commercial_context_id": int(context.id),
                "work_session_commercial_context_id": int(
                    expected_commercial_context_id
                ),
            },
        )

    branch_id = await db.scalar(
        select(InventoryLocation.branch_id).where(
            InventoryLocation.company_id == int(company_id),
            InventoryLocation.id == int(route.source_location_id),
        )
    )
    return context, (int(branch_id) if branch_id is not None else None)


async def _variant_uom_contracts(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: Sequence[int],
) -> dict[int, tuple[int, int, int]]:
    normalized = sorted({int(value) for value in variant_ids})
    if not normalized:
        return {}
    if any(value <= 0 for value in normalized):
        raise PricingError(
            "PRICE_RESOLVE_INPUT_INVALID",
            "معرفات الأصناف يجب أن تكون موجبة.",
            status_code=422,
        )

    rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.base_uom_id,
                ProductVariant.packs_per_carton,
            ).where(
                ProductVariant.company_id == int(company_id),
                ProductVariant.id.in_(normalized),
            ).order_by(ProductVariant.id.asc())
        )
    ).all()
    by_variant = {
        int(row.id): (
            int(row.base_uom_id),
            int(row.packs_per_carton or 0),
        )
        for row in rows
    }
    if set(by_variant) != set(normalized):
        raise PricingError(
            "PRICE_VARIANT_NOT_FOUND",
            "أحد الأصناف المطلوب تسعيرها مفقود أو خارج الشركة.",
            status_code=404,
        )

    conversion_rows = (
        await db.execute(
            select(ProductUomConversion).where(
                ProductUomConversion.company_id == int(company_id),
                ProductUomConversion.product_variant_id.in_(normalized),
            ).order_by(
                ProductUomConversion.product_variant_id.asc(),
                ProductUomConversion.id.asc(),
            )
        )
    ).scalars().all()

    candidates: dict[int, set[int]] = {
        variant_id: set() for variant_id in normalized
    }
    for row in conversion_rows:
        variant_id = int(row.product_variant_id)
        base_uom_id, packs_per_carton = by_variant[variant_id]
        if packs_per_carton <= 0:
            continue

        numerator = Decimal(row.numerator)
        denominator = Decimal(row.denominator)

        # Exact-rational contract used by the legacy carton/pack bridge:
        # to_quantity = from_quantity * numerator / denominator.
        # The carton UOM must therefore map exactly to packs_per_carton
        # base units; names/codes never carry authority.
        if (
            int(row.to_uom_id) == base_uom_id
            and int(row.from_uom_id) != base_uom_id
            and numerator == denominator * packs_per_carton
        ):
            candidates[variant_id].add(int(row.from_uom_id))

        if (
            int(row.from_uom_id) == base_uom_id
            and int(row.to_uom_id) != base_uom_id
            and denominator == numerator * packs_per_carton
        ):
            candidates[variant_id].add(int(row.to_uom_id))

    result: dict[int, tuple[int, int, int]] = {}
    for variant_id in normalized:
        base_uom_id, packs_per_carton = by_variant[variant_id]
        if packs_per_carton <= 0:
            raise PricingError(
                "PRICE_UOM_MAPPING_UNRESOLVED",
                "packs_per_carton غير صالح لعقد البيع القديم.",
                context={"product_variant_id": variant_id},
            )

        if packs_per_carton == 1:
            carton_uom_id = base_uom_id
        else:
            variant_candidates = sorted(candidates[variant_id])
            if not variant_candidates:
                raise PricingError(
                    "PRICE_UOM_MAPPING_UNRESOLVED",
                    "لا يوجد UOM صريح يمثل كرتونة كاملة لهذا الصنف.",
                    context={
                        "product_variant_id": variant_id,
                        "base_uom_id": base_uom_id,
                        "packs_per_carton": packs_per_carton,
                    },
                )
            if len(variant_candidates) != 1:
                raise PricingError(
                    "PRICE_UOM_MAPPING_AMBIGUOUS",
                    "أكثر من UOM يطابق تعريف الكرتونة؛ يجب إزالة التعارض.",
                    context={
                        "product_variant_id": variant_id,
                        "candidate_uom_ids": variant_candidates,
                    },
                )
            carton_uom_id = variant_candidates[0]

        result[variant_id] = (
            base_uom_id,
            carton_uom_id,
            packs_per_carton,
        )
    return result


async def resolve_legacy_driver_prices_bulk(
    db: AsyncSession,
    *,
    company_id: int,
    dispatch_route_id: int,
    variant_ids: Sequence[int],
    customer_id: Optional[int] = None,
    expected_commercial_context_id: Optional[int] = None,
) -> dict[int, LegacyDriverPrice]:
    contracts = await _variant_uom_contracts(
        db,
        company_id=company_id,
        variant_ids=variant_ids,
    )
    if not contracts:
        return {}

    context, branch_id = await _route_context_and_branch(
        db,
        company_id=company_id,
        dispatch_route_id=dispatch_route_id,
        expected_commercial_context_id=expected_commercial_context_id,
    )

    pairs = []
    for variant_id, (
        pack_uom_id,
        carton_uom_id,
        _,
    ) in contracts.items():
        pairs.append((variant_id, pack_uom_id))
        pairs.append((variant_id, carton_uom_id))

    resolutions = await resolve_prices_bulk(
        db,
        company_id=company_id,
        pairs=pairs,
        customer_id=customer_id,
        branch_id=branch_id,
        as_of=context.pricing_locked_at,
        publication_revision_ceiling=int(
            context.price_publication_revision
        ),
        assignment_revision_ceiling=int(context.assignment_revision),
    )

    result: dict[int, LegacyDriverPrice] = {}
    for variant_id, (
        pack_uom_id,
        carton_uom_id,
        packs_per_carton,
    ) in contracts.items():
        pack_resolution = resolutions[(variant_id, pack_uom_id)]
        carton_resolution = resolutions[(variant_id, carton_uom_id)]

        transaction_currency = str(
            context.transaction_currency_code
        ).upper()
        if (
            str(pack_resolution.currency_code).upper()
            != transaction_currency
            or str(carton_resolution.currency_code).upper()
            != transaction_currency
        ):
            raise PricingError(
                "COMMERCIAL_CURRENCY_MISMATCH",
                "عملة السعر المنشور لا تطابق عملة RouteCommercialContext.",
                context={
                    "product_variant_id": variant_id,
                    "transaction_currency_code":
                        context.transaction_currency_code,
                },
            )

        result[variant_id] = LegacyDriverPrice(
            product_variant_id=variant_id,
            pack_uom_id=pack_uom_id,
            carton_uom_id=carton_uom_id,
            packs_per_carton=packs_per_carton,
            price_per_pack=_legacy_money_12_3(
                pack_resolution.amount,
                "price_per_pack",
            ),
            price_per_carton=_legacy_money_12_3(
                carton_resolution.amount,
                "price_per_carton",
            ),
            pack_resolution=pack_resolution,
            carton_resolution=carton_resolution,
        )
    return result


async def resolve_work_session_pack_prices_bulk(
    db: AsyncSession,
    *,
    company_id: int,
    work_session_id: int,
    variant_ids: Sequence[int],
) -> dict[int, Decimal]:
    normalized = sorted({int(value) for value in variant_ids})
    if not normalized:
        return {}

    session = await db.scalar(
        select(WorkSession).where(
            WorkSession.company_id == int(company_id),
            WorkSession.id == int(work_session_id),
        )
    )
    if session is None:
        raise PricingError(
            "COMMERCIAL_CONTEXT_REQUIRED",
            "جلسة العمل المطلوبة غير موجودة.",
            status_code=404,
        )
    if session.commercial_context_id is None:
        raise PricingError(
            "COMMERCIAL_CONTEXT_REQUIRED",
            "جلسة العمل لا تحمل سياقاً تجارياً مقفلاً.",
            context={"work_session_id": int(work_session_id)},
        )

    route = await db.scalar(
        select(DispatchRoute).where(
            DispatchRoute.company_id == int(company_id),
            DispatchRoute.work_session_id == int(work_session_id),
            DispatchRoute.driver_id == int(session.driver_id),
        ).order_by(
            DispatchRoute.id.desc()
        ).limit(1)
    )
    if route is None:
        raise PricingError(
            "COMMERCIAL_ROUTE_NOT_FOUND",
            "جلسة العمل لا ترتبط بخط سير تجاري صالح.",
            context={"work_session_id": int(work_session_id)},
        )

    context, branch_id = await _route_context_and_branch(
        db,
        company_id=company_id,
        dispatch_route_id=int(route.id),
        expected_commercial_context_id=int(
            session.commercial_context_id
        ),
    )

    variant_rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.base_uom_id,
            ).where(
                ProductVariant.company_id == int(company_id),
                ProductVariant.id.in_(normalized),
            ).order_by(ProductVariant.id.asc())
        )
    ).all()
    base_uoms = {
        int(row.id): int(row.base_uom_id)
        for row in variant_rows
    }
    if set(base_uoms) != set(normalized):
        raise PricingError(
            "PRICE_VARIANT_NOT_FOUND",
            "أحد أصناف العجز مفقود أو خارج الشركة.",
            status_code=404,
        )

    resolutions = await resolve_prices_bulk(
        db,
        company_id=company_id,
        pairs=[
            (variant_id, base_uoms[variant_id])
            for variant_id in normalized
        ],
        customer_id=None,
        branch_id=branch_id,
        as_of=context.pricing_locked_at,
        publication_revision_ceiling=int(
            context.price_publication_revision
        ),
        assignment_revision_ceiling=int(context.assignment_revision),
    )

    result: dict[int, Decimal] = {}
    for variant_id in normalized:
        resolution = resolutions[
            (variant_id, base_uoms[variant_id])
        ]
        if (
            str(resolution.currency_code).upper()
            != str(context.transaction_currency_code).upper()
        ):
            raise PricingError(
                "COMMERCIAL_CURRENCY_MISMATCH",
                "عملة سعر العجز لا تطابق عملة RouteCommercialContext.",
                context={"product_variant_id": variant_id},
            )
        result[variant_id] = _legacy_money_12_3(
            resolution.amount,
            "financial_unit_price_snapshot",
        )
    return result
