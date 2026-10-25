from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from types import SimpleNamespace
from typing import Iterable
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.inventory_rules import batch_sellability_predicate
from domains.uom_authority import UomAuthorityError, load_variant_uom_authorities
from domains.vehicles import (
    read_vehicle_operational_state,
    resolve_vehicle_custody_location_id,
    vehicle_is_operational,
)
from domains.vehicles.contracts import CURRENT_ROUTE_STATUSES, VehicleError
from models import (
    DispatchRoute,
    InventoryBalance,
    InventoryLocation,
    InventoryLock,
    InventoryStockPolicy,
    ProductBatch,
    ProductLocation,
    ProductVariant,
    UOM,
    WorkSession,
)
from product_lifecycle import (
    DEFAULT_PRODUCT_LOCATION_FLAGS,
    ROUTE_LOAD_NEW,
    acquire_product_lifecycle_guards,
    evaluate_product_capability,
    product_capability_predicate,
    product_location_allows,
    record_domain_event,
)
from quantity import canonical_quantity
from services import (
    InventoryMutationError,
    InventoryRuleError,
    acquire_inventory_location_guard,
    allocate_fefo_inventory_batch,
    apply_inventory_movements_batch,
    begin_idempotent_operation,
    complete_idempotent_operation,
    get_company_local_date,
    resolve_inflight_transfer_destination_statuses,
)


_STOCK_STATUSES = frozenset(
    {"AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING"}
)
_MODE_DIRECT = "DIRECT"
_MODE_ROUTE = "ROUTE"
_MODE_SETTLEMENT = "SETTLEMENT_REQUIRED"


@dataclass(frozen=True, slots=True)
class VehicleLoadOwner:
    mode: str
    route_id: int | None = None
    work_session_id: int | None = None


def _error(code: str, message: str, *, status_code: int = 409, **context) -> VehicleError:
    return VehicleError(code, message, status_code=status_code, context=context)


def _encode_cursor(*, scope: str, name: str, row_id: int) -> str:
    payload = json.dumps(
        {"s": scope, "n": name, "i": int(row_id)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, scope: str) -> tuple[str, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
        if payload.get("s") != scope:
            raise ValueError
        name = str(payload["n"])
        row_id = int(payload["i"])
        if row_id <= 0:
            raise ValueError
        return name, row_id
    except Exception as exc:
        raise _error(
            "VEHICLE_LOAD_CURSOR_INVALID",
            "تعذر متابعة النتائج. حدّث القائمة وحاول مجددًا.",
            status_code=400,
        ) from exc


async def _require(access: BackofficeCapabilityAccess, code: str, location_id: int) -> None:
    try:
        await access.require(code, int(location_id))
    except BackofficeCapabilityAccessRejected as exc:
        raise _error(
            "VEHICLE_LOAD_PERMISSION_DENIED",
            "لا تملك الصلاحية المطلوبة على موقع المخزون المحدد.",
            status_code=403,
        ) from exc


async def _vehicle_location(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    require_active: bool = True,
) -> int:
    try:
        return int(
            await resolve_vehicle_custody_location_id(
                db,
                company_id=int(company_id),
                vehicle_id=int(vehicle_id),
                require_active=require_active,
            )
        )
    except VehicleError:
        raise
    except Exception as exc:
        raise _error(
            "VEHICLE_CUSTODY_LOCATION_UNAVAILABLE",
            "موقع مخزون السيارة غير جاهز.",
        ) from exc


async def resolve_vehicle_load_owner(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
) -> VehicleLoadOwner:
    session_row = (
        await db.execute(
            select(
                DispatchRoute.id,
                DispatchRoute.work_session_id,
                WorkSession.end_time,
            )
            .join(
                WorkSession,
                and_(
                    WorkSession.company_id == DispatchRoute.company_id,
                    WorkSession.id == DispatchRoute.work_session_id,
                ),
            )
            .where(
                DispatchRoute.company_id == int(company_id),
                DispatchRoute.vehicle_id == int(vehicle_id),
                WorkSession.inventory_reconciled_at.is_(None),
            )
            .order_by(WorkSession.id.desc())
            .limit(1)
        )
    ).first()
    if session_row is not None:
        if session_row.end_time is not None:
            return VehicleLoadOwner(
                _MODE_SETTLEMENT,
                route_id=int(session_row.id),
                work_session_id=int(session_row.work_session_id),
            )
        return VehicleLoadOwner(
            _MODE_ROUTE,
            route_id=int(session_row.id),
            work_session_id=int(session_row.work_session_id),
        )

    route_id = await db.scalar(
        select(DispatchRoute.id)
        .where(
            DispatchRoute.company_id == int(company_id),
            DispatchRoute.vehicle_id == int(vehicle_id),
            DispatchRoute.status.in_(CURRENT_ROUTE_STATUSES),
        )
        .order_by(DispatchRoute.id.desc())
        .limit(1)
    )
    if route_id is not None:
        return VehicleLoadOwner(_MODE_ROUTE, route_id=int(route_id))
    return VehicleLoadOwner(_MODE_DIRECT)


async def _permission_available(
    access: BackofficeCapabilityAccess,
    code: str,
    location_id: int,
) -> bool:
    try:
        await access.require(code, int(location_id))
        return True
    except BackofficeCapabilityAccessRejected:
        return False


async def _warehouse_exists_with_capability(
    db: AsyncSession,
    *,
    access: BackofficeCapabilityAccess,
    code: str,
) -> bool:
    row = await db.scalar(
        select(InventoryLocation.id)
        .where(
            InventoryLocation.company_id == access.company_id,
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
            access.location_filter(code),
        )
        .order_by(InventoryLocation.id.asc())
        .limit(1)
    )
    return row is not None


async def vehicle_load_snapshot(
    db: AsyncSession,
    *,
    access: BackofficeCapabilityAccess,
    vehicle_id: int,
) -> dict:
    company_id = access.company_id
    vehicle_location_id = await _vehicle_location(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        require_active=True,
    )
    await _require(access, "inventory.read", vehicle_location_id)
    owner = await resolve_vehicle_load_owner(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    )
    vehicle = await read_vehicle_operational_state(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
    )
    operational = vehicle_is_operational(vehicle)

    rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.name,
                ProductVariant.sku,
                ProductVariant.base_uom_id,
                UOM.code.label("base_uom_code"),
                UOM.name.label("base_uom_name"),
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                InventoryBalance.stock_status,
                func.sum(InventoryBalance.on_hand_quantity).label("on_hand"),
                func.sum(InventoryBalance.reserved_quantity).label("reserved"),
            )
            .join(
                InventoryBalance,
                and_(
                    InventoryBalance.company_id == ProductVariant.company_id,
                    InventoryBalance.product_variant_id == ProductVariant.id,
                ),
            )
            .join(UOM, UOM.id == ProductVariant.base_uom_id)
            .where(
                ProductVariant.company_id == company_id,
                InventoryBalance.location_id == vehicle_location_id,
                or_(
                    InventoryBalance.on_hand_quantity > 0,
                    InventoryBalance.reserved_quantity > 0,
                ),
            )
            .group_by(
                ProductVariant.id,
                ProductVariant.name,
                ProductVariant.sku,
                ProductVariant.base_uom_id,
                UOM.code,
                UOM.name,
                ProductVariant.quantity_scale,
                ProductVariant.quantity_step,
                InventoryBalance.stock_status,
            )
            .order_by(ProductVariant.name.asc(), ProductVariant.id.asc(), InventoryBalance.stock_status.asc())
        )
    ).all()

    reserved_present = any(Decimal(row.reserved or 0) > 0 for row in rows)
    can_add = False
    can_unload = False
    if owner.mode == _MODE_DIRECT and not reserved_present:
        can_add = (
            operational
            and await _permission_available(access, "transfer.destination", vehicle_location_id)
            and await _warehouse_exists_with_capability(db, access=access, code="transfer.send")
        )
        can_unload = (
            await _permission_available(access, "transfer.send", vehicle_location_id)
            and await _warehouse_exists_with_capability(db, access=access, code="transfer.destination")
            and any(Decimal(row.on_hand or 0) - Decimal(row.reserved or 0) > 0 for row in rows)
        )

    return {
        "vehicle_id": int(vehicle_id),
        "mode": owner.mode,
        "route_id": owner.route_id,
        "work_session_id": owner.work_session_id,
        "vehicle_operational": bool(operational),
        "can_add": bool(can_add),
        "can_unload": bool(can_unload),
        "items": [
            {
                "product_variant_id": int(row.id),
                "product_name": str(row.name),
                "sku": row.sku,
                "base_uom_id": int(row.base_uom_id),
                "base_uom_code": str(row.base_uom_code),
                "base_uom_name": str(row.base_uom_name),
                "quantity_scale": int(row.quantity_scale),
                "quantity_step": canonical_quantity(row.quantity_step),
                "stock_status": str(row.stock_status),
                "on_hand_quantity": canonical_quantity(row.on_hand or 0),
                "reserved_quantity": canonical_quantity(row.reserved or 0),
                "available_quantity": canonical_quantity(
                    Decimal(row.on_hand or 0) - Decimal(row.reserved or 0)
                ),
            }
            for row in rows
        ],
    }


async def vehicle_load_warehouses(
    db: AsyncSession,
    *,
    access: BackofficeCapabilityAccess,
    vehicle_id: int,
    direction: str,
    search: str | None,
    cursor: str | None,
    limit: int,
) -> dict:
    company_id = access.company_id
    vehicle_location_id = await _vehicle_location(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        require_active=True,
    )
    owner = await resolve_vehicle_load_owner(db, company_id=company_id, vehicle_id=vehicle_id)
    if owner.mode != _MODE_DIRECT:
        raise _error(
            "VEHICLE_LOAD_OWNED_BY_WORKFLOW",
            "حمولة السيارة تُدار حالياً من مسار تشغيلي آخر.",
            route_id=owner.route_id,
            work_session_id=owner.work_session_id,
        )

    normalized_direction = str(direction or "").strip().upper()
    if normalized_direction == "ADD":
        await _require(access, "transfer.destination", vehicle_location_id)
        warehouse_capability = "transfer.send"
    elif normalized_direction == "UNLOAD":
        await _require(access, "transfer.send", vehicle_location_id)
        warehouse_capability = "transfer.destination"
    else:
        raise _error(
            "VEHICLE_LOAD_DIRECTION_INVALID",
            "اتجاه حركة الحمولة غير صالح.",
            status_code=422,
        )

    clean_search = (search or "").strip().lower()
    scope = f"vehicle-load-warehouse|{company_id}|{vehicle_id}|{normalized_direction}|{clean_search}"
    stmt = select(
        InventoryLocation.id,
        InventoryLocation.name,
        InventoryLocation.code,
    ).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.location_type == "WAREHOUSE",
        InventoryLocation.is_active.is_(True),
        access.location_filter(warehouse_capability),
    )
    if clean_search:
        escaped = clean_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                func.lower(InventoryLocation.name).like(pattern, escape="\\"),
                func.lower(InventoryLocation.code).like(pattern, escape="\\"),
            )
        )
    if cursor:
        cursor_name, cursor_id = _decode_cursor(cursor, scope=scope)
        stmt = stmt.where(
            or_(
                InventoryLocation.name > cursor_name,
                and_(InventoryLocation.name == cursor_name, InventoryLocation.id > cursor_id),
            )
        )
    rows = (
        await db.execute(
            stmt.order_by(InventoryLocation.name.asc(), InventoryLocation.id.asc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        next_cursor = _encode_cursor(
            scope=scope,
            name=str(page[-1].name),
            row_id=int(page[-1].id),
        )
    return {
        "items": [
            {"id": int(row.id), "name": str(row.name), "code": str(row.code)}
            for row in page
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


async def vehicle_load_source_inventory(
    db: AsyncSession,
    *,
    access: BackofficeCapabilityAccess,
    vehicle_id: int,
    warehouse_id: int,
    search: str | None,
    cursor: str | None,
    limit: int,
) -> dict:
    company_id = access.company_id
    vehicle_location_id = await _vehicle_location(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        require_active=True,
    )
    owner = await resolve_vehicle_load_owner(db, company_id=company_id, vehicle_id=vehicle_id)
    if owner.mode != _MODE_DIRECT:
        raise _error("VEHICLE_LOAD_OWNED_BY_WORKFLOW", "حمولة السيارة تُدار من مسار تشغيلي آخر.")
    vehicle = await read_vehicle_operational_state(db, company_id=company_id, vehicle_id=vehicle_id)
    if not vehicle_is_operational(vehicle):
        raise _error("VEHICLE_NOT_OPERATIONAL", "السيارة متوقفة أو في الصيانة ولا تقبل حمولة جديدة.")

    await _require(access, "transfer.send", warehouse_id)
    await _require(access, "transfer.destination", vehicle_location_id)
    reserved_total = await db.scalar(
        select(func.coalesce(func.sum(InventoryBalance.reserved_quantity), 0)).where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == int(vehicle_location_id),
            InventoryBalance.reserved_quantity > 0,
        )
    )
    if Decimal(reserved_total or 0) > 0:
        raise _error(
            "VEHICLE_LOAD_PENDING_RESERVATION",
            "يوجد حجز مخزون معلّق على السيارة؛ عالج الحجز أو العهدة قبل تعديل الحمولة.",
        )

    warehouse = await db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id == int(warehouse_id),
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
        )
    )
    if warehouse is None:
        raise _error("VEHICLE_LOAD_WAREHOUSE_NOT_FOUND", "المستودع غير موجود أو غير فعال.", status_code=404)

    as_of_date = await get_company_local_date(db, company_id)
    available = func.sum(InventoryBalance.on_hand_quantity - InventoryBalance.reserved_quantity)
    active_lock = (
        select(InventoryLock.id)
        .where(
            InventoryLock.company_id == company_id,
            InventoryLock.location_id == int(warehouse_id),
            InventoryLock.released_at.is_(None),
            or_(
                InventoryLock.product_variant_id.is_(None),
                and_(
                    InventoryLock.product_variant_id == InventoryBalance.product_variant_id,
                    or_(InventoryLock.batch_id.is_(None), InventoryLock.batch_id == InventoryBalance.batch_id),
                ),
            ),
        )
        .correlate(InventoryBalance)
        .exists()
    )
    sellable = batch_sellability_predicate(
        as_of_date,
        expiry_control_mode=ProductVariant.expiry_control_mode,
        minimum_remaining_shelf_life_days=InventoryStockPolicy.minimum_remaining_shelf_life_days,
    )
    stmt = (
        select(
            ProductVariant.id,
            ProductVariant.name,
            ProductVariant.sku,
            ProductVariant.base_uom_id,
            UOM.code,
            UOM.name.label("uom_name"),
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            available.label("available_quantity"),
        )
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id == ProductVariant.company_id,
                InventoryBalance.product_variant_id == ProductVariant.id,
            ),
        )
        .join(
            ProductBatch,
            and_(
                ProductBatch.company_id == InventoryBalance.company_id,
                ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
                ProductBatch.id == InventoryBalance.batch_id,
            ),
        )
        .join(UOM, UOM.id == ProductVariant.base_uom_id)
        .join(
            ProductLocation,
            and_(
                ProductLocation.company_id == ProductVariant.company_id,
                ProductLocation.location_id == int(warehouse_id),
                ProductLocation.product_variant_id == ProductVariant.id,
            ),
        )
        .outerjoin(
            InventoryStockPolicy,
            and_(
                InventoryStockPolicy.company_id == ProductVariant.company_id,
                InventoryStockPolicy.location_id == int(warehouse_id),
                InventoryStockPolicy.product_variant_id == ProductVariant.id,
                InventoryStockPolicy.is_active.is_(True),
            ),
        )
        .where(
            ProductVariant.company_id == company_id,
            product_capability_predicate(ProductVariant, ROUTE_LOAD_NEW),
            ProductLocation.operational_flags["outbound_enabled"].as_boolean().is_(True),
            InventoryBalance.location_id == int(warehouse_id),
            InventoryBalance.stock_status == "AVAILABLE",
            sellable,
            ~active_lock,
        )
        .group_by(
            ProductVariant.id,
            ProductVariant.name,
            ProductVariant.sku,
            ProductVariant.base_uom_id,
            UOM.code,
            UOM.name,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
        )
        .having(available > 0)
    )
    clean_search = (search or "").strip().lower()
    if clean_search:
        escaped = clean_search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"%{escaped}%"
        stmt = stmt.where(
            or_(
                func.lower(ProductVariant.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(ProductVariant.sku, "")).like(pattern, escape="\\"),
            )
        )
    scope = f"vehicle-load-source|{company_id}|{vehicle_id}|{warehouse_id}|{clean_search}"
    if cursor:
        cursor_name, cursor_id = _decode_cursor(cursor, scope=scope)
        stmt = stmt.where(
            or_(
                ProductVariant.name > cursor_name,
                and_(ProductVariant.name == cursor_name, ProductVariant.id > cursor_id),
            )
        )
    rows = (
        await db.execute(
            stmt.order_by(ProductVariant.name.asc(), ProductVariant.id.asc()).limit(limit + 1)
        )
    ).all()
    has_more = len(rows) > limit
    page = rows[:limit]
    next_cursor = None
    if has_more and page:
        next_cursor = _encode_cursor(scope=scope, name=str(page[-1].name), row_id=int(page[-1].id))
    return {
        "items": [
            {
                "product_variant_id": int(row.id),
                "product_name": str(row.name),
                "sku": row.sku,
                "base_uom_id": int(row.base_uom_id),
                "base_uom_code": str(row.code),
                "base_uom_name": str(row.uom_name),
                "quantity_scale": int(row.quantity_scale),
                "quantity_step": canonical_quantity(row.quantity_step),
                "available_quantity": canonical_quantity(row.available_quantity or 0),
            }
            for row in page
        ],
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


async def _lock_direct_context(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_id: int,
    vehicle_location_id: int,
    warehouse_id: int,
) -> VehicleLoadOwner:
    for location_id in sorted({int(vehicle_location_id), int(warehouse_id)}):
        await acquire_inventory_location_guard(
            db,
            company_id,
            location_id,
            exclusive=True,
        )
    resolved_vehicle_location = await _vehicle_location(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        require_active=True,
    )
    if resolved_vehicle_location != int(vehicle_location_id):
        raise _error("VEHICLE_CUSTODY_CHANGED", "تغير موقع عهدة السيارة أثناء العملية.")
    owner = await resolve_vehicle_load_owner(db, company_id=company_id, vehicle_id=vehicle_id)
    if owner.mode != _MODE_DIRECT:
        raise _error(
            "VEHICLE_LOAD_OWNED_BY_WORKFLOW",
            "أصبحت حمولة السيارة مرتبطة بمسار أو جلسة عمل؛ استخدم مسارها التشغيلي.",
            route_id=owner.route_id,
            work_session_id=owner.work_session_id,
        )
    warehouse = await db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id == int(warehouse_id),
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
        )
    )
    if warehouse is None:
        raise _error("VEHICLE_LOAD_WAREHOUSE_NOT_FOUND", "المستودع غير موجود أو غير فعال.", status_code=404)
    return owner


async def _ensure_unload_product_locations(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_id: int,
    variant_ids: Iterable[int],
    actor_id: int,
    request_id: UUID,
) -> None:
    ids = sorted({int(value) for value in variant_ids})
    if not ids:
        return
    existing = set(
        (
            await db.scalars(
                select(ProductLocation.product_variant_id).where(
                    ProductLocation.company_id == company_id,
                    ProductLocation.location_id == int(warehouse_id),
                    ProductLocation.product_variant_id.in_(ids),
                )
            )
        ).all()
    )
    missing = sorted(set(ids) - {int(value) for value in existing})
    if not missing:
        return
    rows = list(
        (
            await db.execute(
                pg_insert(ProductLocation)
                .values([
                    {
                        "company_id": company_id,
                        "location_id": int(warehouse_id),
                        "product_variant_id": variant_id,
                        "operational_flags": dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                        "created_by": int(actor_id),
                    }
                    for variant_id in missing
                ])
                .on_conflict_do_nothing(constraint="uq_product_location_assignment")
                .returning(ProductLocation.id, ProductLocation.product_variant_id)
            )
        ).all()
    )
    for product_location_id, variant_id in rows:
        record_domain_event(
            db,
            company_id=company_id,
            actor_id=int(actor_id),
            request_id=request_id,
            event_type="ProductLocationAssigned",
            entity_type="ProductLocation",
            entity_id=int(product_location_id),
            reason="AUTO_VEHICLE_UNLOAD_DESTINATION",
            before=None,
            after={
                "id": int(product_location_id),
                "company_id": company_id,
                "location_id": int(warehouse_id),
                "product_variant_id": int(variant_id),
                "operational_flags": dict(DEFAULT_PRODUCT_LOCATION_FLAGS),
                "version": 1,
                "created_by": int(actor_id),
            },
        )


async def _allocate_vehicle_status(
    db: AsyncSession,
    *,
    company_id: int,
    vehicle_location_id: int,
    product_variant_id: int,
    stock_status: str,
    quantity: Decimal,
) -> list[tuple[int, Decimal]]:
    rows = (
        await db.execute(
            select(
                InventoryBalance.batch_id,
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
            )
            .join(
                ProductBatch,
                and_(
                    ProductBatch.company_id == InventoryBalance.company_id,
                    ProductBatch.product_variant_id == InventoryBalance.product_variant_id,
                    ProductBatch.id == InventoryBalance.batch_id,
                ),
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == int(vehicle_location_id),
                InventoryBalance.product_variant_id == int(product_variant_id),
                InventoryBalance.stock_status == stock_status,
                InventoryBalance.on_hand_quantity > InventoryBalance.reserved_quantity,
            )
            .order_by(
                ProductBatch.expiry_date.asc().nulls_last(),
                ProductBatch.id.asc(),
                InventoryBalance.id.asc(),
            )
            .with_for_update()
        )
    ).all()
    remaining = Decimal(quantity)
    allocations: list[tuple[int, Decimal]] = []
    for batch_id, on_hand, reserved in rows:
        free = Decimal(on_hand or 0) - Decimal(reserved or 0)
        if free <= 0:
            continue
        take = min(free, remaining)
        allocations.append((int(batch_id), take))
        remaining -= take
        if remaining == 0:
            break
    if remaining > 0:
        raise _error(
            "VEHICLE_LOAD_INSUFFICIENT_STOCK",
            "رصيد السيارة الحر لا يغطي الكمية المطلوبة.",
            product_variant_id=int(product_variant_id),
            stock_status=stock_status,
            shortage=canonical_quantity(remaining),
        )
    return allocations


def _preserve_or_tighten_unload_status(
    source_status: str,
    current_safe_status: str,
) -> str:
    """Never make Vehicle custody more sellable while unloading it."""
    source = str(source_status or "").strip().upper()
    safe = str(current_safe_status or "").strip().upper()
    if source in {"DAMAGED", "DISPOSAL_PENDING"}:
        return source
    if safe == "RECALLED" or source == "RECALLED":
        return "RECALLED"
    if safe == "BLOCKED" or source == "BLOCKED":
        return "BLOCKED"
    if safe == "QUARANTINED" or source == "QUARANTINED":
        return "QUARANTINED"
    return "AVAILABLE"


async def _safe_unload_terminal_statuses(
    db: AsyncSession,
    *,
    company_id: int,
    warehouse_id: int,
    allocations: list[dict],
) -> dict[int, str]:
    """Reuse the canonical in-flight safety resolver for direct Vehicle cleanup.

    Direct Vehicle unload has no TransferHeader/Line document, so we provide the
    resolver only the immutable-shaped evidence it requires. Creation evidence
    is the current locked Product lifecycle revision: the operation starts and
    finishes in this same transaction, while the resolver owns Batch/shelf-life
    and current safety precedence.
    """
    if not allocations:
        return {}

    variant_ids = sorted({
        int(item["product_variant_id"])
        for item in allocations
    })
    variant_rows = (
        await db.execute(
            select(
                ProductVariant.id,
                ProductVariant.lifecycle_status,
                ProductVariant.operational_hold,
                ProductVariant.lifecycle_revision,
            ).where(
                ProductVariant.company_id == int(company_id),
                ProductVariant.id.in_(variant_ids),
            )
        )
    ).all()
    variants = {int(row.id): row for row in variant_rows}
    if set(variants) != set(variant_ids):
        raise _error(
            "VEHICLE_LOAD_PRODUCT_NOT_FOUND",
            "أحد أصناف عهدة السيارة لم يعد موجوداً داخل الشركة.",
            status_code=409,
        )

    lines = []
    for index, item in enumerate(allocations, start=1):
        variant = variants[int(item["product_variant_id"])]
        lines.append(SimpleNamespace(
            id=index,
            product_variant_id=int(item["product_variant_id"]),
            batch_id=int(item["batch_id"]),
            source_stock_status=str(item["stock_status"]),
            lifecycle_revision_snapshot=int(variant.lifecycle_revision),
            lifecycle_status_snapshot=str(variant.lifecycle_status),
            operational_hold_snapshot=str(variant.operational_hold),
        ))

    resolved = await resolve_inflight_transfer_destination_statuses(
        db,
        company_id=int(company_id),
        destination_location_id=int(warehouse_id),
        transfer_purpose="WAREHOUSE_BALANCING",
        lines=lines,
    )
    return {
        index: _preserve_or_tighten_unload_status(
            str(allocations[index - 1]["stock_status"]),
            resolved[index],
        )
        for index in resolved
    }


def _request_hash(*, vehicle_id: int, warehouse_id: int, direction: str, items: list[dict]) -> str:
    body = {
        "vehicle_id": int(vehicle_id),
        "warehouse_id": int(warehouse_id),
        "direction": direction,
        "items": sorted(
            [
                {
                    "product_variant_id": int(item["product_variant_id"]),
                    "stock_status": item.get("stock_status"),
                    "quantity": canonical_quantity(item["quantity"]),
                }
                for item in items
            ],
            key=lambda row: (row["product_variant_id"], row["stock_status"] or ""),
        ),
    }
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


async def mutate_vehicle_load(
    db: AsyncSession,
    *,
    access: BackofficeCapabilityAccess,
    actor_id: int,
    vehicle_id: int,
    warehouse_id: int,
    direction: str,
    request_id: UUID,
    items: list[dict],
) -> dict:
    if not items:
        raise _error("VEHICLE_LOAD_ITEMS_REQUIRED", "أضف صنفاً واحداً على الأقل.", status_code=422)
    normalized_direction = str(direction or "").strip().upper()
    if normalized_direction not in {"ADD", "UNLOAD"}:
        raise _error("VEHICLE_LOAD_DIRECTION_INVALID", "اتجاه حركة الحمولة غير صالح.", status_code=422)

    company_id = access.company_id
    vehicle_location_id = await _vehicle_location(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        require_active=True,
    )
    if normalized_direction == "ADD":
        await _require(access, "transfer.send", warehouse_id)
        await _require(access, "transfer.destination", vehicle_location_id)
    else:
        await _require(access, "transfer.send", vehicle_location_id)
        await _require(access, "transfer.destination", warehouse_id)

    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=int(actor_id),
            operation=f"VEHICLE_LOAD_{normalized_direction}",
            request_id=str(request_id),
            request_hash=_request_hash(
                vehicle_id=vehicle_id,
                warehouse_id=warehouse_id,
                direction=normalized_direction,
                items=items,
            ),
        )
    except InventoryMutationError as exc:
        raise _error(
            "VEHICLE_LOAD_IDEMPOTENCY_CONFLICT",
            str(exc),
        ) from exc
    if replay is not None:
        await db.rollback()
        return replay

    await _lock_direct_context(
        db,
        company_id=company_id,
        vehicle_id=vehicle_id,
        vehicle_location_id=vehicle_location_id,
        warehouse_id=warehouse_id,
    )

    ids = sorted({int(item["product_variant_id"]) for item in items})
    try:
        authorities = await load_variant_uom_authorities(
            db,
            company_id=company_id,
            variant_ids=ids,
        )
    except UomAuthorityError as exc:
        raise _error(
            exc.code,
            exc.message,
            status_code=422,
            **exc.context,
        ) from exc
    normalized_items = []
    seen = set()
    for item in items:
        variant_id = int(item["product_variant_id"])
        status = str(item.get("stock_status") or "AVAILABLE").upper()
        if status not in _STOCK_STATUSES:
            raise _error("VEHICLE_LOAD_STOCK_STATUS_INVALID", "حالة المخزون غير صالحة.", status_code=422)
        if normalized_direction == "ADD" and status != "AVAILABLE":
            raise _error("VEHICLE_LOAD_ADD_STATUS_INVALID", "إضافة الحمولة تقبل المخزون الصالح فقط.", status_code=422)
        key = (variant_id, status)
        if key in seen:
            raise _error("VEHICLE_LOAD_DUPLICATE_ITEM", "لا تكرر نفس الصنف والحالة في الطلب.", status_code=422)
        seen.add(key)
        try:
            quantity = authorities[variant_id].validate_canonical_total(
                Decimal(item["quantity"]),
                field_name="quantity",
            )
        except (UomAuthorityError, KeyError, ValueError) as exc:
            raise _error("VEHICLE_LOAD_QUANTITY_INVALID", "الكمية المطلوبة غير صالحة.", status_code=422) from exc
        if quantity <= 0:
            raise _error("VEHICLE_LOAD_QUANTITY_INVALID", "الكمية يجب أن تكون أكبر من صفر.", status_code=422)
        normalized_items.append(
            {"product_variant_id": variant_id, "stock_status": status, "quantity": quantity}
        )

    if normalized_direction == "ADD":
        vehicle = await read_vehicle_operational_state(
            db, company_id=company_id, vehicle_id=vehicle_id
        )
        if not vehicle_is_operational(vehicle):
            raise _error("VEHICLE_NOT_OPERATIONAL", "السيارة متوقفة أو في الصيانة ولا تقبل حمولة جديدة.")
        await acquire_product_lifecycle_guards(db, company_id, ids, exclusive=False)
        variants = list(
            (
                await db.scalars(
                    select(ProductVariant).where(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(ids),
                    )
                )
            ).all()
        )
        variant_map = {int(row.id): row for row in variants}
        assignments = {
            int(row.product_variant_id): row
            for row in (
                await db.scalars(
                    select(ProductLocation).where(
                        ProductLocation.company_id == company_id,
                        ProductLocation.location_id == int(warehouse_id),
                        ProductLocation.product_variant_id.in_(ids),
                    )
                )
            ).all()
        }
        for variant_id in ids:
            variant = variant_map.get(variant_id)
            if variant is None:
                raise _error("VEHICLE_LOAD_PRODUCT_NOT_FOUND", "أحد الأصناف غير موجود.", status_code=404)
            capability = evaluate_product_capability(
                variant.lifecycle_status,
                variant.operational_hold,
                ROUTE_LOAD_NEW,
            )
            if not capability.allowed:
                raise _error(capability.code, "لا يمكن تحميل الصنف في حالته الحالية.")
            if not product_location_allows(
                getattr(assignments.get(variant_id), "operational_flags", None),
                ROUTE_LOAD_NEW,
            ):
                raise _error(
                    "PRODUCT_LOCATION_REQUIRED",
                    "الصنف غير مهيأ للصرف من المستودع المصدر.",
                    product_variant_id=variant_id,
                    warehouse_id=int(warehouse_id),
                )
        as_of = await get_company_local_date(db, company_id)
        allocations = await allocate_fefo_inventory_batch(
            db,
            company_id=company_id,
            location_id=int(warehouse_id),
            requests={item["product_variant_id"]: item["quantity"] for item in normalized_items},
            as_of_date=as_of,
            require_full=True,
        )
        specs = []
        for item in normalized_items:
            variant_id = item["product_variant_id"]
            for index, (batch_id, qty) in enumerate(allocations.get(variant_id, [])):
                specs.append(
                    {
                        "product_variant_id": variant_id,
                        "batch_id": int(batch_id),
                        "quantity": qty,
                        "movement_kind": "PHYSICAL",
                        "reference_type": "VEHICLE_LOAD_DIRECT",
                        "reference_id": str(request_id),
                        "idempotency_key": f"VLOAD-{request_id}-{variant_id}-{batch_id}-{index}",
                        "source_location_id": int(warehouse_id),
                        "destination_location_id": int(vehicle_location_id),
                        "source_stock_status": "AVAILABLE",
                        "destination_stock_status": "AVAILABLE",
                        "work_session_id": None,
                        "notes": f"تحميل مباشر لسيارة {vehicle_id} بدون خط تشغيلي نشط.",
                    }
                )
    else:
        await _ensure_unload_product_locations(
            db,
            company_id=company_id,
            warehouse_id=int(warehouse_id),
            variant_ids=ids,
            actor_id=int(actor_id),
            request_id=request_id,
        )
        allocated_rows: list[dict] = []
        for item in normalized_items:
            allocations = await _allocate_vehicle_status(
                db,
                company_id=company_id,
                vehicle_location_id=vehicle_location_id,
                product_variant_id=item["product_variant_id"],
                stock_status=item["stock_status"],
                quantity=item["quantity"],
            )
            for batch_id, qty in allocations:
                allocated_rows.append({
                    "product_variant_id": item["product_variant_id"],
                    "batch_id": int(batch_id),
                    "quantity": qty,
                    "stock_status": item["stock_status"],
                })

        safe_statuses = await _safe_unload_terminal_statuses(
            db,
            company_id=company_id,
            warehouse_id=int(warehouse_id),
            allocations=allocated_rows,
        )
        specs = []
        for index, row in enumerate(allocated_rows, start=1):
            source_status = str(row["stock_status"])
            final_status = safe_statuses[index]
            movement_key = (
                f"VUNLOAD-{request_id}-{row['product_variant_id']}-"
                f"{source_status}-{row['batch_id']}-{index}"
            )
            specs.append(
                {
                    "product_variant_id": row["product_variant_id"],
                    "batch_id": row["batch_id"],
                    "quantity": row["quantity"],
                    "movement_kind": "PHYSICAL",
                    "reference_type": "VEHICLE_UNLOAD_DIRECT",
                    "reference_id": str(request_id),
                    "idempotency_key": movement_key,
                    "source_location_id": int(vehicle_location_id),
                    "destination_location_id": int(warehouse_id),
                    "source_stock_status": source_status,
                    "destination_stock_status": source_status,
                    "work_session_id": None,
                    "notes": (
                        f"تفريغ مباشر من سيارة {vehicle_id} "
                        f"إلى مستودع {warehouse_id}."
                    ),
                }
            )
            if final_status != source_status:
                specs.append(
                    {
                        "product_variant_id": row["product_variant_id"],
                        "batch_id": row["batch_id"],
                        "quantity": row["quantity"],
                        "movement_kind": "STATUS_CHANGE",
                        "reference_type": "VEHICLE_UNLOAD_SAFE_STATUS",
                        "reference_id": str(request_id),
                        "idempotency_key": f"{movement_key}-STATUS",
                        "source_location_id": int(warehouse_id),
                        "destination_location_id": int(warehouse_id),
                        "source_stock_status": source_status,
                        "destination_stock_status": final_status,
                        "work_session_id": None,
                        "notes": (
                            "Vehicle unload safety status: "
                            f"{source_status}->{final_status}"
                        ),
                    }
                )

    if not specs:
        raise _error("VEHICLE_LOAD_NO_MOVEMENT", "لم ينتج عن الطلب أي حركة مخزون.", status_code=422)
    try:
        movements = await apply_inventory_movements_batch(
            db,
            company_id=company_id,
            performed_by=int(actor_id),
            movements=specs,
        )
    except (InventoryMutationError, InventoryRuleError) as exc:
        raise _error(
            getattr(exc, "code", "VEHICLE_LOAD_INVENTORY_CONFLICT"),
            getattr(exc, "message", str(exc)),
        ) from exc

    response = {
        "vehicle_id": int(vehicle_id),
        "warehouse_id": int(warehouse_id),
        "direction": normalized_direction,
        "movement_count": len(movements),
        "message": (
            "تمت إضافة الحمولة إلى السيارة."
            if normalized_direction == "ADD"
            else "تم تفريغ الحمولة إلى المستودع."
        ),
    }
    complete_idempotent_operation(idem, response)
    await db.commit()
    return response
