from __future__ import annotations

import base64
import csv
import hashlib
import io
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.pricing.core import PricingError, maker_checker_enabled, money_20_6
from domains.pricing.publishing import (
    create_assignment,
    create_draft_entry,
    create_price_book,
    create_publication,
    publish_publication,
)
from domains.pricing.resolver import resolve_prices_bulk
from inventory_access import InventoryAccess
from models import (
    Company,
    Driver,
    PriceBook,
    PriceBookAssignment,
    Product,
    ProductUomConversion,
    ProductVariant,
    SystemAuditLog,
    UOM,
)
from product_lifecycle import (
    ProductLifecycleTransitionError,
    apply_variant_publish_transition,
    record_domain_event,
    variant_snapshot,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter(prefix="/simple-products", tags=["Simple Products"])

_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.-]*$")
MAX_IMPORT_ROWS = 200


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _text(
    value: Any,
    field: str,
    maximum: int,
    *,
    optional: bool = False,
) -> Optional[str]:
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


def _code(value: Any) -> Optional[str]:
    clean = _text(value, "رمز المنتج", 100, optional=True)
    if clean is None:
        return None
    clean = clean.upper()
    if not _CODE_RE.fullmatch(clean):
        raise ValueError(
            "رمز المنتج يقبل A-Z والأرقام والنقاط والشرطة والشرطة السفلية فقط."
        )
    return clean


def _money_input(value: Any) -> Decimal:
    if value is None or isinstance(value, (bool, float)):
        raise ValueError("سعر الكرتونة يجب أن يرسل كقيمة عشرية دقيقة.")
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
        raise ValueError("سعر الكرتونة غير صالح.") from exc
    if not parsed.is_finite() or parsed <= 0:
        raise ValueError("سعر الكرتونة يجب أن يكون أكبر من صفر.")
    return parsed


class SimpleProductInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=150)
    code: Optional[str] = Field(None, max_length=100)
    units_per_carton: int = Field(gt=0, le=1_000_000)
    carton_price: Decimal

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> str:
        return _text(value, "اسم المنتج", 150)  # type: ignore[return-value]

    @field_validator("code", mode="before")
    @classmethod
    def normalize_code(cls, value: Any) -> Optional[str]:
        return _code(value)

    @field_validator("carton_price", mode="before")
    @classmethod
    def normalize_price(cls, value: Any) -> Decimal:
        return _money_input(value)


class SimpleProductCreate(SimpleProductInput):
    request_id: UUID


class SimplePriceUpdate(StrictRequest):
    request_id: UUID
    carton_price: Decimal

    @field_validator("carton_price", mode="before")
    @classmethod
    def normalize_price(cls, value: Any) -> Decimal:
        return _money_input(value)


class CsvImportRequest(StrictRequest):
    request_id: UUID
    csv_text: str = Field(min_length=1, max_length=5_000_000)


def _request_hash(payload: BaseModel, **scope: Any) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    body.update(scope)
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cursor(value: Optional[str]) -> int:
    if value is None:
        return 0
    try:
        raw = base64.urlsafe_b64decode(
            value + "=" * (-len(value) % 4)
        ).decode("ascii")
        parsed = int(raw)
    except Exception as exc:
        raise HTTPException(
            400,
            detail={
                "code": "INVALID_CURSOR",
                "message": "مؤشر الصفحة غير صالح.",
                "context": {},
            },
        ) from exc
    if parsed <= 0:
        raise HTTPException(
            400,
            detail={
                "code": "INVALID_CURSOR",
                "message": "مؤشر الصفحة غير صالح.",
                "context": {},
            },
        )
    return parsed


def _next_cursor(value: int) -> str:
    return base64.urlsafe_b64encode(
        str(value).encode("ascii")
    ).decode("ascii").rstrip("=")


def _search_pattern(value: str) -> str:
    clean = (
        value.strip()
        .lower()
        .replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )
    return f"%{clean}%"


def _pricing_http_error(exc: PricingError) -> HTTPException:
    return HTTPException(exc.status_code, detail=exc.as_detail())


async def _require(
    db: AsyncSession,
    actor: Driver,
    permission: str,
) -> None:
    await InventoryAccess(db, actor).require(
        permission,
        any_location=True,
    )


async def _require_simple_manage(
    db: AsyncSession,
    actor: Driver,
) -> None:
    for permission in (
        "catalog.manage",
        "catalog.publish",
        "pricing.manage",
    ):
        await _require(db, actor, permission)


def _audit(
    db: AsyncSession,
    actor: Driver,
    target: str,
    action: str,
    payload: dict[str, Any],
) -> None:
    db.add(
        SystemAuditLog(
            company_id=actor.company_id,
            admin_id=actor.id,
            target_id=target,
            action_type=action,
            old_value=None,
            new_value=json.dumps(
                payload,
                ensure_ascii=False,
                default=str,
                sort_keys=True,
            ),
        )
    )


async def _uoms(db: AsyncSession) -> tuple[UOM, UOM]:
    rows = list(
        (
            await db.scalars(
                select(UOM)
                .where(UOM.code.in_(("EACH", "CARTON")))
                .order_by(UOM.code.asc())
            )
        ).all()
    )
    by_code = {str(row.code).upper(): row for row in rows}
    each = by_code.get("EACH")
    carton = by_code.get("CARTON")
    if each is None or carton is None:
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_UOM_MISSING",
                "message": "إعداد وحدات الحبة والكرتونة غير مكتمل في النظام.",
                "context": {},
            },
        )
    return each, carton


def derive_unit_price(
    carton_price: Decimal,
    units_per_carton: int,
) -> Decimal:
    if units_per_carton <= 0:
        raise ValueError("units_per_carton must be positive")
    amount = money_20_6(carton_price)
    unit = money_20_6(amount / Decimal(units_per_carton))
    if unit <= 0:
        raise ValueError("derived unit price must be positive")
    return unit


async def _company(
    db: AsyncSession,
    company_id: int,
) -> Company:
    row = await db.scalar(
        select(Company).where(Company.id == int(company_id))
    )
    if row is None:
        raise HTTPException(
            404,
            detail={
                "code": "COMPANY_NOT_FOUND",
                "message": "الشركة غير موجودة.",
                "context": {},
            },
        )
    return row


async def _assert_simple_pricing_mode(
    db: AsyncSession,
    *,
    company_id: int,
    as_of: datetime,
) -> PriceBookAssignment | None:
    if await maker_checker_enabled(db, int(company_id)):
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCTS_APPROVAL_MODE_UNSUPPORTED",
                "message": (
                    "وضع المنتجات المبسط غير متوافق مع مراجعة واعتماد الأسعار "
                    "المتقدمة المفعلة حالياً."
                ),
                "context": {},
            },
        )

    advanced_assignment_id = await db.scalar(
        select(PriceBookAssignment.id)
        .where(
            PriceBookAssignment.company_id == int(company_id),
            PriceBookAssignment.scope_type != "COMPANY_DEFAULT",
            or_(
                func.upper_inf(PriceBookAssignment.effectivity),
                func.upper(PriceBookAssignment.effectivity) > as_of,
            ),
        )
        .order_by(PriceBookAssignment.id.asc())
        .limit(1)
    )
    if advanced_assignment_id is not None:
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCTS_ADVANCED_PRICING_ACTIVE",
                "message": (
                    "توجد سياسة تسعير متقدمة حالية أو مجدولة لهذه الشركة. "
                    "الوضع المبسط يتطلب سعراً أساسياً واحداً للشركة."
                ),
                "context": {
                    "assignment_id": int(advanced_assignment_id),
                },
            },
        )

    future_default_id = await db.scalar(
        select(PriceBookAssignment.id)
        .where(
            PriceBookAssignment.company_id == int(company_id),
            PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
            func.lower(PriceBookAssignment.effectivity) > as_of,
        )
        .order_by(PriceBookAssignment.id.asc())
        .limit(1)
    )
    if future_default_id is not None:
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCTS_FUTURE_PRICING_ACTIVE",
                "message": (
                    "يوجد تغيير سعر أساسي مجدول مسبقاً. "
                    "ألغِ الجدولة المتقدمة قبل استخدام الوضع المبسط."
                ),
                "context": {
                    "assignment_id": int(future_default_id),
                },
            },
        )

    defaults = list(
        (
            await db.scalars(
                select(PriceBookAssignment)
                .where(
                    PriceBookAssignment.company_id == int(company_id),
                    PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
                    PriceBookAssignment.scope_id.is_(None),
                    PriceBookAssignment.effectivity.contains(as_of),
                )
                .order_by(
                    PriceBookAssignment.priority.desc(),
                    PriceBookAssignment.revision.desc(),
                    PriceBookAssignment.id.desc(),
                )
            )
        ).all()
    )
    if len(defaults) > 1:
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCTS_MULTIPLE_DEFAULT_PRICES",
                "message": (
                    "يوجد أكثر من سعر أساسي فعال للشركة. "
                    "هذا إعداد متقدم لا يديره الوضع المبسط."
                ),
                "context": {
                    "assignment_ids": [int(row.id) for row in defaults],
                },
            },
        )
    if defaults and not bool(defaults[0].allow_offers):
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCTS_OFFERS_BLOCKED",
                "message": (
                    "السعر الأساسي الحالي مضبوط كسعر نهائي يمنع العروض. "
                    "هذا إعداد متقدم لا يديره الوضع المبسط."
                ),
                "context": {
                    "assignment_id": int(defaults[0].id),
                },
            },
        )
    return defaults[0] if defaults else None


async def _current_default_book(
    db: AsyncSession,
    *,
    company: Company,
    assignment: PriceBookAssignment | None,
) -> PriceBook | None:
    if assignment is None:
        return None
    book = await db.scalar(
        select(PriceBook).where(
            PriceBook.company_id == int(company.id),
            PriceBook.id == int(assignment.price_book_id),
            PriceBook.status == "ACTIVE",
        )
    )
    if book is None:
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_DEFAULT_PRICE_BOOK_INVALID",
                "message": "إعداد السعر الأساسي للشركة غير صالح.",
                "context": {
                    "assignment_id": int(assignment.id),
                },
            },
        )
    if (
        str(book.currency_code).strip().upper()
        != str(company.currency_code).strip().upper()
    ):
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_CURRENCY_MISMATCH",
                "message": (
                    "عملة السعر الأساسي تختلف عن عملة الشركة. "
                    "هذا إعداد متقدم لا يديره الوضع المبسط."
                ),
                "context": {
                    "price_book_id": int(book.id),
                },
            },
        )
    return book


async def _ensure_default_book(
    db: AsyncSession,
    *,
    company: Company,
    actor_id: int,
    as_of: datetime,
    assignment: PriceBookAssignment | None,
) -> PriceBook:
    current = await _current_default_book(
        db,
        company=company,
        assignment=assignment,
    )
    if current is not None:
        return current

    preferred_codes = ("DEFAULT", "SIMPLE_DEFAULT", "SMB_DEFAULT")
    existing = list(
        (
            await db.scalars(
                select(PriceBook)
                .where(
                    PriceBook.company_id == int(company.id),
                    PriceBook.code.in_(preferred_codes),
                )
                .order_by(PriceBook.id.asc())
            )
        ).all()
    )
    book = next(
        (row for row in existing if row.status == "ACTIVE"),
        None,
    )
    if book is None:
        used = {str(row.code).upper() for row in existing}
        free_code = next(
            (code for code in preferred_codes if code not in used),
            None,
        )
        if free_code is None:
            raise HTTPException(
                409,
                detail={
                    "code": "SIMPLE_PRODUCT_DEFAULT_BOOK_CONFLICT",
                    "message": (
                        "تعذر إنشاء سجل السعر الأساسي تلقائياً بسبب إعداد "
                        "تسعير سابق غير متوافق."
                    ),
                    "context": {},
                },
            )
        book = await create_price_book(
            db,
            company_id=int(company.id),
            actor_id=int(actor_id),
            code=free_code,
            name="الأسعار الأساسية",
            currency_code=str(company.currency_code).upper(),
            applicability_metadata={
                "managed_by": "simple_products",
            },
        )

    if (
        str(book.currency_code).strip().upper()
        != str(company.currency_code).strip().upper()
    ):
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_CURRENCY_MISMATCH",
                "message": "سجل السعر الأساسي لا يستخدم عملة الشركة.",
                "context": {
                    "price_book_id": int(book.id),
                },
            },
        )

    await create_assignment(
        db,
        company_id=int(company.id),
        actor_id=int(actor_id),
        price_book_id=int(book.id),
        scope_type="COMPANY_DEFAULT",
        scope_id=None,
        allow_offers=True,
        priority=0,
        effective_from=as_of,
        effective_to=None,
    )
    return book


async def _assert_simple_variant(
    db: AsyncSession,
    *,
    company_id: int,
    variant: ProductVariant,
    each_uom_id: int,
    carton_uom_id: int,
) -> None:
    if int(variant.base_uom_id) != int(each_uom_id):
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_BASE_UOM_UNSUPPORTED",
                "message": (
                    "هذا المنتج يستخدم بنية وحدات متقدمة ولا يمكن تعديل "
                    "سعره من الشاشة المبسطة."
                ),
                "context": {
                    "product_variant_id": int(variant.id),
                },
            },
        )
    packs = int(variant.packs_per_carton or 0)
    if packs <= 0:
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_PACKAGING_INVALID",
                "message": "عدد الحبات في الكرتونة غير صالح لهذا المنتج.",
                "context": {
                    "product_variant_id": int(variant.id),
                },
            },
        )
    if packs == 1:
        return
    conversions = list(
        (
            await db.scalars(
                select(ProductUomConversion).where(
                    ProductUomConversion.company_id == int(company_id),
                    ProductUomConversion.product_variant_id == int(variant.id),
                    ProductUomConversion.from_uom_id == int(carton_uom_id),
                    ProductUomConversion.to_uom_id == int(each_uom_id),
                )
            )
        ).all()
    )
    valid = [
        row
        for row in conversions
        if Decimal(row.numerator) / Decimal(row.denominator)
        == Decimal(packs)
    ]
    if len(valid) != 1:
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_CARTON_MAPPING_INVALID",
                "message": (
                    "تحويل الكرتونة إلى الحبات غير صالح لهذا المنتج."
                ),
                "context": {
                    "product_variant_id": int(variant.id),
                },
            },
        )


async def _create_structure(
    db: AsyncSession,
    *,
    actor: Driver,
    item: SimpleProductInput,
    request_id: UUID,
    row_index: int,
    each: UOM,
    carton: UOM,
) -> ProductVariant:
    seed = request_id.hex[:12].upper()
    code = item.code or f"PRD-{seed}-{row_index:03d}"

    product = Product(
        company_id=int(actor.company_id),
        code=code,
        name=item.name,
    )
    db.add(product)
    await db.flush()

    variant = ProductVariant(
        company_id=int(actor.company_id),
        product_id=int(product.id),
        base_uom_id=int(each.id),
        name=item.name,
        sku=code,
        quantity_scale=0,
        quantity_step=Decimal("1"),
        lot_control_mode="REQUIRED",
        expiry_control_mode="REQUIRED",
        lifecycle_status="DRAFT",
        operational_hold="NONE",
        packs_per_carton=int(item.units_per_carton),
    )
    db.add(variant)
    await db.flush()

    if int(item.units_per_carton) > 1:
        db.add(
            ProductUomConversion(
                company_id=int(actor.company_id),
                product_variant_id=int(variant.id),
                from_uom_id=int(carton.id),
                to_uom_id=int(each.id),
                numerator=Decimal(int(item.units_per_carton)),
                denominator=Decimal("1"),
                quantity_scale=0,
            )
        )

    before = variant_snapshot(variant)
    transition_now = datetime.now(timezone.utc).replace(tzinfo=None)
    try:
        event_type, transition_message = apply_variant_publish_transition(
            variant,
            transition_now,
        )
    except ProductLifecycleTransitionError as exc:
        raise HTTPException(
            exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "context": {},
            },
        ) from exc

    variant.lifecycle_revision += 1
    variant.version += 1
    variant.updated_at = transition_now
    after = variant_snapshot(variant)
    record_domain_event(
        db,
        company_id=int(actor.company_id),
        actor_id=int(actor.id),
        request_id=request_id,
        event_type=event_type,
        entity_type="ProductVariant",
        entity_id=int(variant.id),
        reason=transition_message,
        before=before,
        after=after,
    )
    await db.flush()
    return variant


async def _publish_prices(
    db: AsyncSession,
    *,
    actor: Driver,
    book: PriceBook,
    priced_items: list[tuple[ProductVariant, Decimal]],
    each: UOM,
    carton: UOM,
    effective_at: datetime,
    request_id: UUID,
) -> None:
    publication = await create_publication(
        db,
        company_id=int(actor.company_id),
        actor_id=int(actor.id),
        book_id=int(book.id),
        expected_book_version=int(book.version),
        effective_at=effective_at,
        request_id=request_id,
    )

    for variant, carton_price_raw in priced_items:
        carton_price = money_20_6(carton_price_raw)
        packs = int(variant.packs_per_carton)
        unit_price = derive_unit_price(carton_price, packs)

        await create_draft_entry(
            db,
            company_id=int(actor.company_id),
            publication_id=int(publication.id),
            expected_publication_version=int(publication.version),
            product_variant_id=int(variant.id),
            uom_id=int(each.id),
            amount=unit_price,
            effective_from=effective_at,
            effective_to=None,
            priority=0,
            metadata={
                "managed_by": "simple_products",
                "derived_from": "carton_price",
                "units_per_carton": packs,
            },
        )
        if packs > 1:
            await create_draft_entry(
                db,
                company_id=int(actor.company_id),
                publication_id=int(publication.id),
                expected_publication_version=int(publication.version),
                product_variant_id=int(variant.id),
                uom_id=int(carton.id),
                amount=carton_price,
                effective_from=effective_at,
                effective_to=None,
                priority=0,
                metadata={
                    "managed_by": "simple_products",
                    "authoritative_input": "carton_price",
                    "units_per_carton": packs,
                },
            )

    await publish_publication(
        db,
        company_id=int(actor.company_id),
        actor_id=int(actor.id),
        publication_id=int(publication.id),
        expected_version=int(publication.version),
    )


def _simple_row(
    *,
    variant: ProductVariant,
    product: Product,
    currency_code: str,
    carton_price: Decimal | None,
    unit_price: Decimal | None,
    compatible: bool,
) -> dict[str, Any]:
    return {
        "id": int(variant.id),
        "product_id": int(product.id),
        "name": str(variant.name),
        "code": str(product.code),
        "units_per_carton": int(variant.packs_per_carton),
        "currency_code": str(currency_code).upper(),
        "carton_price": (
            format(carton_price, ".6f")
            if carton_price is not None
            else None
        ),
        "unit_price": (
            format(unit_price, ".6f")
            if unit_price is not None
            else None
        ),
        "lifecycle_status": str(variant.lifecycle_status),
        "simple_compatible": bool(compatible),
    }


async def _compatibility_map(
    db: AsyncSession,
    *,
    company_id: int,
    variants: list[ProductVariant],
    each: UOM,
    carton: UOM,
) -> dict[int, bool]:
    if not variants:
        return {}
    ids = [int(row.id) for row in variants]
    conversions = list(
        (
            await db.scalars(
                select(ProductUomConversion).where(
                    ProductUomConversion.company_id == int(company_id),
                    ProductUomConversion.product_variant_id.in_(ids),
                    ProductUomConversion.from_uom_id == int(carton.id),
                    ProductUomConversion.to_uom_id == int(each.id),
                )
            )
        ).all()
    )
    by_variant: dict[int, list[ProductUomConversion]] = {}
    for row in conversions:
        by_variant.setdefault(
            int(row.product_variant_id),
            [],
        ).append(row)

    result: dict[int, bool] = {}
    for variant in variants:
        packs = int(variant.packs_per_carton or 0)
        if int(variant.base_uom_id) != int(each.id) or packs <= 0:
            result[int(variant.id)] = False
            continue
        if packs == 1:
            result[int(variant.id)] = True
            continue
        rows = by_variant.get(int(variant.id), [])
        matches = [
            row
            for row in rows
            if Decimal(row.numerator) / Decimal(row.denominator)
            == Decimal(packs)
        ]
        result[int(variant.id)] = len(matches) == 1
    return result


async def _current_prices(
    db: AsyncSession,
    *,
    company_id: int,
    variants: list[ProductVariant],
    each: UOM,
    carton: UOM,
    as_of: datetime,
) -> dict[int, tuple[Decimal | None, Decimal | None]]:
    if not variants:
        return {}
    pairs: list[tuple[int, int]] = []
    for variant in variants:
        pairs.append((int(variant.id), int(each.id)))
        if int(variant.packs_per_carton or 0) > 1:
            pairs.append((int(variant.id), int(carton.id)))

    try:
        rows = await resolve_prices_bulk(
            db,
            company_id=int(company_id),
            pairs=pairs,
            customer_id=None,
            branch_id=None,
            as_of=as_of,
            allow_unresolved_pairs=True,
        )
    except PricingError as exc:
        if exc.code == "PRICE_NOT_RESOLVED":
            return {}
        raise

    result: dict[int, tuple[Decimal | None, Decimal | None]] = {}
    for variant in variants:
        variant_id = int(variant.id)
        unit_row = rows.get((variant_id, int(each.id)))
        packs = int(variant.packs_per_carton or 0)
        carton_row = (
            unit_row
            if packs == 1
            else rows.get((variant_id, int(carton.id)))
        )
        result[variant_id] = (
            Decimal(carton_row.amount)
            if carton_row is not None
            else None,
            Decimal(unit_row.amount)
            if unit_row is not None
            else None,
        )
    return result


@router.get("")
async def list_simple_products(
    search: Optional[str] = Query(None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    await _require(db, actor, "pricing.view")

    as_of = datetime.now(timezone.utc)
    company = await _company(db, actor.company_id)
    assignment = await _assert_simple_pricing_mode(
        db,
        company_id=actor.company_id,
        as_of=as_of,
    )
    book = await _current_default_book(
        db,
        company=company,
        assignment=assignment,
    )
    currency = str(
        book.currency_code
        if book is not None
        else company.currency_code
    ).upper()

    after_id = _cursor(cursor)
    stmt = (
        select(ProductVariant, Product)
        .join(
            Product,
            (Product.company_id == ProductVariant.company_id)
            & (Product.id == ProductVariant.product_id),
        )
        .where(
            ProductVariant.company_id == int(actor.company_id),
            ProductVariant.id > after_id,
            ProductVariant.lifecycle_status.in_(("ACTIVE", "RETIRING")),
        )
    )
    if search:
        pattern = _search_pattern(search)
        stmt = stmt.where(
            or_(
                func.lower(ProductVariant.name).like(
                    pattern,
                    escape="\\",
                ),
                func.lower(ProductVariant.sku).like(
                    pattern,
                    escape="\\",
                ),
                func.lower(Product.code).like(
                    pattern,
                    escape="\\",
                ),
            )
        )
    rows = list(
        (
            await db.execute(
                stmt.order_by(ProductVariant.id.asc()).limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    variants = [row[0] for row in page]
    each, carton = await _uoms(db)

    compatible = await _compatibility_map(
        db,
        company_id=actor.company_id,
        variants=variants,
        each=each,
        carton=carton,
    )
    try:
        prices = await _current_prices(
            db,
            company_id=actor.company_id,
            variants=variants,
            each=each,
            carton=carton,
            as_of=as_of,
        )
    except PricingError as exc:
        raise _pricing_http_error(exc) from exc

    return {
        "currency_code": currency,
        "items": [
            _simple_row(
                variant=variant,
                product=product,
                currency_code=currency,
                carton_price=prices.get(
                    int(variant.id),
                    (None, None),
                )[0],
                unit_price=prices.get(
                    int(variant.id),
                    (None, None),
                )[1],
                compatible=compatible.get(
                    int(variant.id),
                    False,
                ),
            )
            for variant, product in page
        ],
        "next_cursor": (
            _next_cursor(page[-1][0].id)
            if has_more and page
            else None
        ),
        "has_more": has_more,
    }


async def _create_many(
    db: AsyncSession,
    *,
    actor: Driver,
    request_id: UUID,
    items: list[SimpleProductInput],
) -> list[ProductVariant]:
    as_of = datetime.now(timezone.utc)
    assignment = await _assert_simple_pricing_mode(
        db,
        company_id=actor.company_id,
        as_of=as_of,
    )
    company = await _company(db, actor.company_id)
    each, carton = await _uoms(db)
    book = await _ensure_default_book(
        db,
        company=company,
        actor_id=actor.id,
        as_of=as_of,
        assignment=assignment,
    )

    variants: list[ProductVariant] = []
    priced: list[tuple[ProductVariant, Decimal]] = []
    for index, item in enumerate(items, start=1):
        variant = await _create_structure(
            db,
            actor=actor,
            item=item,
            request_id=request_id,
            row_index=index,
            each=each,
            carton=carton,
        )
        variants.append(variant)
        priced.append((variant, item.carton_price))

    await _publish_prices(
        db,
        actor=actor,
        book=book,
        priced_items=priced,
        each=each,
        carton=carton,
        effective_at=as_of,
        request_id=request_id,
    )
    return variants


@router.post("", status_code=201)
async def create_simple_product(
    payload: SimpleProductCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_simple_manage(db, actor)
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="SIMPLE_PRODUCT_CREATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay

        item = SimpleProductInput.model_validate(
            payload.model_dump(exclude={"request_id"})
        )
        variants = await _create_many(
            db,
            actor=actor,
            request_id=payload.request_id,
            items=[item],
        )
        unit_price = derive_unit_price(
            payload.carton_price,
            payload.units_per_carton,
        )
        response = {
            "message": "تم إنشاء المنتج واعتماد سعره.",
            "product_variant_id": int(variants[0].id),
            "carton_price": format(
                money_20_6(payload.carton_price),
                ".6f",
            ),
            "unit_price": format(unit_price, ".6f"),
        }
        _audit(
            db,
            actor,
            f"ProductVariant_{variants[0].id}",
            "SIMPLE_PRODUCT_CREATED",
            response,
        )
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
        ValueError,
    ) as exc:
        await db.rollback()
        code = "SIMPLE_PRODUCT_CONFLICT"
        message = (
            "تعذر إنشاء المنتج بسبب تعارض في الرمز أو بيانات المنتج أو السعر."
        )
        if isinstance(exc, InventoryMutationError):
            code, message = "IDEMPOTENCY_CONFLICT", str(exc)
        raise HTTPException(
            409,
            detail={
                "code": code,
                "message": message,
                "context": {},
            },
        ) from exc


@router.patch("/{variant_id}/price")
async def update_simple_product_price(
    variant_id: int,
    payload: SimplePriceUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_simple_manage(db, actor)
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="SIMPLE_PRODUCT_PRICE_UPDATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(
                payload,
                variant_id=variant_id,
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay

        as_of = datetime.now(timezone.utc)
        assignment = await _assert_simple_pricing_mode(
            db,
            company_id=actor.company_id,
            as_of=as_of,
        )
        variant = await db.scalar(
            select(ProductVariant)
            .where(
                ProductVariant.company_id == int(actor.company_id),
                ProductVariant.id == int(variant_id),
                ProductVariant.lifecycle_status.in_(
                    ("ACTIVE", "RETIRING")
                ),
            )
            .with_for_update()
        )
        if variant is None:
            raise HTTPException(
                404,
                detail={
                    "code": "PRODUCT_NOT_FOUND",
                    "message": "المنتج غير موجود.",
                    "context": {},
                },
            )

        each, carton = await _uoms(db)
        await _assert_simple_variant(
            db,
            company_id=actor.company_id,
            variant=variant,
            each_uom_id=each.id,
            carton_uom_id=carton.id,
        )
        company = await _company(db, actor.company_id)
        book = await _ensure_default_book(
            db,
            company=company,
            actor_id=actor.id,
            as_of=as_of,
            assignment=assignment,
        )
        await _publish_prices(
            db,
            actor=actor,
            book=book,
            priced_items=[(variant, payload.carton_price)],
            each=each,
            carton=carton,
            effective_at=as_of,
            request_id=payload.request_id,
        )

        unit_price = derive_unit_price(
            payload.carton_price,
            int(variant.packs_per_carton),
        )
        response = {
            "message": "تم تحديث السعر واعتماده.",
            "product_variant_id": int(variant.id),
            "carton_price": format(
                money_20_6(payload.carton_price),
                ".6f",
            ),
            "unit_price": format(unit_price, ".6f"),
        }
        _audit(
            db,
            actor,
            f"ProductVariant_{variant.id}",
            "SIMPLE_PRODUCT_PRICE_UPDATED",
            response,
        )
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
        ValueError,
    ) as exc:
        await db.rollback()
        code = "SIMPLE_PRODUCT_PRICE_CONFLICT"
        message = "تعذر تحديث السعر."
        if isinstance(exc, InventoryMutationError):
            code, message = "IDEMPOTENCY_CONFLICT", str(exc)
        raise HTTPException(
            409,
            detail={
                "code": code,
                "message": message,
                "context": {},
            },
        ) from exc


_HEADER_ALIASES = {
    "name": {"name", "اسم المنتج", "الاسم"},
    "code": {"code", "رمز المنتج", "الكود"},
    "units_per_carton": {
        "units_per_carton",
        "عدد الحبات في الكرتونة",
        "الحبات بالكرتونة",
    },
    "carton_price": {
        "carton_price",
        "سعر الكرتونة",
    },
}


def _canonical_header(value: str) -> str | None:
    clean = value.strip().lower()
    for canonical, aliases in _HEADER_ALIASES.items():
        if clean in {
            alias.lower()
            for alias in aliases
        }:
            return canonical
    return None


def _parse_csv(csv_text: str) -> list[SimpleProductInput]:
    text_value = csv_text.lstrip("\ufeff")
    reader = csv.DictReader(io.StringIO(text_value))
    if not reader.fieldnames:
        raise HTTPException(
            422,
            detail={
                "code": "CSV_HEADERS_MISSING",
                "message": "ملف CSV لا يحتوي عناوين أعمدة.",
                "context": {},
            },
        )

    mapped: dict[str, str] = {}
    for header in reader.fieldnames:
        canonical = _canonical_header(header)
        if canonical:
            if canonical in mapped:
                raise HTTPException(
                    422,
                    detail={
                        "code": "CSV_HEADER_DUPLICATE",
                        "message": f"العمود {canonical} مكرر.",
                        "context": {},
                    },
                )
            mapped[canonical] = header

    required = {
        "name",
        "units_per_carton",
        "carton_price",
    }
    missing = sorted(required - set(mapped))
    if missing:
        raise HTTPException(
            422,
            detail={
                "code": "CSV_HEADERS_INVALID",
                "message": (
                    "الأعمدة المطلوبة هي: "
                    "name, units_per_carton, carton_price."
                ),
                "context": {
                    "missing": missing,
                },
            },
        )

    items: list[SimpleProductInput] = []
    for row_number, raw in enumerate(reader, start=2):
        if not any(
            str(value or "").strip()
            for value in raw.values()
        ):
            continue

        payload = {
            key: (raw.get(source) or "").strip()
            for key, source in mapped.items()
        }
        if payload.get("code") == "":
            payload["code"] = None
        try:
            items.append(
                SimpleProductInput.model_validate(payload)
            )
        except ValidationError as exc:
            first = exc.errors()[0]
            raise HTTPException(
                422,
                detail={
                    "code": "CSV_ROW_INVALID",
                    "message": (
                        f"خطأ في الصف {row_number}: "
                        f"{first.get('msg', 'بيانات غير صالحة')}"
                    ),
                    "context": {
                        "row": row_number,
                    },
                },
            ) from exc

        if len(items) > MAX_IMPORT_ROWS:
            raise HTTPException(
                422,
                detail={
                    "code": "CSV_TOO_MANY_ROWS",
                    "message": (
                        "الحد الأقصى للاستيراد في العملية الواحدة "
                        f"هو {MAX_IMPORT_ROWS} منتج."
                    ),
                    "context": {
                        "max_rows": MAX_IMPORT_ROWS,
                    },
                },
            )

    if not items:
        raise HTTPException(
            422,
            detail={
                "code": "CSV_EMPTY",
                "message": "ملف CSV لا يحتوي منتجات.",
                "context": {},
            },
        )
    return items


@router.post("/import-csv")
async def import_simple_products_csv(
    payload: CsvImportRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_simple_manage(db, actor)
    items = _parse_csv(payload.csv_text)
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="SIMPLE_PRODUCT_CSV_IMPORT",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay

        variants = await _create_many(
            db,
            actor=actor,
            request_id=payload.request_id,
            items=items,
        )
        response = {
            "message": (
                f"تم استيراد {len(variants)} منتج واعتماد أسعارها."
            ),
            "imported_count": len(variants),
        }
        _audit(
            db,
            actor,
            "SimpleProductCsvImport",
            "SIMPLE_PRODUCT_CSV_IMPORTED",
            response,
        )
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
        ValueError,
    ) as exc:
        await db.rollback()
        code = "SIMPLE_PRODUCT_CSV_CONFLICT"
        message = (
            "تم رفض الملف بالكامل بسبب تعارض في أحد المنتجات. "
            "لم يتم حفظ أي صف."
        )
        if isinstance(exc, InventoryMutationError):
            code, message = "IDEMPOTENCY_CONFLICT", str(exc)
        raise HTTPException(
            409,
            detail={
                "code": code,
                "message": message,
                "context": {},
            },
        ) from exc
