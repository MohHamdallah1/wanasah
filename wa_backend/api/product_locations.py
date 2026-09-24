"""Explicit tenant/location-scoped ProductLocation assignments."""

import hashlib
import json
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import Driver, InventoryLocation, ProductLocation, ProductVariant
from product_lifecycle import (
    DEFAULT_PRODUCT_LOCATION_FLAGS,
    acquire_product_lifecycle_guards,
    product_location_delete_blockers,
    record_domain_event,
    validate_product_location_flags,
)
from services import InventoryMutationError, begin_idempotent_operation, complete_idempotent_operation


router = APIRouter(prefix="/warehouse/product-locations", tags=["Product Locations"])


def _error(status: int, code: str, message: str, **context: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "context": context})


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ProductLocationCreate(StrictRequest):
    request_id: UUID
    location_id: int = Field(gt=0)
    product_variant_id: int = Field(gt=0)
    operational_flags: dict[str, bool] = Field(default_factory=lambda: dict(DEFAULT_PRODUCT_LOCATION_FLAGS))

    @field_validator("operational_flags")
    @classmethod
    def flags_value(cls, value: Any) -> dict[str, bool]:
        return validate_product_location_flags(value)


class ProductLocationUpdate(StrictRequest):
    request_id: UUID
    expected_version: int = Field(gt=0)
    operational_flags: dict[str, bool]

    @field_validator("operational_flags")
    @classmethod
    def flags_value(cls, value: Any) -> dict[str, bool]:
        return validate_product_location_flags(value)


class ProductLocationDelete(StrictRequest):
    request_id: UUID
    expected_version: int = Field(gt=0)
    location_id: int | None = Field(default=None, gt=0)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def reason_value(cls, value: Any) -> str:
        if not isinstance(value, str) or not value.strip() or len(value.strip()) > 1000:
            raise ValueError("reason غير صالح")
        return value.strip()


def _hash(payload: BaseModel, **scope: Any) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    body.update(scope)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cursor(value: Optional[str]) -> int:
    if value is None:
        return 0
    if not value.isdigit() or int(value) <= 0:
        raise _error(400, "INVALID_CURSOR", "Cursor ربط المنتجات غير صالح.")
    return int(value)


def _row(item: ProductLocation, location: InventoryLocation, variant: ProductVariant) -> dict[str, Any]:
    return {
        "id": item.id,
        "location": {"id": location.id, "code": location.code, "name": location.name, "location_type": location.location_type},
        "product_variant": {"id": variant.id, "sku": variant.sku, "name": variant.name, "lifecycle_status": variant.lifecycle_status},
        "operational_flags": validate_product_location_flags(item.operational_flags),
        "version": item.version,
        "created_by": item.created_by,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


@router.get("")
async def list_product_locations(
    location_id: Optional[int] = Query(None, gt=0),
    product_variant_id: Optional[int] = Query(None, gt=0),
    cursor: Optional[str] = Query(None, max_length=32),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, actor)
    if location_id is not None:
        await access.require("product_location.read", location_id)
    else:
        await access.require("product_location.read", any_location=True)
    stmt = (
        select(ProductLocation, InventoryLocation, ProductVariant)
        .join(
            InventoryLocation,
            (InventoryLocation.company_id == ProductLocation.company_id)
            & (InventoryLocation.id == ProductLocation.location_id),
        )
        .join(
            ProductVariant,
            (ProductVariant.company_id == ProductLocation.company_id)
            & (ProductVariant.id == ProductLocation.product_variant_id),
        )
        .where(
            ProductLocation.company_id == actor.company_id,
            ProductLocation.id > _cursor(cursor),
            access.location_filter("product_location.read", ProductLocation.location_id),
        )
    )
    if location_id is not None:
        stmt = stmt.where(ProductLocation.location_id == location_id)
    if product_variant_id is not None:
        stmt = stmt.where(ProductLocation.product_variant_id == product_variant_id)
    rows = list((await db.execute(stmt.order_by(ProductLocation.id.asc()).limit(limit + 1))).all())
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_row(item, location, variant) for item, location, variant in page],
        "next_cursor": str(page[-1][0].id) if has_more else None,
        "has_more": has_more,
    }


@router.post("", status_code=201)
async def create_product_location(
    payload: ProductLocationCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, actor)
    await access.require("product_location.manage", payload.location_id)
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRODUCT_LOCATION_CREATE",
            request_id=str(payload.request_id),
            request_hash=_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay
        await acquire_product_lifecycle_guards(db, actor.company_id, [payload.product_variant_id], exclusive=True)
        location = await db.scalar(select(InventoryLocation).where(
            InventoryLocation.company_id == actor.company_id,
            InventoryLocation.id == payload.location_id,
            InventoryLocation.is_active.is_(True),
            InventoryLocation.is_system_managed.is_(False),
        ).with_for_update(read=True))
        if location is None:
            raise _error(404, "PRODUCT_LOCATION_TARGET_NOT_FOUND", "الموقع غير موجود أو غير قابل للربط.")
        variant = await db.scalar(select(ProductVariant).where(
            ProductVariant.company_id == actor.company_id,
            ProductVariant.id == payload.product_variant_id,
        ).with_for_update(read=True))
        if variant is None:
            raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
        if variant.lifecycle_status != "ACTIVE":
            raise _error(409, "PRODUCT_LOCATION_VARIANT_NOT_ACTIVE", "يمكن ربط موقع جديد بصنف ACTIVE فقط.")
        item = ProductLocation(
            company_id=actor.company_id,
            location_id=payload.location_id,
            product_variant_id=payload.product_variant_id,
            operational_flags=payload.operational_flags,
            created_by=actor.id,
        )
        db.add(item)
        await db.flush()
        response = {"message": "تم ربط الصنف بالموقع دون إنشاء رصيد أو سياسة.", "product_location": _row(item, location, variant)}
        record_domain_event(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            request_id=payload.request_id,
            event_type="ProductLocationAssigned",
            entity_type="ProductLocation",
            entity_id=item.id,
            reason="Explicit product-location assignment",
            before=None,
            after=response["product_location"],
        )
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "PRODUCT_LOCATION_CONFLICT", "الصنف مربوط بهذا الموقع مسبقاً أو أن النطاق غير صالح.") from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise _error(409, "IDEMPOTENCY_CONFLICT", str(exc)) from exc


@router.patch("/{product_location_id}")
async def update_product_location(
    product_location_id: int,
    payload: ProductLocationUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    item_scope = await db.execute(select(ProductLocation.location_id, ProductLocation.product_variant_id).where(
        ProductLocation.company_id == actor.company_id,
        ProductLocation.id == product_location_id,
    ))
    scope = item_scope.one_or_none()
    if scope is None:
        raise _error(404, "PRODUCT_LOCATION_NOT_FOUND", "ربط الصنف بالموقع غير موجود.")
    await InventoryAccess(db, actor).require("product_location.manage", scope.location_id)
    try:
        idem, replay = await begin_idempotent_operation(
            db, company_id=actor.company_id, actor_id=actor.id,
            operation="PRODUCT_LOCATION_UPDATE", request_id=str(payload.request_id),
            request_hash=_hash(payload, product_location_id=product_location_id),
        )
        if replay is not None:
            await db.rollback()
            return replay
        await acquire_product_lifecycle_guards(db, actor.company_id, [scope.product_variant_id], exclusive=True)
        item = await db.scalar(select(ProductLocation).where(
            ProductLocation.company_id == actor.company_id,
            ProductLocation.id == product_location_id,
        ).with_for_update())
        if item is None:
            raise _error(404, "PRODUCT_LOCATION_NOT_FOUND", "ربط الصنف بالموقع غير موجود.")
        if item.version != payload.expected_version:
            raise _error(409, "PRODUCT_LOCATION_VERSION_CONFLICT", "تغير الربط؛ حدّث البيانات وأعد المحاولة.", current_version=item.version)
        before = {"operational_flags": validate_product_location_flags(item.operational_flags), "version": item.version}
        item.operational_flags = payload.operational_flags
        item.version += 1
        await db.flush()
        location = await db.scalar(select(InventoryLocation).where(
            InventoryLocation.company_id == actor.company_id,
            InventoryLocation.id == item.location_id,
        ))
        variant = await db.scalar(select(ProductVariant).where(ProductVariant.company_id == actor.company_id, ProductVariant.id == item.product_variant_id))
        response = {"message": "تم تحديث صلاحيات تشغيل الصنف في الموقع.", "product_location": _row(item, location, variant)}
        record_domain_event(
            db, company_id=actor.company_id, actor_id=actor.id, request_id=payload.request_id,
            event_type="ProductLocationUpdated", entity_type="ProductLocation", entity_id=item.id,
            reason="Operational flags updated", before=before, after=response["product_location"],
        )
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except (IntegrityError, InventoryMutationError) as exc:
        await db.rollback()
        raise _error(409, "PRODUCT_LOCATION_CONFLICT", str(exc)) from exc


@router.delete("/{product_location_id}")
async def delete_product_location(
    product_location_id: int,
    payload: ProductLocationDelete,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, actor)
    await access.require(
        "product_location.manage",
        any_location=True,
    )
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRODUCT_LOCATION_DELETE",
            request_id=str(payload.request_id),
            request_hash=_hash(
                payload,
                product_location_id=product_location_id,
            ),
        )
        if replay is not None:
            replay_location_id = replay.get(
                "location_id",
                payload.location_id,
            )
            if (
                isinstance(replay_location_id, int)
                and replay_location_id > 0
            ):
                await access.require(
                    "product_location.manage",
                    replay_location_id,
                )
            await db.rollback()
            return replay

        scope = (
            await db.execute(
                select(
                    ProductLocation.location_id,
                    ProductLocation.product_variant_id,
                ).where(
                    ProductLocation.company_id
                    == actor.company_id,
                    ProductLocation.id
                    == product_location_id,
                )
            )
        ).one_or_none()
        if scope is None:
            raise _error(
                404,
                "PRODUCT_LOCATION_NOT_FOUND",
                "ربط الصنف بالموقع غير موجود.",
            )

        location_id = int(
            scope.location_id
        )
        if (
            payload.location_id
            is not None
            and payload.location_id
            != location_id
        ):
            raise _error(
                409,
                "PRODUCT_LOCATION_SCOPE_MISMATCH",
                "نطاق ربط الصنف بالموقع غير متطابق.",
            )

        await access.require(
            "product_location.manage",
            location_id,
        )
        await acquire_product_lifecycle_guards(
            db,
            actor.company_id,
            [
                scope.product_variant_id
            ],
            exclusive=True,
        )

        item = await db.scalar(
            select(ProductLocation)
            .where(
                ProductLocation.company_id
                == actor.company_id,
                ProductLocation.id
                == product_location_id,
            )
            .with_for_update()
        )
        if item is None:
            raise _error(
                404,
                "PRODUCT_LOCATION_NOT_FOUND",
                "ربط الصنف بالموقع غير موجود.",
            )
        if (
            item.version
            != payload.expected_version
        ):
            raise _error(
                409,
                "PRODUCT_LOCATION_VERSION_CONFLICT",
                "تغير الربط؛ حدّث البيانات وأعد المحاولة.",
                current_version=item.version,
            )

        blockers = await product_location_delete_blockers(
            db,
            actor.company_id,
            item.location_id,
            item.product_variant_id,
        )
        if blockers:
            raise _error(
                409,
                "PRODUCT_LOCATION_DELETE_BLOCKED",
                "لا يمكن حذف ربط مستخدم أو ذي سجل تاريخي.",
                blockers=blockers,
            )

        before = {
            "id": item.id,
            "location_id":
                item.location_id,
            "product_variant_id":
                item.product_variant_id,
            "operational_flags":
                validate_product_location_flags(
                    item.operational_flags
                ),
            "version":
                item.version,
        }
        await db.delete(item)
        record_domain_event(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            request_id=payload.request_id,
            event_type="ProductLocationRemoved",
            entity_type="ProductLocation",
            entity_id=item.id,
            reason=payload.reason,
            before=before,
            after=None,
        )

        response = {
            "message":
                "تم حذف الربط غير المستخدم.",
            "product_location_id":
                item.id,
            "location_id":
                location_id,
        }
        complete_idempotent_operation(
            idem,
            response,
        )
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except (
        IntegrityError,
        InventoryMutationError,
    ) as exc:
        await db.rollback()
        raise _error(
            409,
            "PRODUCT_LOCATION_CONFLICT",
            str(exc),
        ) from exc
