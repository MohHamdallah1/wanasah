from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from sqlalchemy import and_, case, func, or_, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory_rules import batch_sellability_predicate
from models import (
    Company,
    DispatchRoute,
    InventoryBalance,
    InventoryLiveStockCompanySummary,
    InventoryLiveStockProjection,
    InventoryLiveStockWarehouseSummary,
    InventoryLocation,
    InventoryStockPolicy,
    ProductBatch,
    ProductVariant,
    utc_now,
)


PROJECTION_VERSION = 1
_MAX_PROJECTOR_KEYS = 10_000
_COARSE_GUARD_THRESHOLD = 1_000
_ZERO = Decimal("0")


class LiveStockProjectionError(RuntimeError):
    pass


def _positive_int(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise LiveStockProjectionError(f"{field} must be a positive integer.")
    try:
        parsed_decimal = Decimal(str(value))
    except Exception as exc:
        raise LiveStockProjectionError(f"{field} must be a positive integer.") from exc
    if (
        not parsed_decimal.is_finite()
        or parsed_decimal != parsed_decimal.to_integral_value()
        or parsed_decimal <= 0
    ):
        raise LiveStockProjectionError(f"{field} must be a positive integer.")
    return int(parsed_decimal)


def _normalize_ids(values: Iterable[int], field: str) -> list[int]:
    result = sorted({_positive_int(value, field) for value in values})
    if len(result) > _MAX_PROJECTOR_KEYS:
        raise LiveStockProjectionError(
            f"{field} scope exceeds the safe limit of {_MAX_PROJECTOR_KEYS}."
        )
    return result


def _normalize_keys(
    keys: Iterable[tuple[int, int]],
) -> list[tuple[int, int]]:
    normalized = sorted(
        {
            (
                _positive_int(warehouse_id, "warehouse_location_id"),
                _positive_int(variant_id, "product_variant_id"),
            )
            for warehouse_id, variant_id in keys
        }
    )
    if len(normalized) > _MAX_PROJECTOR_KEYS:
        raise LiveStockProjectionError(
            f"projection key scope exceeds the safe limit of {_MAX_PROJECTOR_KEYS}."
        )
    return normalized


async def _acquire_text_guards(
    db: AsyncSession,
    keys: Sequence[str],
    *,
    shared: bool,
) -> None:
    if not keys:
        return
    lock_function = (
        "pg_advisory_xact_lock_shared" if shared else "pg_advisory_xact_lock"
    )
    await db.execute(
        text(
            f"""
            SELECT {lock_function}(hashtextextended(lock_key, 0))
            FROM unnest(CAST(:lock_keys AS text[])) AS t(lock_key)
            ORDER BY lock_key
            """
        ),
        {"lock_keys": sorted(set(keys))},
    )


async def _acquire_company_projection_guard(
    db: AsyncSession,
    *,
    company_id: int,
    exclusive: bool,
) -> None:
    company_id = _positive_int(company_id, "company_id")
    await _acquire_text_guards(
        db,
        [f"live-stock-company:{company_id}"],
        shared=not exclusive,
    )


async def acquire_live_stock_vehicle_guards(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_ids: Iterable[int],
) -> None:
    company_id = _positive_int(company_id, "company_id")
    ids = _normalize_ids(vehicle_ids, "vehicle_id")
    await _acquire_text_guards(
        db,
        [f"live-stock-vehicle:{company_id}:{vehicle_id}" for vehicle_id in ids],
        shared=False,
    )


async def _acquire_variant_guards(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: Iterable[int],
    exclusive: bool,
) -> None:
    company_id = _positive_int(company_id, "company_id")
    ids = _normalize_ids(variant_ids, "product_variant_id")
    await _acquire_text_guards(
        db,
        [f"live-stock-variant:{company_id}:{variant_id}" for variant_id in ids],
        shared=not exclusive,
    )


async def _acquire_projection_key_guards(
    db: AsyncSession,
    *,
    company_id: int,
    keys: Sequence[tuple[int, int]],
) -> None:
    await _acquire_text_guards(
        db,
        [
            f"live-stock-key:{company_id}:{warehouse_id}:{variant_id}"
            for warehouse_id, variant_id in keys
        ],
        shared=False,
    )


async def _company_local_date(db: AsyncSession, company_id: int) -> date:
    timezone_name = await db.scalar(
        select(Company.timezone).where(Company.id == company_id)
    )
    if not timezone_name:
        raise LiveStockProjectionError(
            "Company timezone is required for Live Stock projection."
        )
    try:
        value = await db.scalar(
            text("SELECT (CURRENT_TIMESTAMP AT TIME ZONE :timezone_name)::date"),
            {"timezone_name": str(timezone_name).strip()},
        )
    except Exception as exc:
        raise LiveStockProjectionError(
            f"Invalid company timezone: {timezone_name}"
        ) from exc
    if type(value) is not date:
        raise LiveStockProjectionError(
            "Could not resolve the company-local operational date."
        )
    return value


async def get_live_stock_vehicle_sources(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_ids: Iterable[int],
) -> dict[int, int]:
    company_id = _positive_int(company_id, "company_id")
    ids = _normalize_ids(vehicle_ids, "vehicle_id")
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                DispatchRoute.vehicle_id,
                DispatchRoute.source_location_id,
            )
            .where(
                DispatchRoute.company_id == company_id,
                DispatchRoute.vehicle_id.in_(ids),
            )
            .distinct(DispatchRoute.vehicle_id)
            .order_by(DispatchRoute.vehicle_id, DispatchRoute.id.desc())
        )
    ).all()
    return {
        int(vehicle_id): int(source_location_id)
        for vehicle_id, source_location_id in rows
        if vehicle_id is not None and source_location_id is not None
    }


async def _ensure_warehouse_summaries(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_ids: Sequence[int],
) -> None:
    if not warehouse_ids:
        return

    insert_stmt = (
        pg_insert(InventoryLiveStockWarehouseSummary)
        .values(
            [
                {
                    "company_id": company_id,
                    "warehouse_location_id": warehouse_id,
                    "projection_state": "BUILDING",
                    "projection_version": PROJECTION_VERSION,
                    "revision": 1,
                }
                for warehouse_id in warehouse_ids
            ]
        )
        .on_conflict_do_nothing(
            index_elements=["company_id", "warehouse_location_id"]
        )
        .returning(InventoryLiveStockWarehouseSummary.warehouse_location_id)
    )
    inserted_ids = [
        int(value)
        for value in (await db.execute(insert_stmt)).scalars().all()
    ]
    if not inserted_ids:
        return

    aggregate_rows = (
        await db.execute(
            select(
                InventoryLiveStockProjection.warehouse_location_id,
                func.count().label("row_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (InventoryLiveStockProjection.is_low_stock.is_(True), 1),
                            else_=0,
                        )
                    ),
                    0,
                ).label("alert_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    InventoryLiveStockProjection.lifecycle_status
                                    != "ACTIVE",
                                    or_(
                                        InventoryLiveStockProjection.has_warehouse_presence.is_(
                                            True
                                        ),
                                        InventoryLiveStockProjection.has_vehicle_presence.is_(
                                            True
                                        ),
                                    ),
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ).label("nonactive_count"),
            )
            .where(
                InventoryLiveStockProjection.company_id == company_id,
                InventoryLiveStockProjection.warehouse_location_id.in_(
                    inserted_ids
                ),
            )
            .group_by(InventoryLiveStockProjection.warehouse_location_id)
        )
    ).all()
    aggregates = {
        int(row.warehouse_location_id): (
            int(row.alert_count or 0),
            int(row.nonactive_count or 0),
            int(row.row_count or 0),
        )
        for row in aggregate_rows
    }
    for warehouse_id in inserted_ids:
        alert_count, nonactive_count, row_count = aggregates.get(
            warehouse_id, (0, 0, 0)
        )
        await db.execute(
            update(InventoryLiveStockWarehouseSummary)
            .where(
                InventoryLiveStockWarehouseSummary.company_id == company_id,
                InventoryLiveStockWarehouseSummary.warehouse_location_id
                == warehouse_id,
            )
            .values(
                alert_count=alert_count,
                nonactive_visible_count=nonactive_count,
                projected_row_count=row_count,
                updated_at=utc_now(),
            )
        )


def _nonactive_visible_from_values(values: Mapping[str, object]) -> bool:
    return (
        str(values["lifecycle_status"]) != "ACTIVE"
        and (
            bool(values["has_warehouse_presence"])
            or bool(values["has_vehicle_presence"])
        )
    )


def _nonactive_visible_from_row(row: InventoryLiveStockProjection) -> bool:
    return (
        row.lifecycle_status != "ACTIVE"
        and (bool(row.has_warehouse_presence) or bool(row.has_vehicle_presence))
    )


async def refresh_live_stock_keys(
    db: AsyncSession,
    *,
    company_id: int,
    keys: Iterable[tuple[int, int]],
    computed_for_date: date | None = None,
    variant_guard_exclusive: bool = False,
    _company_guard_held: bool = False,
    _force_coarse_guard: bool = False,
) -> None:
    company_id = _positive_int(company_id, "company_id")
    normalized_keys = _normalize_keys(keys)
    if not normalized_keys:
        return

    variant_ids = sorted(
        {variant_id for _warehouse_id, variant_id in normalized_keys}
    )
    coarse_guard = (
        _force_coarse_guard
        or len(normalized_keys) >= _COARSE_GUARD_THRESHOLD
        or len(variant_ids) >= _COARSE_GUARD_THRESHOLD
    )
    if not _company_guard_held:
        await _acquire_company_projection_guard(
            db,
            company_id=company_id,
            exclusive=coarse_guard,
        )
    if not coarse_guard:
        await _acquire_variant_guards(
            db,
            company_id=company_id,
            variant_ids=variant_ids,
            exclusive=variant_guard_exclusive,
        )
        await _acquire_projection_key_guards(
            db,
            company_id=company_id,
            keys=normalized_keys,
        )

    if computed_for_date is None:
        computed_for_date = await _company_local_date(db, company_id)
    if type(computed_for_date) is not date:
        raise LiveStockProjectionError("computed_for_date must be a date.")

    warehouse_ids = sorted({warehouse_id for warehouse_id, _ in normalized_keys})
    warehouses = set(
        (
            await db.execute(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id.in_(warehouse_ids),
                    InventoryLocation.location_type == "WAREHOUSE",
                )
            )
        ).scalars().all()
    )
    warehouses = {int(value) for value in warehouses}

    variants = {
        int(row.id): row
        for row in (
            await db.execute(
                select(ProductVariant).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(variant_ids),
                )
            )
        ).scalars().all()
    }

    active_keys = [
        key
        for key in normalized_keys
        if key[0] in warehouses and key[1] in variants
    ]
    await _ensure_warehouse_summaries(
        db,
        company_id=company_id,
        warehouse_ids=sorted({key[0] for key in active_keys}),
    )

    policy_rows = (
        await db.execute(
            select(
                InventoryStockPolicy.location_id,
                InventoryStockPolicy.product_variant_id,
                InventoryStockPolicy.minimum_quantity,
                InventoryStockPolicy.minimum_remaining_shelf_life_days,
            ).where(
                InventoryStockPolicy.company_id == company_id,
                InventoryStockPolicy.is_active.is_(True),
                tuple_(
                    InventoryStockPolicy.location_id,
                    InventoryStockPolicy.product_variant_id,
                ).in_(active_keys),
            )
        )
    ).all() if active_keys else []
    policies = {
        (int(row.location_id), int(row.product_variant_id)): row
        for row in policy_rows
    }

    min_shelf_life = func.coalesce(
        InventoryStockPolicy.minimum_remaining_shelf_life_days,
        0,
    )
    sellable_batch = batch_sellability_predicate(
        computed_for_date,
        expiry_control_mode=ProductVariant.expiry_control_mode,
        minimum_remaining_shelf_life_days=min_shelf_life,
    )
    transition_scope = and_(
        InventoryBalance.stock_status == "AVAILABLE",
        InventoryBalance.on_hand_quantity > 0,
        ProductBatch.is_active.is_(True),
        ProductBatch.disposition == "RELEASED",
    )
    expiry_transition = ProductBatch.expiry_date - min_shelf_life + 1

    direct_rows = (
        await db.execute(
            select(
                InventoryBalance.location_id,
                InventoryBalance.product_variant_id,
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status == "AVAILABLE",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ).label("warehouse_on_hand"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status == "AVAILABLE",
                                InventoryBalance.reserved_quantity,
                            ),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ).label("warehouse_reserved"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    InventoryBalance.stock_status == "AVAILABLE",
                                    sellable_batch,
                                ),
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ).label("warehouse_sellable_on_hand"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                and_(
                                    InventoryBalance.stock_status == "AVAILABLE",
                                    sellable_batch,
                                ),
                                InventoryBalance.reserved_quantity,
                            ),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ).label("warehouse_sellable_reserved"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status.in_(
                                    [
                                        "QUARANTINED",
                                        "BLOCKED",
                                        "RECALLED",
                                        "DISPOSAL_PENDING",
                                    ]
                                ),
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ).label("blocked_status_packs"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status == "RECALLED",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ).label("recalled_packs"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status == "DAMAGED",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=_ZERO,
                        )
                    ),
                    _ZERO,
                ).label("damaged_packs"),
                func.min(
                    case(
                        (
                            and_(
                                transition_scope,
                                ProductBatch.production_date.is_not(None),
                                ProductBatch.production_date > computed_for_date,
                            ),
                            ProductBatch.production_date,
                        ),
                        else_=None,
                    )
                ).label("next_production_transition"),
                func.min(
                    case(
                        (
                            and_(
                                transition_scope,
                                ProductVariant.expiry_control_mode.in_(
                                    ["OPTIONAL", "REQUIRED"]
                                ),
                                ProductBatch.expiry_date.is_not(None),
                                expiry_transition > computed_for_date,
                            ),
                            expiry_transition,
                        ),
                        else_=None,
                    )
                ).label("next_expiry_transition"),
            )
            .select_from(InventoryBalance)
            .join(
                ProductBatch,
                and_(
                    ProductBatch.company_id == InventoryBalance.company_id,
                    ProductBatch.product_variant_id
                    == InventoryBalance.product_variant_id,
                    ProductBatch.id == InventoryBalance.batch_id,
                ),
            )
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == InventoryBalance.company_id,
                    ProductVariant.id == InventoryBalance.product_variant_id,
                ),
            )
            .outerjoin(
                InventoryStockPolicy,
                and_(
                    InventoryStockPolicy.company_id
                    == InventoryBalance.company_id,
                    InventoryStockPolicy.location_id
                    == InventoryBalance.location_id,
                    InventoryStockPolicy.product_variant_id
                    == InventoryBalance.product_variant_id,
                    InventoryStockPolicy.is_active.is_(True),
                ),
            )
            .where(
                InventoryBalance.company_id == company_id,
                tuple_(
                    InventoryBalance.location_id,
                    InventoryBalance.product_variant_id,
                ).in_(active_keys),
            )
            .group_by(
                InventoryBalance.location_id,
                InventoryBalance.product_variant_id,
            )
        )
    ).all() if active_keys else []
    direct = {
        (int(row.location_id), int(row.product_variant_id)): row
        for row in direct_rows
    }

    latest_route = (
        select(
            DispatchRoute.vehicle_id.label("vehicle_id"),
            DispatchRoute.source_location_id.label("source_location_id"),
        )
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.vehicle_id.is_not(None),
        )
        .distinct(DispatchRoute.vehicle_id)
        .order_by(DispatchRoute.vehicle_id, DispatchRoute.id.desc())
        .subquery("live_stock_latest_vehicle_route")
    )

    vehicle_rows = (
        await db.execute(
            select(
                latest_route.c.source_location_id.label("warehouse_location_id"),
                InventoryBalance.product_variant_id,
                func.coalesce(
                    func.sum(InventoryBalance.on_hand_quantity),
                    _ZERO,
                ).label("vehicle_packs"),
            )
            .select_from(InventoryBalance)
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == InventoryBalance.company_id,
                    InventoryLocation.id == InventoryBalance.location_id,
                    InventoryLocation.location_type == "VEHICLE",
                    InventoryLocation.is_active.is_(True),
                    InventoryLocation.vehicle_id.is_not(None),
                ),
            )
            .join(
                latest_route,
                latest_route.c.vehicle_id == InventoryLocation.vehicle_id,
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.stock_status != "DAMAGED",
                tuple_(
                    latest_route.c.source_location_id,
                    InventoryBalance.product_variant_id,
                ).in_(active_keys),
            )
            .group_by(
                latest_route.c.source_location_id,
                InventoryBalance.product_variant_id,
            )
        )
    ).all() if active_keys else []
    vehicle = {
        (int(row.warehouse_location_id), int(row.product_variant_id)): Decimal(
            row.vehicle_packs or 0
        )
        for row in vehicle_rows
    }

    existing_rows = (
        await db.execute(
            select(InventoryLiveStockProjection)
            .where(
                InventoryLiveStockProjection.company_id == company_id,
                tuple_(
                    InventoryLiveStockProjection.warehouse_location_id,
                    InventoryLiveStockProjection.product_variant_id,
                ).in_(normalized_keys),
            )
            .order_by(
                InventoryLiveStockProjection.warehouse_location_id,
                InventoryLiveStockProjection.product_variant_id,
            )
            .with_for_update()
        )
    ).scalars().all()
    existing = {
        (int(row.warehouse_location_id), int(row.product_variant_id)): row
        for row in existing_rows
    }

    summary_deltas: dict[int, list[int]] = defaultdict(lambda: [0, 0, 0])
    projection_fields = (
        "variant_name",
        "lifecycle_status",
        "operational_hold",
        "warehouse_on_hand",
        "warehouse_reserved",
        "warehouse_sellable_on_hand",
        "warehouse_sellable_reserved",
        "blocked_status_packs",
        "recalled_packs",
        "damaged_packs",
        "vehicle_packs",
        "minimum_quantity",
        "has_active_policy",
        "is_low_stock",
        "has_warehouse_presence",
        "has_vehicle_presence",
        "next_transition_date",
        "computed_for_date",
    )

    for warehouse_id, variant_id in normalized_keys:
        key = (warehouse_id, variant_id)
        old = existing.get(key)
        variant = variants.get(variant_id)
        if warehouse_id not in warehouses or variant is None:
            new_values = None
        else:
            aggregate = direct.get(key)
            policy = policies.get(key)
            warehouse_on_hand = Decimal(
                getattr(aggregate, "warehouse_on_hand", 0) or 0
            )
            warehouse_reserved = Decimal(
                getattr(aggregate, "warehouse_reserved", 0) or 0
            )
            warehouse_sellable_on_hand = Decimal(
                getattr(aggregate, "warehouse_sellable_on_hand", 0) or 0
            )
            warehouse_sellable_reserved = Decimal(
                getattr(aggregate, "warehouse_sellable_reserved", 0) or 0
            )
            blocked_status_packs = Decimal(
                getattr(aggregate, "blocked_status_packs", 0) or 0
            )
            recalled_packs = Decimal(
                getattr(aggregate, "recalled_packs", 0) or 0
            )
            damaged_packs = Decimal(
                getattr(aggregate, "damaged_packs", 0) or 0
            )
            vehicle_packs = vehicle.get(key, _ZERO)
            minimum_quantity = (
                Decimal(policy.minimum_quantity or 0)
                if policy is not None
                else _ZERO
            )
            has_active_policy = policy is not None
            has_warehouse_presence = (
                warehouse_on_hand > 0
                or blocked_status_packs > 0
                or damaged_packs > 0
            )
            has_vehicle_presence = vehicle_packs > 0
            sparse = (
                has_active_policy
                or has_warehouse_presence
                or has_vehicle_presence
            )
            if not sparse:
                new_values = None
            else:
                next_candidates = [
                    value
                    for value in (
                        getattr(aggregate, "next_production_transition", None),
                        getattr(aggregate, "next_expiry_transition", None),
                    )
                    if value is not None and value > computed_for_date
                ]
                next_transition_date = (
                    min(next_candidates) if next_candidates else None
                )
                is_low_stock = (
                    has_active_policy
                    and minimum_quantity > 0
                    and variant.lifecycle_status == "ACTIVE"
                    and variant.operational_hold == "NONE"
                    and (
                        warehouse_sellable_on_hand
                        - warehouse_sellable_reserved
                    )
                    <= minimum_quantity
                )
                new_values = {
                    "variant_name": str(variant.name),
                    "lifecycle_status": str(variant.lifecycle_status),
                    "operational_hold": str(variant.operational_hold),
                    "warehouse_on_hand": warehouse_on_hand,
                    "warehouse_reserved": warehouse_reserved,
                    "warehouse_sellable_on_hand": warehouse_sellable_on_hand,
                    "warehouse_sellable_reserved": warehouse_sellable_reserved,
                    "blocked_status_packs": blocked_status_packs,
                    "recalled_packs": recalled_packs,
                    "damaged_packs": damaged_packs,
                    "vehicle_packs": vehicle_packs,
                    "minimum_quantity": minimum_quantity,
                    "has_active_policy": has_active_policy,
                    "is_low_stock": is_low_stock,
                    "has_warehouse_presence": has_warehouse_presence,
                    "has_vehicle_presence": has_vehicle_presence,
                    "next_transition_date": next_transition_date,
                    "computed_for_date": computed_for_date,
                }

        old_alert = bool(old.is_low_stock) if old is not None else False
        old_nonactive = (
            _nonactive_visible_from_row(old) if old is not None else False
        )
        old_present = old is not None

        new_alert = (
            bool(new_values["is_low_stock"]) if new_values is not None else False
        )
        new_nonactive = (
            _nonactive_visible_from_values(new_values)
            if new_values is not None
            else False
        )
        new_present = new_values is not None

        if (
            old_alert != new_alert
            or old_nonactive != new_nonactive
            or old_present != new_present
        ):
            delta = summary_deltas[warehouse_id]
            delta[0] += int(new_alert) - int(old_alert)
            delta[1] += int(new_nonactive) - int(old_nonactive)
            delta[2] += int(new_present) - int(old_present)

        if new_values is None:
            if old is not None:
                await db.delete(old)
            continue

        if old is None:
            db.add(
                InventoryLiveStockProjection(
                    company_id=company_id,
                    warehouse_location_id=warehouse_id,
                    product_variant_id=variant_id,
                    revision=1,
                    **new_values,
                )
            )
            continue

        changed = any(
            getattr(old, field) != new_values[field]
            for field in projection_fields
        )
        if not changed:
            continue
        for field in projection_fields:
            setattr(old, field, new_values[field])
        old.revision = int(old.revision) + 1
        old.updated_at = utc_now()

    await db.flush()

    for warehouse_id in sorted(summary_deltas):
        alert_delta, nonactive_delta, row_delta = summary_deltas[warehouse_id]
        if not (alert_delta or nonactive_delta or row_delta):
            continue
        result = await db.execute(
            update(InventoryLiveStockWarehouseSummary)
            .where(
                InventoryLiveStockWarehouseSummary.company_id == company_id,
                InventoryLiveStockWarehouseSummary.warehouse_location_id
                == warehouse_id,
            )
            .values(
                alert_count=(
                    InventoryLiveStockWarehouseSummary.alert_count + alert_delta
                ),
                nonactive_visible_count=(
                    InventoryLiveStockWarehouseSummary.nonactive_visible_count
                    + nonactive_delta
                ),
                projected_row_count=(
                    InventoryLiveStockWarehouseSummary.projected_row_count
                    + row_delta
                ),
                revision=InventoryLiveStockWarehouseSummary.revision + 1,
                updated_at=utc_now(),
            )
        )
        if result.rowcount != 1:
            raise LiveStockProjectionError(
                "Live Stock warehouse summary is missing during projection update."
            )
    await db.flush()


async def _candidate_keys_for_variants(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: Sequence[int],
) -> list[tuple[int, int]]:
    if not variant_ids:
        return []

    keys: set[tuple[int, int]] = set(
        (
            int(warehouse_id),
            int(variant_id),
        )
        for warehouse_id, variant_id in (
            await db.execute(
                select(
                    InventoryLiveStockProjection.warehouse_location_id,
                    InventoryLiveStockProjection.product_variant_id,
                ).where(
                    InventoryLiveStockProjection.company_id == company_id,
                    InventoryLiveStockProjection.product_variant_id.in_(
                        variant_ids
                    ),
                )
            )
        ).all()
    )

    policy_rows = (
        await db.execute(
            select(
                InventoryStockPolicy.location_id,
                InventoryStockPolicy.product_variant_id,
            )
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id
                    == InventoryStockPolicy.company_id,
                    InventoryLocation.id == InventoryStockPolicy.location_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                ),
            )
            .where(
                InventoryStockPolicy.company_id == company_id,
                InventoryStockPolicy.product_variant_id.in_(variant_ids),
                InventoryStockPolicy.is_active.is_(True),
            )
        )
    ).all()
    keys.update(
        (int(row.location_id), int(row.product_variant_id))
        for row in policy_rows
    )

    direct_rows = (
        await db.execute(
            select(
                InventoryBalance.location_id,
                InventoryBalance.product_variant_id,
            )
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == InventoryBalance.company_id,
                    InventoryLocation.id == InventoryBalance.location_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                ),
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id.in_(variant_ids),
                or_(
                    InventoryBalance.on_hand_quantity > 0,
                    InventoryBalance.reserved_quantity > 0,
                ),
            )
            .distinct()
        )
    ).all()
    keys.update(
        (int(row.location_id), int(row.product_variant_id))
        for row in direct_rows
    )

    latest_route = (
        select(
            DispatchRoute.vehicle_id.label("vehicle_id"),
            DispatchRoute.source_location_id.label("source_location_id"),
        )
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.vehicle_id.is_not(None),
        )
        .distinct(DispatchRoute.vehicle_id)
        .order_by(DispatchRoute.vehicle_id, DispatchRoute.id.desc())
        .subquery("live_stock_candidate_latest_route")
    )
    vehicle_rows = (
        await db.execute(
            select(
                latest_route.c.source_location_id,
                InventoryBalance.product_variant_id,
            )
            .select_from(InventoryBalance)
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == InventoryBalance.company_id,
                    InventoryLocation.id == InventoryBalance.location_id,
                    InventoryLocation.location_type == "VEHICLE",
                    InventoryLocation.is_active.is_(True),
                    InventoryLocation.vehicle_id.is_not(None),
                ),
            )
            .join(
                latest_route,
                latest_route.c.vehicle_id == InventoryLocation.vehicle_id,
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id.in_(variant_ids),
                InventoryBalance.stock_status != "DAMAGED",
                InventoryBalance.on_hand_quantity > 0,
            )
            .distinct()
        )
    ).all()
    keys.update(
        (int(row.source_location_id), int(row.product_variant_id))
        for row in vehicle_rows
        if row.source_location_id is not None
    )
    return _normalize_keys(keys)


async def refresh_live_stock_variants(
    db: AsyncSession,
    *,
    company_id: int,
    variant_ids: Iterable[int],
    computed_for_date: date | None = None,
) -> None:
    company_id = _positive_int(company_id, "company_id")
    ids = _normalize_ids(variant_ids, "product_variant_id")
    if not ids:
        return
    coarse_guard = len(ids) >= _COARSE_GUARD_THRESHOLD
    if coarse_guard:
        await _acquire_company_projection_guard(
            db,
            company_id=company_id,
            exclusive=True,
        )
    else:
        await _acquire_variant_guards(
            db,
            company_id=company_id,
            variant_ids=ids,
            exclusive=True,
        )
    keys = await _candidate_keys_for_variants(
        db,
        company_id=company_id,
        variant_ids=ids,
    )
    if keys:
        await refresh_live_stock_keys(
            db,
            company_id=company_id,
            keys=keys,
            computed_for_date=computed_for_date,
            variant_guard_exclusive=True,
            _company_guard_held=coarse_guard,
            _force_coarse_guard=coarse_guard,
        )


async def refresh_live_stock_from_movement_specs(
    db: AsyncSession,
    *,
    company_id: int,
    movement_specs: Sequence[Mapping[str, object]],
) -> None:
    company_id = _positive_int(company_id, "company_id")
    if not movement_specs:
        return

    variant_ids = _normalize_ids(
        [
            int(spec["product_variant_id"])
            for spec in movement_specs
            if spec.get("product_variant_id") is not None
        ],
        "product_variant_id",
    )
    location_ids = _normalize_ids(
        [
            int(location_id)
            for spec in movement_specs
            for location_id in (
                spec.get("source_location_id"),
                spec.get("destination_location_id"),
            )
            if location_id is not None
        ],
        "location_id",
    )
    if not variant_ids or not location_ids:
        return

    location_rows = (
        await db.execute(
            select(
                InventoryLocation.id,
                InventoryLocation.location_type,
                InventoryLocation.vehicle_id,
            ).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.id.in_(location_ids),
            )
        )
    ).all()
    location_map = {
        int(row.id): (str(row.location_type), row.vehicle_id)
        for row in location_rows
    }

    vehicle_ids = sorted(
        {
            int(vehicle_id)
            for location_type, vehicle_id in location_map.values()
            if location_type == "VEHICLE" and vehicle_id is not None
        }
    )
    if vehicle_ids:
        await acquire_live_stock_vehicle_guards(
            db,
            company_id=company_id,
            vehicle_ids=vehicle_ids,
        )
    coarse_guard = len(variant_ids) >= _COARSE_GUARD_THRESHOLD
    if coarse_guard:
        await _acquire_company_projection_guard(
            db,
            company_id=company_id,
            exclusive=True,
        )
    else:
        await _acquire_variant_guards(
            db,
            company_id=company_id,
            variant_ids=variant_ids,
            exclusive=False,
        )
    vehicle_sources = await get_live_stock_vehicle_sources(
        db,
        company_id=company_id,
        vehicle_ids=vehicle_ids,
    )

    keys: set[tuple[int, int]] = set()
    for spec in movement_specs:
        variant_id = int(spec["product_variant_id"])
        for raw_location_id in (
            spec.get("source_location_id"),
            spec.get("destination_location_id"),
        ):
            if raw_location_id is None:
                continue
            location_id = int(raw_location_id)
            location = location_map.get(location_id)
            if location is None:
                continue
            location_type, vehicle_id = location
            if location_type == "WAREHOUSE":
                keys.add((location_id, variant_id))
            elif location_type == "VEHICLE" and vehicle_id is not None:
                source = vehicle_sources.get(int(vehicle_id))
                if source is not None:
                    keys.add((source, variant_id))

    if keys:
        await refresh_live_stock_keys(
            db,
            company_id=company_id,
            keys=keys,
            _company_guard_held=coarse_guard,
            _force_coarse_guard=coarse_guard,
        )


async def refresh_live_stock_vehicle_attribution(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_ids: Iterable[int],
    previous_sources: Mapping[int, int],
) -> None:
    company_id = _positive_int(company_id, "company_id")
    ids = _normalize_ids(vehicle_ids, "vehicle_id")
    if not ids:
        return

    await acquire_live_stock_vehicle_guards(
        db,
        company_id=company_id,
        vehicle_ids=ids,
    )

    vehicle_locations = (
        await db.execute(
            select(
                InventoryLocation.id,
                InventoryLocation.vehicle_id,
            ).where(
                InventoryLocation.company_id == company_id,
                InventoryLocation.location_type == "VEHICLE",
                InventoryLocation.vehicle_id.in_(ids),
                InventoryLocation.is_active.is_(True),
            )
        )
    ).all()
    location_to_vehicle = {
        int(row.id): int(row.vehicle_id)
        for row in vehicle_locations
        if row.vehicle_id is not None
    }
    if not location_to_vehicle:
        return

    stock_rows = (
        await db.execute(
            select(
                InventoryBalance.location_id,
                InventoryBalance.product_variant_id,
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id.in_(
                    sorted(location_to_vehicle)
                ),
                InventoryBalance.stock_status != "DAMAGED",
                InventoryBalance.on_hand_quantity > 0,
            )
            .distinct()
        )
    ).all()
    variants_by_vehicle: dict[int, set[int]] = defaultdict(set)
    for row in stock_rows:
        vehicle_id = location_to_vehicle.get(int(row.location_id))
        if vehicle_id is not None:
            variants_by_vehicle[vehicle_id].add(int(row.product_variant_id))

    variant_ids = sorted(
        {
            variant_id
            for values in variants_by_vehicle.values()
            for variant_id in values
        }
    )
    if not variant_ids:
        return

    coarse_guard = len(variant_ids) >= _COARSE_GUARD_THRESHOLD
    if coarse_guard:
        await _acquire_company_projection_guard(
            db,
            company_id=company_id,
            exclusive=True,
        )
    else:
        await _acquire_variant_guards(
            db,
            company_id=company_id,
            variant_ids=variant_ids,
            exclusive=True,
        )
    current_sources = await get_live_stock_vehicle_sources(
        db,
        company_id=company_id,
        vehicle_ids=ids,
    )

    keys: set[tuple[int, int]] = set()
    for vehicle_id in ids:
        sources = {
            int(source)
            for source in (
                previous_sources.get(vehicle_id),
                current_sources.get(vehicle_id),
            )
            if source is not None
        }
        for source in sources:
            for variant_id in variants_by_vehicle.get(vehicle_id, set()):
                keys.add((source, variant_id))

    if keys:
        await refresh_live_stock_keys(
            db,
            company_id=company_id,
            keys=keys,
            variant_guard_exclusive=True,
            _company_guard_held=coarse_guard,
            _force_coarse_guard=coarse_guard,
        )


async def apply_live_stock_active_variant_delta(
    db: AsyncSession,
    *,
    company_id: int,
    delta: int,
) -> None:
    company_id = _positive_int(company_id, "company_id")
    if not isinstance(delta, int) or isinstance(delta, bool):
        raise LiveStockProjectionError("active variant delta must be an integer.")

    await _acquire_text_guards(
        db,
        [f"live-stock-company-summary:{company_id}"],
        shared=False,
    )
    summary = await db.scalar(
        select(InventoryLiveStockCompanySummary)
        .where(InventoryLiveStockCompanySummary.company_id == company_id)
        .with_for_update()
    )
    if summary is None:
        current_count = int(
            (
                await db.scalar(
                    select(func.count(ProductVariant.id)).where(
                        ProductVariant.company_id == company_id,
                        ProductVariant.lifecycle_status == "ACTIVE",
                    )
                )
            )
            or 0
        )
        db.add(
            InventoryLiveStockCompanySummary(
                company_id=company_id,
                active_variant_count=current_count,
                projection_state="BUILDING",
                projection_version=PROJECTION_VERSION,
                revision=1,
            )
        )
        await db.flush()
        return

    new_count = int(summary.active_variant_count) + delta
    if new_count < 0:
        raise LiveStockProjectionError(
            "Live Stock active variant summary would become negative."
        )
    if delta:
        summary.active_variant_count = new_count
        summary.revision = int(summary.revision) + 1
        summary.updated_at = utc_now()
        await db.flush()


async def refresh_due_live_stock_transitions(
    db: AsyncSession,
    *,
    company_id: int,
    as_of_date: date | None = None,
    limit: int = 5000,
) -> int:
    company_id = _positive_int(company_id, "company_id")
    if limit <= 0 or limit > _MAX_PROJECTOR_KEYS:
        raise LiveStockProjectionError("transition refresh limit is invalid.")
    if as_of_date is None:
        as_of_date = await _company_local_date(db, company_id)

    rows = (
        await db.execute(
            select(
                InventoryLiveStockProjection.warehouse_location_id,
                InventoryLiveStockProjection.product_variant_id,
            )
            .where(
                InventoryLiveStockProjection.company_id == company_id,
                InventoryLiveStockProjection.next_transition_date.is_not(None),
                InventoryLiveStockProjection.next_transition_date <= as_of_date,
            )
            .order_by(
                InventoryLiveStockProjection.next_transition_date,
                InventoryLiveStockProjection.warehouse_location_id,
                InventoryLiveStockProjection.product_variant_id,
            )
            .limit(limit)
        )
    ).all()
    keys = [
        (int(row.warehouse_location_id), int(row.product_variant_id))
        for row in rows
    ]
    if keys:
        await refresh_live_stock_keys(
            db,
            company_id=company_id,
            keys=keys,
            computed_for_date=as_of_date,
        )
    return len(keys)
