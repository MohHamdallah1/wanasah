"""Dead-simple SMB product API backed by catalog and temporal pricing engines."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)
from sqlalchemy import and_, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from config import Config
from database import get_db
from domains.pricing.core import PricingError
from domains.product_tracking import (
    ProductTrackingError,
    resolve_product_tracking_modes,
)
from domains.simple_products.service import (
    SimpleProductError,
    SimpleProductSpec,
    assert_simple_pricing_mode,
    clean_text,
    create_family,
    create_products_and_prices,
    current_default_book,
    current_prices,
    current_primary_barcodes,
    list_families,
    list_package_uoms,
    load_company,
    load_sale_shapes,
    normalize_package_code,
    parse_optional_money,
    rename_family,
    resolve_price_pair,
    simple_compatibility_clause,
    simple_price_exists_clause,
    update_prices,
)
from inventory_access import InventoryAccess
from models import (
    Driver,
    Product,
    ProductBarcode,
    ProductImportJob,
    ProductImportRow,
    ProductVariant,
    SystemAuditLog,
)
from product_import_queue import (
    enqueue_new_import,
    requeue_import,
    retry_failed_import,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)

router = APIRouter(
    prefix="/simple-products",
    tags=["Simple Products"],
)

MAX_IMPORT_FILE_BYTES = 8 * 1024 * 1024
_ALLOWED_IMPORT_SUFFIXES = {".csv", ".xlsx"}

_CANONICAL_MAPPING_FIELDS = {
    "name",
    "family",
    "package_uom",
    "units_per_package",
    "package_price",
    "unit_price",
    "unit_barcode",
    "package_barcode",
    "lot_control_mode",
    "expiry_control_mode",
}


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SimpleProductCreate(StrictRequest):
    request_id: UUID
    name: str = Field(min_length=1, max_length=200)
    family_id: int | None = Field(None, gt=0)
    family_name: str | None = Field(None, max_length=150)
    package_uom_code: str | None = Field(
        "CARTON",
        max_length=30,
    )
    units_per_package: int = Field(
        50,
        gt=0,
        le=1_000_000,
    )
    package_price: Decimal | None = None
    unit_price: Decimal | None = None
    unit_barcode: str | None = Field(
        None,
        max_length=128,
    )
    package_barcode: str | None = Field(
        None,
        max_length=128,
    )
    lot_control_mode: str | None = Field(
        None,
        max_length=20,
    )
    expiry_control_mode: str | None = Field(
        None,
        max_length=20,
    )

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        result = clean_text(
            value,
            "product_name",
            200,
        )
        assert result is not None
        return result

    @field_validator("family_name", mode="before")
    @classmethod
    def family_value(
        cls,
        value: Any,
    ) -> str | None:
        return clean_text(
            value,
            "family_name",
            150,
            optional=True,
        )

    @field_validator(
        "package_uom_code",
        mode="before",
    )
    @classmethod
    def package_uom_value(
        cls,
        value: Any,
    ) -> str | None:
        return normalize_package_code(value)

    @field_validator(
        "unit_barcode",
        "package_barcode",
        mode="before",
    )
    @classmethod
    def barcode_value(
        cls,
        value: Any,
        info,
    ) -> str | None:
        return clean_text(
            value,
            info.field_name,
            128,
            optional=True,
        )

    @field_validator(
        "package_price",
        "unit_price",
        mode="before",
    )
    @classmethod
    def price_value(
        cls,
        value: Any,
        info,
    ) -> Decimal | None:
        return parse_optional_money(
            value,
            info.field_name,
        )

    @model_validator(mode="after")
    def product_contract(self):
        if (
            self.family_id is not None
            and self.family_name is not None
        ):
            raise ValueError(
                "Choose an existing family or a new family name, not both."
            )
        if self.package_uom_code is None:
            self.units_per_package = 1

        resolve_price_pair(
            units_per_package=self.units_per_package,
            package_uom_code=self.package_uom_code,
            package_price=self.package_price,
            unit_price=self.unit_price,
        )
        return self


class SimplePriceUpdate(StrictRequest):
    request_id: UUID
    package_price: Decimal | None = None
    unit_price: Decimal | None = None

    @field_validator(
        "package_price",
        "unit_price",
        mode="before",
    )
    @classmethod
    def price_value(
        cls,
        value: Any,
        info,
    ) -> Decimal | None:
        return parse_optional_money(
            value,
            info.field_name,
        )

    @model_validator(mode="after")
    def at_least_one(self):
        if (
            self.package_price is None
            and self.unit_price is None
        ):
            raise ValueError(
                "Provide package_price or unit_price."
            )
        return self


class FamilyCreate(StrictRequest):
    request_id: UUID
    name: str = Field(
        min_length=1,
        max_length=150,
    )

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        result = clean_text(
            value,
            "family_name",
            150,
        )
        assert result is not None
        return result


class FamilyUpdate(StrictRequest):
    request_id: UUID
    expected_version: int = Field(gt=0)
    name: str = Field(
        min_length=1,
        max_length=150,
    )

    @field_validator("name", mode="before")
    @classmethod
    def name_value(cls, value: Any) -> str:
        result = clean_text(
            value,
            "family_name",
            150,
        )
        assert result is not None
        return result


class ImportMappingRequest(StrictRequest):
    mapping: dict[str, str]

    @field_validator("mapping")
    @classmethod
    def mapping_contract(
        cls,
        value: dict[str, str],
    ) -> dict[str, str]:
        unknown = set(value) - _CANONICAL_MAPPING_FIELDS
        if unknown:
            raise ValueError(
                "Unknown import mapping field."
            )
        cleaned = {
            str(key): str(header).strip()
            for key, header in value.items()
            if str(header).strip()
        }
        if len(cleaned.values()) != len(
            set(cleaned.values())
        ):
            raise ValueError(
                "One source column cannot map to multiple fields."
            )
        return cleaned


def _http_error(
    exc: SimpleProductError,
) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "context": exc.context,
        },
    )


def _pricing_error(
    exc: PricingError,
) -> HTTPException:
    return HTTPException(
        exc.status_code,
        detail=exc.as_detail(),
    )


def _request_hash(
    payload: BaseModel,
    **scope: Any,
) -> str:
    body = payload.model_dump(
        mode="json",
        exclude={"request_id"},
    )
    body.update(scope)
    encoded = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(
        encoded.encode("utf-8")
    ).hexdigest()


def _invalid_cursor(
    exc: Exception | None = None,
) -> HTTPException:
    error = HTTPException(
        400,
        detail={
            "code": "INVALID_CURSOR",
            "message": "Invalid cursor.",
            "context": {},
        },
    )
    if exc is not None:
        error.__cause__ = exc
    return error


def _search_tokens(
    search: str | None,
) -> tuple[str, ...]:
    if not search:
        return ()
    return tuple(
        token
        for token in search.strip().lower().split()
        if token
    )


def _escaped_like(token: str) -> str:
    return (
        token.replace("\\", "\\\\")
        .replace("%", "\\%")
        .replace("_", "\\_")
    )


def _cursor_scope(
    *,
    company_id: int,
    search: str | None,
    limit: int,
) -> str:
    normalized_search = " ".join(
        _search_tokens(search)
    )
    encoded = json.dumps(
        {
            "company_id": int(company_id),
            "search": normalized_search,
            "limit": int(limit),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _cursor_signature(payload: bytes) -> bytes:
    return hmac.new(
        Config.SECRET_KEY.encode("utf-8"),
        payload,
        hashlib.sha256,
    ).digest()


def _cursor(
    value: str | None,
    *,
    company_id: int,
    search: str | None,
    limit: int,
) -> int:
    if value is None:
        return 0
    try:
        payload_part, signature_part = value.split(".", 1)
        payload = base64.urlsafe_b64decode(
            payload_part
            + "=" * (-len(payload_part) % 4)
        )
        signature = base64.urlsafe_b64decode(
            signature_part
            + "=" * (-len(signature_part) % 4)
        )
        if not hmac.compare_digest(
            signature,
            _cursor_signature(payload),
        ):
            raise ValueError("cursor signature mismatch")
        data = json.loads(payload.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or set(data)
            != {"v", "after", "scope"}
            or data.get("v") != 1
            or not isinstance(data.get("after"), int)
            or data["after"] <= 0
            or data.get("scope")
            != _cursor_scope(
                company_id=company_id,
                search=search,
                limit=limit,
            )
        ):
            raise ValueError("cursor payload mismatch")
        return int(data["after"])
    except Exception as exc:
        raise _invalid_cursor(exc) from exc


def _next_cursor(
    value: int,
    *,
    company_id: int,
    search: str | None,
    limit: int,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "after": int(value),
            "scope": _cursor_scope(
                company_id=company_id,
                search=search,
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
        _cursor_signature(payload)
    ).decode("ascii").rstrip("=")
    return f"{payload_part}.{signature_part}"



_PRODUCT_LIFECYCLES = {"ACTIVE", "RETIRING"}
_PRODUCT_TRACKING_TYPES = {
    "NONE",
    "LOT",
    "EXPIRY",
    "LOT_EXPIRY",
}
_PRODUCT_SORT_FIELDS = {
    "id",
    "name",
    "family",
    "sku",
    "lifecycle",
}
_PRODUCT_SORT_DIRECTIONS = {"asc", "desc"}


def _product_query_error(
    *,
    code: str,
    field: str,
    value: Any,
) -> HTTPException:
    return HTTPException(
        422,
        detail={
            "code": code,
            "message": f"Invalid {field}.",
            "context": {
                "field": field,
                "value": value,
            },
        },
    )


def _normalized_product_choice(
    value: str | None,
    *,
    field: str,
    allowed: set[str],
    uppercase: bool,
    code: str,
) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise _product_query_error(
            code=code,
            field=field,
            value=value,
        )
    clean = value.strip()
    normalized = (
        clean.upper()
        if uppercase
        else clean.lower()
    )
    if normalized not in allowed:
        raise _product_query_error(
            code=code,
            field=field,
            value=value,
        )
    return normalized


def _effective_barcode_exists(
    *,
    company_id: int,
    as_of: datetime,
    pattern: str | None = None,
):
    conditions = [
        ProductBarcode.company_id
        == int(company_id),
        ProductBarcode.product_variant_id
        == ProductVariant.id,
        ProductBarcode.is_active.is_(True),
        ProductBarcode.valid_from <= as_of,
        or_(
            ProductBarcode.valid_to.is_(None),
            ProductBarcode.valid_to > as_of,
        ),
    ]
    if pattern is not None:
        conditions.append(
            func.lower(
                ProductBarcode.barcode
            ).like(
                pattern,
                escape="\\",
            )
        )
    return (
        select(ProductBarcode.id)
        .where(*conditions)
        .correlate(ProductVariant)
        .exists()
    )


def _tracking_type_clause(
    tracking_type: str,
):
    lot_tracked = (
        ProductVariant.lot_control_mode != "NONE"
    )
    expiry_tracked = (
        ProductVariant.expiry_control_mode != "NONE"
    )
    if tracking_type == "NONE":
        return and_(
            ~lot_tracked,
            ~expiry_tracked,
        )
    if tracking_type == "LOT":
        return and_(
            lot_tracked,
            ~expiry_tracked,
        )
    if tracking_type == "EXPIRY":
        return and_(
            ~lot_tracked,
            expiry_tracked,
        )
    return and_(
        lot_tracked,
        expiry_tracked,
    )


def _product_sort_key(
    sort_by: str,
):
    if sort_by == "id":
        return ProductVariant.id
    if sort_by == "name":
        return func.lower(
            ProductVariant.name
        )
    if sort_by == "family":
        return func.lower(Product.name)
    if sort_by == "sku":
        return func.lower(
            ProductVariant.sku
        )
    return ProductVariant.lifecycle_status


def _product_cursor_scope(
    *,
    company_id: int,
    search: str | None,
    family_id: int | None,
    lifecycle: str | None,
    tracking_type: str | None,
    simple_compatible: bool | None,
    has_barcode: bool | None,
    has_price: bool | None,
    lot_tracked: bool | None,
    expiry_tracked: bool | None,
    sort_by: str,
    sort_dir: str,
    limit: int,
) -> str:
    encoded = json.dumps(
        {
            "company_id": int(company_id),
            "search": " ".join(
                _search_tokens(search)
            ),
            "family_id": family_id,
            "lifecycle": lifecycle,
            "tracking_type": tracking_type,
            "simple_compatible":
                simple_compatible,
            "has_barcode": has_barcode,
            "has_price": has_price,
            "lot_tracked": lot_tracked,
            "expiry_tracked":
                expiry_tracked,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "limit": int(limit),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _product_cursor(
    value: str | None,
    *,
    company_id: int,
    search: str | None,
    family_id: int | None,
    lifecycle: str | None,
    tracking_type: str | None,
    simple_compatible: bool | None,
    has_barcode: bool | None,
    has_price: bool | None,
    lot_tracked: bool | None,
    expiry_tracked: bool | None,
    sort_by: str,
    sort_dir: str,
    limit: int,
) -> tuple[int | str | None, int | None]:
    if value is None:
        return None, None
    try:
        payload_part, signature_part = value.split(
            ".",
            1,
        )
        payload = base64.urlsafe_b64decode(
            payload_part
            + "=" * (-len(payload_part) % 4)
        )
        signature = base64.urlsafe_b64decode(
            signature_part
            + "=" * (-len(signature_part) % 4)
        )
        if not hmac.compare_digest(
            signature,
            _cursor_signature(payload),
        ):
            raise ValueError(
                "product cursor signature mismatch"
            )
        data = json.loads(
            payload.decode("utf-8")
        )
        if (
            not isinstance(data, dict)
            or set(data)
            != {
                "v",
                "after_key",
                "after_id",
                "scope",
            }
            or data.get("v") != 1
            or not isinstance(
                data.get("after_id"),
                int,
            )
            or data["after_id"] <= 0
            or data.get("scope")
            != _product_cursor_scope(
                company_id=company_id,
                search=search,
                family_id=family_id,
                lifecycle=lifecycle,
                tracking_type=tracking_type,
                simple_compatible=
                    simple_compatible,
                has_barcode=has_barcode,
                has_price=has_price,
                lot_tracked=lot_tracked,
                expiry_tracked=
                    expiry_tracked,
                sort_by=sort_by,
                sort_dir=sort_dir,
                limit=limit,
            )
        ):
            raise ValueError(
                "product cursor payload mismatch"
            )
        after_key = data.get("after_key")
        if sort_by == "id":
            if (
                not isinstance(after_key, int)
                or after_key <= 0
                or after_key != data["after_id"]
            ):
                raise ValueError(
                    "invalid product id cursor key"
                )
        elif (
            not isinstance(after_key, str)
            or not after_key.strip()
            or len(after_key) > 200
        ):
            raise ValueError(
                "invalid product text cursor key"
            )
        return (
            after_key,
            int(data["after_id"]),
        )
    except Exception as exc:
        raise _invalid_cursor(exc) from exc


def _product_next_cursor(
    *,
    sort_key: int | str,
    variant_id: int,
    company_id: int,
    search: str | None,
    family_id: int | None,
    lifecycle: str | None,
    tracking_type: str | None,
    simple_compatible: bool | None,
    has_barcode: bool | None,
    has_price: bool | None,
    lot_tracked: bool | None,
    expiry_tracked: bool | None,
    sort_by: str,
    sort_dir: str,
    limit: int,
) -> str:
    if variant_id <= 0:
        raise ValueError(
            "Invalid product cursor source."
        )
    if sort_by == "id":
        if (
            not isinstance(sort_key, int)
            or sort_key != variant_id
        ):
            raise ValueError(
                "Invalid product id cursor source."
            )
    elif (
        not isinstance(sort_key, str)
        or not sort_key.strip()
        or len(sort_key) > 200
    ):
        raise ValueError(
            "Invalid product text cursor source."
        )
    payload = json.dumps(
        {
            "v": 1,
            "after_key": sort_key,
            "after_id": int(variant_id),
            "scope": _product_cursor_scope(
                company_id=company_id,
                search=search,
                family_id=family_id,
                lifecycle=lifecycle,
                tracking_type=tracking_type,
                simple_compatible=
                    simple_compatible,
                has_barcode=has_barcode,
                has_price=has_price,
                lot_tracked=lot_tracked,
                expiry_tracked=
                    expiry_tracked,
                sort_by=sort_by,
                sort_dir=sort_dir,
                limit=limit,
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload_part = base64.urlsafe_b64encode(
        payload
    ).decode("ascii").rstrip("=")
    signature_part = base64.urlsafe_b64encode(
        _cursor_signature(payload)
    ).decode("ascii").rstrip("=")
    return f"{payload_part}.{signature_part}"


def _family_cursor_scope(
    *,
    company_id: int,
    search: str | None,
    limit: int,
) -> str:
    normalized_search = (
        search.strip().lower()
        if search
        else ""
    )
    encoded = json.dumps(
        {
            "company_id": int(company_id),
            "search": normalized_search,
            "limit": int(limit),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _family_cursor(
    value: str | None,
    *,
    company_id: int,
    search: str | None,
    limit: int,
) -> tuple[str | None, int | None]:
    if value is None:
        return None, None
    try:
        payload_part, signature_part = value.split(".", 1)
        payload = base64.urlsafe_b64decode(
            payload_part
            + "=" * (-len(payload_part) % 4)
        )
        signature = base64.urlsafe_b64decode(
            signature_part
            + "=" * (-len(signature_part) % 4)
        )
        if not hmac.compare_digest(
            signature,
            _cursor_signature(payload),
        ):
            raise ValueError(
                "family cursor signature mismatch"
            )
        data = json.loads(payload.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or set(data)
            != {
                "v",
                "after_name",
                "after_id",
                "scope",
            }
            or data.get("v") != 1
            or not isinstance(
                data.get("after_name"),
                str,
            )
            or not data["after_name"].strip()
            or len(data["after_name"]) > 150
            or not isinstance(
                data.get("after_id"),
                int,
            )
            or data["after_id"] <= 0
            or data.get("scope")
            != _family_cursor_scope(
                company_id=company_id,
                search=search,
                limit=limit,
            )
        ):
            raise ValueError(
                "family cursor payload mismatch"
            )
        return (
            data["after_name"],
            int(data["after_id"]),
        )
    except Exception as exc:
        raise _invalid_cursor(exc) from exc


def _family_next_cursor(
    *,
    sort_name: str,
    family_id: int,
    company_id: int,
    search: str | None,
    limit: int,
) -> str:
    # sort_name is the exact key produced by PostgreSQL lower(name).
    # Do not recompute it in Python; keyset continuation must use the
    # same ordering expression that produced the page.
    if (
        not sort_name
        or not sort_name.strip()
        or len(sort_name) > 150
        or family_id <= 0
    ):
        raise ValueError("Invalid family cursor source.")
    payload = json.dumps(
        {
            "v": 1,
            "after_name": sort_name,
            "after_id": int(family_id),
            "scope": _family_cursor_scope(
                company_id=company_id,
                search=search,
                limit=limit,
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload_part = base64.urlsafe_b64encode(
        payload
    ).decode("ascii").rstrip("=")
    signature_part = base64.urlsafe_b64encode(
        _cursor_signature(payload)
    ).decode("ascii").rstrip("=")
    return f"{payload_part}.{signature_part}"


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


async def _require(
    db: AsyncSession,
    actor: Driver,
    permission: str,
) -> None:
    await InventoryAccess(
        db,
        actor,
    ).require(
        permission,
        any_location=True,
    )


async def _require_manage(
    db: AsyncSession,
    actor: Driver,
) -> None:
    for permission in (
        "catalog.manage",
        "catalog.publish",
        "pricing.manage",
    ):
        await _require(
            db,
            actor,
            permission,
        )


@router.get("/package-uoms")
async def package_uoms(
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    try:
        return {
            "items": await list_package_uoms(db)
        }
    except SimpleProductError as exc:
        raise _http_error(exc) from exc


@router.get("/families")
async def families(
    search: str | None = Query(
        None,
        max_length=100,
    ),
    cursor: str | None = Query(
        None,
        max_length=2048,
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
    ),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    company_id = int(actor.company_id)
    after_name, after_id = _family_cursor(
        cursor,
        company_id=company_id,
        search=search,
        limit=limit,
    )
    rows = await list_families(
        db,
        company_id=company_id,
        search=search,
        after_name=after_name,
        after_id=after_id,
        limit=limit + 1,
    )
    page_rows = rows[:limit]
    has_more = len(rows) > limit
    page = [
        {
            key: value
            for key, value in row.items()
            if key != "_sort_name"
        }
        for row in page_rows
    ]
    return {
        "items": page,
        "next_cursor": (
            _family_next_cursor(
                sort_name=str(
                    page_rows[-1]["_sort_name"]
                ),
                family_id=int(
                    page_rows[-1]["id"]
                ),
                company_id=company_id,
                search=search,
                limit=limit,
            )
            if has_more and page_rows
            else None
        ),
        "has_more": has_more,
    }


@router.post(
    "/families",
    status_code=201,
)
async def create_product_family(
    payload: FamilyCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.manage",
    )
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            operation="SIMPLE_PRODUCT_FAMILY_CREATE_V1",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay

        row = await create_family(
            db,
            company_id=int(actor.company_id),
            request_id=payload.request_id,
            name=payload.name,
        )
        response = {
            "id": int(row.id),
            "name": str(row.name),
            "version": int(row.version),
            "variant_count": 0,
        }
        _audit(
            db,
            actor,
            f"Product_{row.id}",
            "SIMPLE_PRODUCT_FAMILY_CREATED",
            response,
        )
        complete_idempotent_operation(
            idem,
            response,
        )
        await db.commit()
        return response
    except SimpleProductError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
    ) as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_FAMILY_CONFLICT",
                "message": "Product family could not be created.",
                "context": {},
            },
        ) from exc


@router.patch("/families/{family_id}")
async def update_product_family(
    family_id: int,
    payload: FamilyUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.manage",
    )
    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            operation="SIMPLE_PRODUCT_FAMILY_RENAME_V1",
            request_id=str(payload.request_id),
            request_hash=_request_hash(
                payload,
                family_id=int(family_id),
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay

        row = await rename_family(
            db,
            company_id=int(actor.company_id),
            family_id=int(family_id),
            expected_version=int(
                payload.expected_version
            ),
            name=payload.name,
        )
        response = {
            "id": int(row.id),
            "name": str(row.name),
            "version": int(row.version),
        }
        _audit(
            db,
            actor,
            f"Product_{row.id}",
            "SIMPLE_PRODUCT_FAMILY_RENAMED",
            response,
        )
        complete_idempotent_operation(
            idem,
            response,
        )
        await db.commit()
        return response
    except SimpleProductError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_FAMILY_IDEMPOTENCY_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc


@router.get("")
async def list_simple_products(
    search: str | None = Query(
        None,
        min_length=2,
        max_length=100,
    ),
    cursor: str | None = Query(
        None,
        max_length=2048,
    ),
    limit: int = Query(
        50,
        ge=1,
        le=200,
    ),
    family_id: int | None = None,
    lifecycle: str | None = None,
    tracking_type: str | None = None,
    simple_compatible: bool | None = None,
    has_barcode: bool | None = None,
    has_price: bool | None = None,
    lot_tracked: bool | None = None,
    expiry_tracked: bool | None = None,
    sort_by: str = "id",
    sort_dir: str = "asc",
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )

    if (
        family_id is not None
        and (
            isinstance(family_id, bool)
            or family_id <= 0
        )
    ):
        raise _product_query_error(
            code="SIMPLE_PRODUCT_FILTER_INVALID",
            field="family_id",
            value=family_id,
        )
    lifecycle_value = _normalized_product_choice(
        lifecycle,
        field="lifecycle",
        allowed=_PRODUCT_LIFECYCLES,
        uppercase=True,
        code="SIMPLE_PRODUCT_FILTER_INVALID",
    )
    tracking_value = _normalized_product_choice(
        tracking_type,
        field="tracking_type",
        allowed=_PRODUCT_TRACKING_TYPES,
        uppercase=True,
        code="SIMPLE_PRODUCT_FILTER_INVALID",
    )
    sort_by_value = _normalized_product_choice(
        sort_by,
        field="sort_by",
        allowed=_PRODUCT_SORT_FIELDS,
        uppercase=False,
        code="SIMPLE_PRODUCT_SORT_INVALID",
    )
    sort_dir_value = _normalized_product_choice(
        sort_dir,
        field="sort_dir",
        allowed=_PRODUCT_SORT_DIRECTIONS,
        uppercase=False,
        code="SIMPLE_PRODUCT_SORT_INVALID",
    )
    assert sort_by_value is not None
    assert sort_dir_value is not None

    try:
        company_id = int(actor.company_id)
        access = InventoryAccess(db, actor)
        can_view_pricing = bool(
            await db.scalar(
                select(
                    access.allows(
                        "pricing.view",
                        any_location=True,
                    )
                )
            )
        )
        if (
            has_price is not None
            and not can_view_pricing
        ):
            raise HTTPException(
                403,
                detail={
                    "code":
                        "SIMPLE_PRODUCT_PRICE_FILTER_FORBIDDEN",
                    "message":
                        "Price filtering requires pricing.view.",
                    "context": {},
                },
            )

        now = datetime.now(timezone.utc)
        company = await load_company(
            db,
            company_id,
        )
        book = None
        if can_view_pricing:
            assignment = await assert_simple_pricing_mode(
                db,
                company_id=company_id,
                as_of=now,
            )
            book = await current_default_book(
                db,
                company=company,
                assignment=assignment,
            )
        currency = str(
            book.currency_code
            if book is not None
            else company.currency_code
        ).upper()

        after_key, after_id = _product_cursor(
            cursor,
            company_id=company_id,
            search=search,
            family_id=family_id,
            lifecycle=lifecycle_value,
            tracking_type=tracking_value,
            simple_compatible=simple_compatible,
            has_barcode=has_barcode,
            has_price=has_price,
            lot_tracked=lot_tracked,
            expiry_tracked=expiry_tracked,
            sort_by=sort_by_value,
            sort_dir=sort_dir_value,
            limit=limit,
        )
        sort_key = _product_sort_key(
            sort_by_value
        )
        search_tokens = _search_tokens(search)
        needs_product_join = bool(
            search_tokens
        ) or sort_by_value == "family"

        selected = [
            ProductVariant,
            sort_key.label("_sort_key"),
        ]
        if needs_product_join:
            selected.insert(
                1,
                Product,
            )

        stmt = select(*selected)
        if needs_product_join:
            stmt = stmt.join(
                Product,
                (
                    Product.company_id
                    == ProductVariant.company_id
                )
                & (
                    Product.id
                    == ProductVariant.product_id
                ),
            )
        stmt = stmt.where(
            ProductVariant.company_id
            == company_id,
            ProductVariant.lifecycle_status.in_(
                ("ACTIVE", "RETIRING")
            ),
        )

        if family_id is not None:
            stmt = stmt.where(
                ProductVariant.product_id
                == int(family_id)
            )
        if lifecycle_value is not None:
            stmt = stmt.where(
                ProductVariant.lifecycle_status
                == lifecycle_value
            )
        if tracking_value is not None:
            stmt = stmt.where(
                _tracking_type_clause(
                    tracking_value
                )
            )
        if lot_tracked is not None:
            lot_clause = (
                ProductVariant.lot_control_mode
                != "NONE"
            )
            stmt = stmt.where(
                lot_clause
                if lot_tracked
                else ~lot_clause
            )
        if expiry_tracked is not None:
            expiry_clause = (
                ProductVariant.expiry_control_mode
                != "NONE"
            )
            stmt = stmt.where(
                expiry_clause
                if expiry_tracked
                else ~expiry_clause
            )

        compatibility_clause = (
            simple_compatibility_clause(
                company_id=company_id,
            )
        )
        if simple_compatible is not None:
            stmt = stmt.where(
                compatibility_clause
                if simple_compatible
                else ~compatibility_clause
            )

        barcode_now = now.replace(
            tzinfo=None
        )
        barcode_exists = _effective_barcode_exists(
            company_id=company_id,
            as_of=barcode_now,
        )
        if has_barcode is not None:
            stmt = stmt.where(
                barcode_exists
                if has_barcode
                else ~barcode_exists
            )

        if has_price is not None:
            if book is None:
                if has_price:
                    stmt = stmt.where(false())
            else:
                price_exists = (
                    simple_price_exists_clause(
                        company_id=company_id,
                        price_book_id=int(
                            book.id
                        ),
                        as_of=now,
                    )
                )
                stmt = stmt.where(
                    price_exists
                    if has_price
                    else ~price_exists
                )

        for token in search_tokens:
            pattern = (
                f"%{_escaped_like(token)}%"
            )
            barcode_match = (
                _effective_barcode_exists(
                    company_id=company_id,
                    as_of=barcode_now,
                    pattern=pattern,
                )
            )
            stmt = stmt.where(
                or_(
                    func.lower(
                        ProductVariant.name
                    ).like(
                        pattern,
                        escape="\\",
                    ),
                    func.lower(
                        Product.name
                    ).like(
                        pattern,
                        escape="\\",
                    ),
                    func.lower(
                        ProductVariant.sku
                    ).like(
                        pattern,
                        escape="\\",
                    ),
                    barcode_match,
                )
            )

        if (
            after_key is not None
            and after_id is not None
        ):
            if sort_dir_value == "asc":
                stmt = stmt.where(
                    or_(
                        sort_key > after_key,
                        and_(
                            sort_key == after_key,
                            ProductVariant.id
                            > after_id,
                        ),
                    )
                )
            else:
                stmt = stmt.where(
                    or_(
                        sort_key < after_key,
                        and_(
                            sort_key == after_key,
                            ProductVariant.id
                            < after_id,
                        ),
                    )
                )

        if sort_dir_value == "asc":
            ordering = (
                sort_key.asc(),
                ProductVariant.id.asc(),
            )
        else:
            ordering = (
                sort_key.desc(),
                ProductVariant.id.desc(),
            )

        rows = list(
            (
                await db.execute(
                    stmt.order_by(
                        *ordering
                    ).limit(limit + 1)
                )
            ).all()
        )
        raw_page = rows[:limit]
        has_more = len(rows) > limit

        if needs_product_join:
            page = [
                (variant, product, sort_value)
                for variant, product, sort_value
                in raw_page
            ]
        else:
            page_variants = [
                variant
                for variant, _sort_value
                in raw_page
            ]
            product_ids = sorted(
                {
                    int(variant.product_id)
                    for variant in page_variants
                }
            )
            products_by_id = {
                int(product.id): product
                for product in (
                    await db.scalars(
                        select(Product).where(
                            Product.company_id
                            == company_id,
                            Product.id.in_(
                                product_ids
                            ),
                        )
                    )
                ).all()
            }
            page = [
                (
                    variant,
                    products_by_id[
                        int(variant.product_id)
                    ],
                    sort_value,
                )
                for variant, sort_value
                in raw_page
            ]

        variants = [
            variant
            for variant, _product, _sort
            in page
        ]

        shapes = await load_sale_shapes(
            db,
            company_id=company_id,
            variants=variants,
        )
        prices = (
            await current_prices(
                db,
                company_id=company_id,
                variants=variants,
                shapes=shapes,
                as_of=now,
            )
            if can_view_pricing
            else {}
        )
        barcodes = await current_primary_barcodes(
            db,
            company_id=company_id,
            variants=variants,
            shapes=shapes,
        )
        compatible = {
            int(variant.id):
                int(variant.id) in shapes
            for variant in variants
        }

        items = []
        for variant, product, _sort in page:
            shape = shapes.get(
                int(variant.id)
            )
            package_price, unit_price = prices.get(
                int(variant.id),
                (None, None),
            )
            unit_barcode, package_barcode = barcodes.get(
                int(variant.id),
                (None, None),
            )
            items.append(
                {
                    "id": int(variant.id),
                    "product_id": int(product.id),
                    "name": str(variant.name),
                    "family_name": str(product.name),
                    "sku": str(variant.sku),
                    "units_per_package": (
                        int(shape.units_per_package)
                        if shape is not None
                        else None
                    ),
                    "legacy_packs_per_carton": int(
                        variant.packs_per_carton
                    ),
                    "base_uom_id": (
                        int(shape.base_uom.id)
                        if shape is not None
                        else int(variant.base_uom_id)
                    ),
                    "package_uom_id": (
                        int(shape.package_uom.id)
                        if shape is not None
                        and shape.package_uom is not None
                        else None
                    ),
                    "package_uom_code": (
                        str(shape.package_uom.code)
                        if shape is not None
                        and shape.package_uom is not None
                        else None
                    ),
                    "currency_code": currency,
                    "package_price": (
                        format(
                            package_price,
                            ".6f",
                        )
                        if package_price
                        is not None
                        else None
                    ),
                    "unit_price": (
                        format(
                            unit_price,
                            ".6f",
                        )
                        if unit_price is not None
                        else None
                    ),
                    "unit_barcode": unit_barcode,
                    "package_barcode":
                        package_barcode,
                    "package_uses_base_barcode": bool(
                        variant.package_uses_base_barcode
                    ),
                    "version": int(
                        variant.version
                    ),
                    "lot_control_mode": str(
                        variant.lot_control_mode
                    ),
                    "expiry_control_mode": str(
                        variant.expiry_control_mode
                    ),
                    "lifecycle_status": str(
                        variant.lifecycle_status
                    ),
                    "simple_compatible": bool(
                        compatible.get(
                            int(variant.id),
                            False,
                        )
                    ),
                }
            )

        return {
            "currency_code": currency,
            "pricing_visible":
                can_view_pricing,
            "items": items,
            "next_cursor": (
                _product_next_cursor(
                    sort_key=page[-1][2],
                    variant_id=int(
                        page[-1][0].id
                    ),
                    company_id=company_id,
                    search=search,
                    family_id=family_id,
                    lifecycle=lifecycle_value,
                    tracking_type=tracking_value,
                    simple_compatible=
                        simple_compatible,
                    has_barcode=has_barcode,
                    has_price=has_price,
                    lot_tracked=lot_tracked,
                    expiry_tracked=
                        expiry_tracked,
                    sort_by=sort_by_value,
                    sort_dir=sort_dir_value,
                    limit=limit,
                )
                if has_more and page
                else None
            ),
            "has_more": has_more,
        }
    except SimpleProductError as exc:
        raise _http_error(exc) from exc
    except PricingError as exc:
        raise _pricing_error(exc) from exc


@router.post("", status_code=201)
async def create_simple_product(
    payload: SimpleProductCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)

    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            operation="SIMPLE_PRODUCT_CREATE_V3",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay

        created = await create_products_and_prices(
            db,
            actor=actor,
            request_id=payload.request_id,
            specs=[
                SimpleProductSpec(
                    name=payload.name,
                    family_id=payload.family_id,
                    family_name=payload.family_name,
                    package_uom_code=payload.package_uom_code,
                    units_per_package=payload.units_per_package,
                    package_price=payload.package_price,
                    unit_price=payload.unit_price,
                    unit_barcode=payload.unit_barcode,
                    package_barcode=payload.package_barcode,
                    lot_control_mode=payload.lot_control_mode,
                    expiry_control_mode=payload.expiry_control_mode,
                )
            ],
        )
        variant, prices = created[0]
        response = {
            "message": "Product created.",
            "product_variant_id": int(variant.id),
            "package_price": (
                format(
                    prices.package_price,
                    ".6f",
                )
                if prices.package_price is not None
                else None
            ),
            "unit_price": format(
                prices.unit_price,
                ".6f",
            ),
            "lot_control_mode": str(
                variant.lot_control_mode
            ),
            "expiry_control_mode": str(
                variant.expiry_control_mode
            ),
        }
        _audit(
            db,
            actor,
            f"ProductVariant_{variant.id}",
            "SIMPLE_PRODUCT_CREATED_V3",
            response,
        )
        complete_idempotent_operation(
            idem,
            response,
        )
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except SimpleProductError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    except PricingError as exc:
        await db.rollback()
        raise _pricing_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
    ) as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_CONFLICT",
                "message": "Product could not be saved because of a data conflict.",
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
    await _require(
        db,
        actor,
        "pricing.manage",
    )

    try:
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            operation="SIMPLE_PRODUCT_PRICE_UPDATE_V3",
            request_id=str(payload.request_id),
            request_hash=_request_hash(
                payload,
                variant_id=int(variant_id),
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay

        variant = await db.scalar(
            select(ProductVariant)
            .where(
                ProductVariant.company_id
                == int(actor.company_id),
                ProductVariant.id
                == int(variant_id),
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
                    "message": "Product was not found.",
                    "context": {},
                },
            )

        prices = await update_prices(
            db,
            actor=actor,
            request_id=payload.request_id,
            variant=variant,
            package_price=payload.package_price,
            unit_price=payload.unit_price,
        )
        response = {
            "message": "Prices updated.",
            "product_variant_id": int(variant.id),
            "package_price": (
                format(
                    prices.package_price,
                    ".6f",
                )
                if prices.package_price is not None
                else None
            ),
            "unit_price": format(
                prices.unit_price,
                ".6f",
            ),
        }
        _audit(
            db,
            actor,
            f"ProductVariant_{variant.id}",
            "SIMPLE_PRODUCT_PRICE_UPDATED_V3",
            response,
        )
        complete_idempotent_operation(
            idem,
            response,
        )
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except SimpleProductError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
    except PricingError as exc:
        await db.rollback()
        raise _pricing_error(exc) from exc
    except (
        InventoryMutationError,
        IntegrityError,
    ) as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "SIMPLE_PRODUCT_PRICE_CONFLICT",
                "message": "Prices could not be updated.",
                "context": {},
            },
        ) from exc


@router.post("/imports", status_code=202)
async def create_product_import(
    request_id: UUID = Form(...),
    default_lot_control_mode: str | None = Form(None),
    default_expiry_control_mode: str | None = Form(None),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)

    file_name = str(
        file.filename or ""
    ).strip()
    if (
        not file_name
        or len(file_name) > 255
        or "\x00" in file_name
    ):
        await file.close()
        raise HTTPException(
            422,
            detail={
                "code": "PRODUCT_IMPORT_FILE_NAME_INVALID",
                "message": "Invalid file name.",
                "context": {},
            },
        )

    suffix = (
        "."
        + file_name.lower().rsplit(".", 1)[-1]
        if "." in file_name
        else ""
    )
    if suffix not in _ALLOWED_IMPORT_SUFFIXES:
        await file.close()
        raise HTTPException(
            415,
            detail={
                "code": "PRODUCT_IMPORT_FILE_TYPE_UNSUPPORTED",
                "message": "Upload a CSV or XLSX file.",
                "context": {},
            },
        )

    payload = await file.read(
        MAX_IMPORT_FILE_BYTES + 1
    )
    content_type = str(
        file.content_type
        or "application/octet-stream"
    )
    await file.close()

    if not payload:
        raise HTTPException(
            422,
            detail={
                "code": "PRODUCT_IMPORT_FILE_EMPTY",
                "message": "The import file is empty.",
                "context": {},
            },
        )
    if len(payload) > MAX_IMPORT_FILE_BYTES:
        raise HTTPException(
            413,
            detail={
                "code": "PRODUCT_IMPORT_FILE_TOO_LARGE",
                "message": "The import file is larger than 8MB.",
                "context": {
                    "max_bytes": MAX_IMPORT_FILE_BYTES
                },
            },
        )

    try:
        tracking_defaults = await resolve_product_tracking_modes(
            db,
            company_id=int(actor.company_id),
            lot_control_mode=default_lot_control_mode,
            expiry_control_mode=default_expiry_control_mode,
        )
        queued = await enqueue_new_import(
            company_id=int(actor.company_id),
            actor_id=int(actor.id),
            request_id=request_id,
            file_name=file_name,
            content_type=content_type,
            payload=payload,
            source_sha256=hashlib.sha256(
                payload
            ).hexdigest(),
            default_lot_control_mode=(
                tracking_defaults.lot_control_mode
            ),
            default_expiry_control_mode=(
                tracking_defaults.expiry_control_mode
            ),
        )
    except ProductTrackingError as exc:
        raise HTTPException(
            exc.status_code,
            detail={
                "code": exc.code,
                "message": exc.message,
                "context": exc.context,
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_IMPORT_REQUEST_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail={
                "code": "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message": "Import could not be queued.",
                "context": {},
            },
        ) from exc

    return {
        "job_id": str(queued["job_id"]),
        "status": str(queued["status"]),
        "replayed": bool(queued["replayed"]),
        "default_lot_control_mode": (
            tracking_defaults.lot_control_mode
        ),
        "default_expiry_control_mode": (
            tracking_defaults.expiry_control_mode
        ),
        "message": "Import accepted for background processing.",
    }


def _job_payload(
    job: ProductImportJob,
) -> dict[str, Any]:
    return {
        "job_id": str(job.id),
        "status": str(job.status),
        "file_name": str(job.file_name),
        "total_rows": int(job.total_rows),
        "processed_rows": int(job.processed_rows),
        "valid_rows": int(job.valid_rows),
        "failed_rows": int(job.failed_rows),
        "detected_headers": list(
            job.detected_headers or []
        ),
        "suggested_mapping": dict(
            job.suggested_mapping or {}
        ),
        "column_mapping": dict(
            job.column_mapping or {}
        ),
        "default_lot_control_mode": str(
            job.default_lot_control_mode
        ),
        "default_expiry_control_mode": str(
            job.default_expiry_control_mode
        ),
        "error_summary": dict(
            job.error_summary or {}
        ),
        "created_at": (
            job.created_at.isoformat()
            if job.created_at
            else None
        ),
        "started_at": (
            job.started_at.isoformat()
            if job.started_at
            else None
        ),
        "finished_at": (
            job.finished_at.isoformat()
            if job.finished_at
            else None
        ),
    }


@router.get("/imports/{job_id}")
async def get_product_import(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    job = await db.scalar(
        select(ProductImportJob).where(
            ProductImportJob.company_id
            == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    errors = []
    if str(job.status) == "VALIDATION_FAILED":
        rows = list(
            (
                await db.scalars(
                    select(ProductImportRow)
                    .where(
                        ProductImportRow.company_id
                        == int(actor.company_id),
                        ProductImportRow.job_id
                        == job_id,
                        ProductImportRow.status
                        == "FAILED",
                    )
                    .order_by(
                        ProductImportRow.row_number.asc()
                    )
                    .limit(50)
                )
            ).all()
        )
        errors = [
            {
                "row_number": int(
                    row.row_number
                ),
                "code": row.error_code,
                "message": row.error_message,
            }
            for row in rows
        ]

    result = _job_payload(job)
    result["errors"] = errors
    return result


@router.get("/imports/{job_id}/errors")
async def get_product_import_errors(
    job_id: UUID,
    after_row: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(
        db,
        actor,
        "catalog.read",
    )
    job_exists = await db.scalar(
        select(ProductImportJob.id).where(
            ProductImportJob.company_id == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job_exists is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    rows = list(
        (
            await db.scalars(
                select(ProductImportRow)
                .where(
                    ProductImportRow.company_id == int(actor.company_id),
                    ProductImportRow.job_id == job_id,
                    ProductImportRow.status == "FAILED",
                    ProductImportRow.row_number > int(after_row),
                )
                .order_by(ProductImportRow.row_number.asc())
                .limit(limit + 1)
            )
        ).all()
    )
    page = rows[:limit]
    has_more = len(rows) > limit
    return {
        "items": [
            {
                "row_number": int(row.row_number),
                "code": row.error_code,
                "message": row.error_message,
            }
            for row in page
        ],
        "next_after_row": (
            int(page[-1].row_number)
            if has_more and page
            else None
        ),
    }


@router.put(
    "/imports/{job_id}/mapping",
    status_code=202,
)
async def set_product_import_mapping(
    job_id: UUID,
    payload: ImportMappingRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)

    job = await db.scalar(
        select(ProductImportJob).where(
            ProductImportJob.company_id
            == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    headers = set(
        job.detected_headers or []
    )
    for field, header in payload.mapping.items():
        if (
            field not in _CANONICAL_MAPPING_FIELDS
            or header not in headers
        ):
            raise HTTPException(
                422,
                detail={
                    "code": "PRODUCT_IMPORT_MAPPING_INVALID",
                    "message": "Column mapping is invalid.",
                    "context": {},
                },
            )

    if not payload.mapping.get("name"):
        raise HTTPException(
            422,
            detail={
                "code": "PRODUCT_IMPORT_MAPPING_NAME_REQUIRED",
                "message": "Map the product-name column.",
                "context": {},
            },
        )
    if not (
        payload.mapping.get("package_price")
        or payload.mapping.get("unit_price")
    ):
        raise HTTPException(
            422,
            detail={
                "code": "PRODUCT_IMPORT_MAPPING_PRICE_REQUIRED",
                "message": "Map package_price or unit_price.",
                "context": {},
            },
        )

    try:
        status = await requeue_import(
            company_id=int(actor.company_id),
            job_id=job_id,
            mapping=payload.mapping,
        )
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_IMPORT_MAPPING_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail={
                "code": "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message": "Import could not be requeued.",
                "context": {},
            },
        ) from exc

    return {
        "job_id": str(job_id),
        "status": str(status),
        "message": "Column mapping accepted.",
    }


@router.post(
    "/imports/{job_id}/retry",
    status_code=202,
)
async def retry_product_import(
    job_id: UUID,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require_manage(db, actor)

    job = await db.scalar(
        select(ProductImportJob).where(
            ProductImportJob.company_id
            == int(actor.company_id),
            ProductImportJob.id == job_id,
        )
    )
    if job is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRODUCT_IMPORT_NOT_FOUND",
                "message": "Import job was not found.",
                "context": {},
            },
        )

    try:
        status = await retry_failed_import(
            company_id=int(actor.company_id),
            job_id=job_id,
        )
    except ValueError as exc:
        raise HTTPException(
            409,
            detail={
                "code": "PRODUCT_IMPORT_NOT_RETRYABLE",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except Exception as exc:
        raise HTTPException(
            503,
            detail={
                "code": "PRODUCT_IMPORT_QUEUE_UNAVAILABLE",
                "message": "Import could not be retried.",
                "context": {},
            },
        ) from exc

    return {
        "job_id": str(job_id),
        "status": str(status),
        "message": "Import retry accepted.",
    }
