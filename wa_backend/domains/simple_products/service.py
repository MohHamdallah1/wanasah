"""Simple product facade over catalog + temporal pricing authorities.

The dashboard intentionally exposes a tiny SMB workflow. Internally this module
keeps Product/ProductVariant/UOM/PriceBook authority intact.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from sqlalchemy import String, and_, cast, func, or_, select, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from domains.pricing.core import PricingError, maker_checker_enabled, money_20_6
from domains.pricing.publishing import (
    create_assignment,
    create_direct_publication,
    create_price_book,
)
from domains.pricing.resolver import resolve_prices_bulk
from domains.simple_products.observability import product_phase
from domains.live_stock_projection.service import (
    LiveStockProjectionError,
    apply_live_stock_active_variant_delta,
)
from domains.product_tracking import (
    ProductTrackingDefaults,
    ProductTrackingError,
    load_company_product_tracking_defaults,
    resolve_product_tracking_modes_from_defaults,
)
from models import (
    Company,
    Driver,
    PriceBook,
    PriceBookAssignment,
    PriceBookEntry,
    PricePublication,
    Product,
    ProductBarcode,
    ProductUomConversion,
    ProductVariant,
    UOM,
)
from product_lifecycle import (
    ProductLifecycleTransitionError,
    create_published_variants,
    record_domain_event,
)

_CODE_CLEAN_RE = re.compile(r"[^A-Z0-9_.-]+")
_DIGITS_RE = re.compile(r"^\d+$")

BASE_UOM_CODE = "EACH"
SUPPORTED_PACKAGE_UOM_CODES = (
    "CARTON",
    "CASE",
    "PACK",
    "BAG",
    "SACK",
    "TRAY",
    "CRATE",
    "BUNDLE",
    "PALLET",
)


class SimpleProductError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = context or {}


@dataclass(frozen=True)
class SimpleProductSpec:
    name: str
    units_per_package: int
    package_uom_code: str | None = "CARTON"
    package_price: Decimal | None = None
    unit_price: Decimal | None = None
    family_id: int | None = None
    family_name: str | None = None
    family_mode: str | None = None  # None preserves existing import/legacy semantics.
    unit_barcode: str | None = None
    package_barcode: str | None = None
    lot_control_mode: str | None = None
    expiry_control_mode: str | None = None


@dataclass(frozen=True)
class ResolvedPricePair:
    package_price: Decimal | None
    unit_price: Decimal
    package_derived: bool
    unit_derived: bool


@dataclass(frozen=True)
class SaleShape:
    base_uom: UOM
    package_uom: UOM | None
    units_per_package: int


def clean_text(
    value: Any,
    field: str,
    maximum: int,
    *,
    optional: bool = False,
) -> str | None:
    if value is None:
        if optional:
            return None
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FIELD_REQUIRED",
            f"{field} is required.",
            status_code=422,
            context={"field": field},
        )
    clean = str(value).strip()
    if "\x00" in clean or len(clean) > maximum:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FIELD_INVALID",
            f"{field} is invalid.",
            status_code=422,
            context={"field": field},
        )
    if not clean:
        if optional:
            return None
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FIELD_REQUIRED",
            f"{field} is required.",
            status_code=422,
            context={"field": field},
        )
    return clean


def parse_optional_money(value: Any, field: str) -> Decimal | None:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, (bool, float)):
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PRICE_INVALID",
            f"{field} must be an exact decimal value.",
            status_code=422,
            context={"field": field},
        )
    try:
        amount = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError, AttributeError) as exc:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PRICE_INVALID",
            f"{field} is invalid.",
            status_code=422,
            context={"field": field},
        ) from exc
    if not amount.is_finite() or amount <= 0:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PRICE_INVALID",
            f"{field} must be greater than zero.",
            status_code=422,
            context={"field": field},
        )
    try:
        amount = money_20_6(amount)
    except Exception as exc:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PRICE_INVALID",
            f"{field} is outside the supported money range.",
            status_code=422,
            context={"field": field},
        ) from exc
    if amount <= 0:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PRICE_INVALID",
            f"{field} must be greater than zero.",
            status_code=422,
            context={"field": field},
        )
    return amount


def normalize_package_code(value: Any) -> str | None:
    if value is None:
        return None
    clean = str(value).strip().upper()
    if not clean or clean in {"NONE", "NO_PACKAGE"}:
        return None
    if clean not in SUPPORTED_PACKAGE_UOM_CODES:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PACKAGE_UOM_UNSUPPORTED",
            "The selected package unit is not supported by the simple product workflow.",
            status_code=422,
            context={"package_uom_code": clean},
        )
    return clean


def resolve_price_pair(
    *,
    units_per_package: int,
    package_uom_code: str | None,
    package_price: Any = None,
    unit_price: Any = None,
) -> ResolvedPricePair:
    package_code = normalize_package_code(package_uom_code)
    if type(units_per_package) is not int or units_per_package <= 0:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PACKAGING_INVALID",
            "units_per_package must be a positive integer.",
            status_code=422,
        )

    package = parse_optional_money(package_price, "package_price")
    unit = parse_optional_money(unit_price, "unit_price")

    if package_code is None:
        if units_per_package != 1:
            raise SimpleProductError(
                "SIMPLE_PRODUCT_NO_PACKAGE_FACTOR_INVALID",
                "A product without an outer package must use units_per_package=1.",
                status_code=422,
            )
        if package is not None:
            raise SimpleProductError(
                "SIMPLE_PRODUCT_PACKAGE_PRICE_WITHOUT_PACKAGE",
                "package_price cannot be supplied when there is no outer package.",
                status_code=422,
            )
        if unit is None:
            raise SimpleProductError(
                "SIMPLE_PRODUCT_PRICE_REQUIRED",
                "unit_price is required when the product has no outer package.",
                status_code=422,
            )
        return ResolvedPricePair(
            package_price=None,
            unit_price=unit,
            package_derived=False,
            unit_derived=False,
        )

    if units_per_package < 2:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PACKAGE_FACTOR_INVALID",
            "An outer package must contain at least two base units.",
            status_code=422,
        )
    if package is None and unit is None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_PRICE_REQUIRED",
            "Provide package_price or unit_price.",
            status_code=422,
        )

    package_derived = package is None
    unit_derived = unit is None
    if package is None:
        assert unit is not None
        package = money_20_6(unit * Decimal(units_per_package))
    if unit is None:
        assert package is not None
        unit = money_20_6(package / Decimal(units_per_package))

    return ResolvedPricePair(
        package_price=package,
        unit_price=unit,
        package_derived=package_derived,
        unit_derived=unit_derived,
    )


def _valid_gtin(value: str) -> bool:
    if not _DIGITS_RE.fullmatch(value) or len(value) not in {8, 12, 13, 14}:
        return False
    digits = [int(char) for char in value]
    expected = (
        10
        - sum(
            digit * (3 if (len(digits) - 1 - index) % 2 == 0 else 1)
            for index, digit in enumerate(digits[:-1])
        )
        % 10
    ) % 10
    return digits[-1] == expected


def barcode_type(value: str) -> str:
    if _valid_gtin(value):
        return {
            8: "EAN8",
            12: "UPC_A",
            13: "EAN13",
            14: "GTIN14",
        }[len(value)]
    return "INTERNAL"


def normalize_barcode(value: Any, field: str) -> str | None:
    return clean_text(value, field, 128, optional=True)


def _auto_code(prefix: str, request_id: UUID, index: int) -> str:
    raw = f"{prefix}-{request_id.hex[:16]}-{index:05d}".upper()
    return _CODE_CLEAN_RE.sub("-", raw)[:100].strip("-")


async def _family_name_lock(
    db: AsyncSession,
    *,
    company_id: int,
    family_name: str,
) -> None:
    await db.execute(
        text(
            "SELECT pg_advisory_xact_lock("
            ":company_id, hashtext(:family_name))"
        ),
        {
            "company_id": int(company_id),
            "family_name": family_name.strip().lower(),
        },
    )


async def _load_uom_code(
    db: AsyncSession,
    code: str,
    *,
    batch_cache: dict[str, UOM] | None = None,
) -> UOM:
    normalized = str(code).strip().upper()
    # UOM is immutable global reference data. Reuse reference rows only within
    # this one product-creation batch; never cache across tenants/requests.
    if batch_cache is not None and normalized in batch_cache:
        return batch_cache[normalized]
    row = await db.scalar(
        select(UOM).where(UOM.code == normalized)
    )
    if row is None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_UOM_MISSING",
            "Required UOM reference data is missing.",
            context={"uom_code": normalized},
        )
    if batch_cache is not None:
        batch_cache[normalized] = row
    return row


async def list_package_uoms(db: AsyncSession) -> list[dict[str, Any]]:
    rows = list(
        (
            await db.scalars(
                select(UOM)
                .where(UOM.code.in_(SUPPORTED_PACKAGE_UOM_CODES))
                .order_by(UOM.id.asc())
            )
        ).all()
    )
    by_code = {str(row.code).upper(): row for row in rows}
    missing = [
        code
        for code in SUPPORTED_PACKAGE_UOM_CODES
        if code not in by_code
    ]
    if missing:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_UOM_MISSING",
            "Package UOM reference data is incomplete.",
            context={"missing_codes": missing},
        )
    return [
        {"id": int(by_code[code].id), "code": code}
        for code in SUPPORTED_PACKAGE_UOM_CODES
    ]


async def load_company(db: AsyncSession, company_id: int) -> Company:
    row = await db.scalar(
        select(Company).where(Company.id == int(company_id))
    )
    if row is None:
        raise SimpleProductError(
            "COMPANY_NOT_FOUND",
            "Company was not found.",
            status_code=404,
        )
    return row


async def assert_simple_pricing_mode(
    db: AsyncSession,
    *,
    company_id: int,
    as_of: datetime,
) -> PriceBookAssignment | None:
    if await maker_checker_enabled(db, int(company_id)):
        raise SimpleProductError(
            "SIMPLE_PRODUCTS_APPROVAL_MODE_UNSUPPORTED",
            "Simple products cannot run while advanced price approval is enabled.",
        )

    # Preserve the exact previous error precedence while replacing three
    # PriceBookAssignment reads (advanced, future default, active default)
    # with one tenant-scoped snapshot.
    advanced_predicate = and_(
        PriceBookAssignment.scope_type != "COMPANY_DEFAULT",
        or_(
            func.upper_inf(PriceBookAssignment.effectivity),
            func.upper(PriceBookAssignment.effectivity) > as_of,
        ),
    )
    future_default_predicate = and_(
        PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
        func.lower(PriceBookAssignment.effectivity) > as_of,
    )
    active_default_predicate = and_(
        PriceBookAssignment.scope_type == "COMPANY_DEFAULT",
        PriceBookAssignment.scope_id.is_(None),
        PriceBookAssignment.effectivity.contains(as_of),
    )
    policy_rows = (
        await db.execute(
            select(
                PriceBookAssignment,
                advanced_predicate.label("is_advanced"),
                future_default_predicate.label("is_future_default"),
                active_default_predicate.label("is_active_default"),
            )
            .where(
                PriceBookAssignment.company_id == int(company_id),
                or_(
                    advanced_predicate,
                    future_default_predicate,
                    active_default_predicate,
                ),
            )
            .execution_options(
                wanasah_sql_trace_label="simple_pricing_policy_assignments"
            )
        )
    ).all()

    advanced = sorted(
        (
            assignment
            for assignment, is_advanced, _is_future, _is_default in policy_rows
            if bool(is_advanced)
        ),
        key=lambda row: int(row.id),
    )
    if advanced:
        raise SimpleProductError(
            "SIMPLE_PRODUCTS_ADVANCED_PRICING_ACTIVE",
            "Advanced pricing is active or scheduled for this company.",
            context={"assignment_id": int(advanced[0].id)},
        )

    future = sorted(
        (
            assignment
            for assignment, _is_advanced, is_future, _is_default in policy_rows
            if bool(is_future)
        ),
        key=lambda row: int(row.id),
    )
    if future:
        raise SimpleProductError(
            "SIMPLE_PRODUCTS_FUTURE_PRICING_ACTIVE",
            "A future company-default price assignment is already scheduled.",
            context={"assignment_id": int(future[0].id)},
        )

    defaults = [
        assignment
        for assignment, _is_advanced, _is_future, is_default in policy_rows
        if bool(is_default)
    ]
    defaults.sort(
        key=lambda row: (
            int(row.priority),
            int(row.revision),
            int(row.id),
        ),
        reverse=True,
    )
    if len(defaults) > 1:
        raise SimpleProductError(
            "SIMPLE_PRODUCTS_MULTIPLE_DEFAULT_PRICES",
            "More than one company-default pricing assignment is active.",
        )
    if defaults and not bool(defaults[0].allow_offers):
        raise SimpleProductError(
            "SIMPLE_PRODUCTS_OFFERS_BLOCKED",
            "The active default price is configured as offer-exclusive.",
        )
    return defaults[0] if defaults else None


async def load_company_and_current_default_book(
    db: AsyncSession,
    *,
    company_id: int,
    assignment: PriceBookAssignment | None,
) -> tuple[Company, PriceBook | None]:
    """Load the company and assigned active book in one common-path query."""
    if assignment is None:
        return await load_company(db, company_id), None

    row = (
        await db.execute(
            select(Company, PriceBook)
            .select_from(Company)
            .outerjoin(
                PriceBook,
                and_(
                    PriceBook.company_id == Company.id,
                    PriceBook.id == int(assignment.price_book_id),
                    PriceBook.status == "ACTIVE",
                ),
            )
            .where(Company.id == int(company_id))
            .execution_options(
                wanasah_sql_trace_label="simple_pricing_company_default_book"
            )
        )
    ).one_or_none()
    if row is None:
        raise SimpleProductError(
            "COMPANY_NOT_FOUND",
            "Company was not found.",
            status_code=404,
        )

    company, book = row
    if book is None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_DEFAULT_PRICE_BOOK_INVALID",
            "The company default price book is invalid.",
        )
    if str(book.currency_code).upper() != str(company.currency_code).upper():
        raise SimpleProductError(
            "SIMPLE_PRODUCT_CURRENCY_MISMATCH",
            "The default price-book currency differs from the company currency.",
        )
    return company, book


async def current_default_book(
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
        raise SimpleProductError(
            "SIMPLE_PRODUCT_DEFAULT_PRICE_BOOK_INVALID",
            "The company default price book is invalid.",
        )
    if str(book.currency_code).upper() != str(company.currency_code).upper():
        raise SimpleProductError(
            "SIMPLE_PRODUCT_CURRENCY_MISMATCH",
            "The default price-book currency differs from the company currency.",
        )
    return book


async def ensure_default_book(
    db: AsyncSession,
    *,
    company: Company,
    actor_id: int,
    as_of: datetime,
    assignment: PriceBookAssignment | None,
) -> PriceBook:
    current = await current_default_book(
        db,
        company=company,
        assignment=assignment,
    )
    if current is not None:
        return current

    codes = ("DEFAULT", "SIMPLE_DEFAULT", "SMB_DEFAULT")
    existing = list(
        (
            await db.scalars(
                select(PriceBook)
                .where(
                    PriceBook.company_id == int(company.id),
                    PriceBook.code.in_(codes),
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
        free = next(
            (code for code in codes if code not in used),
            None,
        )
        if free is None:
            raise SimpleProductError(
                "SIMPLE_PRODUCT_DEFAULT_BOOK_CONFLICT",
                "No safe default price-book code is available.",
            )
        book = await create_price_book(
            db,
            company_id=int(company.id),
            actor_id=int(actor_id),
            code=free,
            name="Default prices",
            currency_code=str(company.currency_code).upper(),
            applicability_metadata={"managed_by": "simple_products"},
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


async def list_families(
    db: AsyncSession,
    *,
    company_id: int,
    search: str | None = None,
    after_name: str | None = None,
    after_id: int | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    name_key = func.lower(Product.name)
    stmt = (
        select(
            Product.id,
            Product.name,
            Product.version,
            name_key.label("sort_name"),
            func.count(ProductVariant.id).label("variant_count"),
        )
        .outerjoin(
            ProductVariant,
            (ProductVariant.company_id == Product.company_id)
            & (ProductVariant.product_id == Product.id),
        )
        .where(Product.company_id == int(company_id))
    )
    if search:
        escaped = (
            search.strip()
            .lower()
            .replace("\\", "\\\\")
            .replace("%", "\\%")
            .replace("_", "\\_")
        )
        stmt = stmt.where(
            name_key.like(
                f"%{escaped}%",
                escape="\\",
            )
        )

    if (after_name is None) != (after_id is None):
        raise ValueError(
            "Family keyset cursor requires name and id together."
        )
    if after_name is not None and after_id is not None:
        if not after_name.strip() or after_id <= 0:
            raise ValueError("Invalid family keyset cursor.")
        stmt = stmt.where(
            or_(
                name_key > after_name,
                (name_key == after_name)
                & (Product.id > int(after_id)),
            )
        )

    rows = (
        await db.execute(
            stmt.group_by(
                Product.id,
                name_key,
            )
            .order_by(name_key.asc(), Product.id.asc())
            .limit(limit)
        )
    ).all()
    return [
        {
            "id": int(row.id),
            "name": str(row.name),
            "version": int(row.version),
            "variant_count": int(row.variant_count or 0),
            "_sort_name": str(row.sort_name),
        }
        for row in rows
    ]


async def _family_matches_by_normalized_names(
    db: AsyncSession,
    *,
    company_id: int,
    normalized_names: list[str],
) -> list[tuple[Product, str]]:
    """Resolve at most two Product masters per normalized name under FORCE RLS.

    The SECURITY DEFINER function validates app.current_tenant and performs the
    lower(name) predicate below the RLS security barrier, where the matching
    expression index is usable. The outer Product join remains tenant-scoped and
    returns ORM entities in the caller's normal session.
    """
    names = sorted(set(normalized_names))
    if not names:
        return []
    resolver = (
        func.public.simple_products_family_match_ids(
            int(company_id),
            cast(names, ARRAY(String())),
        )
        .table_valued("id", "normalized")
        .alias("family_name_matches")
    )
    rows = (
        await db.execute(
            select(Product, resolver.c.normalized)
            .join(
                resolver,
                and_(
                    Product.company_id == int(company_id),
                    Product.id == resolver.c.id,
                ),
            )
            .where(Product.company_id == int(company_id))
            .order_by(Product.id.asc())
            .execution_options(
                wanasah_sql_trace_label="simple_product_family_name_resolver"
            )
        )
    ).all()
    return [(row, str(normalized)) for row, normalized in rows]


async def create_family(
    db: AsyncSession,
    *,
    company_id: int,
    request_id: UUID,
    name: str,
) -> Product:
    clean_name = clean_text(name, "family_name", 200)
    assert clean_name is not None
    await _family_name_lock(
        db,
        company_id=int(company_id),
        family_name=clean_name,
    )

    existing_matches = await _family_matches_by_normalized_names(
        db,
        company_id=int(company_id),
        normalized_names=[clean_name.lower()],
    )
    if existing_matches:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT",
            "A family with this name already exists.",
        )

    row = Product(
        company_id=int(company_id),
        code=_auto_code("FAM", request_id, 1),
        name=clean_name,
    )
    db.add(row)
    await db.flush()
    return row


async def rename_family(
    db: AsyncSession,
    *,
    company_id: int,
    family_id: int,
    expected_version: int,
    name: str,
) -> Product:
    clean_name = clean_text(name, "family_name", 200)
    assert clean_name is not None
    await _family_name_lock(
        db,
        company_id=int(company_id),
        family_name=clean_name,
    )

    row = await db.scalar(
        select(Product)
        .where(
            Product.company_id == int(company_id),
            Product.id == int(family_id),
        )
        .with_for_update()
    )
    if row is None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NOT_FOUND",
            "Product family was not found.",
            status_code=404,
        )
    if int(row.version) != int(expected_version):
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_VERSION_CONFLICT",
            "The product family changed. Refresh and retry.",
            context={"current_version": int(row.version)},
        )

    duplicate_matches = await _family_matches_by_normalized_names(
        db,
        company_id=int(company_id),
        normalized_names=[clean_name.lower()],
    )
    duplicate = next(
        (
            family
            for family, _normalized in duplicate_matches
            if int(family.id) != int(family_id)
        ),
        None,
    )
    if duplicate is not None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT",
            "A family with this name already exists.",
        )

    row.name = clean_name
    row.version += 1
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()
    return row


async def delete_family(
    db: AsyncSession,
    *,
    company_id: int,
    family_id: int,
    expected_version: int,
) -> Product:
    row = await db.scalar(
        select(Product)
        .where(
            Product.company_id == int(company_id),
            Product.id == int(family_id),
        )
        .with_for_update()
    )
    if row is None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NOT_FOUND",
            "Product family was not found.",
            status_code=404,
        )
    if int(row.version) != int(expected_version):
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_VERSION_CONFLICT",
            "The product family changed. Refresh and retry.",
            context={
                "family_id": int(family_id),
                "current_version": int(row.version),
            },
        )

    linked_variant_id = await db.scalar(
        select(ProductVariant.id)
        .where(
            ProductVariant.company_id == int(company_id),
            ProductVariant.product_id == int(family_id),
        )
        .limit(1)
    )
    if linked_variant_id is not None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NOT_EMPTY",
            "A product family containing products cannot be deleted.",
            context={
                "family_id": int(family_id),
                "sample_product_variant_id": int(linked_variant_id),
            },
        )

    await db.delete(row)
    await db.flush()
    return row



@dataclass
class _BatchFamilyLookup:
    """Only for one same-company transaction; not a global family identity cache."""

    locked_names: frozenset[str]
    matches: dict[str, list[Product]]
    # Positive ID lookups require a row lock in this exact transaction scope.
    by_id: dict[tuple[int, int], Product] = field(default_factory=dict)
    _id_scope: tuple[Any, Any, Any] | None = field(default=None, init=False)

    def locked_ids(self, db: AsyncSession) -> dict[tuple[int, int], Product]:
        scope = (db, db.get_transaction(), db.get_nested_transaction())
        if (
            scope[1] is None
            or not scope[1].is_active
            or (scope[2] is not None and not scope[2].is_active)
            or self._id_scope is None
            or any(previous is not current for previous, current in zip(
                self._id_scope, scope,
            ))
        ):
            # Rollback to a savepoint can release the corresponding row locks.
            # A reused lookup must reacquire them, even in the same session.
            self.by_id.clear()
        self._id_scope = scope
        return self.by_id

    def remember(self, row: Product) -> None:
        normalized = str(row.name).lower()
        if normalized not in self.locked_names:
            return
        current = self.matches.setdefault(normalized, [])
        current.append(row)
        # The previous resolver used ORDER BY id ASC LIMIT 2. This retains
        # its ambiguity semantics when this transaction itself creates rows.
        current.sort(key=lambda item: int(item.id))
        del current[2:]


async def _lock_distinct_family_names(
    db: AsyncSession,
    *,
    company_id: int,
    normalized_names: list[str],
) -> None:
    """Acquire the existing tenant/name advisory locks in one SQL round trip.

    PostgreSQL's recursive CTE evaluates one dependent step at a time. Each
    step acquires the *same* (company_id, hashtext(lower(name))) transaction
    lock used by single-family commands. The caller supplies names sorted in
    a deterministic order; a reverse-order bulk worker cannot acquire its
    second lock before its first lock has been acquired. A simple SELECT of
    pg_advisory_xact_lock(...) with ORDER BY is not used: target-list function
    evaluation order can differ from the intended locking order.
    """
    if not normalized_names:
        return
    if normalized_names != sorted(set(normalized_names)):
        raise ValueError("Family lock keys must be distinct and sorted.")
    count = await db.scalar(
        text(
            """
            WITH RECURSIVE acquired(position, lock_token) AS (
                SELECT 1::bigint,
                       pg_advisory_xact_lock(
                           :company_id,
                           hashtext((CAST(:family_names AS text[]))[1])
                       )
                UNION ALL
                SELECT acquired.position + 1,
                       pg_advisory_xact_lock(
                           :company_id,
                           hashtext(
                               (CAST(:family_names AS text[]))[
                                   acquired.position + 1
                               ]
                           )
                       )
                FROM acquired
                WHERE acquired.position < cardinality(
                    CAST(:family_names AS text[])
                )
            )
            SELECT count(lock_token) FROM acquired
            """
        ),
        {
            "company_id": int(company_id),
            "family_names": normalized_names,
        },
    )
    if int(count or 0) != len(normalized_names):
        raise RuntimeError("Incomplete tenant-scoped family advisory lock acquisition.")


async def _prefetch_batch_families(
    db: AsyncSession,
    *,
    actor: Driver,
    specs: list[SimpleProductSpec],
) -> _BatchFamilyLookup:
    """Acquire distinct existing family-name locks BEFORE one tenant SELECT.

    No UNIQUE(company,name) exists, so ON CONFLICT(name) is NOT a legal
    replacement for the historical per-name advisory concurrency authority.
    Sorted lock acquisition prevents our bulk workers from taking these name
    locks in opposite orders. Other entrypoints keep their own lock contracts.
    """
    names: set[str] = set()
    for spec in specs:
        if spec.family_mode not in (None, "new") or spec.family_id is not None:
            continue
        if spec.family_mode == "new" and (
            spec.family_name is None or not spec.family_name.strip()
        ):
            continue
        try:
            family_name = (
                clean_text(spec.family_name, "family_name", 200, optional=True)
                if spec.family_name is not None else None
            )
            family_name = family_name or clean_text(
                spec.name, "product_name", 200,
            )
        except SimpleProductError:
            # Keep the original in-order per-row error contract: this row
            # will be rejected by the real resolver at its original location.
            continue
        assert family_name is not None
        names.add(family_name.lower())

    locked_names = frozenset(names)
    if not names:
        return _BatchFamilyLookup(locked_names, {})

    # One statement/round-trip for this transaction's sorted, unique names.
    # Never replace these locks with ON CONFLICT(name): our Product schema
    # permits same-name independent masters (family_mode='none').
    await _lock_distinct_family_names(
        db,
        company_id=int(actor.company_id),
        normalized_names=sorted(names),
    )
    rows = await _family_matches_by_normalized_names(
        db,
        company_id=int(actor.company_id),
        normalized_names=sorted(names),
    )
    matches: dict[str, list[Product]] = {}
    for row, normalized in rows:
        matches.setdefault(str(normalized), []).append(row)
    return _BatchFamilyLookup(locked_names, matches)


def _plan_unique_implicit_families(
    specs: list[SimpleProductSpec],
) -> dict[int, tuple[str, str]]:
    """Pure candidate plan; never create masters or surface a future row error.

    Count new/none names too: an overlapping implicit name must keep the
    ordered resolver's reuse/conflict/ambiguity semantics.
    """
    candidates: dict[int, tuple[str, str]] = {}
    counts: dict[str, int] = {}
    for index, spec in enumerate(specs, start=1):
        if (
            spec.family_id is not None
            or spec.family_mode not in (None, "none", "new")
        ):
            continue
        if spec.family_mode == "new" and (
            spec.family_name is None or not spec.family_name.strip()
        ):
            continue
        try:
            if spec.family_mode == "none":
                family_name = clean_text(spec.name, "product_name", 200)
            else:
                family_name = (
                    clean_text(spec.family_name, "family_name", 200, optional=True)
                    if spec.family_name is not None else None
                ) or clean_text(spec.name, "product_name", 200)
        except SimpleProductError:
            # Preserve the original per-row error location and classification.
            continue
        assert family_name is not None
        normalized = family_name.lower()
        counts[normalized] = counts.get(normalized, 0) + 1
        if spec.family_mode is None:
            candidates[index] = (family_name, normalized)

    return {
        index: (family_name, normalized)
        for index, (family_name, normalized) in candidates.items()
        if counts[normalized] == 1
    }


async def _prefill_unique_implicit_families(
    db: AsyncSession,
    *,
    actor: Driver,
    request_id: UUID,
    specs: list[SimpleProductSpec],
    lookup: _BatchFamilyLookup,
    candidates: dict[int, tuple[str, str]],
    start_index: int,
    uom_cache: dict[str, UOM],
    tracking_defaults: ProductTrackingDefaults | None,
    per_spec_barcodes: list[tuple[str | None, str | None, bool]],
) -> None:
    """Flush only a contiguous, validated implicit run at its family step.

    Lookahead uses existing caches and pure domain validators only. An explicit
    selection, name overlap, invalid row or missing cached input is a barrier,
    not an error to raise early. The ordinary row loop remains authoritative.
    """
    if tracking_defaults is None:
        # Its first read/validation belongs AFTER the first family resolution.
        return

    ready: list[tuple[int, str]] = []
    for index in range(start_index, len(specs) + 1):
        candidate = candidates.get(index)
        if candidate is None:
            break
        family_name, normalized = candidate
        if (
            normalized not in lookup.locked_names
            or lookup.matches.get(normalized)
        ):
            break
        spec = specs[index - 1]
        try:
            clean_text(spec.name, "product_name", 200)
            # Never issue a lookahead UOM SELECT: it could fail before an earlier
            # parent INSERT. Unseen codes return to the ordinary ordered loop.
            base = uom_cache.get(BASE_UOM_CODE)
            package_code = normalize_package_code(spec.package_uom_code)
            if base is None:
                break
            package = uom_cache.get(package_code) if package_code else None
            if package_code is not None and package is None:
                break
            resolve_price_pair(
                units_per_package=(
                    int(spec.units_per_package) if package is not None else 1
                ),
                package_uom_code=str(package.code) if package is not None else None,
                package_price=spec.package_price,
                unit_price=spec.unit_price,
            )
            resolve_product_tracking_modes_from_defaults(
                tracking_defaults,
                lot_control_mode=spec.lot_control_mode,
                expiry_control_mode=spec.expiry_control_mode,
            )
        except (
            ProductTrackingError, PricingError, ValueError, TypeError, ArithmeticError,
        ):
            break
        if package is None and per_spec_barcodes[index - 1][1] is not None:
            break
        ready.append((index, family_name))

    # No Product objects are constructed until every row in this run passes
    # both sides of its family step. Later failing rows are never prefetched.
    pending = [
        Product(
            company_id=int(actor.company_id),
            code=_auto_code("FAM", request_id, index),
            name=family_name,
        )
        for index, family_name in ready
    ]
    if not pending:
        return
    db.add_all(pending)
    with product_phase(db, "family_flush"):
        await db.flush()
    for family in pending:
        lookup.remember(family)


async def _resolve_family(
    db: AsyncSession,
    *,
    actor: Driver,
    spec: SimpleProductSpec,
    request_id: UUID,
    index: int,
    batch_lookup: _BatchFamilyLookup | None = None,
) -> Product:
    mode = spec.family_mode
    if mode not in (None, "none", "existing", "new"):
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_MODE_INVALID",
            "Invalid family selection.",
            status_code=422,
        )
    if mode == "none":
        if spec.family_id is not None or spec.family_name is not None:
            raise SimpleProductError(
                "SIMPLE_PRODUCT_FAMILY_AMBIGUOUS",
                "Without family must not select an existing or new family.",
                status_code=422,
            )
        name = clean_text(spec.name, "product_name", 200)
        assert name is not None
        # Independent master. Never reuse a same-name parent implicitly.
        row = Product(
            company_id=int(actor.company_id),
            code=_auto_code("FAM", request_id, index),
            name=name,
        )
        db.add(row)
        with product_phase(db, "family_flush"):
            await db.flush()
        if batch_lookup is not None:
            batch_lookup.remember(row)
        return row
    if mode == "existing" and (
        spec.family_id is None or spec.family_name is not None
    ):
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_SELECTION_REQUIRED",
            "Select an existing family by id.",
            status_code=422,
        )
    if mode == "new" and (
        spec.family_id is not None
        or spec.family_name is None
        or not spec.family_name.strip()
    ):
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NAME_REQUIRED",
            "Provide a new family name.",
            status_code=422,
        )
    if spec.family_id is not None and spec.family_name is not None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_AMBIGUOUS",
            "Choose an existing family or provide a new family name, not both.",
            status_code=422,
        )

    if spec.family_id is not None:
        # Resolve lazily after the original selection checks. A positive hit
        # is safe only while its same-scope key-share lock protects the FK.
        key = (int(actor.company_id), int(spec.family_id))
        locked_ids = (
            batch_lookup.locked_ids(db) if batch_lookup is not None else {}
        )
        row = locked_ids.get(key)
        if row is None:
            row = await db.scalar(
                select(Product)
                .where(
                    Product.company_id == key[0],
                    Product.id == key[1],
                )
                .with_for_update(read=True, key_share=True)
                .execution_options(populate_existing=True)
            )
        if row is None:
            raise SimpleProductError(
                "SIMPLE_PRODUCT_FAMILY_NOT_FOUND",
                "Product family was not found.",
                status_code=404,
            )
        if batch_lookup is not None:
            # The SELECT may have autobegun a transaction. Bind after it too.
            batch_lookup.locked_ids(db)[key] = row
        return row

    family_name = (
        clean_text(
            spec.family_name,
            "family_name",
            200,
            optional=True,
        )
        if spec.family_name is not None
        else None
    )
    family_name = family_name or clean_text(
        spec.name,
        "product_name",
        200,
    )
    assert family_name is not None

    normalized = family_name.lower()
    if batch_lookup is not None and normalized in batch_lookup.locked_names:
        # This transaction already acquired the name's existing advisory
        # lock and read the at-most-two matched masters under tenant RLS.
        matches = list(batch_lookup.matches.get(normalized, ()))
    else:
        await _family_name_lock(
            db,
            company_id=int(actor.company_id),
            family_name=family_name,
        )
        matches = [
            family
            for family, _normalized in await _family_matches_by_normalized_names(
                db,
                company_id=int(actor.company_id),
                normalized_names=[normalized],
            )
        ]
    if mode == "new" and matches:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT",
            "A family with this name already exists.",
            status_code=409,
        )
    if len(matches) > 1:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_FAMILY_NAME_AMBIGUOUS",
            "More than one family has the same name. Select the family by id.",
        )
    if matches:
        return matches[0]

    row = Product(
        company_id=int(actor.company_id),
        code=_auto_code("FAM", request_id, index),
        name=family_name,
    )
    db.add(row)
    with product_phase(db, "family_flush"):
        await db.flush()
    if batch_lookup is not None:
        batch_lookup.remember(row)
    return row


async def _assert_barcodes_available(
    db: AsyncSession,
    *,
    company_id: int,
    values: list[str],
) -> None:
    if not values:
        return
    duplicate = await db.scalar(
        select(ProductBarcode.barcode)
        .where(
            ProductBarcode.company_id == int(company_id),
            ProductBarcode.barcode.in_(values),
            ProductBarcode.is_active.is_(True),
        )
        .limit(1)
    )
    if duplicate is not None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_BARCODE_CONFLICT",
            "Barcode is already active on another product.",
            context={"barcode": str(duplicate)},
        )


async def _load_shape_for_spec(
    db: AsyncSession,
    *,
    spec: SimpleProductSpec,
    batch_cache: dict[str, UOM] | None = None,
) -> SaleShape:
    base = await _load_uom_code(db, BASE_UOM_CODE, batch_cache=batch_cache)
    package_code = normalize_package_code(spec.package_uom_code)
    if package_code is None:
        return SaleShape(
            base_uom=base,
            package_uom=None,
            units_per_package=1,
        )
    package = await _load_uom_code(db, package_code, batch_cache=batch_cache)
    return SaleShape(
        base_uom=base,
        package_uom=package,
        units_per_package=int(spec.units_per_package),
    )


async def create_product_structures(
    db: AsyncSession,
    *,
    actor: Driver,
    request_id: UUID,
    specs: list[SimpleProductSpec],
):
    with product_phase(db, "barcode_python"):
        normalized_barcodes: list[str] = []
        per_spec_barcodes: list[
            tuple[str | None, str | None, bool]
        ] = []

        for spec in specs:
            unit_barcode = normalize_barcode(
                spec.unit_barcode,
                "unit_barcode",
            )
            package_barcode = normalize_barcode(
                spec.package_barcode,
                "package_barcode",
            )
            shared = (
                unit_barcode is not None
                and package_barcode is not None
                and unit_barcode == package_barcode
            )

            if unit_barcode:
                normalized_barcodes.append(unit_barcode)
            if package_barcode and not shared:
                normalized_barcodes.append(package_barcode)
            per_spec_barcodes.append(
                (unit_barcode, package_barcode, shared)
            )

        if len(normalized_barcodes) != len(set(normalized_barcodes)):
            raise SimpleProductError(
                "SIMPLE_PRODUCT_BARCODE_DUPLICATE",
                "The same active barcode cannot identify two different products.",
                status_code=422,
            )

    await _assert_barcodes_available(
        db,
        company_id=int(actor.company_id),
        values=normalized_barcodes,
    )

    result = []
    staged_variants: list[tuple[
        ProductVariant, SimpleProductSpec, Any, SaleShape,
        str | None, str | None, bool,
    ]] = []
    # One UOM-code lookup per distinct code in a batch, not two SELECTs
    # for every product. The cache is short-lived and lives only in the
    # current transaction + company boundary.
    batch_uom_cache: dict[str, UOM] = {}
    # Read and validate company tracking defaults once per bounded creation
    # transaction. Values are immutable and the per-SKU overrides are still
    # validated by the Product Tracking domain's own resolver. No global cache.
    batch_tracking_defaults: ProductTrackingDefaults | None = None
    # This is a per-transaction, scoped family lookup; duplicates in the
    # same file still obey original new/none/implicit and ambiguity contracts.
    batch_family_lookup = await _prefetch_batch_families(
        db, actor=actor, specs=specs,
    )
    implicit_family_candidates = _plan_unique_implicit_families(specs)
    for index, spec in enumerate(specs, start=1):
        name = clean_text(spec.name, "product_name", 200)
        assert name is not None
        shape = await _load_shape_for_spec(
            db, spec=spec, batch_cache=batch_uom_cache,
        )
        prices = resolve_price_pair(
            units_per_package=int(shape.units_per_package),
            package_uom_code=(
                str(shape.package_uom.code)
                if shape.package_uom is not None
                else None
            ),
            package_price=spec.package_price,
            unit_price=spec.unit_price,
        )

        await _prefill_unique_implicit_families(
            db, actor=actor, request_id=request_id,
            specs=specs, lookup=batch_family_lookup,
            candidates=implicit_family_candidates, start_index=index,
            uom_cache=batch_uom_cache,
            tracking_defaults=batch_tracking_defaults,
            per_spec_barcodes=per_spec_barcodes,
        )
        family = await _resolve_family(
            db,
            actor=actor,
            spec=spec,
            request_id=request_id,
            index=index,
            batch_lookup=batch_family_lookup,
        )

        try:
            if batch_tracking_defaults is None:
                batch_tracking_defaults = await load_company_product_tracking_defaults(
                    db,
                    company_id=int(actor.company_id),
                )
            tracking = resolve_product_tracking_modes_from_defaults(
                batch_tracking_defaults,
                lot_control_mode=spec.lot_control_mode,
                expiry_control_mode=spec.expiry_control_mode,
            )
        except ProductTrackingError as exc:
            raise SimpleProductError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                context=exc.context,
            ) from exc

        unit_barcode, package_barcode, shared_barcode = (
            per_spec_barcodes[index - 1]
        )
        if shape.package_uom is None and package_barcode is not None:
            raise SimpleProductError(
                "SIMPLE_PRODUCT_PACKAGE_BARCODE_WITHOUT_PACKAGE",
                "package_barcode cannot be supplied without an outer package.",
                status_code=422,
            )

        with product_phase(db, "variant_objects"):
            variant = ProductVariant(
                company_id=int(actor.company_id),
                product_id=int(family.id),
                base_uom_id=int(shape.base_uom.id),
                name=name,
                sku=_auto_code("SKU", request_id, index),
                quantity_scale=0,
                quantity_step=Decimal("1"),
                lot_control_mode=tracking.lot_control_mode,
                expiry_control_mode=tracking.expiry_control_mode,
                lifecycle_status="DRAFT",
                operational_hold="NONE",
                packs_per_carton=int(shape.units_per_package),
                package_uses_base_barcode=bool(shared_barcode),
            )
            staged_variants.append((
                variant, spec, prices, shape,
                unit_barcode, package_barcode, shared_barcode,
            ))

    # All family/UOM/tracking/barcode validations precede lifecycle preparation.
    # The creation primitive captures real DRAFT evidence and applies the same
    # publish authority before one final-state INSERT with ORM-generated IDs.
    # Keep the existing phase label; its flush now inserts published new SKUs.
    with product_phase(db, "draft_flush"):
        try:
            await create_published_variants(
                db,
                rows=[row[0] for row in staged_variants],
                company_id=int(actor.company_id),
                actor_id=int(actor.id),
                request_id=request_id,
            )
        except ProductLifecycleTransitionError as exc:
            raise SimpleProductError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
            ) from exc

    with product_phase(db, "activation_objects"):
        for (
            variant, spec, prices, shape,
            unit_barcode, package_barcode, shared_barcode,
        ) in staged_variants:
            if shape.package_uom is not None:
                db.add(
                    ProductUomConversion(
                        company_id=int(actor.company_id),
                        product_variant_id=int(variant.id),
                        from_uom_id=int(shape.package_uom.id),
                        to_uom_id=int(shape.base_uom.id),
                        numerator=Decimal(int(shape.units_per_package)),
                        denominator=Decimal("1"),
                        quantity_scale=0,
                    )
                )

            # Barcode effectivity remains the exact authoritative publish time.
            now = variant.published_at
            if unit_barcode:
                db.add(
                    ProductBarcode(
                        company_id=int(actor.company_id),
                        product_variant_id=int(variant.id),
                        uom_id=int(shape.base_uom.id),
                        barcode=unit_barcode,
                        barcode_type=barcode_type(unit_barcode),
                        is_primary=True,
                        valid_from=now,
                        valid_to=None,
                        is_active=True,
                    )
                )

            if (
                package_barcode
                and not shared_barcode
                and shape.package_uom is not None
            ):
                db.add(
                    ProductBarcode(
                        company_id=int(actor.company_id),
                        product_variant_id=int(variant.id),
                        uom_id=int(shape.package_uom.id),
                        barcode=package_barcode,
                        barcode_type=barcode_type(package_barcode),
                        is_primary=True,
                        valid_from=now,
                        valid_to=None,
                        is_active=True,
                    )
                )

            result.append((variant, spec, prices, shape))

    with product_phase(db, "activation_flush"):
        await db.flush()
    if result:
        try:
            await apply_live_stock_active_variant_delta(
                db,
                company_id=int(actor.company_id),
                delta=len(result),
            )
        except LiveStockProjectionError as exc:
            raise SimpleProductError(
                "LIVE_STOCK_PROJECTION_FAILED",
                "تعذر تحديث عرض المخزون الحي بأمان.",
                status_code=500,
            ) from exc
    return result


def _build_price_entry_payloads(
    *,
    rows,
    effective_at: datetime,
) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for variant, _spec, prices, shape in rows:
        entries.append({
            "product_variant_id": int(variant.id),
            "uom_id": int(shape.base_uom.id),
            "amount": prices.unit_price,
            "effective_from": effective_at,
            "effective_to": None,
            "priority": 0,
            "metadata": {
                "managed_by": "simple_products",
                "price_input": (
                    "derived" if prices.unit_derived else "explicit"
                ),
                "package_uom_code": (
                    str(shape.package_uom.code)
                    if shape.package_uom is not None
                    else None
                ),
                "units_per_package": int(shape.units_per_package),
            },
        })
        if shape.package_uom is not None:
            assert prices.package_price is not None
            entries.append({
                "product_variant_id": int(variant.id),
                "uom_id": int(shape.package_uom.id),
                "amount": prices.package_price,
                "effective_from": effective_at,
                "effective_to": None,
                "priority": 0,
                "metadata": {
                    "managed_by": "simple_products",
                    "price_input": (
                        "derived" if prices.package_derived else "explicit"
                    ),
                    "package_uom_code": str(shape.package_uom.code),
                    "units_per_package": int(shape.units_per_package),
                },
            })
    return entries


async def publish_prices(
    db: AsyncSession,
    *,
    actor: Driver,
    book: PriceBook,
    rows,
    effective_at: datetime,
    request_id: UUID,
) -> None:
    with product_phase(db, "price_publication_create"):
        direct_scope = await create_direct_publication(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            book_id=int(book.id),
            expected_book_version=int(book.version),
            effective_at=effective_at,
            request_id=request_id,
        )
        publication = direct_scope.publication

    with product_phase(db, "price_entries_python"):
        entries = _build_price_entry_payloads(
            rows=rows,
            effective_at=effective_at,
        )
    # PriceBookEntry validation is bounded. Bulk dashboard calls may contain
    # more than 100 SKUs; preserve one publication and its cumulative version.
    with product_phase(db, "price_draft_entries"):
        for start in range(0, len(entries), 200):
            await direct_scope.add_draft_entries(
                expected_publication_version=int(publication.version),
                entries=entries[start:start + 200],
            )

    with product_phase(db, "price_publish"):
        await direct_scope.publish(
            actor_id=int(actor.id),
            expected_version=int(publication.version),
        )



async def publish_initial_prices(
    db: AsyncSession,
    *,
    actor: Driver,
    book: PriceBook,
    rows,
    effective_at: datetime,
    request_id: UUID,
) -> None:
    """Publish first-ever prices for newly created products in one row write."""
    with product_phase(db, "price_publication_create"):
        direct_scope = await create_direct_publication(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            book_id=int(book.id),
            expected_book_version=int(book.version),
            effective_at=effective_at,
            request_id=request_id,
        )
        publication = direct_scope.publication

    with product_phase(db, "price_entries_python"):
        entries = _build_price_entry_payloads(
            rows=rows,
            effective_at=effective_at,
        )
    with product_phase(db, "price_publish"):
        await direct_scope.publish_initial_entries(
            actor_id=int(actor.id),
            expected_version=int(publication.version),
            entries=entries,
        )


async def create_products_and_prices(
    db: AsyncSession,
    *,
    actor: Driver,
    request_id: UUID,
    specs: list[SimpleProductSpec],
):
    if not specs:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_EMPTY",
            "No products were provided.",
            status_code=422,
        )

    now = datetime.now(timezone.utc)
    with product_phase(db, "pricing_policy"):
        assignment = await assert_simple_pricing_mode(
            db,
            company_id=int(actor.company_id),
            as_of=now,
        )
        company, current_book = await load_company_and_current_default_book(
            db,
            company_id=int(actor.company_id),
            assignment=assignment,
        )
        book = (
            current_book
            if current_book is not None
            else await ensure_default_book(
                db,
                company=company,
                actor_id=int(actor.id),
                as_of=now,
                assignment=None,
            )
        )

    with product_phase(db, "product_structures"):
        structures = await create_product_structures(
            db,
            actor=actor,
            request_id=request_id,
            specs=specs,
        )
    await publish_initial_prices(
        db,
        actor=actor,
        book=book,
        rows=structures,
        effective_at=now,
        request_id=request_id,
    )
    return [
        (variant, prices)
        for variant, _spec, prices, _shape in structures
    ]


async def load_sale_shapes(
    db: AsyncSession,
    *,
    company_id: int,
    variants: list[ProductVariant],
) -> dict[int, SaleShape]:
    if not variants:
        return {}

    base_uom = await _load_uom_code(db, BASE_UOM_CODE)
    ids = [int(variant.id) for variant in variants]
    rows = list(
        (
            await db.execute(
                select(ProductUomConversion, UOM)
                .join(
                    UOM,
                    UOM.id
                    == ProductUomConversion.from_uom_id,
                )
                .where(
                    ProductUomConversion.company_id
                    == int(company_id),
                    ProductUomConversion.product_variant_id.in_(
                        ids
                    ),
                    ProductUomConversion.to_uom_id
                    == int(base_uom.id),
                    UOM.code.in_(
                        SUPPORTED_PACKAGE_UOM_CODES
                    ),
                )
            )
        ).all()
    )

    by_variant: dict[
        int,
        list[tuple[ProductUomConversion, UOM]],
    ] = {}
    for conversion, uom in rows:
        by_variant.setdefault(
            int(conversion.product_variant_id),
            [],
        ).append((conversion, uom))

    result: dict[int, SaleShape] = {}
    for variant in variants:
        variant_id = int(variant.id)
        if int(variant.base_uom_id) != int(base_uom.id):
            continue

        factor = int(variant.packs_per_carton or 0)
        if factor <= 0:
            continue

        candidates = [
            (conversion, uom)
            for conversion, uom in by_variant.get(
                variant_id,
                [],
            )
            if Decimal(conversion.numerator)
            / Decimal(conversion.denominator)
            == Decimal(factor)
        ]

        if factor == 1:
            if not candidates:
                result[variant_id] = SaleShape(
                    base_uom=base_uom,
                    package_uom=None,
                    units_per_package=1,
                )
            # A distinct 1:1 package conversion is valid catalog data,
            # but it is not a safe simple-product package shape.
            continue
        if len(candidates) == 1:
            result[variant_id] = SaleShape(
                base_uom=base_uom,
                package_uom=candidates[0][1],
                units_per_package=factor,
            )

    return result


async def assert_simple_variant(
    db: AsyncSession,
    *,
    company_id: int,
    variant: ProductVariant,
) -> SaleShape:
    shapes = await load_sale_shapes(
        db,
        company_id=int(company_id),
        variants=[variant],
    )
    shape = shapes.get(int(variant.id))
    if shape is None:
        raise SimpleProductError(
            "SIMPLE_PRODUCT_UOM_SHAPE_UNSUPPORTED",
            "This product uses a UOM shape that the simple workflow cannot edit safely.",
        )
    return shape


async def update_prices(
    db: AsyncSession,
    *,
    actor: Driver,
    request_id: UUID,
    variant: ProductVariant,
    package_price: Any = None,
    unit_price: Any = None,
) -> ResolvedPricePair:
    now = datetime.now(timezone.utc)
    assignment = await assert_simple_pricing_mode(
        db,
        company_id=int(actor.company_id),
        as_of=now,
    )
    shape = await assert_simple_variant(
        db,
        company_id=int(actor.company_id),
        variant=variant,
    )
    prices = resolve_price_pair(
        units_per_package=int(shape.units_per_package),
        package_uom_code=(
            str(shape.package_uom.code)
            if shape.package_uom is not None
            else None
        ),
        package_price=package_price,
        unit_price=unit_price,
    )

    company, current_book = await load_company_and_current_default_book(
        db,
        company_id=int(actor.company_id),
        assignment=assignment,
    )
    book = (
        current_book
        if current_book is not None
        else await ensure_default_book(
            db,
            company=company,
            actor_id=int(actor.id),
            as_of=now,
            assignment=None,
        )
    )
    spec = SimpleProductSpec(
        name=str(variant.name),
        units_per_package=int(shape.units_per_package),
        package_uom_code=(
            str(shape.package_uom.code)
            if shape.package_uom is not None
            else None
        ),
        package_price=prices.package_price,
        unit_price=prices.unit_price,
    )
    await publish_prices(
        db,
        actor=actor,
        book=book,
        rows=[(variant, spec, prices, shape)],
        effective_at=now,
        request_id=request_id,
    )
    return prices


async def current_prices(
    db: AsyncSession,
    *,
    company_id: int,
    variants: list[ProductVariant],
    shapes: dict[int, SaleShape],
    as_of: datetime,
):
    if not variants:
        return {}

    pairs: list[tuple[int, int]] = []
    for variant in variants:
        shape = shapes.get(int(variant.id))
        if shape is None:
            continue
        pairs.append(
            (int(variant.id), int(shape.base_uom.id))
        )
        if shape.package_uom is not None:
            pairs.append(
                (
                    int(variant.id),
                    int(shape.package_uom.id),
                )
            )

    if not pairs:
        return {}

    try:
        resolved = await resolve_prices_bulk(
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

    result = {}
    for variant in variants:
        variant_id = int(variant.id)
        shape = shapes.get(variant_id)
        if shape is None:
            continue
        unit = resolved.get(
            (variant_id, int(shape.base_uom.id))
        )
        package = (
            resolved.get(
                (
                    variant_id,
                    int(shape.package_uom.id),
                )
            )
            if shape.package_uom is not None
            else None
        )
        result[variant_id] = (
            Decimal(package.amount)
            if package is not None
            else None,
            Decimal(unit.amount)
            if unit is not None
            else None,
        )
    return result


async def current_primary_barcodes(
    db: AsyncSession,
    *,
    company_id: int,
    variants: list[ProductVariant],
    shapes: dict[int, SaleShape],
):
    if not variants:
        return {}

    ids = [int(variant.id) for variant in variants]
    rows = list(
        (
            await db.scalars(
                select(ProductBarcode).where(
                    ProductBarcode.company_id
                    == int(company_id),
                    ProductBarcode.product_variant_id.in_(
                        ids
                    ),
                    ProductBarcode.is_active.is_(True),
                    ProductBarcode.is_primary.is_(True),
                )
            )
        ).all()
    )

    by_variant: dict[int, list[ProductBarcode]] = {}
    for row in rows:
        by_variant.setdefault(
            int(row.product_variant_id),
            [],
        ).append(row)

    variants_by_id = {
        int(variant.id): variant
        for variant in variants
    }
    result: dict[
        int,
        tuple[str | None, str | None],
    ] = {}

    for variant_id in ids:
        shape = shapes.get(variant_id)
        if shape is None:
            result[variant_id] = (None, None)
            continue

        unit_barcode = None
        package_barcode = None
        for row in by_variant.get(variant_id, []):
            if int(row.uom_id) == int(shape.base_uom.id):
                unit_barcode = str(row.barcode)
            elif (
                shape.package_uom is not None
                and int(row.uom_id)
                == int(shape.package_uom.id)
            ):
                package_barcode = str(row.barcode)

        if (
            shape.package_uom is not None
            and bool(
                variants_by_id[
                    variant_id
                ].package_uses_base_barcode
            )
        ):
            package_barcode = unit_barcode

        result[variant_id] = (
            unit_barcode,
            package_barcode,
        )

    return result



def simple_compatibility_clause(
    *,
    company_id: int,
):
    """SQL predicate matching the Simple Products sale-shape contract."""
    base_uom_id = (
        select(UOM.id)
        .where(UOM.code == BASE_UOM_CODE)
        .limit(1)
        .scalar_subquery()
    )
    matching_package_count = (
        select(func.count(ProductUomConversion.id))
        .select_from(ProductUomConversion)
        .join(
            UOM,
            UOM.id
            == ProductUomConversion.from_uom_id,
        )
        .where(
            ProductUomConversion.company_id
            == int(company_id),
            ProductUomConversion.product_variant_id
            == ProductVariant.id,
            ProductUomConversion.to_uom_id
            == base_uom_id,
            UOM.code.in_(
                SUPPORTED_PACKAGE_UOM_CODES
            ),
            ProductUomConversion.numerator
            == (
                ProductVariant.packs_per_carton
                * ProductUomConversion.denominator
            ),
        )
        .correlate(ProductVariant)
        .scalar_subquery()
    )
    return and_(
        ProductVariant.base_uom_id
        == base_uom_id,
        ProductVariant.packs_per_carton > 0,
        or_(
            and_(
                ProductVariant.packs_per_carton == 1,
                matching_package_count == 0,
            ),
            and_(
                ProductVariant.packs_per_carton > 1,
                matching_package_count == 1,
            ),
        ),
    )


def simple_price_exists_clause(
    *,
    company_id: int,
    price_book_id: int,
    as_of: datetime,
):
    """Current simple-visible price existence, usable before pagination."""
    package_uom_match = (
        select(ProductUomConversion.id)
        .select_from(ProductUomConversion)
        .join(
            UOM,
            UOM.id
            == ProductUomConversion.from_uom_id,
        )
        .where(
            ProductUomConversion.company_id
            == int(company_id),
            ProductUomConversion.product_variant_id
            == ProductVariant.id,
            ProductUomConversion.to_uom_id
            == ProductVariant.base_uom_id,
            UOM.code.in_(
                SUPPORTED_PACKAGE_UOM_CODES
            ),
            ProductUomConversion.numerator
            == (
                ProductVariant.packs_per_carton
                * ProductUomConversion.denominator
            ),
            PriceBookEntry.uom_id
            == ProductUomConversion.from_uom_id,
        )
        .correlate(
            ProductVariant,
            PriceBookEntry,
        )
        .exists()
    )
    current_price = (
        select(PriceBookEntry.id)
        .join(
            PricePublication,
            (
                PricePublication.company_id
                == PriceBookEntry.company_id
            )
            & (
                PricePublication.id
                == PriceBookEntry.publication_id
            ),
        )
        .where(
            PriceBookEntry.company_id
            == int(company_id),
            PriceBookEntry.price_book_id
            == int(price_book_id),
            PriceBookEntry.product_variant_id
            == ProductVariant.id,
            PriceBookEntry.is_published.is_(True),
            PriceBookEntry.effectivity.contains(as_of),
            PricePublication.status.in_(
                ("PUBLISHED", "SUPERSEDED")
            ),
            PricePublication.published_at.is_not(None),
            PricePublication.published_at <= as_of,
            or_(
                PriceBookEntry.uom_id
                == ProductVariant.base_uom_id,
                package_uom_match,
            ),
        )
        .correlate(ProductVariant)
        .exists()
    )
    return and_(
        simple_compatibility_clause(
            company_id=int(company_id),
        ),
        current_price,
    )


async def simple_compatibility(
    db: AsyncSession,
    *,
    company_id: int,
    variants: list[ProductVariant],
) -> dict[int, bool]:
    shapes = await load_sale_shapes(
        db,
        company_id=int(company_id),
        variants=variants,
    )
    return {
        int(variant.id): int(variant.id) in shapes
        for variant in variants
    }
