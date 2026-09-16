"""Dead-simple product UX backed by catalog and temporal pricing engines."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.pricing.core import PricingError
from domains.simple_products.service import (
    SimpleProductError, SimpleProductSpec, assert_simple_pricing_mode,
    clean_text, create_products_and_prices, current_default_book,
    current_prices, current_primary_barcodes, list_families, load_company,
    load_uoms, parse_optional_money, resolve_price_pair,
    simple_compatibility, update_prices,
)
from inventory_access import InventoryAccess
from models import Driver, Product, ProductImportJob, ProductImportRow, ProductVariant, SystemAuditLog
from product_import_queue import enqueue_new_import, requeue_import, retry_failed_import
from services import InventoryMutationError, begin_idempotent_operation, complete_idempotent_operation

router = APIRouter(prefix="/simple-products", tags=["Simple Products"])
MAX_IMPORT_FILE_BYTES = 8 * 1024 * 1024
_ALLOWED_IMPORT_SUFFIXES = {".csv", ".xlsx"}
_CANONICAL_MAPPING_FIELDS = {
    "name", "family", "units_per_carton", "carton_price", "unit_price",
    "unit_barcode", "carton_barcode",
}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimpleProductCreate(StrictRequest):
    request_id: UUID
    name: str = Field(min_length=1, max_length=200)
    family_id: int | None = Field(None, gt=0)
    family_name: str | None = Field(None, max_length=150)
    units_per_carton: int = Field(gt=0, le=1_000_000)
    carton_price: Decimal | None = None
    unit_price: Decimal | None = None
    unit_barcode: str | None = Field(None, max_length=128)
    carton_barcode: str | None = Field(None, max_length=128)

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        result = clean_text(value, "اسم المنتج", 200)
        assert result is not None
        return result

    @field_validator("family_name", mode="before")
    @classmethod
    def family_value(cls, value: Any) -> str | None:
        return clean_text(value, "العائلة", 150, optional=True)

    @field_validator("unit_barcode", "carton_barcode", mode="before")
    @classmethod
    def barcode_value(cls, value: Any, info) -> str | None:
        label = "باركود الحبة" if info.field_name == "unit_barcode" else "باركود الكرتونة"
        return clean_text(value, label, 128, optional=True)

    @field_validator("carton_price", "unit_price", mode="before")
    @classmethod
    def price_value(cls, value: Any, info) -> Decimal | None:
        label = "سعر الكرتونة" if info.field_name == "carton_price" else "سعر الحبة"
        return parse_optional_money(value, label)

    @model_validator(mode="after")
    def product_contract(self):
        if self.family_id is not None and self.family_name is not None:
            raise ValueError("اختر عائلة موجودة أو اكتب عائلة جديدة، وليس الاثنين.")
        resolve_price_pair(units_per_carton=self.units_per_carton,
                           carton_price=self.carton_price, unit_price=self.unit_price)
        return self


class SimplePriceUpdate(StrictRequest):
    request_id: UUID
    carton_price: Decimal | None = None
    unit_price: Decimal | None = None

    @field_validator("carton_price", "unit_price", mode="before")
    @classmethod
    def price_value(cls, value: Any, info) -> Decimal | None:
        return parse_optional_money(value, "سعر الكرتونة" if info.field_name == "carton_price" else "سعر الحبة")

    @model_validator(mode="after")
    def at_least_one(self):
        if self.carton_price is None and self.unit_price is None:
            raise ValueError("أدخل سعر الكرتونة أو سعر الحبة على الأقل.")
        return self


class ImportMappingRequest(StrictRequest):
    mapping: dict[str, str]

    @field_validator("mapping")
    @classmethod
    def mapping_contract(cls, value: dict[str, str]) -> dict[str, str]:
        if set(value) - _CANONICAL_MAPPING_FIELDS:
            raise ValueError("يوجد حقل ربط غير معروف.")
        cleaned = {str(k): str(v).strip() for k, v in value.items() if str(v).strip()}
        if len(cleaned.values()) != len(set(cleaned.values())):
            raise ValueError("لا يمكن ربط نفس العمود بأكثر من حقل.")
        return cleaned


def _http_error(exc: SimpleProductError) -> HTTPException:
    return HTTPException(exc.status_code, detail={"code": exc.code, "message": exc.message, "context": exc.context})


def _pricing_error(exc: PricingError) -> HTTPException:
    return HTTPException(exc.status_code, detail=exc.as_detail())


def _request_hash(payload: BaseModel, **scope: Any) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    body.update(scope)
    encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cursor(value: str | None) -> int:
    if value is None:
        return 0
    try:
        parsed = int(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("ascii"))
    except Exception as exc:
        raise HTTPException(400, detail="مؤشر الصفحة غير صالح.") from exc
    if parsed <= 0:
        raise HTTPException(400, detail="مؤشر الصفحة غير صالح.")
    return parsed


def _next_cursor(value: int) -> str:
    return base64.urlsafe_b64encode(str(value).encode("ascii")).decode("ascii").rstrip("=")


def _audit(db: AsyncSession, actor: Driver, target: str, action: str, payload: dict[str, Any]) -> None:
    db.add(SystemAuditLog(
        company_id=actor.company_id, admin_id=actor.id, target_id=target,
        action_type=action, old_value=None,
        new_value=json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
    ))


async def _require(db: AsyncSession, actor: Driver, permission: str) -> None:
    await InventoryAccess(db, actor).require(permission, any_location=True)


async def _require_manage(db: AsyncSession, actor: Driver) -> None:
    for permission in ("catalog.manage", "catalog.publish", "pricing.manage"):
        await _require(db, actor, permission)


@router.get("/families")
async def families(search: str | None = Query(None, max_length=100),
                   limit: int = Query(50, ge=1, le=100),
                   db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.read")
    try:
        return {"items": await list_families(db, company_id=int(actor.company_id), search=search, limit=limit)}
    except SimpleProductError as exc:
        raise _http_error(exc) from exc


@router.get("")
async def list_simple_products(search: str | None = Query(None, min_length=2, max_length=100),
                               cursor: str | None = Query(None, max_length=512),
                               limit: int = Query(50, ge=1, le=200),
                               db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.read")
    await _require(db, actor, "pricing.view")
    try:
        now = datetime.now(timezone.utc)
        company = await load_company(db, int(actor.company_id))
        assignment = await assert_simple_pricing_mode(db, company_id=int(actor.company_id), as_of=now)
        book = await current_default_book(db, company=company, assignment=assignment)
        currency = str(book.currency_code if book else company.currency_code).upper()
        stmt = select(ProductVariant, Product).join(
            Product, (Product.company_id == ProductVariant.company_id) & (Product.id == ProductVariant.product_id)
        ).where(
            ProductVariant.company_id == int(actor.company_id), ProductVariant.id > _cursor(cursor),
            ProductVariant.lifecycle_status.in_(("ACTIVE", "RETIRING")),
        )
        if search:
            clean = search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(or_(
                func.lower(ProductVariant.name).like(f"%{clean}%", escape="\\"),
                func.lower(Product.name).like(f"%{clean}%", escape="\\"),
            ))
        rows = list((await db.execute(stmt.order_by(ProductVariant.id.asc()).limit(limit + 1))).all())
        page, has_more = rows[:limit], len(rows) > limit
        variants = [row[0] for row in page]
        uoms = await load_uoms(db)
        prices = await current_prices(db, company_id=int(actor.company_id), variants=variants, uoms=uoms, as_of=now)
        barcodes = await current_primary_barcodes(db, company_id=int(actor.company_id), variants=variants, uoms=uoms)
        compatible = await simple_compatibility(db, company_id=int(actor.company_id), variants=variants, uoms=uoms)
        items = []
        for variant, product in page:
            carton_price, unit_price = prices.get(int(variant.id), (None, None))
            unit_barcode, carton_barcode = barcodes.get(int(variant.id), (None, None))
            items.append({
                "id": int(variant.id), "product_id": int(product.id), "name": str(variant.name),
                "family_name": str(product.name), "units_per_carton": int(variant.packs_per_carton),
                "currency_code": currency,
                "carton_price": format(carton_price, ".6f") if carton_price is not None else None,
                "unit_price": format(unit_price, ".6f") if unit_price is not None else None,
                "unit_barcode": unit_barcode, "carton_barcode": carton_barcode,
                "lifecycle_status": str(variant.lifecycle_status),
                "simple_compatible": bool(compatible.get(int(variant.id), False)),
            })
        return {"currency_code": currency, "items": items,
                "next_cursor": _next_cursor(page[-1][0].id) if has_more and page else None,
                "has_more": has_more}
    except SimpleProductError as exc:
        raise _http_error(exc) from exc
    except PricingError as exc:
        raise _pricing_error(exc) from exc


@router.post("", status_code=201)
async def create_simple_product(payload: SimpleProductCreate, db: AsyncSession = Depends(get_db),
                                actor: Driver = Depends(get_current_driver)):
    await _require_manage(db, actor)
    try:
        idem, replay = await begin_idempotent_operation(
            db, company_id=actor.company_id, actor_id=actor.id,
            operation="SIMPLE_PRODUCT_CREATE_V2", request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay
        created = await create_products_and_prices(db, actor=actor, request_id=payload.request_id, specs=[SimpleProductSpec(
            name=payload.name, family_id=payload.family_id, family_name=payload.family_name,
            units_per_carton=payload.units_per_carton, carton_price=payload.carton_price,
            unit_price=payload.unit_price, unit_barcode=payload.unit_barcode,
            carton_barcode=payload.carton_barcode,
        )])
        variant, prices = created[0]
        response = {"message": "تم إنشاء المنتج واعتماد سعره.", "product_variant_id": int(variant.id),
                    "carton_price": format(prices.carton_price, ".6f"), "unit_price": format(prices.unit_price, ".6f")}
        _audit(db, actor, f"ProductVariant_{variant.id}", "SIMPLE_PRODUCT_CREATED_V2", response)
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback(); raise
    except SimpleProductError as exc:
        await db.rollback(); raise _http_error(exc) from exc
    except PricingError as exc:
        await db.rollback(); raise _pricing_error(exc) from exc
    except (InventoryMutationError, IntegrityError) as exc:
        await db.rollback()
        raise HTTPException(409, detail={"code": "SIMPLE_PRODUCT_CONFLICT", "message": "تعذر حفظ المنتج بسبب تعارض في بيانات المنتج أو الباركود.", "context": {}}) from exc


@router.patch("/{variant_id}/price")
async def update_simple_product_price(variant_id: int, payload: SimplePriceUpdate,
                                      db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require_manage(db, actor)
    try:
        idem, replay = await begin_idempotent_operation(
            db, company_id=actor.company_id, actor_id=actor.id,
            operation="SIMPLE_PRODUCT_PRICE_UPDATE_V2", request_id=str(payload.request_id),
            request_hash=_request_hash(payload, variant_id=variant_id),
        )
        if replay is not None:
            await db.rollback(); return replay
        variant = await db.scalar(select(ProductVariant).where(
            ProductVariant.company_id == int(actor.company_id), ProductVariant.id == int(variant_id),
            ProductVariant.lifecycle_status.in_(("ACTIVE", "RETIRING")),
        ).with_for_update())
        if variant is None:
            raise HTTPException(404, detail="المنتج غير موجود.")
        prices = await update_prices(db, actor=actor, request_id=payload.request_id, variant=variant,
                                     carton_price=payload.carton_price, unit_price=payload.unit_price)
        response = {"message": "تم تحديث الأسعار.", "product_variant_id": int(variant.id),
                    "carton_price": format(prices.carton_price, ".6f"), "unit_price": format(prices.unit_price, ".6f")}
        _audit(db, actor, f"ProductVariant_{variant.id}", "SIMPLE_PRODUCT_PRICE_UPDATED_V2", response)
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback(); raise
    except SimpleProductError as exc:
        await db.rollback(); raise _http_error(exc) from exc
    except PricingError as exc:
        await db.rollback(); raise _pricing_error(exc) from exc
    except (InventoryMutationError, IntegrityError) as exc:
        await db.rollback(); raise HTTPException(409, detail="تعذر تحديث السعر.") from exc


@router.post("/imports", status_code=202)
async def create_product_import(
    request_id: UUID = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)
    file_name = str(file.filename or "").strip()
    if not file_name or len(file_name) > 255 or "\x00" in file_name:
        await file.close()
        raise HTTPException(
            422,
            detail={
                "code": "PRODUCT_IMPORT_FILE_NAME_INVALID",
                "message": "اسم الملف غير صالح.",
                "context": {},
            },
        )
    suffix = "." + file_name.lower().rsplit(".", 1)[-1] if "." in file_name else ""
    if suffix not in _ALLOWED_IMPORT_SUFFIXES:
        raise HTTPException(415, detail={"code": "PRODUCT_IMPORT_FILE_TYPE_UNSUPPORTED", "message": "ارفع ملف CSV أو XLSX.", "context": {}})
    payload = await file.read(MAX_IMPORT_FILE_BYTES + 1)
    await file.close()
    if not payload:
        raise HTTPException(422, detail="الملف فارغ.")
    if len(payload) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(413, detail="حجم ملف الاستيراد أكبر من 8MB.")
    try:
        job_id = await enqueue_new_import(
            company_id=int(actor.company_id), actor_id=int(actor.id), request_id=request_id,
            file_name=file_name,
            content_type=str(file.content_type or "application/octet-stream"), payload=payload,
            source_sha256=hashlib.sha256(payload).hexdigest(),
        )
    except Exception as exc:
        raise HTTPException(503, detail="تعذر إدراج عملية الاستيراد في الطابور.") from exc
    return {"job_id": str(job_id), "status": "QUEUED", "message": "تم استلام الملف وسيتم تجهيزه في الخلفية."}


def _job_payload(job: ProductImportJob) -> dict[str, Any]:
    return {
        "job_id": str(job.id), "status": str(job.status), "file_name": str(job.file_name),
        "total_rows": int(job.total_rows), "processed_rows": int(job.processed_rows),
        "valid_rows": int(job.valid_rows), "failed_rows": int(job.failed_rows),
        "detected_headers": list(job.detected_headers or []),
        "suggested_mapping": dict(job.suggested_mapping or {}),
        "column_mapping": dict(job.column_mapping or {}), "error_summary": dict(job.error_summary or {}),
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.get("/imports/{job_id}")
async def get_product_import(job_id: UUID, db: AsyncSession = Depends(get_db),
                             actor: Driver = Depends(get_current_driver)):
    await _require(db, actor, "catalog.read")
    job = await db.scalar(select(ProductImportJob).where(
        ProductImportJob.company_id == int(actor.company_id), ProductImportJob.id == job_id
    ))
    if job is None:
        raise HTTPException(404, detail="عملية الاستيراد غير موجودة.")
    errors = []
    if str(job.status) == "VALIDATION_FAILED":
        rows = list((await db.scalars(select(ProductImportRow).where(
            ProductImportRow.company_id == int(actor.company_id), ProductImportRow.job_id == job_id,
            ProductImportRow.status == "FAILED",
        ).order_by(ProductImportRow.row_number.asc()).limit(50))).all())
        errors = [{"row_number": int(row.row_number), "code": row.error_code, "message": row.error_message} for row in rows]
    payload = _job_payload(job)
    payload["errors"] = errors
    return payload


@router.put("/imports/{job_id}/mapping", status_code=202)
async def set_product_import_mapping(job_id: UUID, payload: ImportMappingRequest,
                                     db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await _require_manage(db, actor)
    job = await db.scalar(select(ProductImportJob).where(
        ProductImportJob.company_id == int(actor.company_id), ProductImportJob.id == job_id
    ))
    if job is None:
        raise HTTPException(404, detail="عملية الاستيراد غير موجودة.")
    if str(job.status) != "NEEDS_MAPPING":
        raise HTTPException(409, detail="عملية الاستيراد لا تنتظر ربط الأعمدة حالياً.")
    headers = set(job.detected_headers or [])
    if any(field not in _CANONICAL_MAPPING_FIELDS or header not in headers for field, header in payload.mapping.items()):
        raise HTTPException(422, detail="ربط الأعمدة غير صالح.")
    if not payload.mapping.get("name") or not payload.mapping.get("units_per_carton"):
        raise HTTPException(422, detail="اربط اسم المنتج وعدد الحبات في الكرتونة.")
    if not (payload.mapping.get("carton_price") or payload.mapping.get("unit_price")):
        raise HTTPException(422, detail="اربط سعر الكرتونة أو سعر الحبة على الأقل.")
    try:
        await requeue_import(company_id=int(actor.company_id), job_id=job_id, mapping=payload.mapping)
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, detail="تعذر إعادة عملية الاستيراد إلى الطابور.") from exc
    return {"job_id": str(job_id), "status": "QUEUED", "message": "تم اعتماد ربط الأعمدة وسيكمل النظام الاستيراد في الخلفية."}



@router.post("/imports/{job_id}/retry", status_code=202)
async def retry_product_import(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)
    job = await db.scalar(
        select(ProductImportJob).where(
            ProductImportJob.company_id == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(404, detail="عملية الاستيراد غير موجودة.")
    summary = dict(job.error_summary or {})
    if str(job.status) != "FAILED" or summary.get("retryable") is not True:
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_IMPORT_NOT_RETRYABLE",
                "message": "هذه العملية لا تقبل إعادة المحاولة التلقائية.",
                "context": {},
            },
        )
    try:
        await retry_failed_import(
            company_id=int(actor.company_id),
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(409, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail="تعذر إعادة العملية إلى طابور الاستيراد.",
        ) from exc
    return {
        "job_id": str(job_id),
        "status": "QUEUED",
        "message": "تمت إعادة عملية الاستيراد إلى الطابور.",
    }
