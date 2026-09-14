from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.pricing.context import require_route_commercial_context
from domains.pricing.core import PricingError
from domains.sales_calculation.contracts import (
    CalculationInputComponent,
    CalculationInputLine,
    CommercialCalculation,
)
from domains.sales_calculation.core import CalculationError
from domains.sales_calculation.policy import (
    CommercialPolicyError,
    resolve_commercial_rounding_policy,
)
from domains.sales_calculation.service import resolve_and_calculate_document
from domains.uom_authority import (
    UomAuthorityError,
    load_variant_uom_authorities,
)
from models import DispatchRoute, InventoryLocation, ProductVariant
from quantity import QuantityError, validate_variant_quantity


DRIVER_SALE_DOCUMENT_TYPE_CODE = "DRIVER_SALE"


@dataclass(frozen=True)
class DriverSaleInput:
    product_variant_id: int
    carton_quantity: int
    pack_quantity: int


@dataclass(frozen=True)
class DriverSaleUomContract:
    product_variant_id: int
    base_uom_id: int
    carton_uom_id: int
    packs_per_carton: int
    quantity_scale: int
    quantity_step: Decimal


@dataclass(frozen=True)
class ResolvedDriverSale:
    calculation: CommercialCalculation
    commercial_context_id: int
    functional_currency_code: str
    branch_id: int | None
    uom_contracts: dict[int, DriverSaleUomContract]


def _calculation_error_from_uom(exc: UomAuthorityError) -> CalculationError:
    return CalculationError(
        exc.code,
        exc.message,
        status_code=422,
        context=exc.context,
    )


async def resolve_driver_mobile_uom_contracts(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: Sequence[int],
) -> dict[int, DriverSaleUomContract]:
    normalized = sorted({int(value) for value in variant_ids})
    if not normalized or any(value <= 0 for value in normalized):
        raise CalculationError(
            "DRIVER_MOBILE_VARIANTS_INVALID",
            "Driver mobile quantity contracts require positive product variant identifiers.",
            status_code=422,
        )

    rows = (
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
        for row in rows
    }
    missing = sorted(set(normalized) - set(packs_by_variant))
    if missing:
        raise CalculationError(
            "DRIVER_MOBILE_VARIANT_NOT_FOUND",
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
        raise _calculation_error_from_uom(exc) from exc

    result: dict[int, DriverSaleUomContract] = {}
    for variant_id in normalized:
        packs_per_carton = packs_by_variant[variant_id]
        if packs_per_carton <= 0:
            raise CalculationError(
                "DRIVER_MOBILE_PACKAGING_INVALID",
                "packs_per_carton must be positive for the current driver mobile contract.",
                context={"product_variant_id": variant_id},
            )

        authority = authorities[variant_id]
        base_uom_id = int(authority.base_uom_id)

        if packs_per_carton == 1:
            carton_uom_id = base_uom_id
        else:
            target_factor = Fraction(packs_per_carton, 1)
            candidates = sorted(
                int(uom_id)
                for uom_id, factor in authority.factors_to_base.items()
                if int(uom_id) != base_uom_id and factor == target_factor
            )
            if not candidates:
                raise CalculationError(
                    "DRIVER_MOBILE_CARTON_UOM_UNRESOLVED",
                    "No explicit UOM resolves exactly to one carton for this product.",
                    context={
                        "product_variant_id": variant_id,
                        "base_uom_id": base_uom_id,
                        "packs_per_carton": packs_per_carton,
                    },
                )
            if len(candidates) != 1:
                raise CalculationError(
                    "DRIVER_MOBILE_CARTON_UOM_AMBIGUOUS",
                    "More than one UOM resolves exactly to one carton for this product.",
                    context={
                        "product_variant_id": variant_id,
                        "candidate_uom_ids": candidates,
                    },
                )
            carton_uom_id = candidates[0]

        result[variant_id] = DriverSaleUomContract(
            product_variant_id=variant_id,
            base_uom_id=base_uom_id,
            carton_uom_id=carton_uom_id,
            packs_per_carton=packs_per_carton,
            quantity_scale=int(authority.quantity_scale),
            quantity_step=Decimal(authority.quantity_step),
        )

    return result


def mobile_quantity_to_base(
    contract: DriverSaleUomContract,
    *,
    carton_quantity: int,
    pack_quantity: int,
    field_name: str,
    allow_zero: bool = False,
) -> Decimal:
    if (
        type(carton_quantity) is not int
        or type(pack_quantity) is not int
        or carton_quantity < 0
        or pack_quantity < 0
    ):
        raise CalculationError(
            "DRIVER_MOBILE_QUANTITY_INVALID",
            "Driver mobile quantities must be non-negative integers.",
            status_code=422,
            context={
                "product_variant_id": int(contract.product_variant_id),
                "field": field_name,
            },
        )

    canonical = (
        Decimal(carton_quantity) * Decimal(contract.packs_per_carton)
        + Decimal(pack_quantity)
    )
    try:
        return validate_variant_quantity(
            canonical,
            quantity_scale=int(contract.quantity_scale),
            quantity_step=Decimal(contract.quantity_step),
            field_name=field_name,
            allow_zero=allow_zero,
        )
    except QuantityError as exc:
        raise CalculationError(
            "DRIVER_MOBILE_QUANTITY_INVALID",
            str(exc),
            status_code=422,
            context={
                "product_variant_id": int(contract.product_variant_id),
                "field": field_name,
            },
        ) from exc


def _build_calculation_lines(
    inputs: Sequence[DriverSaleInput],
    *,
    contracts: dict[int, DriverSaleUomContract],
) -> tuple[CalculationInputLine, ...]:
    if not inputs:
        raise CalculationError(
            "DRIVER_SALE_EMPTY",
            "Driver sale requires at least one sold product.",
            status_code=422,
        )

    variant_ids = [int(row.product_variant_id) for row in inputs]
    if len(variant_ids) != len(set(variant_ids)):
        raise CalculationError(
            "DRIVER_SALE_DUPLICATE_VARIANT",
            "A driver sale cannot repeat the same product variant.",
            status_code=422,
        )

    lines: list[CalculationInputLine] = []
    for row in inputs:
        variant_id = int(row.product_variant_id)
        contract = contracts.get(variant_id)
        if contract is None:
            raise CalculationError(
                "DRIVER_SALE_UOM_CONTRACT_MISSING",
                "Driver sale UOM contract is missing.",
                context={"product_variant_id": variant_id},
            )

        carton_quantity = row.carton_quantity
        pack_quantity = row.pack_quantity
        mobile_quantity_to_base(
            contract,
            carton_quantity=carton_quantity,
            pack_quantity=pack_quantity,
            field_name=f"sale_quantity[{variant_id}]",
            allow_zero=False,
        )

        if contract.carton_uom_id == contract.base_uom_id:
            components = (
                CalculationInputComponent(
                    uom_id=contract.base_uom_id,
                    quantity=Decimal(carton_quantity + pack_quantity),
                ),
            )
        else:
            component_rows: list[CalculationInputComponent] = []
            if carton_quantity > 0:
                component_rows.append(
                    CalculationInputComponent(
                        uom_id=contract.carton_uom_id,
                        quantity=Decimal(carton_quantity),
                    )
                )
            if pack_quantity > 0:
                component_rows.append(
                    CalculationInputComponent(
                        uom_id=contract.base_uom_id,
                        quantity=Decimal(pack_quantity),
                    )
                )
            components = tuple(component_rows)

        lines.append(
            CalculationInputLine(
                line_id=variant_id,
                product_variant_id=variant_id,
                components=components,
            )
        )

    return tuple(lines)


async def resolve_driver_sale(
    db: AsyncSession,
    *,
    company_id: int,
    dispatch_route_id: int,
    expected_commercial_context_id: int,
    customer_id: int,
    jurisdiction_id: int,
    inputs: Sequence[DriverSaleInput],
    channel_code: str | None = None,
) -> ResolvedDriverSale:
    if (
        int(company_id) <= 0
        or int(dispatch_route_id) <= 0
        or int(expected_commercial_context_id) <= 0
        or int(customer_id) <= 0
        or int(jurisdiction_id) <= 0
    ):
        raise CalculationError(
            "DRIVER_SALE_CONTEXT_INVALID",
            "Driver sale requires explicit positive tenant, route, context, customer and tax jurisdiction identifiers.",
            status_code=422,
        )

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
        raise CalculationError(
            "DRIVER_SALE_ROUTE_NOT_FOUND",
            "Dispatch route was not found inside this company.",
            status_code=404,
            context={"dispatch_route_id": int(dispatch_route_id)},
        )
    if route.source_location_id is None:
        raise CalculationError(
            "DRIVER_SALE_SOURCE_LOCATION_REQUIRED",
            "Dispatch route requires an explicit source inventory location.",
            context={"dispatch_route_id": int(dispatch_route_id)},
        )

    context = await require_route_commercial_context(
        db,
        company_id=int(company_id),
        dispatch_route_id=int(dispatch_route_id),
    )
    if int(context.id) != int(expected_commercial_context_id):
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

    source_location = (
        await db.execute(
            select(
                InventoryLocation.id,
                InventoryLocation.branch_id,
            ).where(
                InventoryLocation.company_id == int(company_id),
                InventoryLocation.id == int(route.source_location_id),
            )
        )
    ).one_or_none()
    if source_location is None:
        raise CalculationError(
            "DRIVER_SALE_SOURCE_LOCATION_NOT_FOUND",
            "Dispatch route source location is missing from this company.",
            context={"source_location_id": int(route.source_location_id)},
        )

    branch_id = (
        int(source_location.branch_id)
        if source_location.branch_id is not None
        else None
    )

    transaction_currency = (
        str(context.transaction_currency_code or "").strip().upper()
    )
    functional_currency = (
        str(context.functional_currency_code or "").strip().upper()
    )
    if not transaction_currency or not functional_currency:
        raise CalculationError(
            "DRIVER_SALE_CURRENCY_CONTEXT_INVALID",
            "Locked commercial context is missing transaction or functional currency.",
        )

    try:
        rounding = await resolve_commercial_rounding_policy(
            db,
            company_id=int(company_id),
            as_of=context.pricing_locked_at,
            expected_currency_code=transaction_currency,
        )
    except CommercialPolicyError as exc:
        raise CalculationError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            context=exc.context,
        ) from exc

    if (
        int(rounding.policy_revision) != int(context.tenant_policy_revision)
        or int(rounding.rounding_policy.version)
        != int(context.rounding_policy_version)
    ):
        raise CalculationError(
            "DRIVER_SALE_ROUNDING_LOCK_MISMATCH",
            "Resolved rounding authority does not match the locked route commercial context.",
            context={
                "resolved_policy_revision": int(rounding.policy_revision),
                "locked_policy_revision": int(context.tenant_policy_revision),
                "resolved_rounding_version": int(
                    rounding.rounding_policy.version
                ),
                "locked_rounding_version": int(
                    context.rounding_policy_version
                ),
            },
        )

    variant_ids = [int(row.product_variant_id) for row in inputs]
    contracts = await resolve_driver_mobile_uom_contracts(
        db,
        company_id=int(company_id),
        variant_ids=variant_ids,
    )
    calculation_lines = _build_calculation_lines(
        inputs,
        contracts=contracts,
    )

    calculation = await resolve_and_calculate_document(
        db,
        company_id=int(company_id),
        lines=calculation_lines,
        customer_id=int(customer_id),
        branch_id=branch_id,
        channel_code=channel_code,
        jurisdiction_id=int(jurisdiction_id),
        document_type_code=DRIVER_SALE_DOCUMENT_TYPE_CODE,
        as_of=context.pricing_locked_at,
        rounding_policy=rounding.rounding_policy,
        price_publication_revision_ceiling=int(
            context.price_publication_revision
        ),
        assignment_revision_ceiling=int(context.assignment_revision),
        offer_revision_ceiling=int(context.offer_ruleset_version),
        tax_revision_ceiling=int(context.tax_ruleset_version),
    )

    if (
        str(calculation.transaction_currency_code).upper()
        != transaction_currency
    ):
        raise CalculationError(
            "DRIVER_SALE_CURRENCY_MISMATCH",
            "Calculated transaction currency does not match the locked route context.",
            context={
                "calculated_currency_code": calculation.transaction_currency_code,
                "locked_currency_code": transaction_currency,
            },
        )

    return ResolvedDriverSale(
        calculation=calculation,
        commercial_context_id=int(context.id),
        functional_currency_code=functional_currency,
        branch_id=branch_id,
        uom_contracts=contracts,
    )
