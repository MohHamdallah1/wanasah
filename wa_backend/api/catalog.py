"""Tenant-scoped product, variant, UOM conversion and barcode foundation."""

import base64
import hashlib
import hmac
import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from config import Config
from database import get_db
from gs1 import Gs1ParseError, parse_gs1
from inventory_access import InventoryAccess
from models import (
    Driver,
    Product,
    ProductBarcode,
    ProductBatch,
    ProductUomConversion,
    ProductVariant,
    SystemAuditLog,
    UOM,
)
from quantity import QuantityError, canonical_quantity, parse_quantity, validate_variant_quantity
from product_lifecycle import (
    ProductLifecycleTransitionError,
    acquire_product_lifecycle_guards,
    apply_variant_publish_transition,
    archive_blockers,
    record_domain_event,
    variant_snapshot,
)
from services import InventoryMutationError, begin_idempotent_operation, complete_idempotent_operation
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    apply_live_stock_active_variant_delta,
    refresh_live_stock_variants,
)


router = APIRouter(prefix="/catalog", tags=["Product Catalog"])
_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]*$")
_DIGITS_RE = re.compile(r"^\d+$")
_BARCODE_TYPES = {"EAN8", "EAN13", "UPC_A", "GTIN14", "GS1_128", "INTERNAL"}
_CONTROL_MODES = {"NONE", "OPTIONAL", "REQUIRED"}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _text(value: Any, field: str, maximum: int, *, optional: bool = False) -> Optional[str]:
    if value is None:
        if optional:
            return None
        raise ValueError(f"{field} مطلوب.")
    if not isinstance(value, str):
        raise ValueError(f"{field} يجب أن يكون نصاً.")
    clean = value.strip()
    if "\x00" in clean or len(clean) > maximum or (not clean and not optional):
        raise ValueError(f"{field} غير صالح.")
    return clean or None


def _code(value: Any) -> str:
    clean = _text(value, "code", 100)
    assert clean is not None
    clean = clean.upper()
    if not _CODE_RE.fullmatch(clean):
        raise ValueError("code يقبل A-Z والأرقام والنقاط والشرطة والشرطة السفلية فقط.")
    return clean


def _sku(value: Any) -> str:
    clean = _text(value, "sku", 100)
    assert clean is not None
    return clean.upper()


def _gtin(value: Any) -> Optional[str]:
    clean = _text(value, "gtin", 14, optional=True)
    if clean is None:
        return None
    if len(clean) not in {8, 12, 13, 14} or not _DIGITS_RE.fullmatch(clean):
        raise ValueError("GTIN يجب أن يكون 8 أو 12 أو 13 أو 14 رقماً.")
    digits = [int(char) for char in clean]
    expected = (10 - sum(
        digit * (3 if (len(digits) - 1 - index) % 2 == 0 else 1)
        for index, digit in enumerate(digits[:-1])
    ) % 10) % 10
    if digits[-1] != expected:
        raise ValueError("رقم تحقق GTIN غير صحيح.")
    return clean


def _request_hash(payload: BaseModel, **scope: Any) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    body.update(scope)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _error(status: int, code: str, message: str, **context: Any) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "context": context})


def _cursor(value: Optional[str]) -> int:
    if value is None:
        return 0
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("ascii")
        parsed = int(raw)
    except Exception as exc:
        raise _error(400, "INVALID_CURSOR", "Cursor الكتالوج غير صالح.") from exc
    if parsed <= 0:
        raise _error(400, "INVALID_CURSOR", "Cursor الكتالوج غير صالح.")
    return parsed


def _next_cursor(value: int) -> str:
    return base64.urlsafe_b64encode(str(value).encode("ascii")).decode("ascii").rstrip("=")


def _barcode_cursor_scope(
    *,
    company_id: int,
    variant_id: int,
    limit: int,
) -> str:
    encoded = json.dumps(
        {
            "company_id": int(company_id),
            "variant_id": int(variant_id),
            "limit": int(limit),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _barcode_cursor_signature(payload: bytes) -> bytes:
    return hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()


def _barcode_cursor(
    value: Optional[str],
    *,
    company_id: int,
    variant_id: int,
    limit: int,
) -> int:
    if value is None:
        return 0
    try:
        payload_part, signature_part = value.split(".", 1)
        payload = base64.urlsafe_b64decode(
            payload_part + "=" * (-len(payload_part) % 4)
        )
        signature = base64.urlsafe_b64decode(
            signature_part + "=" * (-len(signature_part) % 4)
        )
        if not hmac.compare_digest(
            signature,
            _barcode_cursor_signature(payload),
        ):
            raise ValueError("cursor signature mismatch")
        data = json.loads(payload.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"v", "after", "scope"}
            or data.get("v") != 1
            or not isinstance(data.get("after"), int)
            or data["after"] <= 0
            or data.get("scope")
            != _barcode_cursor_scope(
                company_id=company_id,
                variant_id=variant_id,
                limit=limit,
            )
        ):
            raise ValueError("cursor payload mismatch")
        return int(data["after"])
    except Exception as exc:
        raise _error(
            400,
            "INVALID_CURSOR",
            "Cursor الباركود غير صالح.",
        ) from exc


def _barcode_next_cursor(
    value: int,
    *,
    company_id: int,
    variant_id: int,
    limit: int,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "after": int(value),
            "scope": _barcode_cursor_scope(
                company_id=company_id,
                variant_id=variant_id,
                limit=limit,
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    payload_part = base64.urlsafe_b64encode(
        payload
    ).decode("ascii").rstrip("=")
    signature_part = base64.urlsafe_b64encode(
        _barcode_cursor_signature(payload)
    ).decode("ascii").rstrip("=")
    return f"{payload_part}.{signature_part}"


def _search_pattern(value: str) -> str:
    clean = value.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{clean}%"


def _utc_naive(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    if value.tzinfo is None:
        raise ValueError("التاريخ يجب أن يحتوي UTC offset.")
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _barcode_update_valid_to(
    *,
    row_valid_from: datetime,
    requested_valid_to: Optional[datetime],
    is_active: bool,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    valid_to = _utc_naive(requested_valid_to)
    if is_active or valid_to is not None:
        return valid_to

    current = (
        now.astimezone(timezone.utc).replace(tzinfo=None)
        if now is not None and now.tzinfo is not None
        else now
    ) or datetime.now(timezone.utc).replace(tzinfo=None)
    return current if current > row_valid_from else None


async def _require(db: AsyncSession, actor: Driver, permission: str) -> None:
    await InventoryAccess(db, actor).require(permission, any_location=True)


async def _uom_ids(db: AsyncSession, ids: set[int]) -> set[int]:
    if not ids:
        return set()
    return set((await db.scalars(select(UOM.id).where(UOM.id.in_(ids)))).all())


class ProductCreate(StrictRequest):
    request_id: UUID
    code: str = Field(max_length=100)
    name: str = Field(max_length=150)
    description: Optional[str] = Field(None, max_length=4000)
    brand: Optional[str] = Field(None, max_length=100)
    category: Optional[str] = Field(None, max_length=100)

    @field_validator("code", mode="before")
    @classmethod
    def code_value(cls, value: Any) -> str:
        return _code(value)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        return _text(value, "name", 150)  # type: ignore[return-value]

    @field_validator("description", "brand", "category", mode="before")
    @classmethod
    def optional_text(cls, value: Any, info) -> Optional[str]:
        limits = {"description": 4000, "brand": 100, "category": 100}
        return _text(value, info.field_name, limits[info.field_name], optional=True)


class ProductUpdate(ProductCreate):
    expected_version: int = Field(gt=0)


class VariantCreate(StrictRequest):
    request_id: UUID
    product_id: int = Field(gt=0)
    sku: str = Field(max_length=100)
    gtin: Optional[str] = Field(None, max_length=14)
    name: str = Field(max_length=200)
    base_uom_id: int = Field(gt=0)
    quantity_scale: int = Field(ge=0, le=6)
    quantity_step: Decimal
    lot_control_mode: Literal["NONE", "OPTIONAL", "REQUIRED"] = "REQUIRED"
    expiry_control_mode: Literal["NONE", "OPTIONAL", "REQUIRED"] = "REQUIRED"

    @field_validator("sku", mode="before")
    @classmethod
    def sku_value(cls, value: Any) -> str:
        return _sku(value)

    @field_validator("gtin", mode="before")
    @classmethod
    def gtin_value(cls, value: Any) -> Optional[str]:
        return _gtin(value)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        return _text(value, "name", 200)  # type: ignore[return-value]

    @field_validator("quantity_step", mode="before")
    @classmethod
    def step_value(cls, value: Any) -> Decimal:
        return parse_quantity(value, "quantity_step")

    @model_validator(mode="after")
    def validate_step_scale(self):
        validate_variant_quantity(
            self.quantity_step,
            quantity_scale=self.quantity_scale,
            quantity_step=self.quantity_step,
            field_name="quantity_step",
        )
        return self


class VariantUpdate(VariantCreate):
    expected_version: int = Field(gt=0)


class ConversionCreate(StrictRequest):
    request_id: UUID
    from_uom_id: int = Field(gt=0)
    to_uom_id: int = Field(gt=0)
    numerator: Decimal
    denominator: Decimal
    quantity_scale: int = Field(ge=0, le=6)

    @field_validator("numerator", "denominator", mode="before")
    @classmethod
    def exact_value(cls, value: Any, info) -> Decimal:
        return parse_quantity(value, info.field_name)

    @model_validator(mode="after")
    def distinct_units(self):
        if self.from_uom_id == self.to_uom_id:
            raise ValueError("وحدتا التحويل يجب أن تكونا مختلفتين.")
        return self


class ConversionUpdate(ConversionCreate):
    expected_version: int = Field(gt=0)


class BarcodeCreate(StrictRequest):
    request_id: UUID
    uom_id: int = Field(gt=0)
    barcode: str = Field(max_length=128)
    barcode_type: Literal["EAN8", "EAN13", "UPC_A", "GTIN14", "GS1_128", "INTERNAL"]
    is_primary: bool = False
    valid_from: Optional[datetime] = None
    valid_to: Optional[datetime] = None

    @field_validator("barcode", mode="before")
    @classmethod
    def barcode_value(cls, value: Any) -> str:
        return _text(value, "barcode", 128)  # type: ignore[return-value]

    @model_validator(mode="after")
    def validity(self):
        start = _utc_naive(self.valid_from)
        end = _utc_naive(self.valid_to)
        if (
            start is not None
            and end is not None
            and end <= start
        ):
            raise ValueError("valid_to يجب أن يكون بعد valid_from.")
        return self


class BarcodeUpdate(StrictRequest):
    request_id: UUID
    expected_version: int = Field(gt=0)
    is_primary: bool
    valid_to: Optional[datetime] = None
    is_active: bool


class Gs1Request(StrictRequest):
    value: str = Field(min_length=1, max_length=256)


class VariantResolveRequest(StrictRequest):
    ids: list[int] = Field(min_length=1, max_length=5000)

    @field_validator("ids")
    @classmethod
    def validate_ids(cls, values: list[int]) -> list[int]:
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("معرّفات الأصناف غير صالحة.")
        if len(values) != len(set(values)):
            raise ValueError("لا يجوز تكرار معرّف الصنف.")
        return values


class LifecycleCommand(StrictRequest):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("reason", mode="before")
    @classmethod
    def reason_value(cls, value: Any) -> str:
        return _text(value, "reason", 1000)  # type: ignore[return-value]


class CloseRecallCommand(LifecycleCommand):
    target_hold: Literal["NONE", "SALES_HOLD"] = "NONE"


def _product_row(row: Product) -> dict:
    return {
        "id": row.id, "code": row.code, "name": row.name,
        "description": row.description, "brand": row.brand, "category": row.category,
        "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _variant_row(row: ProductVariant, uom: UOM) -> dict:
    return {
        "id": row.id, "product_id": row.product_id, "sku": row.sku, "gtin": row.gtin,
        "name": row.name, "base_uom": {"id": uom.id, "code": uom.code, "name": uom.name},
        "quantity_scale": row.quantity_scale,
        "quantity_step": canonical_quantity(row.quantity_step),
        "lot_control_mode": row.lot_control_mode,
        "expiry_control_mode": row.expiry_control_mode,
        "lifecycle_status": row.lifecycle_status,
        "operational_hold": row.operational_hold,
        "lifecycle_revision": row.lifecycle_revision,
        "version": row.version,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "retired_at": row.retired_at.isoformat() if row.retired_at else None,
        "archived_at": row.archived_at.isoformat() if row.archived_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _conversion_row(row: ProductUomConversion, from_uom: UOM, to_uom: UOM) -> dict:
    return {
        "id": row.id, "product_variant_id": row.product_variant_id,
        "from_uom": {"id": from_uom.id, "code": from_uom.code, "name": from_uom.name},
        "to_uom": {"id": to_uom.id, "code": to_uom.code, "name": to_uom.name},
        "numerator": canonical_quantity(row.numerator), "denominator": canonical_quantity(row.denominator),
        "quantity_scale": row.quantity_scale, "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _barcode_row(row: ProductBarcode, uom: UOM) -> dict:
    return {
        "id": row.id, "product_variant_id": row.product_variant_id,
        "uom": {"id": uom.id, "code": uom.code, "name": uom.name},
        "barcode": row.barcode, "barcode_type": row.barcode_type,
        "is_primary": row.is_primary,
        "valid_from": row.valid_from.isoformat() if row.valid_from else None,
        "valid_to": row.valid_to.isoformat() if row.valid_to else None,
        "is_active": row.is_active, "version": row.version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _audit(db: AsyncSession, actor: Driver, target: str, action: str, old: Any, new: Any) -> None:
    db.add(SystemAuditLog(
        company_id=actor.company_id, admin_id=actor.id, target_id=target, action_type=action,
        old_value=json.dumps(old, ensure_ascii=False, default=str) if old is not None else None,
        new_value=json.dumps(new, ensure_ascii=False, default=str) if new is not None else None,
    ))


@router.get("/uoms")
async def list_uoms(
    db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    rows = (await db.scalars(select(UOM).order_by(UOM.code.asc()))).all()
    return {"items": [{"id": row.id, "code": row.code, "name": row.name} for row in rows]}


@router.get("/products")
async def list_products(
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    after_id = _cursor(cursor)
    stmt = select(Product).where(Product.company_id == actor.company_id, Product.id > after_id)
    if search:
        pattern = _search_pattern(search)
        stmt = stmt.where(or_(func.lower(Product.name).like(pattern, escape="\\"), func.lower(Product.code).like(pattern, escape="\\")))
    rows = list((await db.scalars(stmt.order_by(Product.id.asc()).limit(limit + 1))).all())
    page, has_more = rows[:limit], len(rows) > limit
    return {"items": [_product_row(row) for row in page], "next_cursor": _next_cursor(page[-1].id) if has_more else None, "has_more": has_more}


@router.post("/products", status_code=201)
async def create_product(
    payload: ProductCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(db, company_id=actor.company_id, actor_id=actor.id, operation="CATALOG_PRODUCT_CREATE", request_id=str(payload.request_id), request_hash=_request_hash(payload))
        if replay is not None:
            await db.rollback()
            return replay
        row = Product(company_id=actor.company_id, code=payload.code, name=payload.name, description=payload.description, brand=payload.brand, category=payload.category)
        db.add(row)
        await db.flush()
        response = {"message": "تم إنشاء عائلة المنتج كبيانات مرجعية.", "product": _product_row(row)}
        _audit(db, actor, f"Product_{row.id}", "CATALOG_PRODUCT_CREATED", None, response["product"])
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "PRODUCT_CODE_CONFLICT", "كود المنتج مستخدم داخل الشركة.") from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise _error(409, "IDEMPOTENCY_CONFLICT", str(exc)) from exc


@router.patch("/products/{product_id}")
async def update_product(
    product_id: int, payload: ProductUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(db, company_id=actor.company_id, actor_id=actor.id, operation="CATALOG_PRODUCT_UPDATE", request_id=str(payload.request_id), request_hash=_request_hash(payload, product_id=product_id))
        if replay is not None:
            await db.rollback()
            return replay
        row = await db.scalar(select(Product).where(Product.company_id == actor.company_id, Product.id == product_id).with_for_update())
        if row is None:
            raise _error(404, "PRODUCT_NOT_FOUND", "المنتج غير موجود.")
        if row.version != payload.expected_version:
            raise _error(409, "PRODUCT_VERSION_CONFLICT", "تغير المنتج؛ حدّث البيانات وأعد المحاولة.", current_version=row.version)
        old = _product_row(row)
        for field in ("code", "name", "description", "brand", "category"):
            setattr(row, field, getattr(payload, field))
        row.version += 1
        await db.flush()
        response = {"message": "تم تحديث بيانات المنتج.", "product": _product_row(row)}
        _audit(db, actor, f"Product_{row.id}", "CATALOG_PRODUCT_UPDATED", old, response["product"])
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "PRODUCT_CODE_CONFLICT", "كود المنتج مستخدم داخل الشركة.") from exc


@router.get("/variants")
async def list_variants(
    product_id: Optional[int] = Query(None, gt=0),
    lifecycle_status: Optional[Literal["DRAFT", "ACTIVE", "RETIRING", "ARCHIVED"]] = Query(None),
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(None, max_length=512), limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    stmt = select(ProductVariant, UOM).join(UOM, UOM.id == ProductVariant.base_uom_id).where(ProductVariant.company_id == actor.company_id, ProductVariant.id > _cursor(cursor))
    if product_id is not None:
        stmt = stmt.where(ProductVariant.product_id == product_id)
    if lifecycle_status is not None:
        stmt = stmt.where(ProductVariant.lifecycle_status == lifecycle_status)
    if search:
        pattern = _search_pattern(search)
        stmt = stmt.where(or_(func.lower(ProductVariant.name).like(pattern, escape="\\"), func.lower(ProductVariant.sku).like(pattern, escape="\\")))
    rows = list((await db.execute(stmt.order_by(ProductVariant.id.asc()).limit(limit + 1))).all())
    page, has_more = rows[:limit], len(rows) > limit
    return {"items": [_variant_row(row, uom) for row, uom in page], "next_cursor": _next_cursor(page[-1][0].id) if has_more else None, "has_more": has_more}


@router.post("/variants/resolve")
async def resolve_variants(
    payload: VariantResolveRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    rows = (
        await db.execute(
            select(ProductVariant, UOM)
            .join(UOM, UOM.id == ProductVariant.base_uom_id)
            .where(
                ProductVariant.company_id == actor.company_id,
                ProductVariant.id.in_(payload.ids),
            )
            .order_by(ProductVariant.id.asc())
        )
    ).all()
    return {
        "items": [_variant_row(row, uom) for row, uom in rows],
        "next_cursor": None,
        "has_more": False,
    }


@router.post("/variants", status_code=201)
async def create_variant(
    payload: VariantCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(db, company_id=actor.company_id, actor_id=actor.id, operation="CATALOG_VARIANT_CREATE", request_id=str(payload.request_id), request_hash=_request_hash(payload))
        if replay is not None:
            await db.rollback()
            return replay
        if await db.scalar(select(Product.id).where(Product.company_id == actor.company_id, Product.id == payload.product_id)) is None:
            raise _error(404, "PRODUCT_NOT_FOUND", "عائلة المنتج غير موجودة.")
        if payload.base_uom_id not in await _uom_ids(db, {payload.base_uom_id}):
            raise _error(422, "UOM_NOT_FOUND", "وحدة الأساس غير موجودة.")
        row = ProductVariant(
            company_id=actor.company_id, product_id=payload.product_id, sku=payload.sku, gtin=payload.gtin,
            name=payload.name, base_uom_id=payload.base_uom_id, quantity_scale=payload.quantity_scale,
            quantity_step=payload.quantity_step, lot_control_mode=payload.lot_control_mode,
            expiry_control_mode=payload.expiry_control_mode, lifecycle_status="DRAFT", operational_hold="NONE",
            packs_per_carton=1,
        )
        db.add(row)
        await db.flush()
        uom = await db.get(UOM, row.base_uom_id)
        response = {"message": "تم إنشاء SKU بحالة مسودة دون سعر أو ربط مستودع.", "variant": _variant_row(row, uom)}
        _audit(db, actor, f"ProductVariant_{row.id}", "CATALOG_VARIANT_CREATED", None, response["variant"])
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "VARIANT_IDENTITY_CONFLICT", "SKU أو GTIN مستخدم داخل الشركة.") from exc
    except (InventoryMutationError, QuantityError) as exc:
        await db.rollback()
        raise _error(409, "VARIANT_CONFLICT", str(exc)) from exc


@router.patch("/variants/{variant_id}")
async def update_variant(
    variant_id: int, payload: VariantUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(db, company_id=actor.company_id, actor_id=actor.id, operation="CATALOG_VARIANT_UPDATE", request_id=str(payload.request_id), request_hash=_request_hash(payload, variant_id=variant_id))
        if replay is not None:
            await db.rollback()
            return replay
        row = await db.scalar(select(ProductVariant).where(ProductVariant.company_id == actor.company_id, ProductVariant.id == variant_id).with_for_update())
        if row is None:
            raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
        if row.version != payload.expected_version:
            raise _error(409, "VARIANT_VERSION_CONFLICT", "تغير الصنف؛ حدّث البيانات وأعد المحاولة.", current_version=row.version)
        if row.lifecycle_status != "DRAFT":
            raise _error(409, "VARIANT_STRUCTURE_LOCKED", "الحقول البنيوية قابلة للتعديل في DRAFT فقط.")
        if await db.scalar(select(Product.id).where(Product.company_id == actor.company_id, Product.id == payload.product_id)) is None:
            raise _error(404, "PRODUCT_NOT_FOUND", "عائلة المنتج غير موجودة.")
        if payload.base_uom_id not in await _uom_ids(db, {payload.base_uom_id}):
            raise _error(422, "UOM_NOT_FOUND", "وحدة الأساس غير موجودة.")
        old = {"product_id": row.product_id, "sku": row.sku, "gtin": row.gtin, "name": row.name, "base_uom_id": row.base_uom_id, "quantity_scale": row.quantity_scale, "quantity_step": canonical_quantity(row.quantity_step), "lot_control_mode": row.lot_control_mode, "expiry_control_mode": row.expiry_control_mode, "version": row.version}
        for field in ("product_id", "sku", "gtin", "name", "base_uom_id", "quantity_scale", "quantity_step", "lot_control_mode", "expiry_control_mode"):
            setattr(row, field, getattr(payload, field))
        row.version += 1
        await db.flush()
        uom = await db.get(UOM, row.base_uom_id)
        response = {"message": "تم تحديث بنية الـSKU المسودة.", "variant": _variant_row(row, uom)}
        _audit(db, actor, f"ProductVariant_{row.id}", "CATALOG_VARIANT_UPDATED", old, response["variant"])
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "VARIANT_IDENTITY_CONFLICT", "SKU أو GTIN مستخدم داخل الشركة.") from exc


async def _draft_variant(db: AsyncSession, company_id: int, variant_id: int) -> ProductVariant:
    row = await db.scalar(select(ProductVariant).where(ProductVariant.company_id == company_id, ProductVariant.id == variant_id).with_for_update())
    if row is None:
        raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
    if row.lifecycle_status != "DRAFT":
        raise _error(409, "UOM_STRUCTURE_LOCKED", "تحويلات UOM تصبح immutable بعد نشر الصنف.")
    return row


@router.get("/variants/{variant_id}/conversions")
async def list_conversions(variant_id: int, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.read")
    if await db.scalar(select(ProductVariant.id).where(ProductVariant.company_id == actor.company_id, ProductVariant.id == variant_id)) is None:
        raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
    # SQLAlchemy cannot disambiguate the same UOM entity twice without aliases; resolve the bounded UOM catalog once.
    conversions = (await db.scalars(select(ProductUomConversion).where(ProductUomConversion.company_id == actor.company_id, ProductUomConversion.product_variant_id == variant_id).order_by(ProductUomConversion.id))).all()
    uoms = {row.id: row for row in (await db.scalars(select(UOM).where(UOM.id.in_({u for c in conversions for u in (c.from_uom_id, c.to_uom_id)})))).all()} if conversions else {}
    return {"items": [_conversion_row(row, uoms[row.from_uom_id], uoms[row.to_uom_id]) for row in conversions]}


@router.post("/variants/{variant_id}/conversions", status_code=201)
async def create_conversion(variant_id: int, payload: ConversionCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(db, company_id=actor.company_id, actor_id=actor.id, operation="CATALOG_UOM_CONVERSION_CREATE", request_id=str(payload.request_id), request_hash=_request_hash(payload, variant_id=variant_id))
        if replay is not None:
            await db.rollback()
            return replay
        await _draft_variant(db, actor.company_id, variant_id)
        if await _uom_ids(db, {payload.from_uom_id, payload.to_uom_id}) != {payload.from_uom_id, payload.to_uom_id}:
            raise _error(422, "UOM_NOT_FOUND", "إحدى وحدات التحويل غير موجودة.")
        row = ProductUomConversion(company_id=actor.company_id, product_variant_id=variant_id, from_uom_id=payload.from_uom_id, to_uom_id=payload.to_uom_id, numerator=payload.numerator, denominator=payload.denominator, quantity_scale=payload.quantity_scale)
        db.add(row)
        await db.flush()
        from_uom, to_uom = await db.get(UOM, row.from_uom_id), await db.get(UOM, row.to_uom_id)
        response = {"message": "تمت إضافة تحويل UOM إلى المسودة.", "conversion": _conversion_row(row, from_uom, to_uom)}
        _audit(db, actor, f"ProductUomConversion_{row.id}", "CATALOG_UOM_CONVERSION_CREATED", None, response["conversion"])
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "UOM_CONVERSION_CONFLICT", "تحويل UOM موجود مسبقاً أو غير صالح.") from exc


@router.patch("/conversions/{conversion_id}")
async def update_conversion(
    conversion_id: int,
    payload: ConversionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="CATALOG_UOM_CONVERSION_UPDATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload, conversion_id=conversion_id),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await db.scalar(
            select(ProductUomConversion).where(
                ProductUomConversion.company_id == actor.company_id,
                ProductUomConversion.id == conversion_id,
            ).with_for_update()
        )
        if row is None:
            raise _error(404, "UOM_CONVERSION_NOT_FOUND", "تحويل UOM غير موجود.")
        await _draft_variant(db, actor.company_id, row.product_variant_id)
        if row.version != payload.expected_version:
            raise _error(
                409,
                "UOM_CONVERSION_VERSION_CONFLICT",
                "تغير تحويل UOM؛ حدّث البيانات وأعد المحاولة.",
                current_version=row.version,
            )
        requested_uoms = {payload.from_uom_id, payload.to_uom_id}
        if await _uom_ids(db, requested_uoms) != requested_uoms:
            raise _error(422, "UOM_NOT_FOUND", "إحدى وحدات التحويل غير موجودة.")
        old = {
            "from_uom_id": row.from_uom_id,
            "to_uom_id": row.to_uom_id,
            "numerator": canonical_quantity(row.numerator),
            "denominator": canonical_quantity(row.denominator),
            "quantity_scale": row.quantity_scale,
            "version": row.version,
        }
        row.from_uom_id = payload.from_uom_id
        row.to_uom_id = payload.to_uom_id
        row.numerator = payload.numerator
        row.denominator = payload.denominator
        row.quantity_scale = payload.quantity_scale
        row.version += 1
        await db.flush()
        from_uom = await db.get(UOM, row.from_uom_id)
        to_uom = await db.get(UOM, row.to_uom_id)
        response = {
            "message": "تم تحديث تحويل UOM في المسودة.",
            "conversion": _conversion_row(row, from_uom, to_uom),
        }
        _audit(
            db,
            actor,
            f"ProductUomConversion_{row.id}",
            "CATALOG_UOM_CONVERSION_UPDATED",
            old,
            response["conversion"],
        )
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "UOM_CONVERSION_CONFLICT", "تحويل UOM موجود مسبقاً أو غير صالح.") from exc


@router.get("/variants/{variant_id}/barcodes")
async def list_barcodes(
    variant_id: int,
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    if await db.scalar(
        select(ProductVariant.id).where(
            ProductVariant.company_id == actor.company_id,
            ProductVariant.id == variant_id,
        )
    ) is None:
        raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")

    after_id = _barcode_cursor(
        cursor,
        company_id=actor.company_id,
        variant_id=variant_id,
        limit=limit,
    )
    rows = (
        await db.execute(
            select(ProductBarcode, UOM)
            .join(UOM, UOM.id == ProductBarcode.uom_id)
            .where(
                ProductBarcode.company_id == actor.company_id,
                ProductBarcode.product_variant_id == variant_id,
                ProductBarcode.id > after_id,
            )
            .order_by(ProductBarcode.id.asc())
            .limit(limit + 1)
        )
    ).all()
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [
            _barcode_row(row, uom)
            for row, uom in page
        ],
        "next_cursor": (
            _barcode_next_cursor(
                page[-1][0].id,
                company_id=actor.company_id,
                variant_id=variant_id,
                limit=limit,
            )
            if has_more and page
            else None
        ),
        "has_more": has_more,
    }


@router.post("/variants/{variant_id}/barcodes", status_code=201)
async def create_barcode(variant_id: int, payload: BarcodeCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(db, company_id=actor.company_id, actor_id=actor.id, operation="CATALOG_BARCODE_CREATE", request_id=str(payload.request_id), request_hash=_request_hash(payload, variant_id=variant_id))
        if replay is not None:
            await db.rollback()
            return replay
        if await db.scalar(select(ProductVariant.id).where(ProductVariant.company_id == actor.company_id, ProductVariant.id == variant_id).with_for_update()) is None:
            raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
        if payload.uom_id not in await _uom_ids(db, {payload.uom_id}):
            raise _error(422, "UOM_NOT_FOUND", "وحدة الباركود غير موجودة.")
        if payload.barcode_type != "INTERNAL":
            if payload.barcode_type == "GS1_128":
                parse_gs1(payload.barcode)
            else:
                _gtin(payload.barcode)
        valid_from = (
            _utc_naive(payload.valid_from)
            or datetime.now(timezone.utc).replace(
                tzinfo=None
            )
        )
        row = ProductBarcode(company_id=actor.company_id, product_variant_id=variant_id, uom_id=payload.uom_id, barcode=payload.barcode, barcode_type=payload.barcode_type, is_primary=payload.is_primary, valid_from=valid_from, valid_to=_utc_naive(payload.valid_to), is_active=True)
        db.add(row)
        await db.flush()
        uom = await db.get(UOM, row.uom_id)
        response = {"message": "تمت إضافة الباركود.", "barcode": _barcode_row(row, uom)}
        _audit(db, actor, f"ProductBarcode_{row.id}", "CATALOG_BARCODE_CREATED", None, response["barcode"])
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except Gs1ParseError as exc:
        await db.rollback()
        raise _error(422, "GS1_INVALID", str(exc)) from exc
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "BARCODE_CONFLICT", "الباركود الفعال أو الباركود الأساسي مستخدم مسبقاً.") from exc


@router.patch("/barcodes/{barcode_id}")
async def update_barcode(barcode_id: int, payload: BarcodeUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.manage")
    try:
        record, replay = await begin_idempotent_operation(db, company_id=actor.company_id, actor_id=actor.id, operation="CATALOG_BARCODE_UPDATE", request_id=str(payload.request_id), request_hash=_request_hash(payload, barcode_id=barcode_id))
        if replay is not None:
            await db.rollback()
            return replay
        row = await db.scalar(select(ProductBarcode).where(ProductBarcode.company_id == actor.company_id, ProductBarcode.id == barcode_id).with_for_update())
        if row is None:
            raise _error(404, "BARCODE_NOT_FOUND", "الباركود غير موجود.")
        if row.version != payload.expected_version:
            raise _error(409, "BARCODE_VERSION_CONFLICT", "تغير الباركود؛ حدّث البيانات وأعد المحاولة.", current_version=row.version)
        valid_to = _barcode_update_valid_to(
            row_valid_from=row.valid_from,
            requested_valid_to=payload.valid_to,
            is_active=payload.is_active,
        )
        if valid_to is not None and valid_to <= row.valid_from:
            raise _error(422, "BARCODE_VALIDITY_INVALID", "valid_to يجب أن يكون بعد valid_from.")
        old = {"is_primary": row.is_primary, "valid_to": row.valid_to, "is_active": row.is_active, "version": row.version}
        row.is_primary, row.valid_to, row.is_active = payload.is_primary, valid_to, payload.is_active
        row.version += 1
        await db.flush()
        uom = await db.get(UOM, row.uom_id)
        response = {"message": "تم تحديث صلاحية الباركود دون حذف تاريخه.", "barcode": _barcode_row(row, uom)}
        _audit(db, actor, f"ProductBarcode_{row.id}", "CATALOG_BARCODE_UPDATED", old, response["barcode"])
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "BARCODE_CONFLICT", "الباركود الفعال أو الأساسي يتعارض مع سجل آخر.") from exc


@router.post("/gs1/parse")
async def parse_gs1_endpoint(payload: Gs1Request, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.read")
    try:
        parsed = parse_gs1(payload.value)
    except Gs1ParseError as exc:
        raise _error(422, "GS1_INVALID", str(exc)) from exc
    return {"gtin": parsed.gtin, "lot": parsed.lot, "expiry_date": parsed.expiry_date, "serial": parsed.serial}


async def _run_variant_state_command(
    *,
    variant_id: int,
    payload: LifecycleCommand,
    command: str,
    permission: str,
    db: AsyncSession,
    actor: Driver,
) -> dict:
    await _require(db, actor, permission)
    operation = f"CATALOG_VARIANT_{command.upper().replace('-', '_')}"
    request_hash = _request_hash(payload, variant_id=variant_id, command=command)
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation=operation,
            request_id=str(payload.request_id),
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        await acquire_product_lifecycle_guards(
            db, actor.company_id, [variant_id], exclusive=True,
        )
        row = await db.scalar(
            select(ProductVariant).where(
                ProductVariant.company_id == actor.company_id,
                ProductVariant.id == variant_id,
            ).with_for_update()
        )
        if row is None:
            raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
        if row.version != payload.expected_version:
            raise _error(
                409,
                "VARIANT_VERSION_CONFLICT",
                "تغير الصنف؛ حدّث البيانات وأعد المحاولة.",
                current_version=row.version,
            )

        before = variant_snapshot(row)
        was_active = before["lifecycle_status"] == "ACTIVE"
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        event_type: str
        message: str

        if command == "publish":
            try:
                event_type, message = apply_variant_publish_transition(row, now)
            except ProductLifecycleTransitionError as exc:
                raise _error(
                    exc.status_code,
                    exc.code,
                    exc.message,
                ) from exc
        elif command == "retire":
            if row.lifecycle_status != "ACTIVE":
                raise _error(409, "PRODUCT_RETIRE_TRANSITION_INVALID", "التقاعد مسموح للصنف الفعال فقط.")
            row.lifecycle_status = "RETIRING"
            row.retired_at = now
            event_type, message = "ProductRetired", "دخل الصنف مرحلة التقاعد."
        elif command == "restore":
            if row.lifecycle_status not in {"RETIRING", "ARCHIVED"}:
                raise _error(409, "PRODUCT_RESTORE_TRANSITION_INVALID", "الاستعادة مسموحة للصنف المتقاعد أو المؤرشف فقط.")
            if row.operational_hold == "RECALL":
                raise _error(409, "PRODUCT_RECALL_OPEN", "يجب إغلاق الاستدعاء قبل استعادة الصنف.")
            if not row.sku.strip() or not row.name.strip() or row.base_uom_id is None:
                raise _error(409, "PRODUCT_RESTORE_READINESS_FAILED", "هوية الصنف ووحدة الأساس غير مكتملة.")
            if row.lot_control_mode not in _CONTROL_MODES or row.expiry_control_mode not in _CONTROL_MODES:
                raise _error(409, "PRODUCT_RESTORE_READINESS_FAILED", "سياسة الدفعة أو الصلاحية غير صالحة.")
            row.lifecycle_status = "ACTIVE"
            row.retired_at = None
            row.archived_at = None
            event_type, message = "ProductRestored", "تمت استعادة الصنف إلى الحالة الفعالة."
        elif command == "archive":
            if row.lifecycle_status != "RETIRING":
                raise _error(409, "PRODUCT_ARCHIVE_TRANSITION_INVALID", "الأرشفة مسموحة من RETIRING فقط.")
            if row.operational_hold != "NONE":
                raise _error(409, "PRODUCT_HOLD_OPEN", "يجب إغلاق الإيقاف التشغيلي قبل الأرشفة.")
            blockers = await archive_blockers(db, actor.company_id, variant_id)
            if blockers:
                raise _error(
                    409,
                    "PRODUCT_ARCHIVE_BLOCKED",
                    "لا يمكن أرشفة الصنف قبل معالجة جميع الموانع.",
                    variant_id=variant_id,
                    blockers=blockers,
                )
            row.lifecycle_status = "ARCHIVED"
            row.archived_at = now
            event_type, message = "ProductArchived", "تمت أرشفة الصنف بعد فحص الموانع تحت القفل."
        elif command == "sales-hold":
            if row.lifecycle_status not in {"ACTIVE", "RETIRING"} or row.operational_hold != "NONE":
                raise _error(409, "PRODUCT_SALES_HOLD_TRANSITION_INVALID", "إيقاف البيع يتطلب صنفاً فعالاً أو متقاعداً بلا إيقاف قائم.")
            row.operational_hold = "SALES_HOLD"
            event_type, message = "ProductSalesHoldPlaced", "تم إيقاف بيع وتحميل الصنف."
        elif command == "release-sales-hold":
            if row.operational_hold != "SALES_HOLD":
                raise _error(409, "PRODUCT_SALES_HOLD_RELEASE_INVALID", "لا يوجد إيقاف بيع قابل للتحرير.")
            row.operational_hold = "NONE"
            event_type, message = "ProductSalesHoldReleased", "تم تحرير إيقاف البيع."
        elif command == "recall":
            if row.lifecycle_status not in {"ACTIVE", "RETIRING"} or row.operational_hold not in {"NONE", "SALES_HOLD"}:
                raise _error(409, "PRODUCT_RECALL_TRANSITION_INVALID", "لا يمكن إصدار الاستدعاء من الحالة الحالية.")
            row.operational_hold = "RECALL"
            event_type, message = "ProductRecallIssued", "تم إصدار استدعاء الصنف."
        elif command == "close-recall":
            if row.operational_hold != "RECALL":
                raise _error(409, "PRODUCT_RECALL_CLOSE_INVALID", "لا يوجد استدعاء مفتوح.")
            completion_blockers = [
                item for item in await archive_blockers(db, actor.company_id, variant_id)
                if item["code"] in {
                    "INVENTORY_BALANCE", "OPEN_TRANSFER", "ACTIVE_ROUTE_LOAD",
                    "OPEN_CUSTODY", "OPEN_SHORTAGE",
                }
            ]
            if completion_blockers:
                raise _error(
                    409,
                    "PRODUCT_RECALL_COMPLETION_REQUIRED",
                    "لا يمكن إغلاق الاستدعاء قبل إنهاء المخزون والمستندات المفتوحة.",
                    variant_id=variant_id,
                    blockers=completion_blockers,
                )
            row.operational_hold = payload.target_hold if isinstance(payload, CloseRecallCommand) else "NONE"
            event_type, message = "ProductRecallClosed", "تم إغلاق الاستدعاء بعد فحص الاكتمال."
        else:
            raise RuntimeError("Unknown lifecycle command")

        row.lifecycle_revision += 1
        row.version += 1
        row.updated_at = now
        after = variant_snapshot(row)
        record_domain_event(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            request_id=payload.request_id,
            event_type=event_type,
            entity_type="ProductVariant",
            entity_id=row.id,
            reason=payload.reason,
            before=before,
            after=after,
        )
        await db.flush()
        is_active_now = row.lifecycle_status == "ACTIVE"
        if was_active != is_active_now:
            await apply_live_stock_active_variant_delta(
                db,
                company_id=actor.company_id,
                delta=1 if is_active_now else -1,
            )
        await refresh_live_stock_variants(
            db,
            company_id=actor.company_id,
            variant_ids=[row.id],
        )
        uom = await db.get(UOM, row.base_uom_id)
        response = {"message": message, "variant": _variant_row(row, uom)}
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(409, "PRODUCT_STATE_CONFLICT", "حدث تعارض متزامن أثناء تغيير حالة الصنف.") from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise _error(409, "IDEMPOTENCY_CONFLICT", str(exc)) from exc
    except LiveStockProjectionError as exc:
        await db.rollback()
        raise _error(
            500,
            "LIVE_STOCK_PROJECTION_FAILED",
            "تعذر تحديث عرض المخزون الحي بأمان.",
        ) from exc


@router.post("/variants/{variant_id}/publish")
async def publish_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="publish", permission="catalog.publish", db=db, actor=actor)


@router.post("/variants/{variant_id}/delete-draft")
async def delete_draft_variant(
    variant_id: int,
    payload: LifecycleCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.manage")
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="CATALOG_VARIANT_DELETE_DRAFT",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload, variant_id=variant_id),
        )
        if replay is not None:
            await db.rollback()
            return replay
        await acquire_product_lifecycle_guards(
            db, actor.company_id, [variant_id], exclusive=True,
        )
        row = await db.scalar(
            select(ProductVariant).where(
                ProductVariant.company_id == actor.company_id,
                ProductVariant.id == variant_id,
            ).with_for_update()
        )
        if row is None:
            raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
        if row.version != payload.expected_version:
            raise _error(
                409, "VARIANT_VERSION_CONFLICT",
                "تغير الصنف؛ حدّث البيانات وأعد المحاولة.",
                current_version=row.version,
            )
        if row.lifecycle_status != "DRAFT" or row.operational_hold != "NONE":
            raise _error(
                409, "PRODUCT_DELETE_DRAFT_TRANSITION_INVALID",
                "الحذف النهائي مسموح لمسودة غير منشورة وغير موقوفة فقط.",
            )
        blockers = await archive_blockers(db, actor.company_id, variant_id)
        batch_id = await db.scalar(
            select(ProductBatch.id).where(
                ProductBatch.company_id == actor.company_id,
                ProductBatch.product_variant_id == variant_id,
            ).limit(1)
        )
        if batch_id is not None:
            blockers.append({"code": "PRODUCT_BATCH", "count": 1, "sample_id": int(batch_id)})
        if blockers:
            raise _error(
                409, "PRODUCT_DRAFT_DELETE_BLOCKED",
                "لا يمكن حذف مسودة لها مراجع تشغيلية.",
                variant_id=variant_id, blockers=blockers,
            )
        before = variant_snapshot(row)
        await db.execute(delete(ProductBarcode).where(
            ProductBarcode.company_id == actor.company_id,
            ProductBarcode.product_variant_id == variant_id,
        ))
        await db.execute(delete(ProductUomConversion).where(
            ProductUomConversion.company_id == actor.company_id,
            ProductUomConversion.product_variant_id == variant_id,
        ))
        await db.delete(row)
        record_domain_event(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            request_id=payload.request_id,
            event_type="ProductDraftDeleted",
            entity_type="ProductVariant",
            entity_id=variant_id,
            reason=payload.reason,
            before=before,
            after=None,
        )
        response = {"message": "تم حذف مسودة الصنف غير المستخدمة.", "variant_id": variant_id}
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except IntegrityError as exc:
        await db.rollback()
        raise _error(
            409, "PRODUCT_DRAFT_DELETE_BLOCKED",
            "لا يمكن حذف المسودة لوجود مرجع مرتبط بها.",
        ) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise _error(409, "IDEMPOTENCY_CONFLICT", str(exc)) from exc


@router.post("/variants/{variant_id}/retire")
async def retire_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="retire", permission="catalog.retire", db=db, actor=actor)


@router.post("/variants/{variant_id}/restore")
async def restore_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="restore", permission="catalog.restore", db=db, actor=actor)


@router.get("/variants/{variant_id}/archive-preflight")
async def variant_archive_preflight(variant_id: int, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.archive")
    row = await db.scalar(select(ProductVariant).where(ProductVariant.company_id == actor.company_id, ProductVariant.id == variant_id))
    if row is None:
        raise _error(404, "VARIANT_NOT_FOUND", "الصنف غير موجود.")
    blockers = await archive_blockers(db, actor.company_id, variant_id)
    return {
        "variant_id": variant_id,
        "lifecycle_status": row.lifecycle_status,
        "version": row.version,
        "can_archive": row.lifecycle_status == "RETIRING" and row.operational_hold == "NONE" and not blockers,
        "blockers": blockers,
    }


@router.post("/variants/{variant_id}/archive")
async def archive_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="archive", permission="catalog.archive", db=db, actor=actor)


@router.post("/variants/{variant_id}/sales-hold")
async def place_variant_sales_hold(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="sales-hold", permission="catalog.hold", db=db, actor=actor)


@router.post("/variants/{variant_id}/release-sales-hold")
async def release_variant_sales_hold(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="release-sales-hold", permission="catalog.hold", db=db, actor=actor)


@router.post("/variants/{variant_id}/recall")
async def recall_variant(variant_id: int, payload: LifecycleCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="recall", permission="catalog.hold", db=db, actor=actor)


@router.post("/variants/{variant_id}/close-recall")
async def close_variant_recall(variant_id: int, payload: CloseRecallCommand, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await _run_variant_state_command(variant_id=variant_id, payload=payload, command="close-recall", permission="catalog.hold", db=db, actor=actor)
