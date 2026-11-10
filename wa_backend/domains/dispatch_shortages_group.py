"""Atomic, authorized grouped shortages command (#849 / Dispatch D05).

One tenant-scoped transaction replaces only the selected pending rows. The
canonical OperationIdempotency table owns durable replay; shortage/Visit state,
audit evidence and the result record commit together. No inventory or finance
authority is touched here.
"""
from __future__ import annotations

from hashlib import sha256
import json
from uuid import UUID

from pydantic import Field, ConfigDict, model_validator
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from domains.dispatch_representatives import has_canonical_field_identity
from domains.dispatch_shortage_visits import (
    ensure_shortage_pending_visit, settle_shortage_pending_visit,
)
from models import (
    DispatchRoute, Driver, ProductVariant, Shop, ShortageRequest, SystemAuditLog,
    Visit, Zone,
)
from product_lifecycle import (
    REPLENISHMENT_NEW, acquire_product_lifecycle_guards,
    evaluate_product_capability,
)
from schemas import CreateShortageItem, PositiveDbInt, RequestModel
from services import (
    begin_idempotent_operation, complete_idempotent_operation,
    get_company_local_date,
)


class GroupShortageMutation(RequestModel):
    """Exact already-shipped Dashboard PUT contract; bounded for lock safety."""
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    shortage_ids: list[PositiveDbInt] = Field(min_length=1, max_length=500)
    items: list[CreateShortageItem] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def reject_duplicates(self):
        if len(set(self.shortage_ids)) != len(self.shortage_ids):
            raise ValueError("Duplicate shortage IDs are not allowed")
        pairs = [(int(i.shopId), int(i.product_variant_id)) for i in self.items]
        if len(pairs) != len(set(pairs)):
            raise ValueError("Duplicate shop/product lines are not allowed")
        return self


class ShortageGroupRejected(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _reject(status: int, code: str, message: str):
    raise ShortageGroupRejected(status, code, message)


def _hash_payload(command: GroupShortageMutation) -> str:
    # Canonical ordering means a retry with reordered lines has one identity.
    lines = sorted((
        int(i.zoneId), int(i.shopId), int(i.driverId) if i.driverId is not None else 0,
        int(i.product_variant_id), int(i.quantity),
    ) for i in command.items)
    canonical = json.dumps(
        {"shortage_ids": sorted(map(int, command.shortage_ids)), "items": lines},
        sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


async def _shop_lock(db: AsyncSession, *, company_id: int, shop_id: int):
    # Same advisory namespace and lock ordering as existing POST/DELETE.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(CAST(:company AS integer), hashtext(:key))"),
        {"company": company_id, "key": f"dispatch-shop:{shop_id}"},
    )
    shop = (await db.execute(
        select(Shop).where(Shop.company_id == company_id, Shop.id == shop_id)
        .order_by(Shop.id.asc()).with_for_update()
    )).scalar_one_or_none()
    if shop is None or shop.is_archived or not shop.is_active:
        _reject(404, "SHORTAGE_SHOP_NOT_FOUND", "المحل غير موجود أو غير فعال.")
    return shop


async def _valid_driver_ids(db: AsyncSession, company_id: int, driver_ids: set[int]):
    if not driver_ids:
        return
    rows = (await db.execute(
        select(
            Driver,
            has_canonical_field_identity(company_id=company_id, legacy_driver_id=Driver.id),
        ).where(Driver.company_id == company_id, Driver.id.in_(sorted(driver_ids)))
        # Fail closed rather than wait while a concurrent writer holds zone/Visit
        # locks in the opposite legacy POST path: no driver↔zone deadlock.
        .order_by(Driver.id.asc()).with_for_update(nowait=True)
    )).all()
    valid = {int(driver.id) for driver, has_identity in rows if driver.is_active and has_identity}
    if valid != driver_ids:
        _reject(400, "SHORTAGE_DRIVER_INVALID", "أحد المندوبين غير فعال أو لا يتبع الشركة.")


async def _auto_driver_id(db: AsyncSession, company_id: int, zone_id: int):
    routes = (await db.execute(
        select(DispatchRoute).where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.zone_id == zone_id,
            DispatchRoute.status == "active",
            DispatchRoute.driver_id.is_not(None),
        ).order_by(DispatchRoute.id.asc()).with_for_update(nowait=True)
    )).scalars().all()
    ids = {int(route.driver_id) for route in routes}
    if len(ids) > 1:
        _reject(409, "SHORTAGE_ROUTE_AMBIGUOUS",
                "يوجد أكثر من مندوب في المسارات النشطة للمنطقة.")
    if not ids:
        return None
    driver_id = next(iter(ids))
    valid = (await db.execute(
        select(Driver.id).where(
            Driver.company_id == company_id,
            Driver.id == driver_id,
            Driver.is_active.is_(True),
            has_canonical_field_identity(
                company_id=company_id, legacy_driver_id=Driver.id,
            ),
        ).with_for_update(read=True, nowait=True)
    )).scalar_one_or_none()
    return driver_id if valid is not None else None


async def _pending_visits(
    db: AsyncSession, *, company_id: int, shop_id: int, driver_ids: set[int],
):
    if not driver_ids:
        return {}
    # Preserve canonical pending-visit advisory namespace used by POST.
    keys = [f"pending-visit:{driver}:{shop_id}" for driver in sorted(driver_ids)]
    await db.execute(text(
        """
        SELECT pg_advisory_xact_lock(CAST(:company AS integer), hashtext(lock_key))
        FROM unnest(CAST(:keys AS text[])) AS t(lock_key)
        ORDER BY lock_key
        """
    ), {"company": company_id, "keys": keys})
    rows = (await db.execute(
        select(Visit).where(
            Visit.company_id == company_id,
            Visit.shop_id == shop_id,
            Visit.driver_id.in_(sorted(driver_ids)),
            Visit.status == "Pending",
        ).order_by(Visit.driver_id.asc(), Visit.shop_id.asc(), Visit.id.asc())
        .with_for_update()
    )).scalars().all()
    visits = {}
    for visit in rows:
        driver_id = int(visit.driver_id)
        if driver_id in visits:
            _reject(409, "SHORTAGE_PENDING_VISIT_DUPLICATED",
                    "يوجد أكثر من زيارة معلقة لنفس المندوب والمحل.")
        visits[driver_id] = visit
    return visits


async def replace_shortage_group(
    db: AsyncSession, *, company_id: int, actor_id: int,
    command: GroupShortageMutation,
) -> tuple[dict, bool]:
    """Return (persisted response, was_new_mutation). Caller maps/rolls back exceptions."""
    record, replay = await begin_idempotent_operation(
        db, company_id=company_id, actor_id=actor_id,
        operation="DISPATCH_SHORTAGES_GROUP_V1",
        request_id=str(command.request_id),
        request_hash=_hash_payload(command),
    )
    if replay is not None:
        # Re-auth happened before this function. Release replay row/advisory locks.
        await db.rollback()
        return replay, False

    ids = set(map(int, command.shortage_ids))
    pre = (await db.execute(
        select(ShortageRequest.id, ShortageRequest.shop_id, ShortageRequest.zone_id,
               ShortageRequest.driver_id)
        .where(ShortageRequest.company_id == company_id, ShortageRequest.id.in_(sorted(ids)))
        .order_by(ShortageRequest.id.asc())
    )).all()
    if {int(row.id) for row in pre} != ids:
        _reject(404, "SHORTAGE_SELECTION_NOT_FOUND", "أحد طلبات النواقص غير موجود.")
    shop_ids = {int(row.shop_id) for row in pre}
    zone_ids = {int(row.zone_id) for row in pre}
    old_owners = {int(row.driver_id) if row.driver_id is not None else None for row in pre}
    if len(shop_ids) != 1 or len(zone_ids) != 1 or len(old_owners) != 1:
        _reject(400, "SHORTAGE_SELECTION_MIXED", "يجب تعديل مجموعة محل ومنطقة ومندوب واحدة.")
    shop_id = next(iter(shop_ids))
    zone_id = next(iter(zone_ids))
    old_driver_id = next(iter(old_owners))

    items = command.items
    if any(int(i.shopId) != shop_id or int(i.zoneId) != zone_id for i in items):
        _reject(400, "SHORTAGE_SELECTION_SCOPE",
                "المجموعة لا تسمح بنقل النواقص إلى محل أو منطقة أخرى.")
    product_ids = sorted({int(i.product_variant_id) for i in items})
    if product_ids:
        await acquire_product_lifecycle_guards(db, company_id, product_ids, exclusive=False)
    explicit_drivers = {int(i.driverId) for i in items if i.driverId is not None}
    # Preserve existing POST driver-before-zone ordering.
    await _valid_driver_ids(db, company_id, explicit_drivers)

    zone = (await db.execute(
        select(Zone).where(Zone.company_id == company_id, Zone.id == zone_id)
        # Another transaction may already own this zone while waiting on a
        # driver locked earlier here; NOWAIT converts the cycle to safe 409.
        .order_by(Zone.id.asc()).with_for_update(nowait=True)
    )).scalar_one_or_none()
    if zone is None or not zone.is_active:
        _reject(404, "SHORTAGE_ZONE_UNAVAILABLE", "المنطقة غير موجودة أو مؤرشفة.")
    shop = await _shop_lock(db, company_id=company_id, shop_id=shop_id)
    if shop.zone_id is None or int(shop.zone_id) != zone_id:
        _reject(409, "SHORTAGE_ZONE_CHANGED", "تغيّرت منطقة المحل؛ يرجى تحديث الطلب.")

    # Full pending shop set locks against concurrent POST/DELETE/group writers.
    pending = (await db.execute(
        select(ShortageRequest).where(
            ShortageRequest.company_id == company_id,
            ShortageRequest.shop_id == shop_id,
            ShortageRequest.status == "pending",
        ).order_by(ShortageRequest.id.asc()).with_for_update()
    )).scalars().all()
    indexed = {int(row.id): row for row in pending}
    if not ids <= indexed.keys():
        _reject(409, "SHORTAGE_SELECTION_STALE", "تغيّر أو تمت معالجة أحد الطلبات.")
    selected = [indexed[identifier] for identifier in sorted(ids)]
    if any(int(row.zone_id) != zone_id
           or (int(row.driver_id) if row.driver_id is not None else None) != old_driver_id
           or row.fulfilled_by_visit_id is not None or row.fulfilled_at is not None
           for row in selected):
        _reject(409, "SHORTAGE_SELECTION_CHANGED", "تغيّرت حالة المجموعة؛ أعد تحميلها.")

    variants = (await db.execute(
        select(ProductVariant).where(
            ProductVariant.company_id == company_id,
            ProductVariant.id.in_(product_ids),
        ).order_by(ProductVariant.id.asc())
    )).scalars().all() if product_ids else []
    variant_map = {int(v.id): v for v in variants}
    if set(product_ids) != set(variant_map):
        _reject(404, "SHORTAGE_PRODUCT_NOT_FOUND", "أحد الأصناف غير موجود.")
    for variant in variants:
        eligibility = evaluate_product_capability(
            variant.lifecycle_status, variant.operational_hold, REPLENISHMENT_NEW,
        )
        if not eligibility.allowed:
            _reject(409, eligibility.code, "الصنف غير متاح لإنشاء طلب نقص جديد.")

    existing_pairs = {
        int(row.product_variant_id) for row in pending if int(row.id) not in ids
    }
    if any(int(i.product_variant_id) in existing_pairs for i in items):
        _reject(409, "SHORTAGE_PRODUCT_ALREADY_PENDING",
                "يوجد طلب نقص معلّق خارج المجموعة لأحد الأصناف.")

    automatic_driver = None
    if any(i.driverId is None for i in items):
        automatic_driver = await _auto_driver_id(db, company_id, zone_id)
    resolved = [
        (i, int(i.driverId) if i.driverId is not None else automatic_driver)
        for i in items
    ]
    if len({owner for _, owner in resolved}) > 1:
        _reject(400, "SHORTAGE_GROUP_MIXED_DRIVER",
                "لا يمكن توزيع المجموعة الواحدة على أكثر من مندوب.")
    # Lock both original and intended Visit owners; preserve unrelated owners.
    owners = {driver for _, driver in resolved if driver is not None}
    if old_driver_id is not None:
        owners.add(old_driver_id)
    visits = await _pending_visits(
        db, company_id=company_id, shop_id=shop_id, driver_ids=owners,
    )

    for row in selected:
        await db.delete(row)
    await db.flush()
    new_rows = []
    for item, driver_id in sorted(resolved, key=lambda pair: int(pair[0].product_variant_id)):
        row = ShortageRequest(
            company_id=company_id, zone_id=zone_id, shop_id=shop_id,
            driver_id=driver_id, product_variant_id=int(item.product_variant_id),
            quantity=int(item.quantity),
        )
        db.add(row)
        new_rows.append(row)
    await db.flush()

    if resolved:
        company_date = await get_company_local_date(db, company_id)
        for driver_id in sorted({driver for _, driver in resolved if driver is not None}):
            visits[driver_id] = ensure_shortage_pending_visit(
                db, company_id=company_id, driver_id=driver_id,
                shop=shop, operational_date=company_date, existing=visits.get(driver_id),
            )
    if old_driver_id is not None:
        await settle_shortage_pending_visit(
            db, company_id=company_id, shop=shop, driver_id=old_driver_id,
        )

    response = {
        "message": "تم حذف مجموعة النواقص بنجاح" if not items else "تم تعديل مجموعة النواقص بنجاح",
        "request_id": str(command.request_id),
        "shortage_ids": [int(row.id) for row in new_rows],
    }
    db.add(SystemAuditLog(
        company_id=company_id, admin_id=actor_id,
        target_id=f"ShortageGroup_{shop_id}_{command.request_id}",
        action_type="SHORTAGE_GROUP_DELETE" if not items else "SHORTAGE_GROUP_REPLACE",
        old_value=json.dumps([{
            "id": int(row.id), "product_id": int(row.product_variant_id),
            "quantity": int(row.quantity), "driver_id": row.driver_id,
        } for row in selected], sort_keys=True),
        new_value=json.dumps([{
            "id": int(row.id), "product_id": int(row.product_variant_id),
            "quantity": int(row.quantity), "driver_id": row.driver_id,
        } for row in new_rows], sort_keys=True),
    ))
    complete_idempotent_operation(record, response)
    await db.commit()
    return response, True
