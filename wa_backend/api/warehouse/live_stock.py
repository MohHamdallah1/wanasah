from decimal import Decimal
import logging
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased
from sqlalchemy import Date, Integer, String, and_, bindparam, case, func, or_, select, true, tuple_, union, union_all

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import (
    Company,
    DispatchRoute,
    Driver,
    InventoryBalance,
    InventoryCostEvent,
    InventoryCostState,
    InventoryLiveStockProjection,
    InventoryLocation,
    InventoryStockPolicy,
    Product,
    ProductBatch,
    ProductUomConversion,
    ProductVariant,
    UOM,
)
from quantity import canonical_quantity
from services import (
    batch_sellability_predicate,
    inventory_business_error,
)
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    assert_live_stock_projection_ready,
)
from schemas import (
    WarehouseInventoryAlertSummaryResponse,
    WarehouseInventoryBatchDetailResponse,
    WarehouseInventoryCursorPage,
    WarehouseInventorySummaryResponse,
)

from ._shared import (
    _decode_batch_cursor,
    _decode_variant_cursor,
    _encode_batch_cursor,
    _encode_variant_cursor,
    _escape_like,
    _warehouse_array_membership,
)


logger = logging.getLogger("wanasah_logger")
router = APIRouter()


# =================================================================================
# 2. إشعارات النواقص (Threshold Alerts - Reorder Point)
# =================================================================================
# Legacy unbounded /warehouse/alerts removed; alert metadata now comes from inventory cursor.


# =================================================================================
# 3. جلب حالة المستودع بالكامل من المحرك الموحد
# =================================================================================

# التحقق من جاهزية read model الخاص بالرصيد الحي قبل تنفيذ القراءة.
async def _require_live_stock_read_model_ready(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
):
    try:
        return await assert_live_stock_projection_ready(
            db,
            company_id=company_id,
            warehouse_location_id=location_id,
        )
    except LiveStockProjectionError as exc:
        if "active warehouse" in str(exc):
            exists = await db.scalar(
                select(InventoryLocation.id).where(
                    InventoryLocation.company_id == company_id,
                    InventoryLocation.id == location_id,
                    InventoryLocation.location_type == "WAREHOUSE",
                    InventoryLocation.is_active.is_(True),
                )
            )
            if exists is None:
                raise HTTPException(
                    status_code=404,
                    detail="المستودع غير موجود أو لا يتبع شركتك.",
                ) from exc
        raise HTTPException(
            status_code=503,
            detail=inventory_business_error(
                "LIVE_STOCK_PROJECTION_NOT_READY",
                "الرصيد الحي قيد التحديث. أعد المحاولة بعد لحظات.",
            ),
        ) from exc


# بناء استعلام فرعي لمواقع المركبات المقروءة ضمن صلاحيات المستخدم.
def _readable_vehicle_locations_subquery(
    *,
    company_id: int,
    access: InventoryAccess,
):
    return (
        select(InventoryLocation.id, InventoryLocation.vehicle_id)
        .where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.location_type == "VEHICLE",
            InventoryLocation.is_active.is_(True),
            InventoryLocation.vehicle_id.isnot(None),
            access.location_filter("inventory.read"),
        )
        .subquery("readable_vehicle_locations")
    )


# تحديد أحدث مستودع مصدر لكل مركبة مقروءة لاستخدامه في الرصيد الحي.
def _latest_readable_vehicle_sources_subquery(
    *,
    company_id: int,
    readable_vehicle_locations,
):
    return (
        select(DispatchRoute.vehicle_id, DispatchRoute.source_location_id)
        .where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.vehicle_id.in_(
                select(readable_vehicle_locations.c.vehicle_id)
            ),
        )
        .distinct(DispatchRoute.vehicle_id)
        .order_by(DispatchRoute.vehicle_id, DispatchRoute.id.desc())
        .subquery("latest_readable_vehicle_sources")
    )


# التحقق من صلاحية قراءة الرصيد الحي للمستودع المحدد مع الحفاظ على عزل الشركة.
async def _require_live_stock_warehouse_read(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    access: InventoryAccess,
    actor: Driver,
) -> bool:
    """Validate inventory.read authority for the selected warehouse.

    Company admins need no separate location SQL on the success path because
    the readiness query already joins the active warehouse. Restricted actors
    keep explicit location + permission checks to preserve authorization.
    """
    if bool(actor.is_admin):
        return True

    location_exists = await db.scalar(
        select(InventoryLocation.id).where(
            InventoryLocation.company_id == company_id,
            InventoryLocation.id == location_id,
            InventoryLocation.location_type == "WAREHOUSE",
            InventoryLocation.is_active.is_(True),
        )
    )
    if location_exists is None:
        raise HTTPException(
            status_code=404,
            detail="المستودع غير موجود أو لا يتبع شركتك.",
        )

    permission_row = (
        await db.execute(
            select(
                access.allows(
                    "inventory.read",
                    location_id,
                ).label("location_allowed"),
                access.allows(
                    "inventory.read",
                ).label("company_wide_allowed"),
            )
        )
    ).one()
    if not bool(permission_row.location_allowed):
        raise HTTPException(
            status_code=403,
            detail="لا تملك صلاحية تنفيذ هذه العملية ضمن الموقع المحدد.",
        )
    return bool(permission_row.company_wide_allowed)


# تحديد ترتيب نتائج الرصيد الحي حسب خيار الفرز المطلوب.
def _live_stock_ordering(*, sort: str):
    if sort == "name_desc":
        return (
            ProductVariant.name.desc(),
            ProductVariant.id.desc(),
        )
    return (
        ProductVariant.name.asc(),
        ProductVariant.id.asc(),
    )


# بناء استعلام المرشحين المرئيين في الرصيد الحي حسب الصلاحيات وحضور المخزون.
def _build_visible_inventory_stmt(
    *, company_id: int, location_id: int, access: InventoryAccess,
    company_wide_inventory_read: bool,
    candidate_filters=(), limit: Optional[int] = None,
    sort: str = "name_asc",
):
    """Exact Live Stock visibility with projection-backed warehouse presence."""
    extra_candidate_filters = tuple(candidate_filters)
    candidate_filters = [
        ProductVariant.company_id == company_id,
        *extra_candidate_filters,
    ]
    ordering = _live_stock_ordering(sort=sort) if limit is not None else ()
    descending = sort == "name_desc"

    if company_wide_inventory_read and not extra_candidate_filters:
        stream_limit = limit + 1 if limit is not None else None
        active_stream = (
            select(
                ProductVariant.id.label("id"),
                ProductVariant.name.label("variant_name"),
            )
            .where(
                ProductVariant.company_id == company_id,
                ProductVariant.lifecycle_status == "ACTIVE",
            )
            .order_by(*ordering)
            .limit(stream_limit)
        )
        projection_order = (
            (
                InventoryLiveStockProjection.variant_name.desc(),
                InventoryLiveStockProjection.product_variant_id.desc(),
            )
            if descending
            else (
                InventoryLiveStockProjection.variant_name.asc(),
                InventoryLiveStockProjection.product_variant_id.asc(),
            )
        )
        nonactive_stream = (
            select(
                InventoryLiveStockProjection.product_variant_id.label("id"),
                InventoryLiveStockProjection.variant_name.label(
                    "variant_name"
                ),
            )
            .where(
                InventoryLiveStockProjection.company_id == company_id,
                InventoryLiveStockProjection.warehouse_location_id
                == location_id,
                InventoryLiveStockProjection.lifecycle_status != "ACTIVE",
                or_(
                    InventoryLiveStockProjection.has_warehouse_presence.is_(
                        True
                    ),
                    InventoryLiveStockProjection.has_vehicle_presence.is_(
                        True
                    ),
                ),
            )
            .order_by(*projection_order)
            .limit(stream_limit)
        )
        merged = union_all(
            active_stream,
            nonactive_stream,
        ).subquery("visible_inventory_fast_candidates")
        merged_order = (
            (merged.c.variant_name.desc(), merged.c.id.desc())
            if descending
            else (merged.c.variant_name.asc(), merged.c.id.asc())
        )
        return (
            select(merged.c.id, merged.c.variant_name)
            .order_by(*merged_order)
            .limit(stream_limit)
        )

    if company_wide_inventory_read:
        return (
            select(
                ProductVariant.id,
                ProductVariant.name.label("variant_name"),
            )
            .outerjoin(
                InventoryLiveStockProjection,
                and_(
                    InventoryLiveStockProjection.company_id
                    == ProductVariant.company_id,
                    InventoryLiveStockProjection.product_variant_id
                    == ProductVariant.id,
                    InventoryLiveStockProjection.warehouse_location_id
                    == location_id,
                ),
            )
            .where(
                *candidate_filters,
                or_(
                    ProductVariant.lifecycle_status == "ACTIVE",
                    InventoryLiveStockProjection.has_warehouse_presence.is_(
                        True
                    ),
                    InventoryLiveStockProjection.has_vehicle_presence.is_(
                        True
                    ),
                ),
            )
            .order_by(*ordering)
            .limit(limit + 1 if limit is not None else None)
        )

    active_candidates = (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .where(
            *candidate_filters,
            ProductVariant.lifecycle_status == "ACTIVE",
        )
        .order_by(*ordering)
        .limit(limit + 1 if limit is not None else None)
    )

    warehouse_candidates = (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .join(
            InventoryLiveStockProjection,
            and_(
                InventoryLiveStockProjection.company_id
                == ProductVariant.company_id,
                InventoryLiveStockProjection.product_variant_id
                == ProductVariant.id,
                InventoryLiveStockProjection.warehouse_location_id
                == location_id,
            ),
        )
        .where(
            *candidate_filters,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
            InventoryLiveStockProjection.has_warehouse_presence.is_(True),
        )
        .order_by(*ordering)
        .limit(limit + 1 if limit is not None else None)
    )

    readable_vehicle_locations = _readable_vehicle_locations_subquery(
        company_id=company_id,
        access=access,
    )
    latest_vehicle_sources = _latest_readable_vehicle_sources_subquery(
        company_id=company_id,
        readable_vehicle_locations=readable_vehicle_locations,
    )
    vehicle_candidates = (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .join(
            InventoryBalance,
            and_(
                InventoryBalance.company_id == company_id,
                InventoryBalance.product_variant_id == ProductVariant.id,
                InventoryBalance.stock_status != "DAMAGED",
                InventoryBalance.on_hand_quantity > 0,
            ),
        )
        .join(
            readable_vehicle_locations,
            readable_vehicle_locations.c.id
            == InventoryBalance.location_id,
        )
        .join(
            latest_vehicle_sources,
            and_(
                latest_vehicle_sources.c.vehicle_id
                == readable_vehicle_locations.c.vehicle_id,
                latest_vehicle_sources.c.source_location_id == location_id,
            ),
        )
        .where(
            *candidate_filters,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
        )
        .distinct()
        .order_by(*ordering)
        .limit(limit + 1 if limit is not None else None)
    )

    visible_candidates = union(
        active_candidates,
        warehouse_candidates,
        vehicle_candidates,
    ).subquery("visible_inventory_candidates")
    visible_order = (
        (
            visible_candidates.c.variant_name.desc(),
            visible_candidates.c.id.desc(),
        )
        if descending
        else (
            visible_candidates.c.variant_name.asc(),
            visible_candidates.c.id.asc(),
        )
    )
    return (
        select(
            visible_candidates.c.id,
            visible_candidates.c.variant_name,
        )
        .order_by(*visible_order)
        .limit(limit + 1 if limit is not None else None)
    )


# بناء استعلام المنتجات التي تحقق شروط تنبيه الحد الأدنى للمخزون.
def _build_inventory_alert_variants_stmt(
    *,
    company_id: int,
    location_id: int,
    variant_filters=(),
):
    return (
        select(
            ProductVariant.id,
            ProductVariant.name.label("variant_name"),
        )
        .join(
            InventoryLiveStockProjection,
            and_(
                InventoryLiveStockProjection.company_id
                == ProductVariant.company_id,
                InventoryLiveStockProjection.product_variant_id
                == ProductVariant.id,
                InventoryLiveStockProjection.warehouse_location_id
                == location_id,
            ),
        )
        .where(
            ProductVariant.company_id == company_id,
            InventoryLiveStockProjection.is_low_stock.is_(True),
            *variant_filters,
        )
    )


# بناء استعلام معرفات المنتجات بعد تطبيق فلاتر الرصيد الحي.
def _live_stock_filtered_variant_ids_stmt(
    *,
    company_id: int,
    location_id: int,
    access: InventoryAccess,
    company_wide_inventory_read: bool,
    stock_state: str,
    has_reserved: bool,
    has_unavailable: bool,
    has_damaged: bool,
    has_recalled: bool,
    has_vehicle: bool,
    minimum_unset: bool,
):
    variant = aliased(ProductVariant, name="live_stock_filter_variant")
    projection = aliased(
        InventoryLiveStockProjection,
        name="live_stock_filter_projection",
    )

    projected_on_hand = func.coalesce(projection.warehouse_on_hand, 0)
    projected_reserved = func.coalesce(projection.warehouse_reserved, 0)
    projected_sellable_on_hand = func.coalesce(
        projection.warehouse_sellable_on_hand, 0
    )
    projected_sellable_reserved = func.coalesce(
        projection.warehouse_sellable_reserved, 0
    )
    projected_blocked = func.coalesce(projection.blocked_status_packs, 0)
    projected_damaged = func.coalesce(projection.damaged_packs, 0)
    projected_recalled = func.coalesce(projection.recalled_packs, 0)

    effective_sellable = case(
        (
            and_(
                variant.lifecycle_status == "ACTIVE",
                variant.operational_hold == "NONE",
            ),
            projected_sellable_on_hand - projected_sellable_reserved,
        ),
        else_=0,
    )
    warehouse_total = (
        projected_on_hand + projected_blocked + projected_damaged
    )
    unavailable = (
        warehouse_total - projected_reserved - effective_sellable
    )

    conditions = []
    if stock_state == "on_hand":
        conditions.append(warehouse_total > 0)
    elif stock_state == "sellable":
        conditions.append(effective_sellable > 0)
    elif stock_state == "out_of_stock":
        conditions.append(effective_sellable <= 0)
    elif stock_state == "low_stock":
        conditions.append(projection.is_low_stock.is_(True))

    if has_reserved:
        conditions.append(projected_reserved > 0)
    if has_unavailable:
        conditions.append(unavailable > 0)
    if has_damaged:
        conditions.append(projected_damaged > 0)
    if has_recalled:
        conditions.append(projected_recalled > 0)
    if minimum_unset:
        conditions.append(func.coalesce(projection.minimum_quantity, 0) == 0)

    if has_vehicle:
        if company_wide_inventory_read:
            conditions.append(func.coalesce(projection.vehicle_packs, 0) > 0)
        else:
            readable_vehicle_locations = _readable_vehicle_locations_subquery(
                company_id=company_id,
                access=access,
            )
            latest_vehicle_sources = _latest_readable_vehicle_sources_subquery(
                company_id=company_id,
                readable_vehicle_locations=readable_vehicle_locations,
            )
            readable_vehicle_variants = (
                select(InventoryBalance.product_variant_id)
                .join(
                    readable_vehicle_locations,
                    readable_vehicle_locations.c.id
                    == InventoryBalance.location_id,
                )
                .join(
                    latest_vehicle_sources,
                    and_(
                        latest_vehicle_sources.c.vehicle_id
                        == readable_vehicle_locations.c.vehicle_id,
                        latest_vehicle_sources.c.source_location_id
                        == location_id,
                    ),
                )
                .where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.stock_status != "DAMAGED",
                    InventoryBalance.on_hand_quantity > 0,
                )
                .distinct()
            )
            conditions.append(variant.id.in_(readable_vehicle_variants))

    return (
        select(variant.id)
        .outerjoin(
            projection,
            and_(
                projection.company_id == variant.company_id,
                projection.product_variant_id == variant.id,
                projection.warehouse_location_id == location_id,
            ),
        )
        .where(
            variant.company_id == company_id,
            *conditions,
        )
        .correlate(None)
    )


# جلب ملخص تنبيهات الحد الأدنى للمخزون للمستودع المحدد.
@router.get(
    "/warehouse/inventory/alerts/summary",
    response_model=WarehouseInventoryAlertSummaryResponse,
    status_code=200,
)
async def get_warehouse_inventory_alert_summary(
    location_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id
    await _require_live_stock_warehouse_read(
        db,
        company_id=company_id,
        location_id=location_id,
        access=access,
        actor=current_admin,
    )

    readiness = await _require_live_stock_read_model_ready(
        db,
        company_id=company_id,
        location_id=location_id,
    )
    return {"alert_count": int(readiness.alert_count)}


# جلب ملخص كميات الرصيد الحي للمستودع المحدد.
@router.get("/warehouse/inventory/summary", response_model=WarehouseInventorySummaryResponse)
async def get_warehouse_inventory_summary(
    location_id: int,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id
    company_wide_inventory_read = (
        await _require_live_stock_warehouse_read(
            db,
            company_id=company_id,
            location_id=location_id,
            access=access,
            actor=current_admin,
        )
    )

    readiness = await _require_live_stock_read_model_ready(
        db,
        company_id=company_id,
        location_id=location_id,
    )
    active_count = int(readiness.active_variant_count)
    alert_count = int(readiness.alert_count)

    if company_wide_inventory_read:
        return {
            "stock_total": (
                active_count
                + int(readiness.nonactive_visible_count)
            ),
            "alert_count": alert_count,
        }

    # Restricted actors must not inherit vehicle presence from vehicles they
    # cannot read. Warehouse presence is projection-backed; vehicle-only
    # visibility remains permission-aware and the UNION removes overlap.
    warehouse_nonactive = (
        select(InventoryLiveStockProjection.product_variant_id.label("id"))
        .join(
            ProductVariant,
            and_(
                ProductVariant.company_id
                == InventoryLiveStockProjection.company_id,
                ProductVariant.id
                == InventoryLiveStockProjection.product_variant_id,
            ),
        )
        .where(
            InventoryLiveStockProjection.company_id == company_id,
            InventoryLiveStockProjection.warehouse_location_id
            == location_id,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
            InventoryLiveStockProjection.has_warehouse_presence.is_(True),
        )
    )

    readable_vehicle_locations = _readable_vehicle_locations_subquery(
        company_id=company_id,
        access=access,
    )
    latest_vehicle_sources = _latest_readable_vehicle_sources_subquery(
        company_id=company_id,
        readable_vehicle_locations=readable_vehicle_locations,
    )
    readable_vehicle_nonactive = (
        select(InventoryBalance.product_variant_id.label("id"))
        .join(
            ProductVariant,
            and_(
                ProductVariant.company_id == InventoryBalance.company_id,
                ProductVariant.id == InventoryBalance.product_variant_id,
            ),
        )
        .join(
            readable_vehicle_locations,
            readable_vehicle_locations.c.id == InventoryBalance.location_id,
        )
        .join(
            latest_vehicle_sources,
            and_(
                latest_vehicle_sources.c.vehicle_id
                == readable_vehicle_locations.c.vehicle_id,
                latest_vehicle_sources.c.source_location_id == location_id,
            ),
        )
        .where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.stock_status != "DAMAGED",
            InventoryBalance.on_hand_quantity > 0,
            ProductVariant.lifecycle_status.is_distinct_from("ACTIVE"),
        )
        .distinct()
    )
    nonactive_visible = union(
        warehouse_nonactive,
        readable_vehicle_nonactive,
    ).subquery("restricted_nonactive_visible")
    nonactive_count = int(
        (
            await db.scalar(
                select(func.count()).select_from(nonactive_visible)
            )
        )
        or 0
    )

    return {
        "stock_total": active_count + nonactive_count,
        "alert_count": alert_count,
    }


# جلب عائلات المنتجات المتاحة لفلترة الرصيد الحي.
@router.get(
    "/warehouse/inventory/families",
    status_code=200,
)
async def get_warehouse_inventory_families(
    location_id: int,
    search: Optional[str] = Query(default=None, max_length=100),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id
    await _require_live_stock_warehouse_read(
        db,
        company_id=company_id,
        location_id=location_id,
        access=access,
        actor=current_admin,
    )

    clean_search = " ".join((search or "").strip().lower().split())
    if clean_search and len(clean_search) < 2:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "LIVE_STOCK_FAMILY_SEARCH_TOO_SHORT",
                "message": "Family search requires at least two characters.",
                "context": {},
            },
        )

    filters = [Product.company_id == company_id]
    if clean_search:
        family_tokens = clean_search.split()
        filters.extend(
            or_(
                func.lower(Product.name).like(
                    f"%{_escape_like(token)}%",
                    escape="\\",
                ),
                func.lower(Product.code).like(
                    f"%{_escape_like(token)}%",
                    escape="\\",
                ),
            )
            for token in family_tokens
        )

    rows = (
        await db.execute(
            select(Product.id, Product.name, Product.code)
            .where(*filters)
            .order_by(Product.name.asc(), Product.id.asc())
            .limit(limit + 1)
        )
    ).all()
    page = rows[:limit]
    return {
        "items": [
            {
                "id": int(row.id),
                "name": str(row.name),
                "code": str(row.code),
            }
            for row in page
        ],
        "has_more": len(rows) > limit,
    }


# جلب صفحة Cursor من الرصيد الحي مع الفلاتر والتكاليف والكميات المجمعة.
@router.get(
    "/warehouse/inventory/cursor",
    response_model=WarehouseInventoryCursorPage,
    status_code=200,
)
async def get_warehouse_inventory(
    location_id: int,
    cursor: Optional[str] = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=200),
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    only_alerts: bool = False,
    stock_state: Literal[
        "all", "on_hand", "sellable", "out_of_stock", "low_stock"
    ] = "all",
    family_id: Optional[int] = None,
    has_reserved: bool = False,
    has_unavailable: bool = False,
    has_damaged: bool = False,
    has_recalled: bool = False,
    has_vehicle: bool = False,
    minimum_unset: bool = False,
    sort: Literal["name_asc", "name_desc"] = "name_asc",
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id

    try:
        company_wide_inventory_read = (
            await _require_live_stock_warehouse_read(
                db,
                company_id=company_id,
                location_id=location_id,
                access=access,
                actor=current_admin,
            )
        )

        await _require_live_stock_read_model_ready(
            db,
            company_id=company_id,
            location_id=location_id,
        )

        clean_search = " ".join((search or "").strip().lower().split())
        if clean_search and len(clean_search) < 2:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "LIVE_STOCK_SEARCH_TOO_SHORT",
                    "message": "Inventory search requires at least two characters.",
                    "context": {},
                },
            )
        if only_alerts and stock_state not in {"all", "low_stock"}:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "LIVE_STOCK_ALERT_FILTER_CONFLICT",
                    "message": "Alert-only mode cannot be combined with another stock state.",
                    "context": {},
                },
            )
        if family_id is not None and family_id <= 0:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "LIVE_STOCK_FAMILY_INVALID",
                    "message": "The selected product family is invalid.",
                    "context": {},
                },
            )

        effective_stock_state = (
            "low_stock" if only_alerts else stock_state
        )
        indicator_filters_active = any(
            (
                has_reserved,
                has_unavailable,
                has_damaged,
                has_recalled,
                has_vehicle,
                minimum_unset,
            )
        )

        search_variant_ids = None
        if clean_search:
            search_patterns = [
                f"%{_escape_like(token)}%"
                for token in clean_search.split()
            ]
            search_variant_ids = select(
                func.public.live_stock_search_variant_ids(
                    company_id,
                    bindparam(
                        "live_stock_search_patterns",
                        search_patterns,
                        type_=ARRAY(String()),
                    ),
                )
            )

        scope = (
            f"inventory|{company_id}|{location_id}|{clean_search}|"
            f"{effective_stock_state}|{family_id or 0}|"
            f"{int(has_reserved)}{int(has_unavailable)}"
            f"{int(has_damaged)}{int(has_recalled)}"
            f"{int(has_vehicle)}{int(minimum_unset)}|{sort}"
        )
        candidate_filters = []
        if search_variant_ids is not None:
            candidate_filters.append(
                ProductVariant.id.in_(search_variant_ids)
            )
        if family_id is not None:
            candidate_filters.append(ProductVariant.product_id == family_id)

        use_alert_fast_path = (
            effective_stock_state == "low_stock"
            and not indicator_filters_active
        )
        if (
            not use_alert_fast_path
            and (
                effective_stock_state != "all"
                or indicator_filters_active
            )
        ):
            filtered_ids = _live_stock_filtered_variant_ids_stmt(
                company_id=company_id,
                location_id=location_id,
                access=access,
                company_wide_inventory_read=company_wide_inventory_read,
                stock_state=effective_stock_state,
                has_reserved=has_reserved,
                has_unavailable=has_unavailable,
                has_damaged=has_damaged,
                has_recalled=has_recalled,
                has_vehicle=has_vehicle,
                minimum_unset=minimum_unset,
            )
            candidate_filters.append(ProductVariant.id.in_(filtered_ids))

        if cursor is not None:
            cursor_name, cursor_id = _decode_variant_cursor(
                cursor,
                expected_kind="warehouse-inventory",
                expected_scope=scope,
            )
            cursor_key = tuple_(ProductVariant.name, ProductVariant.id)
            cursor_value = tuple_(cursor_name, cursor_id)
            candidate_filters.append(
                cursor_key < cursor_value
                if sort == "name_desc"
                else cursor_key > cursor_value
            )

        if use_alert_fast_path:
            alerts = _build_inventory_alert_variants_stmt(
                company_id=company_id,
                location_id=location_id,
                variant_filters=candidate_filters,
            ).cte("scoped_alerts").prefix_with("MATERIALIZED")
            alert_order = (
                (alerts.c.variant_name.desc(), alerts.c.id.desc())
                if sort == "name_desc"
                else (alerts.c.variant_name.asc(), alerts.c.id.asc())
            )
            candidate_stmt = (
                select(alerts.c.id, alerts.c.variant_name)
                .order_by(*alert_order)
                .limit(limit + 1)
            )
        else:
            candidate_stmt = _build_visible_inventory_stmt(
                company_id=company_id,
                location_id=location_id,
                access=access,
                company_wide_inventory_read=company_wide_inventory_read,
                candidate_filters=candidate_filters,
                limit=limit,
                sort=sort,
            )

        # Compatibility fields remain nullable; no exact totals on list reads.
        total = None
        candidate_rows = (await db.execute(candidate_stmt)).all()

        has_more = len(candidate_rows) > limit
        page_candidates = candidate_rows[:limit]
        page_variant_ids = [int(row.id) for row in page_candidates]

        alert_count = None
        alert_samples: list[str] = []

        if not page_variant_ids:
            return {
                "items": [],
                "next_cursor": None,
                "has_more": False,
                "total": total,
                "alert_count": alert_count,
                "alert_samples": alert_samples,
            }

        vehicles: dict[int, Decimal] = {}
        if not company_wide_inventory_read:
            readable_vehicle_locations = _readable_vehicle_locations_subquery(
                company_id=company_id,
                access=access,
            )
            latest_vehicle_sources = _latest_readable_vehicle_sources_subquery(
                company_id=company_id,
                readable_vehicle_locations=readable_vehicle_locations,
            )
            vehicle_inventory_stmt = (
                select(
                    InventoryBalance.product_variant_id,
                    func.sum(
                        InventoryBalance.on_hand_quantity
                    ).label("vehicle_packs"),
                )
                .join(
                    readable_vehicle_locations,
                    readable_vehicle_locations.c.id
                    == InventoryBalance.location_id,
                )
                .join(
                    latest_vehicle_sources,
                    and_(
                        latest_vehicle_sources.c.vehicle_id
                        == readable_vehicle_locations.c.vehicle_id,
                        latest_vehicle_sources.c.source_location_id
                        == location_id,
                    ),
                )
                .where(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.stock_status != "DAMAGED",
                    _warehouse_array_membership(
                        InventoryBalance.product_variant_id,
                        page_variant_ids,
                        "inventory_vehicle_page_variant_ids",
                    ),
                    InventoryBalance.on_hand_quantity > 0,
                )
                .group_by(InventoryBalance.product_variant_id)
            )
            vehicles = {
                int(row.product_variant_id): Decimal(
                    row.vehicle_packs or 0
                )
                for row in (
                    await db.execute(vehicle_inventory_stmt)
                ).all()
            }

        # Drive the entire detail read from the bounded page keyset.
        # The two enrichment lookups are indexed LATERAL seeks (max 200 keys),
        # not tenant-wide DISTINCT/GROUP scans. Only scalar columns are selected
        # so the hot path avoids ORM hydration of ProductVariant/UOM/Projection.
        detail_key_scope = (
            func.unnest(
                bindparam(
                    "inventory_detail_page_variant_ids",
                    value=page_variant_ids,
                    type_=ARRAY(Integer),
                )
            )
            .table_valued("product_variant_id")
            .render_derived(name="inventory_detail_keys")
        )

        purchase_uom = aliased(
            UOM,
            name="inventory_latest_purchase_uom",
        )
        latest_purchase_one = (
            select(
                InventoryCostEvent.input_unit_cost.label(
                    "last_purchase_cost"
                ),
                purchase_uom.code.label(
                    "last_purchase_uom_code"
                ),
                InventoryCostEvent.created_at.label(
                    "last_purchase_created_at"
                ),
            )
            .select_from(InventoryCostEvent)
            .join(
                purchase_uom,
                purchase_uom.id == InventoryCostEvent.input_uom_id,
            )
            .where(
                InventoryCostEvent.company_id == company_id,
                InventoryCostEvent.product_variant_id
                == ProductVariant.id,
                InventoryCostEvent.event_type == "PURCHASE_IN",
            )
            .order_by(
                InventoryCostEvent.created_at.desc(),
                InventoryCostEvent.id.desc(),
            )
            .limit(1)
            .lateral("inventory_latest_purchase_one")
        )

        display_uom = aliased(
            UOM,
            name="inventory_display_uom",
        )
        display_factor_expression = (
            ProductUomConversion.numerator
            / ProductUomConversion.denominator
        )
        display_uom_one = (
            select(
                func.count(ProductUomConversion.id).label(
                    "candidate_count"
                ),
                func.min(display_uom.id).label("display_uom_id_raw"),
                func.min(display_uom.code).label(
                    "display_uom_code_raw"
                ),
                func.min(display_uom.name).label(
                    "display_uom_name_raw"
                ),
                func.min(display_factor_expression).label(
                    "display_factor_to_base_raw"
                ),
            )
            .select_from(ProductUomConversion)
            .join(
                display_uom,
                display_uom.id == ProductUomConversion.from_uom_id,
            )
            .where(
                ProductUomConversion.company_id == company_id,
                ProductUomConversion.product_variant_id
                == ProductVariant.id,
                ProductUomConversion.to_uom_id
                == ProductVariant.base_uom_id,
                ProductUomConversion.numerator
                > ProductUomConversion.denominator,
            )
            .lateral("inventory_display_uom_one")
        )

        detail_stmt = (
            select(
                ProductVariant.id.label("variant_id"),
                ProductVariant.name.label("variant_name"),
                ProductVariant.sku.label("sku"),
                ProductVariant.product_id.label("product_id"),
                Product.name.label("family_name"),
                ProductVariant.base_uom_id.label("base_uom_id"),
                ProductVariant.quantity_scale.label("quantity_scale"),
                ProductVariant.quantity_step.label("quantity_step"),
                ProductVariant.lifecycle_status.label(
                    "lifecycle_status"
                ),
                ProductVariant.operational_hold.label(
                    "operational_hold"
                ),
                UOM.code.label("base_uom_code"),
                UOM.name.label("base_uom_name"),
                InventoryLiveStockProjection.warehouse_on_hand.label(
                    "warehouse_on_hand"
                ),
                InventoryLiveStockProjection.warehouse_reserved.label(
                    "warehouse_reserved"
                ),
                InventoryLiveStockProjection.warehouse_sellable_on_hand.label(
                    "warehouse_sellable_on_hand"
                ),
                InventoryLiveStockProjection.warehouse_sellable_reserved.label(
                    "warehouse_sellable_reserved"
                ),
                InventoryLiveStockProjection.blocked_status_packs.label(
                    "blocked_status_packs"
                ),
                InventoryLiveStockProjection.recalled_packs.label(
                    "recalled_packs"
                ),
                InventoryLiveStockProjection.damaged_packs.label(
                    "damaged_packs"
                ),
                InventoryLiveStockProjection.vehicle_packs.label(
                    "projected_vehicle_packs"
                ),
                InventoryLiveStockProjection.minimum_quantity.label(
                    "minimum_quantity"
                ),
                InventoryCostState.average_unit_cost.label(
                    "average_unit_cost"
                ),
                Company.currency_code.label("currency_code"),
                latest_purchase_one.c.last_purchase_cost,
                latest_purchase_one.c.last_purchase_uom_code,
                latest_purchase_one.c.last_purchase_created_at,
                display_uom_one.c.candidate_count,
                display_uom_one.c.display_uom_id_raw,
                display_uom_one.c.display_uom_code_raw,
                display_uom_one.c.display_uom_name_raw,
                display_uom_one.c.display_factor_to_base_raw,
            )
            .select_from(detail_key_scope)
            .join(
                ProductVariant,
                and_(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id
                    == detail_key_scope.c.product_variant_id,
                ),
            )
            .join(
                Product,
                and_(
                    Product.company_id == ProductVariant.company_id,
                    Product.id == ProductVariant.product_id,
                ),
            )
            .join(UOM, UOM.id == ProductVariant.base_uom_id)
            .join(Company, Company.id == ProductVariant.company_id)
            .outerjoin(
                InventoryLiveStockProjection,
                and_(
                    InventoryLiveStockProjection.company_id
                    == ProductVariant.company_id,
                    InventoryLiveStockProjection.product_variant_id
                    == ProductVariant.id,
                    InventoryLiveStockProjection.warehouse_location_id
                    == location_id,
                ),
            )
            .outerjoin(
                InventoryCostState,
                and_(
                    InventoryCostState.company_id
                    == ProductVariant.company_id,
                    InventoryCostState.product_variant_id
                    == ProductVariant.id,
                ),
            )
            .outerjoin(latest_purchase_one, true())
            .outerjoin(display_uom_one, true())
            .order_by(ProductVariant.name, ProductVariant.id)
        )
        detail_rows = (
            await db.execute(detail_stmt)
        ).mappings().all()

        result = []
        for row in detail_rows:
            variant_id = int(row["variant_id"])
            on_hand = Decimal(row["warehouse_on_hand"] or 0)
            reserved = Decimal(row["warehouse_reserved"] or 0)
            projected_sellable_on_hand = Decimal(
                row["warehouse_sellable_on_hand"] or 0
            )
            projected_sellable_reserved = Decimal(
                row["warehouse_sellable_reserved"] or 0
            )

            sellable_on_hand = (
                projected_sellable_on_hand
                if row["lifecycle_status"] == "ACTIVE"
                and row["operational_hold"] == "NONE"
                else Decimal("0")
            )
            sellable_reserved = (
                projected_sellable_reserved
                if row["lifecycle_status"] == "ACTIVE"
                and row["operational_hold"] == "NONE"
                else Decimal("0")
            )

            free_quantity = sellable_on_hand - sellable_reserved
            explicit_blocked = Decimal(
                row["blocked_status_packs"] or 0
            )
            blocked_quantity = (
                on_hand - sellable_on_hand
            ) + explicit_blocked
            recalled = Decimal(row["recalled_packs"] or 0)
            vehicle_total = (
                Decimal(row["projected_vehicle_packs"] or 0)
                if company_wide_inventory_read
                else vehicles.get(variant_id, Decimal("0"))
            )
            damaged = Decimal(row["damaged_packs"] or 0)
            minimum_quantity = Decimal(row["minimum_quantity"] or 0)

            warehouse_on_hand_total = (
                on_hand + explicit_blocked + damaged
            )
            unavailable_quantity = (
                warehouse_on_hand_total - reserved - free_quantity
            )

            if free_quantity < 0:
                raise RuntimeError(
                    f"Inventory invariant violated for "
                    f"product_variant_id={variant_id}: "
                    "sellable reserved quantity exceeds sellable on-hand."
                )
            if blocked_quantity < 0:
                raise RuntimeError(
                    f"Inventory invariant violated for "
                    f"product_variant_id={variant_id}: "
                    "sellable stock exceeds physical AVAILABLE stock."
                )
            if unavailable_quantity < 0:
                raise RuntimeError(
                    f"Inventory business partition violated for "
                    f"product_variant_id={variant_id}: "
                    "on-hand is smaller than reserved plus sellable stock."
                )

            total_physical_available = (
                on_hand + explicit_blocked + vehicle_total
            )

            if int(row["candidate_count"] or 0) == 1:
                display_uom_id = int(row["display_uom_id_raw"])
                display_uom_code = str(row["display_uom_code_raw"])
                display_uom_name = str(row["display_uom_name_raw"])
                display_factor = Decimal(
                    row["display_factor_to_base_raw"]
                )
            else:
                display_uom_id = int(row["base_uom_id"])
                display_uom_code = str(row["base_uom_code"])
                display_uom_name = str(row["base_uom_name"])
                display_factor = Decimal("1")

            has_location_inventory = (
                warehouse_on_hand_total > 0 or vehicle_total > 0
            )

            average_cost_display = None
            if (
                has_location_inventory
                and row["average_unit_cost"] is not None
            ):
                average_cost_display = (
                    Decimal(row["average_unit_cost"]) * display_factor
                ).quantize(Decimal("0.000001"))

            last_purchase_cost = None
            last_purchase_uom_code = None
            last_purchase_date = None
            if (
                has_location_inventory
                and row["last_purchase_cost"] is not None
            ):
                last_purchase_cost = Decimal(
                    row["last_purchase_cost"]
                )
                last_purchase_uom_code = str(
                    row["last_purchase_uom_code"]
                )
                last_purchase_created_at = row[
                    "last_purchase_created_at"
                ]
                last_purchase_date = (
                    last_purchase_created_at.date()
                    if last_purchase_created_at is not None
                    else None
                )

            currency_code = row["currency_code"]
            if not currency_code:
                raise RuntimeError("Company currency is unavailable.")

            result.append({
                "id": variant_id,
                "name": str(row["variant_name"]),
                "sku": row["sku"],
                "product_id": int(row["product_id"]),
                "family_name": str(row["family_name"]),
                "base_uom_id": int(row["base_uom_id"]),
                "base_uom_code": str(row["base_uom_code"]),
                "base_uom_name": str(row["base_uom_name"]),
                "display_uom_id": display_uom_id,
                "display_uom_code": display_uom_code,
                "display_uom_name": display_uom_name,
                "display_factor_to_base": canonical_quantity(
                    display_factor
                ),
                "currency_code": str(currency_code).upper(),
                "average_cost_display": (
                    format(average_cost_display, "f")
                    if average_cost_display is not None
                    else None
                ),
                "last_purchase_cost": (
                    format(last_purchase_cost, "f")
                    if last_purchase_cost is not None
                    else None
                ),
                "last_purchase_uom_code": last_purchase_uom_code,
                "last_purchase_date": last_purchase_date,
                "quantity_scale": int(row["quantity_scale"]),
                "quantity_step": canonical_quantity(
                    row["quantity_step"]
                ),
                "on_hand_quantity": canonical_quantity(
                    warehouse_on_hand_total
                ),
                "reserved_quantity": canonical_quantity(reserved),
                "available_for_sale_quantity": canonical_quantity(
                    free_quantity
                ),
                "unavailable_quantity": canonical_quantity(
                    unavailable_quantity
                ),
                "vehicle_quantity": canonical_quantity(vehicle_total),
                "recalled_quantity": canonical_quantity(recalled),
                "available_quantity": canonical_quantity(free_quantity),
                "blocked_quantity": canonical_quantity(
                    blocked_quantity
                ),
                "total_quantity": canonical_quantity(
                    total_physical_available
                ),
                "damaged_quantity": canonical_quantity(damaged),
                "minimum_quantity": canonical_quantity(
                    minimum_quantity
                ),
            })

        if len(result) != len(page_variant_ids):
            raise RuntimeError(
                "Inventory page identity invariant violated."
            )

        result_by_id = {
            int(item["id"]): item
            for item in result
        }
        result = [
            result_by_id[variant_id]
            for variant_id in page_variant_ids
        ]

        next_cursor = None
        if has_more:
            last_candidate = page_candidates[-1]
            next_cursor = _encode_variant_cursor(
                kind="warehouse-inventory",
                variant_name=str(last_candidate.variant_name),
                variant_id=int(last_candidate.id),
                scope=scope,
            )

        return {
            "items": result,
            "next_cursor": next_cursor,
            "has_more": has_more,
            "total": total,
            "alert_count": alert_count,
            "alert_samples": alert_samples,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            f"خطأ في Cursor المخزون الحي: {str(e)}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="حدث خطأ داخلي أثناء جلب صفحة المخزون.",
        )


# جلب تفاصيل دفعات المنتج وصلاحيتها وكمياتها وتكلفة آخر شراء.
@router.get(
    "/warehouse/inventory/{product_variant_id}/batches",
    response_model=WarehouseInventoryBatchDetailResponse,
    status_code=200,
)
async def get_warehouse_inventory_batches(
    product_variant_id: int,
    location_id: int,
    cursor: Annotated[
        Optional[str],
        Query(max_length=1024),
    ] = None,
    limit: Annotated[
        int,
        Query(ge=1, le=200),
    ] = 100,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_admin)
    company_id = current_admin.company_id

    try:
        if type(limit) is not int or not 1 <= limit <= 200:
            raise HTTPException(
                status_code=422,
                detail="Batch page limit must be between 1 and 200.",
            )
        if cursor is not None and (
            not isinstance(cursor, str)
            or not cursor
            or len(cursor) > 1024
        ):
            raise HTTPException(
                status_code=422,
                detail="Batch cursor format is invalid.",
            )
        location_access_row = (
            await db.execute(
                select(
                    InventoryLocation.location_type,
                    InventoryLocation.is_active,
                    access.allows(
                        "inventory.read",
                        location_id,
                    ).label("can_read"),
                ).where(
                    InventoryLocation.id == location_id,
                    InventoryLocation.company_id == company_id,
                )
            )
        ).one_or_none()

        if location_access_row is None:
            raise HTTPException(
                status_code=404,
                detail="الموقع غير موجود أو غير متاح.",
            )

        if not bool(location_access_row.can_read):
            raise HTTPException(
                status_code=403,
                detail=(
                    "لا تملك صلاحية تنفيذ هذه العملية "
                    "ضمن الموقع المحدد."
                ),
            )

        if (
            location_access_row.location_type != "WAREHOUSE"
            or not bool(location_access_row.is_active)
        ):
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "LIVE_STOCK_LOCATION_NOT_FOUND",
                    "The selected warehouse is unavailable.",
                ),
            )

        variant_company_row = (
            await db.execute(
                select(
                    ProductVariant.id.label("variant_id"),
                    Company.currency_code.label("currency_code"),
                    func.timezone(
                        Company.timezone,
                        func.current_timestamp(),
                    ).cast(Date).label("as_of_date"),
                )
                .join(
                    Company,
                    Company.id == ProductVariant.company_id,
                )
                .where(
                    ProductVariant.id == product_variant_id,
                    ProductVariant.company_id == company_id,
                    Company.id == company_id,
                )
            )
        ).one_or_none()
        if variant_company_row is None:
            raise HTTPException(
                status_code=404,
                detail=inventory_business_error(
                    "LIVE_STOCK_PRODUCT_NOT_FOUND",
                    "The selected product is unavailable.",
                ),
            )

        currency_code = variant_company_row.currency_code
        if not currency_code:
            raise RuntimeError(
                "Company currency is unavailable."
            )

        as_of_date = variant_company_row.as_of_date
        if as_of_date is None:
            raise RuntimeError(
                "Company timezone is unavailable."
            )

        batch_is_sellable = batch_sellability_predicate(
            as_of_date,
            expiry_control_mode=ProductVariant.expiry_control_mode,
            minimum_remaining_shelf_life_days=(
                InventoryStockPolicy.minimum_remaining_shelf_life_days
            ),
        )

        batch_cursor_scope = (
            f"company={company_id}|location={location_id}|"
            f"variant={product_variant_id}"
        )
        batch_cursor_predicate = true()
        if cursor:
            cursor_expiry_date, cursor_batch_id = _decode_batch_cursor(
                cursor,
                expected_scope=batch_cursor_scope,
            )
            if cursor_expiry_date is None:
                batch_cursor_predicate = and_(
                    ProductBatch.expiry_date.is_(None),
                    ProductBatch.id > cursor_batch_id,
                )
            else:
                batch_cursor_predicate = or_(
                    ProductBatch.expiry_date > cursor_expiry_date,
                    and_(
                        ProductBatch.expiry_date == cursor_expiry_date,
                        ProductBatch.id > cursor_batch_id,
                    ),
                    ProductBatch.expiry_date.is_(None),
                )

        batch_presence = (
            select(1)
            .select_from(InventoryBalance)
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id
                == product_variant_id,
                InventoryBalance.batch_id == ProductBatch.id,
                InventoryBalance.on_hand_quantity > 0,
            )
            .exists()
        )

        batch_candidate_stmt = (
            select(
                ProductBatch.id.label("batch_id"),
                ProductBatch.expiry_date,
            )
            .prefix_with("/* inventory_batch_candidates */")
            .where(
                ProductBatch.company_id == company_id,
                ProductBatch.product_variant_id == product_variant_id,
                batch_presence,
                batch_cursor_predicate,
            )
            .order_by(
                ProductBatch.expiry_date.asc().nulls_last(),
                ProductBatch.id.asc(),
            )
            .limit(limit + 1)
        )

        candidate_rows = (
            await db.execute(batch_candidate_stmt)
        ).all()
        has_more = len(candidate_rows) > limit
        page_candidates = candidate_rows[:limit]
        batch_ids = [
            int(row.batch_id)
            for row in page_candidates
        ]

        next_cursor = None
        if has_more and page_candidates:
            last_candidate = page_candidates[-1]
            next_cursor = _encode_batch_cursor(
                expiry_date=last_candidate.expiry_date,
                batch_id=int(last_candidate.batch_id),
                scope=batch_cursor_scope,
            )

        batch_rows = []
        if batch_ids:
            batch_stmt = (
                select(
                    ProductBatch.id.label("batch_id"),
                    ProductBatch.batch_number,
                    ProductBatch.production_date,
                    ProductBatch.expiry_date,
                    ProductBatch.disposition,
                    func.sum(
                        InventoryBalance.on_hand_quantity
                    ).label("on_hand_total"),
                    func.sum(
                        InventoryBalance.reserved_quantity
                    ).label("reserved_total"),
                    func.sum(
                        case(
                            (
                                and_(
                                    InventoryBalance.stock_status
                                    == "AVAILABLE",
                                    batch_is_sellable,
                                ),
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=0,
                        )
                    ).label("sellable_on_hand"),
                    func.sum(
                        case(
                            (
                                and_(
                                    InventoryBalance.stock_status
                                    == "AVAILABLE",
                                    batch_is_sellable,
                                ),
                                InventoryBalance.reserved_quantity,
                            ),
                            else_=0,
                        )
                    ).label("sellable_reserved"),
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status
                                == "QUARANTINED",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=0,
                        )
                    ).label("quarantined_quantity"),
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status
                                == "BLOCKED",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=0,
                        )
                    ).label("blocked_quantity"),
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status
                                == "RECALLED",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=0,
                        )
                    ).label("recalled_quantity"),
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status
                                == "DAMAGED",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=0,
                        )
                    ).label("damaged_quantity"),
                    func.sum(
                        case(
                            (
                                InventoryBalance.stock_status
                                == "DISPOSAL_PENDING",
                                InventoryBalance.on_hand_quantity,
                            ),
                            else_=0,
                        )
                    ).label("disposal_pending_quantity"),
                )
                .prefix_with("/* inventory_batch_aggregate */")
                .join(
                    ProductBatch,
                    and_(
                        ProductBatch.id == InventoryBalance.batch_id,
                        ProductBatch.company_id == company_id,
                        ProductBatch.product_variant_id
                        == product_variant_id,
                    ),
                )
                .join(
                    ProductVariant,
                    and_(
                        ProductVariant.company_id
                        == InventoryBalance.company_id,
                        ProductVariant.id
                        == InventoryBalance.product_variant_id,
                    ),
                )
                .outerjoin(
                    InventoryStockPolicy,
                    and_(
                        InventoryStockPolicy.company_id
                        == InventoryBalance.company_id,
                        InventoryStockPolicy.location_id == location_id,
                        InventoryStockPolicy.product_variant_id
                        == InventoryBalance.product_variant_id,
                        InventoryStockPolicy.is_active.is_(True),
                    ),
                )
                .filter(
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.location_id == location_id,
                    InventoryBalance.product_variant_id
                    == product_variant_id,
                    InventoryBalance.batch_id.in_(batch_ids),
                    ProductBatch.id.in_(batch_ids),
                    InventoryBalance.on_hand_quantity > 0,
                )
                .group_by(
                    ProductBatch.id,
                    ProductBatch.batch_number,
                    ProductBatch.production_date,
                    ProductBatch.expiry_date,
                    ProductBatch.disposition,
                )
                .order_by(
                    ProductBatch.expiry_date.asc().nulls_last(),
                    ProductBatch.id.asc(),
                )
            )

            batch_rows = (await db.execute(batch_stmt)).all()


        latest_purchase_by_batch = {}
        purchase_count_by_batch = {}

        if batch_ids:
            purchase_count_subquery = (
                select(
                    InventoryCostEvent.batch_id.label("batch_id"),
                    func.count(InventoryCostEvent.id).label(
                        "event_count"
                    ),
                )
                .filter(
                    InventoryCostEvent.company_id == company_id,
                    InventoryCostEvent.product_variant_id
                    == product_variant_id,
                    InventoryCostEvent.batch_id.in_(batch_ids),
                    InventoryCostEvent.event_type == "PURCHASE_IN",
                )
                .group_by(InventoryCostEvent.batch_id)
                .subquery("purchase_counts")
            )

            latest_purchase_subquery = (
                select(
                    InventoryCostEvent.batch_id.label("batch_id"),
                    InventoryCostEvent.input_unit_cost.label(
                        "input_unit_cost"
                    ),
                    UOM.code.label("input_uom_code"),
                    InventoryCostEvent.created_at.label(
                        "created_at"
                    ),
                )
                .join(
                    UOM,
                    UOM.id == InventoryCostEvent.input_uom_id,
                )
                .filter(
                    InventoryCostEvent.company_id == company_id,
                    InventoryCostEvent.product_variant_id
                    == product_variant_id,
                    InventoryCostEvent.batch_id.in_(batch_ids),
                    InventoryCostEvent.event_type == "PURCHASE_IN",
                )
                .distinct(InventoryCostEvent.batch_id)
                .order_by(
                    InventoryCostEvent.batch_id,
                    InventoryCostEvent.created_at.desc(),
                    InventoryCostEvent.id.desc(),
                )
                .subquery("latest_purchase")
            )

            purchase_rows = (
                await db.execute(
                    select(
                        purchase_count_subquery.c.batch_id,
                        purchase_count_subquery.c.event_count,
                        latest_purchase_subquery.c.batch_id.label(
                            "latest_batch_id"
                        ),
                        latest_purchase_subquery.c.input_unit_cost,
                        latest_purchase_subquery.c.input_uom_code,
                        latest_purchase_subquery.c.created_at,
                    )
                    .select_from(
                        purchase_count_subquery.outerjoin(
                            latest_purchase_subquery,
                            latest_purchase_subquery.c.batch_id
                            == purchase_count_subquery.c.batch_id,
                        )
                    )
                )
            ).all()

            purchase_count_by_batch = {
                int(row.batch_id): int(row.event_count)
                for row in purchase_rows
            }
            latest_purchase_by_batch = {
                int(row.batch_id): row
                for row in purchase_rows
                if row.latest_batch_id is not None
            }

        batches = []
        for row in batch_rows:
            on_hand_total = Decimal(row.on_hand_total or 0)
            reserved_total = Decimal(row.reserved_total or 0)
            sellable_on_hand = Decimal(
                row.sellable_on_hand or 0
            )
            sellable_reserved = Decimal(
                row.sellable_reserved or 0
            )

            available_for_sale = (
                sellable_on_hand - sellable_reserved
            )
            unavailable = (
                on_hand_total
                - reserved_total
                - available_for_sale
            )

            if available_for_sale < 0 or unavailable < 0:
                raise RuntimeError(
                    "Inventory batch partition invariant failed "
                    f"for product_variant_id={product_variant_id}, "
                    f"batch_id={row.batch_id}."
                )

            quarantined = Decimal(
                row.quarantined_quantity or 0
            )
            blocked = Decimal(row.blocked_quantity or 0)
            recalled = Decimal(row.recalled_quantity or 0)
            damaged = Decimal(row.damaged_quantity or 0)
            disposal_pending = Decimal(
                row.disposal_pending_quantity or 0
            )

            explicit_unavailable = (
                quarantined
                + blocked
                + recalled
                + damaged
                + disposal_pending
            )
            restricted = unavailable - explicit_unavailable
            if restricted < 0:
                raise RuntimeError(
                    "Inventory batch unavailable breakdown "
                    f"exceeded the partition for batch_id={row.batch_id}."
                )

            latest_purchase = latest_purchase_by_batch.get(
                int(row.batch_id)
            )
            latest_purchase_cost = None
            latest_purchase_uom_code = None
            latest_purchase_date = None
            if latest_purchase is not None:
                latest_purchase_cost = Decimal(
                    latest_purchase.input_unit_cost
                )
                latest_purchase_uom_code = str(
                    latest_purchase.input_uom_code
                )
                latest_purchase_date = (
                    latest_purchase.created_at.date()
                )

            batches.append(
                {
                    "batch_id": int(row.batch_id),
                    "batch_number": str(row.batch_number),
                    "production_date": row.production_date,
                    "expiry_date": row.expiry_date,
                    "disposition": str(row.disposition),
                    "days_to_expiry": (
                        (row.expiry_date - as_of_date).days
                        if row.expiry_date is not None
                        else None
                    ),
                    "on_hand_quantity": canonical_quantity(
                        on_hand_total
                    ),
                    "reserved_quantity": canonical_quantity(
                        reserved_total
                    ),
                    "available_for_sale_quantity":
                        canonical_quantity(
                            available_for_sale
                        ),
                    "unavailable_quantity":
                        canonical_quantity(unavailable),
                    "restricted_quantity":
                        canonical_quantity(restricted),
                    "quarantined_quantity":
                        canonical_quantity(quarantined),
                    "blocked_quantity":
                        canonical_quantity(blocked),
                    "recalled_quantity":
                        canonical_quantity(recalled),
                    "damaged_quantity":
                        canonical_quantity(damaged),
                    "disposal_pending_quantity":
                        canonical_quantity(disposal_pending),
                    "latest_purchase_cost": (
                        format(
                            latest_purchase_cost,
                            "f",
                        )
                        if latest_purchase_cost is not None
                        else None
                    ),
                    "latest_purchase_uom_code":
                        latest_purchase_uom_code,
                    "latest_purchase_date":
                        latest_purchase_date,
                    "purchase_event_count":
                        purchase_count_by_batch.get(
                            int(row.batch_id),
                            0,
                        ),
                }
            )

        return {
            "location_id": location_id,
            "product_variant_id": product_variant_id,
            "currency_code": str(currency_code).upper(),
            "batches": batches,
            "next_cursor": next_cursor,
            "has_more": has_more,
        }

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to load live-stock batch details "
            f"for company_id={company_id}, "
            f"location_id={location_id}, "
            f"product_variant_id={product_variant_id}: {exc}",
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail=inventory_business_error(
                "LIVE_STOCK_BATCH_DETAILS_FAILED",
                "Live-stock batch details could not be loaded.",
            ),
        ) from exc


