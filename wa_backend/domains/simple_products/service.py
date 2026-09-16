"""Simple product facade over catalog + temporal pricing authorities."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.pricing.core import PricingError, maker_checker_enabled, money_20_6
from domains.pricing.publishing import (
    create_assignment, create_draft_entry, create_price_book,
    create_publication, publish_publication,
)
from domains.pricing.resolver import resolve_prices_bulk
from models import (
    Company, Driver, PriceBook, PriceBookAssignment, Product,
    ProductBarcode, ProductUomConversion, ProductVariant, UOM,
)
from product_lifecycle import (
    ProductLifecycleTransitionError, apply_variant_publish_transition,
    record_domain_event, variant_snapshot,
)

_CODE_CLEAN_RE = re.compile(r"[^A-Z0-9_.-]+")
_DIGITS_RE = re.compile(r"^\d+$")


class SimpleProductError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 409,
                 context: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}


@dataclass(frozen=True)
class SimpleProductSpec:
    name: str
    units_per_carton: int
    carton_price: Decimal | None = None
    unit_price: Decimal | None = None
    family_id: int | None = None
    family_name: str | None = None
    unit_barcode: str | None = None
    carton_barcode: str | None = None


@dataclass(frozen=True)
class ResolvedPricePair:
    carton_price: Decimal
    unit_price: Decimal
    carton_derived: bool
    unit_derived: bool


@dataclass(frozen=True)
class UomPair:
    each: UOM
    carton: UOM


def clean_text(value: Any, field: str, maximum: int, *, optional: bool = False) -> str | None:
    if value is None:
        if optional:
            return None
        raise SimpleProductError("SIMPLE_PRODUCT_FIELD_REQUIRED", f"{field} مطلوب.", status_code=422)
    clean = str(value).strip()
    if "\x00" in clean or len(clean) > maximum:
        raise SimpleProductError("SIMPLE_PRODUCT_FIELD_INVALID", f"{field} غير صالح.", status_code=422)
    if not clean:
        if optional:
            return None
        raise SimpleProductError("SIMPLE_PRODUCT_FIELD_REQUIRED", f"{field} مطلوب.", status_code=422)
    return clean


def parse_optional_money(value: Any, field: str) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (bool, float)):
        raise SimpleProductError("SIMPLE_PRODUCT_PRICE_INVALID", f"{field} يجب أن يكون قيمة عشرية دقيقة.", status_code=422)
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
        raise SimpleProductError("SIMPLE_PRODUCT_PRICE_INVALID", f"{field} غير صالح.", status_code=422) from exc
    if not amount.is_finite() or amount <= 0:
        raise SimpleProductError("SIMPLE_PRODUCT_PRICE_INVALID", f"{field} يجب أن يكون أكبر من صفر.", status_code=422)
    try:
        amount = money_20_6(amount)
    except Exception as exc:
        raise SimpleProductError("SIMPLE_PRODUCT_PRICE_INVALID", f"{field} خارج نطاق السعر المسموح.", status_code=422) from exc
    if amount <= 0:
        raise SimpleProductError("SIMPLE_PRODUCT_PRICE_INVALID", f"{field} يجب أن يكون أكبر من صفر.", status_code=422)
    return amount


def resolve_price_pair(*, units_per_carton: int, carton_price: Any = None,
                       unit_price: Any = None) -> ResolvedPricePair:
    if type(units_per_carton) is not int or units_per_carton <= 0:
        raise SimpleProductError("SIMPLE_PRODUCT_PACKAGING_INVALID", "عدد الحبات في الكرتونة يجب أن يكون رقماً صحيحاً موجباً.", status_code=422)
    carton = parse_optional_money(carton_price, "سعر الكرتونة")
    unit = parse_optional_money(unit_price, "سعر الحبة")
    if carton is None and unit is None:
        raise SimpleProductError("SIMPLE_PRODUCT_PRICE_REQUIRED", "أدخل سعر الكرتونة أو سعر الحبة على الأقل.", status_code=422)
    carton_derived = carton is None
    unit_derived = unit is None
    if carton is None:
        assert unit is not None
        carton = money_20_6(unit * Decimal(units_per_carton))
    if unit is None:
        unit = money_20_6(carton / Decimal(units_per_carton))
    if units_per_carton == 1 and carton != unit:
        raise SimpleProductError("SIMPLE_PRODUCT_SINGLE_UNIT_PRICE_CONFLICT", "عندما تحتوي الكرتونة على حبة واحدة لا يمكن اعتماد سعرين مختلفين لنفس الوحدة.", status_code=422)
    return ResolvedPricePair(carton, unit, carton_derived, unit_derived)


def _valid_gtin(value: str) -> bool:
    if not _DIGITS_RE.fullmatch(value) or len(value) not in {8, 12, 13, 14}:
        return False
    digits = [int(c) for c in value]
    expected = (10 - sum(
        digit * (3 if (len(digits) - 1 - i) % 2 == 0 else 1)
        for i, digit in enumerate(digits[:-1])
    ) % 10) % 10
    return digits[-1] == expected


def barcode_type(value: str) -> str:
    if _valid_gtin(value):
        return {8: "EAN8", 12: "UPC_A", 13: "EAN13", 14: "GTIN14"}[len(value)]
    return "INTERNAL"


def normalize_barcode(value: Any, field: str) -> str | None:
    return clean_text(value, field, 128, optional=True)


def _auto_code(prefix: str, request_id: UUID, index: int) -> str:
    raw = f"{prefix}-{request_id.hex[:16]}-{index:05d}".upper()
    return _CODE_CLEAN_RE.sub("-", raw)[:100].strip("-")


async def load_uoms(db: AsyncSession) -> UomPair:
    rows = list((await db.scalars(select(UOM).where(UOM.code.in_(("EACH", "CARTON"))))).all())
    by_code = {str(row.code).upper(): row for row in rows}
    if "EACH" not in by_code or "CARTON" not in by_code:
        raise SimpleProductError("SIMPLE_PRODUCT_UOM_MISSING", "إعداد وحدات الحبة والكرتونة غير مكتمل في النظام.")
    return UomPair(each=by_code["EACH"], carton=by_code["CARTON"])


async def load_company(db: AsyncSession, company_id: int) -> Company:
    row = await db.scalar(select(Company).where(Company.id == int(company_id)))
    if row is None:
        raise SimpleProductError("COMPANY_NOT_FOUND", "الشركة غير موجودة.", status_code=404)
    return row


async def assert_simple_pricing_mode(db: AsyncSession, *, company_id: int,
                                     as_of: datetime) -> PriceBookAssignment | None:
    if await maker_checker_enabled(db, int(company_id)):
        raise SimpleProductError("SIMPLE_PRODUCTS_APPROVAL_MODE_UNSUPPORTED", "وضع المنتجات المبسط غير متوافق مع مراجعة واعتماد الأسعار المتقدمة المفعلة حالياً.")
    advanced = await db.scalar(select(PriceBookAssignment.id).where(
        PriceBookAssignment.company_id == int(company_id),
        PriceBookAssignment.scope_type != "COMPANY_DEFAULT",
        or_(func.upper_inf(PriceBookAssignment.effectivity), func.upper(PriceBookAssignment.effectivity) > as_of),
    ).limit(1))
    if advanced is not None:
        raise SimpleProductError("SIMPLE_PRODUCTS_ADVANCED_PRICING_ACTIVE", "توجد سياسة تسعير متقدمة حالية أو مجدولة. الوضع المبسط يتطلب سعراً أساسياً واحداً للشركة.", context={"assignment_id": int(advanced)})
    future = await db.scalar(select(PriceBookAssignment.id).where(
        PriceBookAssignment.company_id == int(company_id),
        PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
        func.lower(PriceBookAssignment.effectivity) > as_of,
    ).limit(1))
    if future is not None:
        raise SimpleProductError("SIMPLE_PRODUCTS_FUTURE_PRICING_ACTIVE", "يوجد تغيير سعر أساسي مجدول مسبقاً. ألغِ الجدولة المتقدمة قبل استخدام الوضع المبسط.", context={"assignment_id": int(future)})
    defaults = list((await db.scalars(select(PriceBookAssignment).where(
        PriceBookAssignment.company_id == int(company_id),
        PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
        PriceBookAssignment.scope_id.is_(None),
        PriceBookAssignment.effectivity.contains(as_of),
    ).order_by(PriceBookAssignment.priority.desc(), PriceBookAssignment.revision.desc(), PriceBookAssignment.id.desc()))).all())
    if len(defaults) > 1:
        raise SimpleProductError("SIMPLE_PRODUCTS_MULTIPLE_DEFAULT_PRICES", "يوجد أكثر من سعر أساسي فعال للشركة. هذا إعداد متقدم لا يديره الوضع المبسط.")
    if defaults and not bool(defaults[0].allow_offers):
        raise SimpleProductError("SIMPLE_PRODUCTS_OFFERS_BLOCKED", "السعر الأساسي الحالي مضبوط كسعر نهائي يمنع العروض. هذا إعداد متقدم لا يديره الوضع المبسط.")
    return defaults[0] if defaults else None


async def current_default_book(db: AsyncSession, *, company: Company,
                               assignment: PriceBookAssignment | None) -> PriceBook | None:
    if assignment is None:
        return None
    book = await db.scalar(select(PriceBook).where(
        PriceBook.company_id == int(company.id), PriceBook.id == int(assignment.price_book_id),
        PriceBook.status == "ACTIVE",
    ))
    if book is None:
        raise SimpleProductError("SIMPLE_PRODUCT_DEFAULT_PRICE_BOOK_INVALID", "إعداد السعر الأساسي للشركة غير صالح.")
    if str(book.currency_code).upper() != str(company.currency_code).upper():
        raise SimpleProductError("SIMPLE_PRODUCT_CURRENCY_MISMATCH", "عملة السعر الأساسي تختلف عن عملة الشركة.")
    return book


async def ensure_default_book(db: AsyncSession, *, company: Company, actor_id: int,
                              as_of: datetime, assignment: PriceBookAssignment | None) -> PriceBook:
    current = await current_default_book(db, company=company, assignment=assignment)
    if current is not None:
        return current
    codes = ("DEFAULT", "SIMPLE_DEFAULT", "SMB_DEFAULT")
    existing = list((await db.scalars(select(PriceBook).where(
        PriceBook.company_id == int(company.id), PriceBook.code.in_(codes)
    ).order_by(PriceBook.id.asc()))).all())
    book = next((row for row in existing if row.status == "ACTIVE"), None)
    if book is None:
        used = {str(row.code).upper() for row in existing}
        free = next((code for code in codes if code not in used), None)
        if free is None:
            raise SimpleProductError("SIMPLE_PRODUCT_DEFAULT_BOOK_CONFLICT", "تعذر إنشاء سجل السعر الأساسي تلقائياً بسبب إعداد سابق غير متوافق.")
        book = await create_price_book(db, company_id=int(company.id), actor_id=int(actor_id),
                                       code=free, name="الأسعار الأساسية",
                                       currency_code=str(company.currency_code).upper(),
                                       applicability_metadata={"managed_by": "simple_products"})
    await create_assignment(db, company_id=int(company.id), actor_id=int(actor_id),
                            price_book_id=int(book.id), scope_type="COMPANY_DEFAULT",
                            scope_id=None, allow_offers=True, priority=0,
                            effective_from=as_of, effective_to=None)
    return book


async def list_families(db: AsyncSession, *, company_id: int, search: str | None = None,
                        limit: int = 50) -> list[dict[str, Any]]:
    stmt = select(Product).where(Product.company_id == int(company_id))
    if search:
        clean = search.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        stmt = stmt.where(func.lower(Product.name).like(f"%{clean}%", escape="\\"))
    rows = list((await db.scalars(stmt.order_by(Product.name.asc(), Product.id.asc()).limit(limit))).all())
    return [{"id": int(row.id), "name": str(row.name)} for row in rows]


async def _resolve_family(db: AsyncSession, *, actor: Driver, spec: SimpleProductSpec,
                          request_id: UUID, index: int) -> Product:
    if spec.family_id is not None and spec.family_name is not None:
        raise SimpleProductError("SIMPLE_PRODUCT_FAMILY_AMBIGUOUS", "اختر عائلة موجودة أو أدخل عائلة جديدة، وليس الاثنين.", status_code=422)
    if spec.family_id is not None:
        row = await db.scalar(select(Product).where(Product.company_id == int(actor.company_id), Product.id == int(spec.family_id)))
        if row is None:
            raise SimpleProductError("SIMPLE_PRODUCT_FAMILY_NOT_FOUND", "عائلة المنتج غير موجودة.", status_code=404)
        return row
    family_name = clean_text(spec.family_name, "العائلة", 150, optional=True) if spec.family_name is not None else None
    family_name = family_name or clean_text(spec.name, "اسم المنتج", 150)
    matches = list((await db.scalars(select(Product).where(
        Product.company_id == int(actor.company_id), func.lower(Product.name) == str(family_name).lower()
    ).order_by(Product.id.asc()).limit(2))).all())
    if len(matches) > 1:
        raise SimpleProductError("SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS", "يوجد أكثر من عائلة بنفس الاسم. اختر العائلة من القائمة.")
    if matches:
        return matches[0]
    row = Product(company_id=int(actor.company_id), code=_auto_code("FAM", request_id, index), name=family_name)
    db.add(row)
    await db.flush()
    return row


async def _assert_barcodes_available(db: AsyncSession, company_id: int, values: list[str]) -> None:
    if not values:
        return
    duplicate = await db.scalar(select(ProductBarcode.barcode).where(
        ProductBarcode.company_id == int(company_id), ProductBarcode.barcode.in_(values),
        ProductBarcode.is_active.is_(True),
    ).limit(1))
    if duplicate is not None:
        raise SimpleProductError("SIMPLE_PRODUCT_BARCODE_CONFLICT", "الباركود مستخدم مسبقاً في منتج آخر.", context={"barcode": str(duplicate)})


async def create_product_structures(db: AsyncSession, *, actor: Driver, request_id: UUID,
                                    specs: list[SimpleProductSpec], uoms: UomPair):
    all_barcodes = [b for spec in specs for b in (
        normalize_barcode(spec.unit_barcode, "باركود الحبة"),
        normalize_barcode(spec.carton_barcode, "باركود الكرتونة"),
    ) if b]
    if len(all_barcodes) != len(set(all_barcodes)):
        raise SimpleProductError("SIMPLE_PRODUCT_BARCODE_DUPLICATE", "يوجد باركود مكرر ضمن المنتجات المدخلة.", status_code=422)
    await _assert_barcodes_available(db, int(actor.company_id), all_barcodes)
    result = []
    for index, spec in enumerate(specs, 1):
        name = clean_text(spec.name, "اسم المنتج", 200)
        prices = resolve_price_pair(units_per_carton=spec.units_per_carton,
                                    carton_price=spec.carton_price, unit_price=spec.unit_price)
        family = await _resolve_family(db, actor=actor, spec=spec, request_id=request_id, index=index)
        variant = ProductVariant(
            company_id=int(actor.company_id), product_id=int(family.id), base_uom_id=int(uoms.each.id),
            name=name, sku=_auto_code("SKU", request_id, index), quantity_scale=0,
            quantity_step=Decimal("1"), lot_control_mode="REQUIRED", expiry_control_mode="REQUIRED",
            lifecycle_status="DRAFT", operational_hold="NONE", packs_per_carton=int(spec.units_per_carton),
        )
        db.add(variant)
        await db.flush()
        if int(spec.units_per_carton) > 1:
            db.add(ProductUomConversion(company_id=int(actor.company_id), product_variant_id=int(variant.id),
                                        from_uom_id=int(uoms.carton.id), to_uom_id=int(uoms.each.id),
                                        numerator=Decimal(int(spec.units_per_carton)), denominator=Decimal("1"), quantity_scale=0))
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        ub = normalize_barcode(spec.unit_barcode, "باركود الحبة")
        cb = normalize_barcode(spec.carton_barcode, "باركود الكرتونة")
        if ub:
            db.add(ProductBarcode(company_id=int(actor.company_id), product_variant_id=int(variant.id),
                                  uom_id=int(uoms.each.id), barcode=ub, barcode_type=barcode_type(ub),
                                  is_primary=True, valid_from=now, valid_to=None, is_active=True))
        if cb:
            if int(spec.units_per_carton) == 1:
                if ub and cb != ub:
                    raise SimpleProductError("SIMPLE_PRODUCT_SINGLE_UNIT_BARCODE_CONFLICT", "عندما تكون الكرتونة حبة واحدة لا يمكن وضع باركودين أساسيين مختلفين لنفس الوحدة.", status_code=422)
                if not ub:
                    db.add(ProductBarcode(company_id=int(actor.company_id), product_variant_id=int(variant.id),
                                          uom_id=int(uoms.each.id), barcode=cb, barcode_type=barcode_type(cb),
                                          is_primary=True, valid_from=now, valid_to=None, is_active=True))
            else:
                db.add(ProductBarcode(company_id=int(actor.company_id), product_variant_id=int(variant.id),
                                      uom_id=int(uoms.carton.id), barcode=cb, barcode_type=barcode_type(cb),
                                      is_primary=True, valid_from=now, valid_to=None, is_active=True))
        before = variant_snapshot(variant)
        try:
            event_type, message = apply_variant_publish_transition(variant, now)
        except ProductLifecycleTransitionError as exc:
            raise SimpleProductError(exc.code, exc.message, status_code=exc.status_code) from exc
        variant.lifecycle_revision += 1
        variant.version += 1
        variant.updated_at = now
        record_domain_event(db, company_id=int(actor.company_id), actor_id=int(actor.id), request_id=request_id,
                            event_type=event_type, entity_type="ProductVariant", entity_id=int(variant.id),
                            reason=message, before=before, after=variant_snapshot(variant))
        result.append((variant, spec, prices))
    await db.flush()
    return result


async def publish_prices(db: AsyncSession, *, actor: Driver, book: PriceBook, rows, uoms: UomPair,
                         effective_at: datetime, request_id: UUID) -> None:
    publication = await create_publication(db, company_id=int(actor.company_id), actor_id=int(actor.id),
                                           book_id=int(book.id), expected_book_version=int(book.version),
                                           effective_at=effective_at, request_id=request_id)
    for variant, _spec, prices in rows:
        await create_draft_entry(db, company_id=int(actor.company_id), publication_id=int(publication.id),
                                 expected_publication_version=int(publication.version), product_variant_id=int(variant.id),
                                 uom_id=int(uoms.each.id), amount=prices.unit_price, effective_from=effective_at,
                                 effective_to=None, priority=0,
                                 metadata={"managed_by": "simple_products", "price_input": "derived" if prices.unit_derived else "explicit", "units_per_carton": int(variant.packs_per_carton)})
        if int(variant.packs_per_carton) > 1:
            await create_draft_entry(db, company_id=int(actor.company_id), publication_id=int(publication.id),
                                     expected_publication_version=int(publication.version), product_variant_id=int(variant.id),
                                     uom_id=int(uoms.carton.id), amount=prices.carton_price, effective_from=effective_at,
                                     effective_to=None, priority=0,
                                     metadata={"managed_by": "simple_products", "price_input": "derived" if prices.carton_derived else "explicit", "units_per_carton": int(variant.packs_per_carton)})
    await publish_publication(db, company_id=int(actor.company_id), actor_id=int(actor.id),
                              publication_id=int(publication.id), expected_version=int(publication.version))


async def create_products_and_prices(db: AsyncSession, *, actor: Driver, request_id: UUID,
                                     specs: list[SimpleProductSpec]):
    if not specs:
        raise SimpleProductError("SIMPLE_PRODUCT_EMPTY", "لا توجد منتجات للحفظ.", status_code=422)
    now = datetime.now(timezone.utc)
    assignment = await assert_simple_pricing_mode(db, company_id=int(actor.company_id), as_of=now)
    company = await load_company(db, int(actor.company_id))
    uoms = await load_uoms(db)
    book = await ensure_default_book(db, company=company, actor_id=int(actor.id), as_of=now, assignment=assignment)
    structures = await create_product_structures(db, actor=actor, request_id=request_id, specs=specs, uoms=uoms)
    await publish_prices(db, actor=actor, book=book, rows=structures, uoms=uoms, effective_at=now, request_id=request_id)
    return [(variant, prices) for variant, _spec, prices in structures]


async def assert_simple_variant(db: AsyncSession, *, company_id: int, variant: ProductVariant, uoms: UomPair) -> None:
    if int(variant.base_uom_id) != int(uoms.each.id):
        raise SimpleProductError("SIMPLE_PRODUCT_BASE_UOM_UNSUPPORTED", "هذا المنتج يستخدم بنية وحدات متقدمة ولا يمكن تعديل سعره من الشاشة المبسطة.")
    packs = int(variant.packs_per_carton or 0)
    if packs <= 0:
        raise SimpleProductError("SIMPLE_PRODUCT_PACKAGING_INVALID", "عدد الحبات في الكرتونة غير صالح لهذا المنتج.")
    if packs == 1:
        return
    rows = list((await db.scalars(select(ProductUomConversion).where(
        ProductUomConversion.company_id == int(company_id), ProductUomConversion.product_variant_id == int(variant.id),
        ProductUomConversion.from_uom_id == int(uoms.carton.id), ProductUomConversion.to_uom_id == int(uoms.each.id),
    ))).all())
    valid = [r for r in rows if Decimal(r.numerator) / Decimal(r.denominator) == Decimal(packs)]
    if len(valid) != 1:
        raise SimpleProductError("SIMPLE_PRODUCT_CARTON_MAPPING_INVALID", "تحويل الكرتونة إلى الحبات غير صالح لهذا المنتج.")


async def update_prices(db: AsyncSession, *, actor: Driver, request_id: UUID, variant: ProductVariant,
                        carton_price: Any = None, unit_price: Any = None) -> ResolvedPricePair:
    now = datetime.now(timezone.utc)
    assignment = await assert_simple_pricing_mode(db, company_id=int(actor.company_id), as_of=now)
    uoms = await load_uoms(db)
    await assert_simple_variant(db, company_id=int(actor.company_id), variant=variant, uoms=uoms)
    prices = resolve_price_pair(units_per_carton=int(variant.packs_per_carton), carton_price=carton_price, unit_price=unit_price)
    company = await load_company(db, int(actor.company_id))
    book = await ensure_default_book(db, company=company, actor_id=int(actor.id), as_of=now, assignment=assignment)
    spec = SimpleProductSpec(name=str(variant.name), units_per_carton=int(variant.packs_per_carton),
                             carton_price=prices.carton_price, unit_price=prices.unit_price)
    await publish_prices(db, actor=actor, book=book, rows=[(variant, spec, prices)], uoms=uoms,
                         effective_at=now, request_id=request_id)
    return prices


async def current_prices(db: AsyncSession, *, company_id: int, variants: list[ProductVariant],
                         uoms: UomPair, as_of: datetime):
    if not variants:
        return {}
    pairs = []
    for v in variants:
        pairs.append((int(v.id), int(uoms.each.id)))
        if int(v.packs_per_carton or 0) > 1:
            pairs.append((int(v.id), int(uoms.carton.id)))
    try:
        resolved = await resolve_prices_bulk(db, company_id=int(company_id), pairs=pairs, customer_id=None,
                                             branch_id=None, as_of=as_of, allow_unresolved_pairs=True)
    except PricingError as exc:
        if exc.code == "PRICE_NOT_RESOLVED":
            return {}
        raise
    result = {}
    for v in variants:
        unit = resolved.get((int(v.id), int(uoms.each.id)))
        carton = unit if int(v.packs_per_carton or 0) == 1 else resolved.get((int(v.id), int(uoms.carton.id)))
        result[int(v.id)] = (Decimal(carton.amount) if carton else None, Decimal(unit.amount) if unit else None)
    return result


async def current_primary_barcodes(db: AsyncSession, *, company_id: int, variants: list[ProductVariant], uoms: UomPair):
    if not variants:
        return {}
    ids = [int(v.id) for v in variants]
    rows = list((await db.scalars(select(ProductBarcode).where(
        ProductBarcode.company_id == int(company_id), ProductBarcode.product_variant_id.in_(ids),
        ProductBarcode.is_active.is_(True), ProductBarcode.is_primary.is_(True),
    ))).all())
    result = {i: [None, None] for i in ids}
    for row in rows:
        if int(row.uom_id) == int(uoms.each.id):
            result[int(row.product_variant_id)][0] = str(row.barcode)
        elif int(row.uom_id) == int(uoms.carton.id):
            result[int(row.product_variant_id)][1] = str(row.barcode)
    return {k: tuple(v) for k, v in result.items()}


async def simple_compatibility(db: AsyncSession, *, company_id: int, variants: list[ProductVariant], uoms: UomPair):
    if not variants:
        return {}
    ids = [int(v.id) for v in variants]
    rows = list((await db.scalars(select(ProductUomConversion).where(
        ProductUomConversion.company_id == int(company_id), ProductUomConversion.product_variant_id.in_(ids),
        ProductUomConversion.from_uom_id == int(uoms.carton.id), ProductUomConversion.to_uom_id == int(uoms.each.id),
    ))).all())
    by_variant = {}
    for row in rows:
        by_variant.setdefault(int(row.product_variant_id), []).append(row)
    result = {}
    for v in variants:
        packs = int(v.packs_per_carton or 0)
        if int(v.base_uom_id) != int(uoms.each.id) or packs <= 0:
            result[int(v.id)] = False
        elif packs == 1:
            result[int(v.id)] = True
        else:
            result[int(v.id)] = len([r for r in by_variant.get(int(v.id), []) if Decimal(r.numerator) / Decimal(r.denominator) == Decimal(packs)]) == 1
    return result
