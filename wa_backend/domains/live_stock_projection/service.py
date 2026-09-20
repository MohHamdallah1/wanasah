from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping, Sequence

from sqlalchemy import Date, Integer, and_, any_, bindparam, case, cast, delete, func, or_, select, text, union, update
from sqlalchemy.dialects.postgresql import ARRAY, insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domains.inventory_rules import (
    batch_metadata_is_sellable,
    batch_next_transition_date,
    batch_sellability_predicate,
)
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
_COARSE_GUARD_THRESHOLD = 256
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


def _array_membership(column, values: Sequence[int], bind_name: str):
    if not values:
        raise LiveStockProjectionError(
            f"{bind_name} cannot be empty for array membership."
        )
    return column == any_(
        bindparam(
            bind_name,
            value=list(values),
            type_=ARRAY(Integer),
        )
    )


def _projection_key_scope(
    keys: Sequence[tuple[int, int]],
    *,
    name: str,
):
    if not keys:
        raise LiveStockProjectionError(
            f"{name} cannot be empty for projection key scope."
        )
    warehouse_ids = [warehouse_id for warehouse_id, _variant_id in keys]
    variant_ids = [variant_id for _warehouse_id, variant_id in keys]
    return (
        func.unnest(
            bindparam(
                f"{name}_warehouse_ids",
                value=warehouse_ids,
                type_=ARRAY(Integer),
            ),
            bindparam(
                f"{name}_variant_ids",
                value=variant_ids,
                type_=ARRAY(Integer),
            ),
        )
        .table_valued(
            "warehouse_location_id",
            "product_variant_id",
        )
        .render_derived(name=f"{name}_keys")
    )


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
                _array_membership(
                    DispatchRoute.vehicle_id,
                    ids,
                    "live_stock_vehicle_source_ids",
                ),
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

    requested = sorted(set(int(value) for value in warehouse_ids))
    existing = {
        int(value)
        for value in (
            await db.execute(
                select(
                    InventoryLiveStockWarehouseSummary.warehouse_location_id
                ).where(
                    InventoryLiveStockWarehouseSummary.company_id == company_id,
                    _array_membership(
                        InventoryLiveStockWarehouseSummary.warehouse_location_id,
                        requested,
                        "live_stock_summary_warehouse_ids",
                    ),
                )
            )
        ).scalars().all()
    }
    missing = [value for value in requested if value not in existing]
    if not missing:
        return

    # Summary creation is rare. Serialize only the missing warehouses instead
    # of making every hot-path refresh contend on INSERT .. ON CONFLICT.
    await _acquire_text_guards(
        db,
        [
            f"live-stock-summary:{company_id}:{warehouse_id}"
            for warehouse_id in missing
        ],
        shared=False,
    )
    existing_after_lock = {
        int(value)
        for value in (
            await db.execute(
                select(
                    InventoryLiveStockWarehouseSummary.warehouse_location_id
                ).where(
                    InventoryLiveStockWarehouseSummary.company_id == company_id,
                    _array_membership(
                        InventoryLiveStockWarehouseSummary.warehouse_location_id,
                        missing,
                        "live_stock_missing_summary_warehouse_ids",
                    ),
                )
            )
        ).scalars().all()
    }
    missing = [
        value for value in missing if value not in existing_after_lock
    ]
    if not missing:
        return

    aggregate_rows = (
        await db.execute(
            select(
                InventoryLiveStockProjection.warehouse_location_id,
                func.count().label("row_count"),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryLiveStockProjection.is_low_stock.is_(True),
                                1,
                            ),
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
                _array_membership(
                    InventoryLiveStockProjection.warehouse_location_id,
                    missing,
                    "live_stock_new_summary_warehouse_ids",
                ),
            )
            .group_by(
                InventoryLiveStockProjection.warehouse_location_id
            )
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

    await db.execute(
        pg_insert(InventoryLiveStockWarehouseSummary).values(
            [
                {
                    "company_id": company_id,
                    "warehouse_location_id": warehouse_id,
                    "projection_state": "BUILDING",
                    "projection_version": PROJECTION_VERSION,
                    "revision": 1,
                    "alert_count": aggregates.get(
                        warehouse_id, (0, 0, 0)
                    )[0],
                    "nonactive_visible_count": aggregates.get(
                        warehouse_id, (0, 0, 0)
                    )[1],
                    "projected_row_count": aggregates.get(
                        warehouse_id, (0, 0, 0)
                    )[2],
                    "updated_at": utc_now(),
                }
                for warehouse_id in missing
            ]
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


async def _apply_warehouse_summary_deltas(
    db: AsyncSession,
    *,
    company_id: int,
    summary_deltas: Mapping[int, Sequence[int]],
) -> None:
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


async def refresh_live_stock_keys(
    db: AsyncSession,
    *,
    company_id: int,
    keys: Iterable[tuple[int, int]],
    computed_for_date: date | None = None,
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
        await _acquire_projection_key_guards(
            db,
            company_id=company_id,
            keys=normalized_keys,
        )

    requested_key_scope = _projection_key_scope(
        normalized_keys,
        name="live_stock_requested",
    )
    company_date_expr = cast(
        func.timezone(Company.timezone, func.current_timestamp()),
        Date,
    )

    metadata_rows = (
        await db.execute(
            select(
                requested_key_scope.c.warehouse_location_id,
                requested_key_scope.c.product_variant_id,
                ProductVariant.name.label("variant_name"),
                ProductVariant.lifecycle_status,
                ProductVariant.operational_hold,
                ProductVariant.expiry_control_mode,
                InventoryStockPolicy.minimum_quantity,
                InventoryStockPolicy.minimum_remaining_shelf_life_days,
                company_date_expr.label("company_local_date"),
                InventoryLiveStockWarehouseSummary.warehouse_location_id.label(
                    "summary_warehouse_id"
                ),
                InventoryLiveStockProjection,
            )
            .select_from(requested_key_scope)
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id
                    == requested_key_scope.c.warehouse_location_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                ),
            )
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id
                    == requested_key_scope.c.product_variant_id,
                ),
            )
            .join(Company, Company.id == company_id)
            .outerjoin(
                InventoryStockPolicy,
                and_(
                    InventoryStockPolicy.company_id == company_id,
                    InventoryStockPolicy.location_id
                    == requested_key_scope.c.warehouse_location_id,
                    InventoryStockPolicy.product_variant_id
                    == requested_key_scope.c.product_variant_id,
                    InventoryStockPolicy.is_active.is_(True),
                ),
            )
            .outerjoin(
                InventoryLiveStockWarehouseSummary,
                and_(
                    InventoryLiveStockWarehouseSummary.company_id
                    == company_id,
                    InventoryLiveStockWarehouseSummary.warehouse_location_id
                    == requested_key_scope.c.warehouse_location_id,
                ),
            )
            .outerjoin(
                InventoryLiveStockProjection,
                and_(
                    InventoryLiveStockProjection.company_id == company_id,
                    InventoryLiveStockProjection.warehouse_location_id
                    == requested_key_scope.c.warehouse_location_id,
                    InventoryLiveStockProjection.product_variant_id
                    == requested_key_scope.c.product_variant_id,
                ),
            )
        )
    ).all()

    metadata = {
        (
            int(row.warehouse_location_id),
            int(row.product_variant_id),
        ): row
        for row in metadata_rows
    }
    existing = {
        (
            int(row.warehouse_location_id),
            int(row.product_variant_id),
        ): row[-1]
        for row in metadata_rows
        if row[-1] is not None
    }
    active_keys = sorted(metadata)
    if computed_for_date is None:
        dates = {
            row.company_local_date
            for row in metadata_rows
            if row.company_local_date is not None
        }
        if len(dates) != 1:
            raise LiveStockProjectionError(
                "Could not resolve one company-local operational date."
            )
        computed_for_date = next(iter(dates))
    if type(computed_for_date) is not date:
        raise LiveStockProjectionError("computed_for_date must be a date.")

    active_key_scope = (
        _projection_key_scope(active_keys, name="live_stock_active")
        if active_keys
        else None
    )
    normalized_key_scope = requested_key_scope

    missing_summary_warehouses = sorted(
        {
            int(row.warehouse_location_id)
            for row in metadata_rows
            if row.summary_warehouse_id is None
        }
    )
    if missing_summary_warehouses:
        await _ensure_warehouse_summaries(
            db,
            company_id=company_id,
            warehouse_ids=missing_summary_warehouses,
        )

    policies = {
        key: row
        for key, row in metadata.items()
        if row.minimum_quantity is not None
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

    direct_agg = (
        select(
            InventoryBalance.location_id.label("warehouse_location_id"),
            InventoryBalance.product_variant_id.label("product_variant_id"),
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
            active_key_scope,
            and_(
                active_key_scope.c.warehouse_location_id
                == InventoryBalance.location_id,
                active_key_scope.c.product_variant_id
                == InventoryBalance.product_variant_id,
            ),
        )
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
        .where(InventoryBalance.company_id == company_id)
        .group_by(
            InventoryBalance.location_id,
            InventoryBalance.product_variant_id,
        )
        .subquery("live_stock_direct_agg")
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
        .subquery("live_stock_latest_vehicle_route")
    )

    vehicle_agg = (
        select(
            latest_route.c.source_location_id.label(
                "warehouse_location_id"
            ),
            InventoryBalance.product_variant_id.label(
                "product_variant_id"
            ),
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
        .join(
            active_key_scope,
            and_(
                active_key_scope.c.warehouse_location_id
                == latest_route.c.source_location_id,
                active_key_scope.c.product_variant_id
                == InventoryBalance.product_variant_id,
            ),
        )
        .where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.stock_status != "DAMAGED",
        )
        .group_by(
            latest_route.c.source_location_id,
            InventoryBalance.product_variant_id,
        )
        .subquery("live_stock_vehicle_agg")
    )

    fact_rows = (
        await db.execute(
            select(
                active_key_scope.c.warehouse_location_id,
                active_key_scope.c.product_variant_id,
                func.coalesce(
                    direct_agg.c.warehouse_on_hand, _ZERO
                ).label("warehouse_on_hand"),
                func.coalesce(
                    direct_agg.c.warehouse_reserved, _ZERO
                ).label("warehouse_reserved"),
                func.coalesce(
                    direct_agg.c.warehouse_sellable_on_hand, _ZERO
                ).label("warehouse_sellable_on_hand"),
                func.coalesce(
                    direct_agg.c.warehouse_sellable_reserved, _ZERO
                ).label("warehouse_sellable_reserved"),
                func.coalesce(
                    direct_agg.c.blocked_status_packs, _ZERO
                ).label("blocked_status_packs"),
                func.coalesce(
                    direct_agg.c.recalled_packs, _ZERO
                ).label("recalled_packs"),
                func.coalesce(
                    direct_agg.c.damaged_packs, _ZERO
                ).label("damaged_packs"),
                func.coalesce(
                    vehicle_agg.c.vehicle_packs, _ZERO
                ).label("vehicle_packs"),
                direct_agg.c.next_production_transition,
                direct_agg.c.next_expiry_transition,
            )
            .select_from(active_key_scope)
            .outerjoin(
                direct_agg,
                and_(
                    direct_agg.c.warehouse_location_id
                    == active_key_scope.c.warehouse_location_id,
                    direct_agg.c.product_variant_id
                    == active_key_scope.c.product_variant_id,
                ),
            )
            .outerjoin(
                vehicle_agg,
                and_(
                    vehicle_agg.c.warehouse_location_id
                    == active_key_scope.c.warehouse_location_id,
                    vehicle_agg.c.product_variant_id
                    == active_key_scope.c.product_variant_id,
                ),
            )
        )
    ).all() if active_keys else []
    facts = {
        (
            int(row.warehouse_location_id),
            int(row.product_variant_id),
        ): row
        for row in fact_rows
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
        variant = metadata.get(key)
        if variant is None:
            new_values = None
        else:
            aggregate = facts.get(key)
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
            vehicle_packs = Decimal(
                getattr(aggregate, "vehicle_packs", 0) or 0
            )
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
                    "variant_name": str(variant.variant_name),
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

    await _apply_warehouse_summary_deltas(
        db,
        company_id=company_id,
        summary_deltas=summary_deltas,
    )


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
                    _array_membership(
                        InventoryLiveStockProjection.product_variant_id,
                        variant_ids,
                        "live_stock_candidate_projection_variant_ids",
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
                _array_membership(
                    InventoryStockPolicy.product_variant_id,
                    variant_ids,
                    "live_stock_candidate_policy_variant_ids",
                ),
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
                _array_membership(
                    InventoryBalance.product_variant_id,
                    variant_ids,
                    "live_stock_candidate_balance_variant_ids",
                ),
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
                _array_membership(
                    InventoryBalance.product_variant_id,
                    variant_ids,
                    "live_stock_candidate_vehicle_variant_ids",
                ),
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
            _company_guard_held=coarse_guard,
            _force_coarse_guard=coarse_guard,
        )


def _impact_decimal(value: object) -> Decimal:
    try:
        return Decimal(str(value or 0))
    except Exception as exc:
        raise LiveStockProjectionError(
            "Live Stock balance impact contains an invalid quantity."
        ) from exc


def _projection_quantities_are_valid(values: Mapping[str, object]) -> bool:
    on_hand = _impact_decimal(values["warehouse_on_hand"])
    reserved = _impact_decimal(values["warehouse_reserved"])
    sellable = _impact_decimal(values["warehouse_sellable_on_hand"])
    sellable_reserved = _impact_decimal(
        values["warehouse_sellable_reserved"]
    )
    blocked = _impact_decimal(values["blocked_status_packs"])
    recalled = _impact_decimal(values["recalled_packs"])
    damaged = _impact_decimal(values["damaged_packs"])
    vehicle = _impact_decimal(values["vehicle_packs"])
    minimum = _impact_decimal(values["minimum_quantity"])
    return (
        on_hand >= 0
        and reserved >= 0
        and reserved <= on_hand
        and sellable >= 0
        and sellable <= on_hand
        and sellable_reserved >= 0
        and sellable_reserved <= sellable
        and blocked >= 0
        and recalled >= 0
        and recalled <= blocked
        and damaged >= 0
        and vehicle >= 0
        and minimum >= 0
    )


async def apply_live_stock_balance_impacts(
    db: AsyncSession,
    *,
    company_id: int,
    impacts: Sequence[Mapping[str, object]],
) -> None:
    """Apply already-locked InventoryBalance before/after deltas transactionally.

    This is the hot mutation path. Full SSOT aggregation remains the authority
    for rebuilds, lifecycle/batch changes, stale-date repair and drift recovery.
    """
    company_id = _positive_int(company_id, "company_id")
    if not impacts:
        return

    normalized_impacts: list[dict[str, object]] = []
    vehicle_ids: set[int] = set()
    for raw in impacts:
        location_id = _positive_int(raw.get("location_id"), "location_id")
        variant_id = _positive_int(
            raw.get("product_variant_id"),
            "product_variant_id",
        )
        location_type = str(raw.get("location_type") or "").upper()
        if location_type not in {"WAREHOUSE", "VEHICLE", "IN_TRANSIT"}:
            raise LiveStockProjectionError(
                f"Unsupported inventory location type: {location_type}"
            )
        vehicle_id = raw.get("vehicle_id")
        if vehicle_id is not None:
            vehicle_id = _positive_int(vehicle_id, "vehicle_id")
        if location_type == "VEHICLE":
            if vehicle_id is None:
                raise LiveStockProjectionError(
                    "Vehicle inventory impact is missing vehicle_id."
                )
            vehicle_ids.add(int(vehicle_id))

        normalized = dict(raw)
        normalized["location_id"] = location_id
        normalized["product_variant_id"] = variant_id
        normalized["location_type"] = location_type
        normalized["vehicle_id"] = vehicle_id
        normalized["stock_status"] = str(
            raw.get("stock_status") or ""
        ).upper()
        normalized_impacts.append(normalized)

    if vehicle_ids:
        await acquire_live_stock_vehicle_guards(
            db,
            company_id=company_id,
            vehicle_ids=sorted(vehicle_ids),
        )
    vehicle_sources = await get_live_stock_vehicle_sources(
        db,
        company_id=company_id,
        vehicle_ids=sorted(vehicle_ids),
    )

    impacts_by_key: dict[
        tuple[int, int],
        list[dict[str, object]],
    ] = defaultdict(list)
    for impact in normalized_impacts:
        location_type = str(impact["location_type"])
        variant_id = int(impact["product_variant_id"])
        if location_type == "WAREHOUSE":
            key = (int(impact["location_id"]), variant_id)
        elif location_type == "VEHICLE":
            source = vehicle_sources.get(int(impact["vehicle_id"]))
            if source is None:
                continue
            key = (int(source), variant_id)
        else:
            continue
        impacts_by_key[key].append(impact)

    keys = _normalize_keys(impacts_by_key)
    if not keys:
        return

    coarse_guard = len(keys) >= _COARSE_GUARD_THRESHOLD
    await _acquire_company_projection_guard(
        db,
        company_id=company_id,
        exclusive=coarse_guard,
    )
    if not coarse_guard:
        await _acquire_projection_key_guards(
            db,
            company_id=company_id,
            keys=keys,
        )

    key_scope = _projection_key_scope(
        keys,
        name="live_stock_delta",
    )
    company_date_expr = cast(
        func.timezone(Company.timezone, func.current_timestamp()),
        Date,
    )
    rows = (
        await db.execute(
            select(
                key_scope.c.warehouse_location_id,
                key_scope.c.product_variant_id,
                InventoryStockPolicy.minimum_quantity,
                InventoryStockPolicy.minimum_remaining_shelf_life_days,
                company_date_expr.label("company_local_date"),
                InventoryLiveStockWarehouseSummary.warehouse_location_id.label(
                    "summary_warehouse_id"
                ),
                InventoryLiveStockProjection,
            )
            .select_from(key_scope)
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id
                    == key_scope.c.warehouse_location_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                ),
            )
            .join(Company, Company.id == company_id)
            .outerjoin(
                InventoryStockPolicy,
                and_(
                    InventoryStockPolicy.company_id == company_id,
                    InventoryStockPolicy.location_id
                    == key_scope.c.warehouse_location_id,
                    InventoryStockPolicy.product_variant_id
                    == key_scope.c.product_variant_id,
                    InventoryStockPolicy.is_active.is_(True),
                ),
            )
            .outerjoin(
                InventoryLiveStockWarehouseSummary,
                and_(
                    InventoryLiveStockWarehouseSummary.company_id
                    == company_id,
                    InventoryLiveStockWarehouseSummary.warehouse_location_id
                    == key_scope.c.warehouse_location_id,
                ),
            )
            .outerjoin(
                InventoryLiveStockProjection,
                and_(
                    InventoryLiveStockProjection.company_id == company_id,
                    InventoryLiveStockProjection.warehouse_location_id
                    == key_scope.c.warehouse_location_id,
                    InventoryLiveStockProjection.product_variant_id
                    == key_scope.c.product_variant_id,
                ),
            )
        )
    ).all()
    metadata = {
        (
            int(row.warehouse_location_id),
            int(row.product_variant_id),
        ): row
        for row in rows
    }
    if set(metadata) != set(keys):
        raise LiveStockProjectionError(
            "A Live Stock impact references an invalid warehouse key."
        )

    dates = {
        row.company_local_date
        for row in rows
        if row.company_local_date is not None
    }
    if len(dates) != 1:
        raise LiveStockProjectionError(
            "Could not resolve one company-local operational date."
        )
    as_of_date = next(iter(dates))
    if type(as_of_date) is not date:
        raise LiveStockProjectionError(
            "Company-local operational date is invalid."
        )

    missing_summaries = sorted(
        {
            int(row.warehouse_location_id)
            for row in rows
            if row.summary_warehouse_id is None
        }
    )
    if missing_summaries:
        await _ensure_warehouse_summaries(
            db,
            company_id=company_id,
            warehouse_ids=missing_summaries,
        )

    fallback_keys: set[tuple[int, int]] = set()
    for key, row in metadata.items():
        old = row[-1]
        minimum_days = int(
            row.minimum_remaining_shelf_life_days or 0
        )
        has_policy = row.minimum_quantity is not None

        if old is not None and (
            old.computed_for_date != as_of_date
            or (
                old.next_transition_date is not None
                and old.next_transition_date <= as_of_date
            )
        ):
            fallback_keys.add(key)
            continue

        had_presence_before = False
        for impact in impacts_by_key[key]:
            before_on_hand = _impact_decimal(
                impact.get("on_hand_before")
            )
            before_reserved = _impact_decimal(
                impact.get("reserved_before")
            )
            location_type = str(impact["location_type"])
            status = str(impact["stock_status"])
            if location_type == "WAREHOUSE":
                if before_on_hand > 0 or before_reserved > 0:
                    had_presence_before = True
            elif (
                location_type == "VEHICLE"
                and status != "DAMAGED"
                and before_on_hand > 0
            ):
                had_presence_before = True

            if (
                old is not None
                and location_type == "WAREHOUSE"
                and status == "AVAILABLE"
                and before_on_hand > 0
                and _impact_decimal(impact.get("on_hand_after")) == 0
            ):
                candidate = batch_next_transition_date(
                    as_of_date=as_of_date,
                    expiry_control_mode=str(
                        impact.get("expiry_control_mode") or ""
                    ),
                    production_date=impact.get("production_date"),
                    expiry_date=impact.get("expiry_date"),
                    minimum_remaining_shelf_life_days=minimum_days,
                    is_active=bool(impact.get("batch_is_active")),
                    disposition=str(
                        impact.get("batch_disposition") or ""
                    ),
                )
                if (
                    candidate is not None
                    and candidate == old.next_transition_date
                ):
                    fallback_keys.add(key)

        if old is None and (has_policy or had_presence_before):
            fallback_keys.add(key)

    summary_deltas: dict[int, list[int]] = defaultdict(
        lambda: [0, 0, 0]
    )
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

    for key in keys:
        if key in fallback_keys:
            continue

        warehouse_id, variant_id = key
        row = metadata[key]
        old = row[-1]
        minimum_quantity = (
            _impact_decimal(row.minimum_quantity)
            if row.minimum_quantity is not None
            else _ZERO
        )
        minimum_days = int(
            row.minimum_remaining_shelf_life_days or 0
        )

        first = impacts_by_key[key][0]
        values: dict[str, object] = {
            "variant_name": (
                str(old.variant_name)
                if old is not None
                else str(first.get("variant_name") or "").strip()
            ),
            "lifecycle_status": (
                str(old.lifecycle_status)
                if old is not None
                else str(first.get("lifecycle_status") or "")
            ),
            "operational_hold": (
                str(old.operational_hold)
                if old is not None
                else str(first.get("operational_hold") or "")
            ),
            "warehouse_on_hand": (
                _impact_decimal(old.warehouse_on_hand)
                if old is not None
                else _ZERO
            ),
            "warehouse_reserved": (
                _impact_decimal(old.warehouse_reserved)
                if old is not None
                else _ZERO
            ),
            "warehouse_sellable_on_hand": (
                _impact_decimal(old.warehouse_sellable_on_hand)
                if old is not None
                else _ZERO
            ),
            "warehouse_sellable_reserved": (
                _impact_decimal(old.warehouse_sellable_reserved)
                if old is not None
                else _ZERO
            ),
            "blocked_status_packs": (
                _impact_decimal(old.blocked_status_packs)
                if old is not None
                else _ZERO
            ),
            "recalled_packs": (
                _impact_decimal(old.recalled_packs)
                if old is not None
                else _ZERO
            ),
            "damaged_packs": (
                _impact_decimal(old.damaged_packs)
                if old is not None
                else _ZERO
            ),
            "vehicle_packs": (
                _impact_decimal(old.vehicle_packs)
                if old is not None
                else _ZERO
            ),
            "minimum_quantity": minimum_quantity,
            "has_active_policy": row.minimum_quantity is not None,
            "next_transition_date": (
                old.next_transition_date if old is not None else None
            ),
            "computed_for_date": as_of_date,
        }

        for impact in impacts_by_key[key]:
            delta_on_hand = (
                _impact_decimal(impact.get("on_hand_after"))
                - _impact_decimal(impact.get("on_hand_before"))
            )
            delta_reserved = (
                _impact_decimal(impact.get("reserved_after"))
                - _impact_decimal(impact.get("reserved_before"))
            )
            location_type = str(impact["location_type"])
            status = str(impact["stock_status"])

            if location_type == "VEHICLE":
                if status != "DAMAGED":
                    values["vehicle_packs"] = (
                        _impact_decimal(values["vehicle_packs"])
                        + delta_on_hand
                    )
                continue

            if status == "AVAILABLE":
                values["warehouse_on_hand"] = (
                    _impact_decimal(values["warehouse_on_hand"])
                    + delta_on_hand
                )
                values["warehouse_reserved"] = (
                    _impact_decimal(values["warehouse_reserved"])
                    + delta_reserved
                )
                sellable = batch_metadata_is_sellable(
                    as_of_date=as_of_date,
                    expiry_control_mode=str(
                        impact.get("expiry_control_mode") or ""
                    ),
                    production_date=impact.get("production_date"),
                    expiry_date=impact.get("expiry_date"),
                    minimum_remaining_shelf_life_days=minimum_days,
                    is_active=bool(impact.get("batch_is_active")),
                    disposition=str(
                        impact.get("batch_disposition") or ""
                    ),
                )
                if sellable:
                    values["warehouse_sellable_on_hand"] = (
                        _impact_decimal(
                            values["warehouse_sellable_on_hand"]
                        )
                        + delta_on_hand
                    )
                    values["warehouse_sellable_reserved"] = (
                        _impact_decimal(
                            values["warehouse_sellable_reserved"]
                        )
                        + delta_reserved
                    )

                if _impact_decimal(impact.get("on_hand_after")) > 0:
                    candidate = batch_next_transition_date(
                        as_of_date=as_of_date,
                        expiry_control_mode=str(
                            impact.get("expiry_control_mode") or ""
                        ),
                        production_date=impact.get("production_date"),
                        expiry_date=impact.get("expiry_date"),
                        minimum_remaining_shelf_life_days=minimum_days,
                        is_active=bool(impact.get("batch_is_active")),
                        disposition=str(
                            impact.get("batch_disposition") or ""
                        ),
                    )
                    current = values["next_transition_date"]
                    if candidate is not None and (
                        current is None or candidate < current
                    ):
                        values["next_transition_date"] = candidate

            elif status in {
                "QUARANTINED",
                "BLOCKED",
                "RECALLED",
                "DISPOSAL_PENDING",
            }:
                values["blocked_status_packs"] = (
                    _impact_decimal(values["blocked_status_packs"])
                    + delta_on_hand
                )
                if status == "RECALLED":
                    values["recalled_packs"] = (
                        _impact_decimal(values["recalled_packs"])
                        + delta_on_hand
                    )
            elif status == "DAMAGED":
                values["damaged_packs"] = (
                    _impact_decimal(values["damaged_packs"])
                    + delta_on_hand
                )
            else:
                raise LiveStockProjectionError(
                    f"Unsupported inventory stock status: {status}"
                )

        if not str(values["variant_name"]).strip():
            raise LiveStockProjectionError(
                "Live Stock impact is missing variant_name."
            )

        if not _projection_quantities_are_valid(values):
            fallback_keys.add(key)
            continue

        values["has_warehouse_presence"] = (
            _impact_decimal(values["warehouse_on_hand"]) > 0
            or _impact_decimal(values["blocked_status_packs"]) > 0
            or _impact_decimal(values["damaged_packs"]) > 0
        )
        values["has_vehicle_presence"] = (
            _impact_decimal(values["vehicle_packs"]) > 0
        )
        values["is_low_stock"] = (
            bool(values["has_active_policy"])
            and minimum_quantity > 0
            and str(values["lifecycle_status"]) == "ACTIVE"
            and str(values["operational_hold"]) == "NONE"
            and (
                _impact_decimal(values["warehouse_sellable_on_hand"])
                - _impact_decimal(
                    values["warehouse_sellable_reserved"]
                )
            )
            <= minimum_quantity
        )

        sparse = (
            bool(values["has_active_policy"])
            or bool(values["has_warehouse_presence"])
            or bool(values["has_vehicle_presence"])
        )
        new_values = values if sparse else None

        old_alert = bool(old.is_low_stock) if old is not None else False
        old_nonactive = (
            _nonactive_visible_from_row(old) if old is not None else False
        )
        old_present = old is not None
        new_alert = (
            bool(new_values["is_low_stock"])
            if new_values is not None
            else False
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
    await _apply_warehouse_summary_deltas(
        db,
        company_id=company_id,
        summary_deltas=summary_deltas,
    )

    if fallback_keys:
        await refresh_live_stock_keys(
            db,
            company_id=company_id,
            keys=sorted(fallback_keys),
            _company_guard_held=True,
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
                _array_membership(
                    InventoryLocation.vehicle_id,
                    ids,
                    "live_stock_attribution_vehicle_ids",
                ),
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


@dataclass(frozen=True)
class LiveStockWarehouseRebuildReport:
    company_id: int
    warehouse_location_id: int
    candidate_keys: int
    drifted_keys: int
    summary_repairs: int


@dataclass(frozen=True)
class LiveStockCompanyRebuildReport:
    company_id: int
    warehouse_count: int
    candidate_keys: int
    drifted_keys: int
    summary_repairs: int
    dropped_inactive_warehouses: int


_PROJECTION_SNAPSHOT_FIELDS = (
    InventoryLiveStockProjection.variant_name,
    InventoryLiveStockProjection.lifecycle_status,
    InventoryLiveStockProjection.operational_hold,
    InventoryLiveStockProjection.warehouse_on_hand,
    InventoryLiveStockProjection.warehouse_reserved,
    InventoryLiveStockProjection.warehouse_sellable_on_hand,
    InventoryLiveStockProjection.warehouse_sellable_reserved,
    InventoryLiveStockProjection.blocked_status_packs,
    InventoryLiveStockProjection.recalled_packs,
    InventoryLiveStockProjection.damaged_packs,
    InventoryLiveStockProjection.vehicle_packs,
    InventoryLiveStockProjection.minimum_quantity,
    InventoryLiveStockProjection.has_active_policy,
    InventoryLiveStockProjection.is_low_stock,
    InventoryLiveStockProjection.has_warehouse_presence,
    InventoryLiveStockProjection.has_vehicle_presence,
    InventoryLiveStockProjection.next_transition_date,
    InventoryLiveStockProjection.computed_for_date,
)


async def _projection_snapshot_for_keys(
    db: AsyncSession,
    *,
    company_id: int,
    keys: Sequence[tuple[int, int]],
) -> dict[tuple[int, int], tuple[object, ...]]:
    if not keys:
        return {}
    scope = _projection_key_scope(keys, name="live_stock_rebuild_snapshot")
    rows = (
        await db.execute(
            select(
                InventoryLiveStockProjection.warehouse_location_id,
                InventoryLiveStockProjection.product_variant_id,
                *_PROJECTION_SNAPSHOT_FIELDS,
            )
            .select_from(scope)
            .join(
                InventoryLiveStockProjection,
                and_(
                    InventoryLiveStockProjection.company_id == company_id,
                    InventoryLiveStockProjection.warehouse_location_id
                    == scope.c.warehouse_location_id,
                    InventoryLiveStockProjection.product_variant_id
                    == scope.c.product_variant_id,
                ),
            )
        )
    ).all()
    return {
        (int(row[0]), int(row[1])): tuple(row[2:])
        for row in rows
    }


def _warehouse_candidate_variant_query(
    *,
    company_id: int,
    warehouse_location_id: int,
):
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
        .subquery("live_stock_rebuild_latest_route")
    )
    vehicle_variants = (
        select(InventoryBalance.product_variant_id)
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
            latest_route.c.source_location_id == warehouse_location_id,
            InventoryBalance.stock_status != "DAMAGED",
            InventoryBalance.on_hand_quantity > 0,
        )
    )
    return union(
        select(InventoryLiveStockProjection.product_variant_id).where(
            InventoryLiveStockProjection.company_id == company_id,
            InventoryLiveStockProjection.warehouse_location_id
            == warehouse_location_id,
        ),
        select(InventoryStockPolicy.product_variant_id).where(
            InventoryStockPolicy.company_id == company_id,
            InventoryStockPolicy.location_id == warehouse_location_id,
            InventoryStockPolicy.is_active.is_(True),
        ),
        select(InventoryBalance.product_variant_id).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == warehouse_location_id,
            or_(
                InventoryBalance.on_hand_quantity > 0,
                InventoryBalance.reserved_quantity > 0,
            ),
        ),
        vehicle_variants,
    ).subquery("live_stock_rebuild_candidate_variants")


async def _ensure_company_summary_exact(
    db: AsyncSession,
    *,
    company_id: int,
    state: str,
    rebuilt: bool,
    verified: bool,
) -> int:
    if state not in {"BUILDING", "READY", "DEGRADED"}:
        raise LiveStockProjectionError("Invalid Live Stock projection state.")

    await _acquire_text_guards(
        db,
        [f"live-stock-company-summary:{company_id}"],
        shared=False,
    )
    active_count = int(
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
    summary = await db.scalar(
        select(InventoryLiveStockCompanySummary)
        .where(InventoryLiveStockCompanySummary.company_id == company_id)
        .with_for_update()
    )
    now = utc_now()
    if summary is None:
        summary = InventoryLiveStockCompanySummary(
            company_id=company_id,
            active_variant_count=active_count,
            projection_state=state,
            projection_version=PROJECTION_VERSION,
            revision=1,
            last_rebuilt_at=now if rebuilt else None,
            last_verified_at=now if verified else None,
        )
        db.add(summary)
    else:
        summary.active_variant_count = active_count
        summary.projection_state = state
        summary.projection_version = PROJECTION_VERSION
        summary.revision = int(summary.revision) + 1
        if rebuilt:
            summary.last_rebuilt_at = now
        if verified:
            summary.last_verified_at = now
        summary.updated_at = now
    await db.flush()
    return active_count


async def _set_warehouse_summary_exact(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_location_id: int,
    state: str,
    rebuilt: bool,
    verified: bool,
) -> int:
    if state not in {"BUILDING", "READY", "DEGRADED"}:
        raise LiveStockProjectionError("Invalid Live Stock projection state.")

    await _ensure_warehouse_summaries(
        db,
        company_id=company_id,
        warehouse_ids=[warehouse_location_id],
    )
    summary = await db.scalar(
        select(InventoryLiveStockWarehouseSummary)
        .where(
            InventoryLiveStockWarehouseSummary.company_id == company_id,
            InventoryLiveStockWarehouseSummary.warehouse_location_id
            == warehouse_location_id,
        )
        .with_for_update()
    )
    if summary is None:
        raise LiveStockProjectionError(
            "Live Stock warehouse summary could not be initialized."
        )

    aggregate = (
        await db.execute(
            select(
                func.count(InventoryLiveStockProjection.product_variant_id),
                func.coalesce(
                    func.sum(
                        case(
                            (
                                InventoryLiveStockProjection.is_low_stock.is_(
                                    True
                                ),
                                1,
                            ),
                            else_=0,
                        )
                    ),
                    0,
                ),
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
                ),
            ).where(
                InventoryLiveStockProjection.company_id == company_id,
                InventoryLiveStockProjection.warehouse_location_id
                == warehouse_location_id,
            )
        )
    ).one()
    expected_rows = int(aggregate[0] or 0)
    expected_alerts = int(aggregate[1] or 0)
    expected_nonactive = int(aggregate[2] or 0)
    repaired = int(
        int(summary.projected_row_count) != expected_rows
        or int(summary.alert_count) != expected_alerts
        or int(summary.nonactive_visible_count) != expected_nonactive
    )

    now = utc_now()
    summary.projected_row_count = expected_rows
    summary.alert_count = expected_alerts
    summary.nonactive_visible_count = expected_nonactive
    summary.projection_state = state
    summary.projection_version = PROJECTION_VERSION
    summary.revision = int(summary.revision) + 1
    if rebuilt:
        summary.last_rebuilt_at = now
    if verified:
        summary.last_verified_at = now
    summary.updated_at = now
    await db.flush()
    return repaired


async def _refresh_company_projection_state(
    db: AsyncSession,
    *,
    company_id: int,
    rebuilt: bool = False,
    verified: bool = False,
) -> None:
    active_warehouses = int(
        (
            await db.scalar(
                select(func.count(InventoryLocation.id)).where(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                )
            )
        )
        or 0
    )
    ready_warehouses = int(
        (
            await db.scalar(
                select(
                    func.count(
                        InventoryLiveStockWarehouseSummary.warehouse_location_id
                    )
                )
                .join(
                    InventoryLocation,
                    and_(
                        InventoryLocation.company_id
                        == InventoryLiveStockWarehouseSummary.company_id,
                        InventoryLocation.id
                        == InventoryLiveStockWarehouseSummary.warehouse_location_id,
                        InventoryLocation.location_type == "WAREHOUSE",
                        InventoryLocation.is_active.is_(True),
                    ),
                )
                .where(
                    InventoryLiveStockWarehouseSummary.company_id == company_id,
                    InventoryLiveStockWarehouseSummary.projection_state
                    == "READY",
                    InventoryLiveStockWarehouseSummary.projection_version
                    == PROJECTION_VERSION,
                )
            )
        )
        or 0
    )
    state = "READY" if ready_warehouses == active_warehouses else "BUILDING"
    await _ensure_company_summary_exact(
        db,
        company_id=company_id,
        state=state,
        rebuilt=rebuilt and state == "READY",
        verified=verified and state == "READY",
    )


async def _rebuild_live_stock_warehouse_locked(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_location_id: int,
    batch_size: int,
    computed_for_date: date,
) -> LiveStockWarehouseRebuildReport:
    location = await db.scalar(
        select(InventoryLocation).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id == warehouse_location_id,
            InventoryLocation.location_type == "WAREHOUSE",
        )
    )
    if location is None:
        raise LiveStockProjectionError("Warehouse location does not exist.")
    if not bool(location.is_active):
        raise LiveStockProjectionError(
            "Inactive warehouses cannot be rebuilt; remove their projection instead."
        )

    await _set_warehouse_summary_exact(
        db,
        company_id=company_id,
        warehouse_location_id=warehouse_location_id,
        state="BUILDING",
        rebuilt=False,
        verified=False,
    )

    candidate_source = _warehouse_candidate_variant_query(
        company_id=company_id,
        warehouse_location_id=warehouse_location_id,
    )
    after_variant_id = 0
    candidate_keys = 0
    drifted_keys = 0

    while True:
        variant_ids = [
            int(value)
            for value in (
                await db.execute(
                    select(candidate_source.c.product_variant_id)
                    .where(
                        candidate_source.c.product_variant_id
                        > after_variant_id
                    )
                    .order_by(candidate_source.c.product_variant_id)
                    .limit(batch_size)
                )
            ).scalars().all()
        ]
        if not variant_ids:
            break

        keys = [
            (warehouse_location_id, variant_id)
            for variant_id in variant_ids
        ]
        before = await _projection_snapshot_for_keys(
            db,
            company_id=company_id,
            keys=keys,
        )
        await refresh_live_stock_keys(
            db,
            company_id=company_id,
            keys=keys,
            computed_for_date=computed_for_date,
            _company_guard_held=True,
            _force_coarse_guard=True,
        )
        after = await _projection_snapshot_for_keys(
            db,
            company_id=company_id,
            keys=keys,
        )
        drifted_keys += sum(
            1
            for key in set(before) | set(after)
            if before.get(key) != after.get(key)
        )
        candidate_keys += len(keys)
        after_variant_id = variant_ids[-1]

    summary_repairs = await _set_warehouse_summary_exact(
        db,
        company_id=company_id,
        warehouse_location_id=warehouse_location_id,
        state="READY",
        rebuilt=True,
        verified=True,
    )
    return LiveStockWarehouseRebuildReport(
        company_id=company_id,
        warehouse_location_id=warehouse_location_id,
        candidate_keys=candidate_keys,
        drifted_keys=drifted_keys,
        summary_repairs=summary_repairs,
    )


async def rebuild_live_stock_warehouse(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_location_id: int,
    batch_size: int = _MAX_PROJECTOR_KEYS,
) -> LiveStockWarehouseRebuildReport:
    company_id = _positive_int(company_id, "company_id")
    warehouse_location_id = _positive_int(
        warehouse_location_id,
        "warehouse_location_id",
    )
    if batch_size <= 0 or batch_size > _MAX_PROJECTOR_KEYS:
        raise LiveStockProjectionError("Live Stock rebuild batch size is invalid.")

    await _acquire_company_projection_guard(
        db,
        company_id=company_id,
        exclusive=True,
    )
    computed_for_date = await _company_local_date(db, company_id)
    report = await _rebuild_live_stock_warehouse_locked(
        db,
        company_id=company_id,
        warehouse_location_id=warehouse_location_id,
        batch_size=batch_size,
        computed_for_date=computed_for_date,
    )
    await _refresh_company_projection_state(
        db,
        company_id=company_id,
        rebuilt=False,
        verified=True,
    )
    return report


async def remove_live_stock_warehouse_projection(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_location_id: int,
) -> int:
    company_id = _positive_int(company_id, "company_id")
    warehouse_location_id = _positive_int(
        warehouse_location_id,
        "warehouse_location_id",
    )
    await _acquire_company_projection_guard(
        db,
        company_id=company_id,
        exclusive=True,
    )
    result = await db.execute(
        delete(InventoryLiveStockProjection).where(
            InventoryLiveStockProjection.company_id == company_id,
            InventoryLiveStockProjection.warehouse_location_id
            == warehouse_location_id,
        )
    )
    await db.execute(
        delete(InventoryLiveStockWarehouseSummary).where(
            InventoryLiveStockWarehouseSummary.company_id == company_id,
            InventoryLiveStockWarehouseSummary.warehouse_location_id
            == warehouse_location_id,
        )
    )
    await db.flush()
    await _refresh_company_projection_state(
        db,
        company_id=company_id,
        verified=True,
    )
    return int(result.rowcount or 0)


async def rebuild_live_stock_company(
    db: AsyncSession,
    *,
    company_id: int,
    batch_size: int = _MAX_PROJECTOR_KEYS,
) -> LiveStockCompanyRebuildReport:
    company_id = _positive_int(company_id, "company_id")
    if batch_size <= 0 or batch_size > _MAX_PROJECTOR_KEYS:
        raise LiveStockProjectionError("Live Stock rebuild batch size is invalid.")

    await _acquire_company_projection_guard(
        db,
        company_id=company_id,
        exclusive=True,
    )
    await _ensure_company_summary_exact(
        db,
        company_id=company_id,
        state="BUILDING",
        rebuilt=False,
        verified=False,
    )
    computed_for_date = await _company_local_date(db, company_id)

    active_warehouse_ids = [
        int(value)
        for value in (
            await db.execute(
                select(InventoryLocation.id)
                .where(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                )
                .order_by(InventoryLocation.id)
            )
        ).scalars().all()
    ]
    known_warehouse_ids = {
        int(value)
        for value in (
            await db.execute(
                union(
                    select(
                        InventoryLiveStockWarehouseSummary.warehouse_location_id
                    ).where(
                        InventoryLiveStockWarehouseSummary.company_id
                        == company_id
                    ),
                    select(
                        InventoryLiveStockProjection.warehouse_location_id
                    ).where(
                        InventoryLiveStockProjection.company_id == company_id
                    ),
                )
            )
        ).scalars().all()
    }
    inactive_warehouse_ids = sorted(
        known_warehouse_ids - set(active_warehouse_ids)
    )
    dropped_inactive = 0
    if inactive_warehouse_ids:
        projection_delete = await db.execute(
            delete(InventoryLiveStockProjection).where(
                InventoryLiveStockProjection.company_id == company_id,
                _array_membership(
                    InventoryLiveStockProjection.warehouse_location_id,
                    inactive_warehouse_ids,
                    "live_stock_rebuild_inactive_warehouses",
                ),
            )
        )
        dropped_inactive = int(projection_delete.rowcount or 0)
        await db.execute(
            delete(InventoryLiveStockWarehouseSummary).where(
                InventoryLiveStockWarehouseSummary.company_id == company_id,
                _array_membership(
                    InventoryLiveStockWarehouseSummary.warehouse_location_id,
                    inactive_warehouse_ids,
                    "live_stock_rebuild_inactive_summaries",
                ),
            )
        )
        await db.flush()

    reports: list[LiveStockWarehouseRebuildReport] = []
    for warehouse_id in active_warehouse_ids:
        reports.append(
            await _rebuild_live_stock_warehouse_locked(
                db,
                company_id=company_id,
                warehouse_location_id=warehouse_id,
                batch_size=batch_size,
                computed_for_date=computed_for_date,
            )
        )

    company_before = await db.scalar(
        select(InventoryLiveStockCompanySummary).where(
            InventoryLiveStockCompanySummary.company_id == company_id
        )
    )
    expected_active_count = int(
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
    company_summary_repair = int(
        company_before is None
        or int(company_before.active_variant_count) != expected_active_count
    )
    await _ensure_company_summary_exact(
        db,
        company_id=company_id,
        state="READY",
        rebuilt=True,
        verified=True,
    )

    return LiveStockCompanyRebuildReport(
        company_id=company_id,
        warehouse_count=len(active_warehouse_ids),
        candidate_keys=sum(report.candidate_keys for report in reports),
        drifted_keys=sum(report.drifted_keys for report in reports),
        summary_repairs=(
            company_summary_repair
            + sum(report.summary_repairs for report in reports)
        ),
        dropped_inactive_warehouses=len(inactive_warehouse_ids),
    )


async def reconcile_live_stock_company(
    db: AsyncSession,
    *,
    company_id: int,
    batch_size: int = _MAX_PROJECTOR_KEYS,
) -> LiveStockCompanyRebuildReport:
    return await rebuild_live_stock_company(
        db,
        company_id=company_id,
        batch_size=batch_size,
    )


async def mark_live_stock_projection_degraded(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_location_id: int | None = None,
) -> None:
    company_id = _positive_int(company_id, "company_id")
    await _acquire_company_projection_guard(
        db,
        company_id=company_id,
        exclusive=True,
    )
    await _ensure_company_summary_exact(
        db,
        company_id=company_id,
        state="DEGRADED",
        rebuilt=False,
        verified=False,
    )
    if warehouse_location_id is not None:
        warehouse_location_id = _positive_int(
            warehouse_location_id,
            "warehouse_location_id",
        )
        await _set_warehouse_summary_exact(
            db,
            company_id=company_id,
            warehouse_location_id=warehouse_location_id,
            state="DEGRADED",
            rebuilt=False,
            verified=False,
        )


async def assert_live_stock_projection_ready(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_location_id: int,
) -> None:
    company_id = _positive_int(company_id, "company_id")
    warehouse_location_id = _positive_int(
        warehouse_location_id,
        "warehouse_location_id",
    )
    row = (
        await db.execute(
            select(
                InventoryLiveStockCompanySummary.projection_state,
                InventoryLiveStockCompanySummary.projection_version,
                InventoryLiveStockWarehouseSummary.projection_state,
                InventoryLiveStockWarehouseSummary.projection_version,
            )
            .join(
                InventoryLiveStockWarehouseSummary,
                InventoryLiveStockWarehouseSummary.company_id
                == InventoryLiveStockCompanySummary.company_id,
            )
            .where(
                InventoryLiveStockCompanySummary.company_id == company_id,
                InventoryLiveStockWarehouseSummary.warehouse_location_id
                == warehouse_location_id,
            )
        )
    ).one_or_none()
    if (
        row is None
        or row[0] != "READY"
        or int(row[1]) != PROJECTION_VERSION
        or row[2] != "READY"
        or int(row[3]) != PROJECTION_VERSION
    ):
        raise LiveStockProjectionError(
            "Live Stock projection is not READY for this warehouse."
        )
