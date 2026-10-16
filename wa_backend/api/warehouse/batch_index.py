from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Date, and_, case, func, or_, select, true
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from config import Config
from database import get_db
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.inventory_rules import (
    batch_metadata_is_sellable,
    batch_sellability_predicate,
)
from domains.product_tracking import (
    INTERNAL_NO_LOT_PREFIX,
    public_batch_number,
)
from models import (
    Company,
    InventoryBalance,
    InventoryLocation,
    InventoryStockPolicy,
    Product,
    ProductBatch,
    ProductUomConversion,
    ProductVariant,
    UOM,
)
from quantity import canonical_quantity
from schemas import (
    WarehouseInventoryBatchIndexCursorPage,
    WarehouseInventoryBatchIndexSummaryResponse,
)
from services import allowed_batch_disposition_targets

from ._shared import _escape_like


router = APIRouter()

ExpiryState = Literal[
    "ALL",
    "EXPIRED",
    "EXPIRES_TODAY",
    "EXPIRING_SOON",
    "NO_EXPIRY",
]
SellabilityFilter = Literal["ALL", "SELLABLE", "NOT_SELLABLE"]
DispositionFilter = Literal[
    "RELEASED",
    "QUARANTINED",
    "BLOCKED",
    "RECALLED",
]
BatchIndexSort = Literal[
    "EXPIRY_ASC",
    "EXPIRY_DESC",
    "PRODUCT_ASC",
    "PRODUCT_DESC",
    "BATCH_IDENTITY_ASC",
    "UNAVAILABLE_DESC",
]

_REASON_ORDER = (
    "BATCH_INACTIVE",
    "DISPOSITION_NOT_RELEASED",
    "PRODUCTION_DATE_IN_FUTURE",
    "EXPIRY_REQUIRED_MISSING",
    "EXPIRY_NOT_ALLOWED",
    "EXPIRED",
    "MINIMUM_REMAINING_SHELF_LIFE_NOT_MET",
)
_MAX_SEARCH_TOKENS = 12
_MAX_EXPIRY_WARNING_DAYS = 3650


def _query_error(code: str, message: str, *, field: str) -> HTTPException:
    return HTTPException(
        status_code=422,
        detail={
            "code": code,
            "message": message,
            "context": {"field": field},
        },
    )


def _invalid_cursor(exc: Exception | None = None) -> HTTPException:
    error = HTTPException(
        status_code=400,
        detail={
            "code": "BATCH_INDEX_CURSOR_INVALID",
            "message": "Invalid or mismatched batch-index cursor.",
            "context": {},
        },
    )
    if exc is not None:
        error.__cause__ = exc
    return error


def _search_tokens(search: str | None) -> tuple[str, ...]:
    if search is None:
        return ()
    if not isinstance(search, str):
        raise _query_error(
            "BATCH_INDEX_SEARCH_INVALID",
            "Search must be text.",
            field="search",
        )
    clean = search.strip()
    if not clean:
        return ()
    tokens = tuple(token.lower() for token in clean.split() if token)
    if len(tokens) > _MAX_SEARCH_TOKENS:
        raise _query_error(
            "BATCH_INDEX_SEARCH_TOO_MANY_TOKENS",
            "Search contains too many tokens.",
            field="search",
        )
    return tokens


def _scope_hash(
    *,
    company_id: int,
    location_id: int,
    search_tokens: tuple[str, ...],
    expiry_state: str,
    expiry_warning_days: int | None,
    sellability: str,
    disposition: str | None,
    has_unavailable: bool | None,
    has_damaged: bool | None,
    has_disposal_pending: bool | None,
    family_id: int | None,
    product_variant_id: int | None,
    sort: str,
    limit: int,
) -> str:
    encoded = json.dumps(
        {
            "company_id": int(company_id),
            "location_id": int(location_id),
            "search": list(search_tokens),
            "expiry_state": expiry_state,
            "expiry_warning_days": expiry_warning_days,
            "sellability": sellability,
            "disposition": disposition,
            "has_unavailable": has_unavailable,
            "has_damaged": has_damaged,
            "has_disposal_pending": has_disposal_pending,
            "family_id": family_id,
            "product_variant_id": product_variant_id,
            "sort": sort,
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


def _decode_cursor_part(value: str) -> bytes:
    if not value or "=" in value:
        raise ValueError("invalid base64url cursor component")
    encoded = value.encode("ascii")
    decoded = base64.b64decode(
        encoded + b"=" * (-len(encoded) % 4),
        altchars=b"-_",
        validate=True,
    )
    canonical = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if not hmac.compare_digest(canonical, value):
        raise ValueError("non-canonical base64url cursor component")
    return decoded


def _decode_cursor(
    cursor: str | None,
    *,
    expected_scope: str,
    expected_sort: str,
) -> dict | None:
    if cursor is None:
        return None
    try:
        payload_part, signature_part = cursor.split(".", 1)
        payload = _decode_cursor_part(payload_part)
        signature = _decode_cursor_part(signature_part)
        if not hmac.compare_digest(signature, _cursor_signature(payload)):
            raise ValueError("cursor signature mismatch")
        data = json.loads(payload.decode("utf-8"))
        if (
            not isinstance(data, dict)
            or set(data) != {"v", "scope", "sort", "batch_id", "key"}
            or data.get("v") != 1
            or data.get("scope") != expected_scope
            or data.get("sort") != expected_sort
            or type(data.get("batch_id")) is not int
            or data["batch_id"] <= 0
        ):
            raise ValueError("cursor payload mismatch")
        key = data.get("key")
        if expected_sort in {"EXPIRY_ASC", "EXPIRY_DESC"}:
            if key is not None:
                if not isinstance(key, str) or len(key) != 10:
                    raise ValueError("invalid expiry cursor key")
                date.fromisoformat(key)
        elif expected_sort in {"PRODUCT_ASC", "PRODUCT_DESC"}:
            if not isinstance(key, str) or not key or len(key) > 200:
                raise ValueError("invalid product cursor key")
        elif expected_sort == "UNAVAILABLE_DESC":
            if not isinstance(key, str):
                raise ValueError("invalid quantity cursor key")
            quantity = Decimal(key)
            if not quantity.is_finite() or quantity < 0:
                raise ValueError("invalid quantity cursor key")
        elif expected_sort == "BATCH_IDENTITY_ASC":
            if key is not None:
                raise ValueError("batch identity cursor must not carry a lot key")
        else:
            raise ValueError("unsupported cursor sort")
        return data
    except (InvalidOperation, ValueError, TypeError, UnicodeError, json.JSONDecodeError) as exc:
        raise _invalid_cursor(exc) from exc


def _encode_cursor(
    *,
    scope: str,
    sort: str,
    batch_id: int,
    key: str | None,
) -> str:
    payload = json.dumps(
        {
            "v": 1,
            "scope": scope,
            "sort": sort,
            "batch_id": int(batch_id),
            "key": key,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload_part = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature_part = base64.urlsafe_b64encode(
        _cursor_signature(payload)
    ).decode("ascii").rstrip("=")
    return f"{payload_part}.{signature_part}"


async def _require_warehouse_inventory_read(
    db: AsyncSession,
    *,
    company_id: int,
    location_id: int,
    access: BackofficeCapabilityAccess,
) -> None:
    location = (
        await db.execute(
            select(
                InventoryLocation.location_type,
                InventoryLocation.is_active,
            ).where(
                InventoryLocation.company_id == int(company_id),
                InventoryLocation.id == int(location_id),
            )
        )
    ).one_or_none()
    if (
        location is None
        or str(location.location_type) != "WAREHOUSE"
        or not bool(location.is_active)
    ):
        raise HTTPException(
            status_code=404,
            detail={
                "code": "BATCH_INDEX_LOCATION_NOT_FOUND",
                "message": "The selected warehouse is unavailable.",
                "context": {},
            },
        )
    try:
        await access.require("inventory.read", location_id=int(location_id))
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(
            status_code=403,
            detail={
                "code": "BATCH_INDEX_READ_FORBIDDEN",
                "message": "Inventory read is not allowed at the selected warehouse.",
                "context": {},
            },
        ) from None


async def _company_local_date(db: AsyncSession, *, company_id: int) -> date:
    as_of_date = await db.scalar(
        select(
            func.timezone(
                Company.timezone,
                func.current_timestamp(),
            ).cast(Date)
        ).where(Company.id == int(company_id))
    )
    if as_of_date is None:
        raise RuntimeError("Company timezone is unavailable.")
    return as_of_date


def _stock_aggregate_subquery(*, company_id: int, location_id: int):
    return (
        select(
            InventoryBalance.product_variant_id.label("product_variant_id"),
            InventoryBalance.batch_id.label("batch_id"),
            func.sum(InventoryBalance.on_hand_quantity).label("on_hand_quantity"),
            func.sum(InventoryBalance.reserved_quantity).label("reserved_quantity"),
            func.sum(
                case(
                    (
                        InventoryBalance.stock_status == "AVAILABLE",
                        InventoryBalance.on_hand_quantity,
                    ),
                    else_=0,
                )
            ).label("available_status_quantity"),
            func.sum(
                case(
                    (
                        InventoryBalance.stock_status == "AVAILABLE",
                        InventoryBalance.reserved_quantity,
                    ),
                    else_=0,
                )
            ).label("available_status_reserved_quantity"),
            func.sum(
                case(
                    (
                        InventoryBalance.stock_status == "QUARANTINED",
                        InventoryBalance.on_hand_quantity,
                    ),
                    else_=0,
                )
            ).label("quarantined_quantity"),
            func.sum(
                case(
                    (
                        InventoryBalance.stock_status == "BLOCKED",
                        InventoryBalance.on_hand_quantity,
                    ),
                    else_=0,
                )
            ).label("blocked_quantity"),
            func.sum(
                case(
                    (
                        InventoryBalance.stock_status == "RECALLED",
                        InventoryBalance.on_hand_quantity,
                    ),
                    else_=0,
                )
            ).label("recalled_quantity"),
            func.sum(
                case(
                    (
                        InventoryBalance.stock_status == "DAMAGED",
                        InventoryBalance.on_hand_quantity,
                    ),
                    else_=0,
                )
            ).label("damaged_quantity"),
            func.sum(
                case(
                    (
                        InventoryBalance.stock_status == "DISPOSAL_PENDING",
                        InventoryBalance.on_hand_quantity,
                    ),
                    else_=0,
                )
            ).label("disposal_pending_quantity"),
        )
        .where(
            InventoryBalance.company_id == int(company_id),
            InventoryBalance.location_id == int(location_id),
            InventoryBalance.batch_id.is_not(None),
            InventoryBalance.on_hand_quantity > 0,
        )
        .group_by(
            InventoryBalance.product_variant_id,
            InventoryBalance.batch_id,
        )
        .subquery("batch_index_stock")
    )


def _display_uom_one_subquery(*, company_id: int):
    display_uom = aliased(UOM, name="batch_index_display_uom")
    factor = ProductUomConversion.numerator / ProductUomConversion.denominator
    return (
        select(
            func.count(ProductUomConversion.id).label("candidate_count"),
            func.min(display_uom.id).label("display_uom_id_raw"),
            func.min(display_uom.code).label("display_uom_code_raw"),
            func.min(display_uom.name).label("display_uom_name_raw"),
            func.min(factor).label("display_factor_to_base_raw"),
        )
        .select_from(ProductUomConversion)
        .join(display_uom, display_uom.id == ProductUomConversion.from_uom_id)
        .where(
            ProductUomConversion.company_id == int(company_id),
            ProductUomConversion.product_variant_id == ProductVariant.id,
            ProductUomConversion.to_uom_id == ProductVariant.base_uom_id,
            ProductUomConversion.numerator > ProductUomConversion.denominator,
        )
        .lateral("batch_index_display_uom_one")
    )


def _search_predicates(tokens: tuple[str, ...]):
    predicates = []
    for token in tokens:
        pattern = f"%{_escape_like(token)}%"
        predicates.append(
            or_(
                func.lower(ProductVariant.name).like(pattern, escape="\\"),
                func.lower(Product.name).like(pattern, escape="\\"),
                func.lower(func.coalesce(ProductVariant.sku, "")).like(
                    pattern,
                    escape="\\",
                ),
                and_(
                    ProductBatch.batch_number.is_not(None),
                    ProductBatch.batch_number.not_like(
                        f"{_escape_like(INTERNAL_NO_LOT_PREFIX)}%",
                        escape="\\",
                    ),
                    func.lower(ProductBatch.batch_number).like(
                        pattern,
                        escape="\\",
                    ),
                ),
            )
        )
    return tuple(predicates)


def _reason_codes(
    *,
    as_of_date: date,
    expiry_control_mode: str,
    production_date: date | None,
    expiry_date: date | None,
    minimum_remaining_shelf_life_days: int,
    is_active: bool,
    disposition: str,
) -> tuple[str, ...]:
    mode = str(expiry_control_mode or "").upper()
    disposition_value = str(disposition or "").upper()
    minimum_days = int(minimum_remaining_shelf_life_days or 0)
    reasons: set[str] = set()

    if not bool(is_active):
        reasons.add("BATCH_INACTIVE")
    if disposition_value != "RELEASED":
        reasons.add("DISPOSITION_NOT_RELEASED")
    if production_date is not None and production_date > as_of_date:
        reasons.add("PRODUCTION_DATE_IN_FUTURE")
    if expiry_date is None and mode == "REQUIRED":
        reasons.add("EXPIRY_REQUIRED_MISSING")
    if expiry_date is not None and mode == "NONE":
        reasons.add("EXPIRY_NOT_ALLOWED")

    expired = expiry_date is not None and expiry_date < as_of_date
    if expired:
        reasons.add("EXPIRED")
    elif minimum_days > 0:
        if expiry_date is None:
            if mode in {"NONE", "OPTIONAL"}:
                reasons.add("MINIMUM_REMAINING_SHELF_LIFE_NOT_MET")
        elif mode != "NONE" and (expiry_date - as_of_date).days < minimum_days:
            reasons.add("MINIMUM_REMAINING_SHELF_LIFE_NOT_MET")

    sellable = batch_metadata_is_sellable(
        as_of_date=as_of_date,
        expiry_control_mode=mode,
        production_date=production_date,
        expiry_date=expiry_date,
        minimum_remaining_shelf_life_days=minimum_days,
        is_active=bool(is_active),
        disposition=disposition_value,
    )
    ordered = tuple(reason for reason in _REASON_ORDER if reason in reasons)
    if sellable and ordered:
        raise RuntimeError("Batch sellability reason invariant failed for sellable batch.")
    if not sellable and not ordered:
        raise RuntimeError("Batch sellability reason invariant failed for non-sellable batch.")
    return ordered


def _expiry_filter(
    *,
    expiry_state: str,
    as_of_date: date,
    expiry_warning_days: int | None,
):
    if expiry_state == "ALL":
        return true()
    if expiry_state == "NO_EXPIRY":
        return ProductBatch.expiry_date.is_(None)
    if expiry_state == "EXPIRED":
        return ProductBatch.expiry_date < as_of_date
    if expiry_state == "EXPIRES_TODAY":
        return ProductBatch.expiry_date == as_of_date
    if expiry_state == "EXPIRING_SOON":
        if expiry_warning_days is None:
            raise _query_error(
                "BATCH_INDEX_EXPIRY_WARNING_REQUIRED",
                "expiry_warning_days is required for EXPIRING_SOON.",
                field="expiry_warning_days",
            )
        return and_(
            ProductBatch.expiry_date > as_of_date,
            ProductBatch.expiry_date
            <= as_of_date + timedelta(days=int(expiry_warning_days)),
        )
    raise _query_error(
        "BATCH_INDEX_EXPIRY_STATE_INVALID",
        "Invalid expiry state.",
        field="expiry_state",
    )


def _cursor_key(row, *, sort: str) -> str | None:
    if sort in {"EXPIRY_ASC", "EXPIRY_DESC"}:
        return row.expiry_date.isoformat() if row.expiry_date is not None else None
    if sort in {"PRODUCT_ASC", "PRODUCT_DESC"}:
        return str(row.product_sort_key)
    if sort == "UNAVAILABLE_DESC":
        return canonical_quantity(Decimal(row.unavailable_quantity or 0))
    return None


def _cursor_predicate(
    cursor_data: dict | None,
    *,
    sort: str,
    unavailable_expression,
):
    if cursor_data is None:
        return true()
    batch_id = int(cursor_data["batch_id"])
    key = cursor_data["key"]

    if sort in {"EXPIRY_ASC", "EXPIRY_DESC"}:
        if key is None:
            return and_(
                ProductBatch.expiry_date.is_(None),
                ProductBatch.id > batch_id,
            )
        expiry_key = date.fromisoformat(key)
        direction = (
            ProductBatch.expiry_date > expiry_key
            if sort == "EXPIRY_ASC"
            else ProductBatch.expiry_date < expiry_key
        )
        return or_(
            direction,
            and_(
                ProductBatch.expiry_date == expiry_key,
                ProductBatch.id > batch_id,
            ),
            ProductBatch.expiry_date.is_(None),
        )

    if sort in {"PRODUCT_ASC", "PRODUCT_DESC"}:
        product_key = str(key)
        product_sort_key = func.lower(ProductVariant.name)
        direction = (
            product_sort_key > product_key
            if sort == "PRODUCT_ASC"
            else product_sort_key < product_key
        )
        return or_(
            direction,
            and_(product_sort_key == product_key, ProductBatch.id > batch_id),
        )

    if sort == "BATCH_IDENTITY_ASC":
        return ProductBatch.id > batch_id

    if sort == "UNAVAILABLE_DESC":
        quantity_key = Decimal(str(key))
        return or_(
            unavailable_expression < quantity_key,
            and_(
                unavailable_expression == quantity_key,
                ProductBatch.id > batch_id,
            ),
        )

    raise ValueError("Unsupported batch-index sort.")


def _ordering(*, sort: str, unavailable_expression):
    if sort == "EXPIRY_ASC":
        return (ProductBatch.expiry_date.asc().nulls_last(), ProductBatch.id.asc())
    if sort == "EXPIRY_DESC":
        return (ProductBatch.expiry_date.desc().nulls_last(), ProductBatch.id.asc())
    if sort == "PRODUCT_ASC":
        return (func.lower(ProductVariant.name).asc(), ProductBatch.id.asc())
    if sort == "PRODUCT_DESC":
        return (func.lower(ProductVariant.name).desc(), ProductBatch.id.asc())
    if sort == "BATCH_IDENTITY_ASC":
        return (ProductBatch.id.asc(),)
    if sort == "UNAVAILABLE_DESC":
        return (unavailable_expression.desc(), ProductBatch.id.asc())
    raise ValueError("Unsupported batch-index sort.")


def _batch_index_query_parts(
    *,
    company_id: int,
    location_id: int,
    as_of_date: date,
):
    stock = _stock_aggregate_subquery(
        company_id=company_id,
        location_id=location_id,
    )
    policy_minimum = func.coalesce(
        InventoryStockPolicy.minimum_remaining_shelf_life_days,
        0,
    )
    batch_is_sellable = batch_sellability_predicate(
        as_of_date,
        expiry_control_mode=ProductVariant.expiry_control_mode,
        minimum_remaining_shelf_life_days=policy_minimum,
    )
    available_for_sale = case(
        (
            batch_is_sellable,
            stock.c.available_status_quantity
            - stock.c.available_status_reserved_quantity,
        ),
        else_=0,
    )
    unavailable = (
        stock.c.on_hand_quantity
        - stock.c.reserved_quantity
        - available_for_sale
    )
    return stock, policy_minimum, batch_is_sellable, available_for_sale, unavailable


@router.get(
    "/warehouse/inventory/batches/cursor",
    response_model=WarehouseInventoryBatchIndexCursorPage,
    status_code=200,
)
async def get_warehouse_inventory_batch_index_cursor(
    location_id: Annotated[int, Query(gt=0)],
    cursor: Annotated[Optional[str], Query(max_length=2048)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    search: Annotated[Optional[str], Query(max_length=200)] = None,
    expiry_state: ExpiryState = "ALL",
    expiry_warning_days: Annotated[
        Optional[int],
        Query(ge=1, le=_MAX_EXPIRY_WARNING_DAYS),
    ] = None,
    sellability: SellabilityFilter = "ALL",
    disposition: Optional[DispositionFilter] = None,
    has_unavailable: Optional[bool] = None,
    has_damaged: Optional[bool] = None,
    has_disposal_pending: Optional[bool] = None,
    family_id: Annotated[Optional[int], Query(gt=0)] = None,
    product_variant_id: Annotated[Optional[int], Query(gt=0)] = None,
    sort: BatchIndexSort = "EXPIRY_ASC",
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(
        get_current_backoffice_capability_access
    ),
):
    company_id = access.company_id
    await _require_warehouse_inventory_read(
        db,
        company_id=company_id,
        location_id=location_id,
        access=access,
    )
    as_of_date = await _company_local_date(db, company_id=company_id)
    tokens = _search_tokens(search)

    if expiry_state != "EXPIRING_SOON" and expiry_warning_days is not None:
        raise _query_error(
            "BATCH_INDEX_EXPIRY_WARNING_SCOPE_INVALID",
            "expiry_warning_days is only valid with EXPIRING_SOON.",
            field="expiry_warning_days",
        )
    expiry_predicate = _expiry_filter(
        expiry_state=expiry_state,
        as_of_date=as_of_date,
        expiry_warning_days=expiry_warning_days,
    )

    scope = _scope_hash(
        company_id=company_id,
        location_id=location_id,
        search_tokens=tokens,
        expiry_state=expiry_state,
        expiry_warning_days=expiry_warning_days,
        sellability=sellability,
        disposition=disposition,
        has_unavailable=has_unavailable,
        has_damaged=has_damaged,
        has_disposal_pending=has_disposal_pending,
        family_id=family_id,
        product_variant_id=product_variant_id,
        sort=sort,
        limit=limit,
    )
    cursor_data = _decode_cursor(
        cursor,
        expected_scope=scope,
        expected_sort=sort,
    )

    stock, policy_minimum, batch_is_sellable, available_for_sale, unavailable = (
        _batch_index_query_parts(
            company_id=company_id,
            location_id=location_id,
            as_of_date=as_of_date,
        )
    )
    base_uom = aliased(UOM, name="batch_index_base_uom")
    display_uom_one = _display_uom_one_subquery(company_id=company_id)
    product_sort_key = func.lower(ProductVariant.name).label("product_sort_key")

    filters = [
        ProductBatch.company_id == company_id,
        ProductVariant.company_id == company_id,
        Product.company_id == company_id,
        ProductBatch.product_variant_id == ProductVariant.id,
        stock.c.product_variant_id == ProductVariant.id,
        stock.c.batch_id == ProductBatch.id,
        expiry_predicate,
        *_search_predicates(tokens),
    ]
    if family_id is not None:
        filters.append(Product.id == int(family_id))
    if product_variant_id is not None:
        filters.append(ProductVariant.id == int(product_variant_id))
    if disposition is not None:
        filters.append(ProductBatch.disposition == disposition)
    if sellability == "SELLABLE":
        filters.append(batch_is_sellable)
    elif sellability == "NOT_SELLABLE":
        filters.append(~batch_is_sellable)
    if has_unavailable is not None:
        filters.append(unavailable > 0 if has_unavailable else unavailable <= 0)
    if has_damaged is not None:
        filters.append(
            stock.c.damaged_quantity > 0
            if has_damaged
            else stock.c.damaged_quantity <= 0
        )
    if has_disposal_pending is not None:
        filters.append(
            stock.c.disposal_pending_quantity > 0
            if has_disposal_pending
            else stock.c.disposal_pending_quantity <= 0
        )

    filters.append(
        _cursor_predicate(
            cursor_data,
            sort=sort,
            unavailable_expression=unavailable,
        )
    )

    stmt = (
        select(
            ProductBatch.id.label("batch_id"),
            ProductBatch.batch_number,
            ProductBatch.production_date,
            ProductBatch.expiry_date,
            ProductBatch.is_active.label("batch_is_active"),
            ProductBatch.disposition,
            ProductBatch.disposition_reason,
            ProductBatch.disposition_revision,
            ProductVariant.id.label("product_variant_id"),
            ProductVariant.product_id.label("product_id"),
            ProductVariant.name.label("product_name"),
            ProductVariant.sku,
            ProductVariant.lot_control_mode,
            ProductVariant.expiry_control_mode,
            ProductVariant.quantity_scale,
            ProductVariant.quantity_step,
            Product.name.label("family_name"),
            base_uom.id.label("base_uom_id"),
            base_uom.code.label("base_uom_code"),
            base_uom.name.label("base_uom_name"),
            display_uom_one.c.candidate_count,
            display_uom_one.c.display_uom_id_raw,
            display_uom_one.c.display_uom_code_raw,
            display_uom_one.c.display_uom_name_raw,
            display_uom_one.c.display_factor_to_base_raw,
            policy_minimum.label("minimum_remaining_shelf_life_days"),
            stock.c.on_hand_quantity,
            stock.c.reserved_quantity,
            stock.c.available_status_quantity,
            stock.c.quarantined_quantity,
            stock.c.blocked_quantity,
            stock.c.recalled_quantity,
            stock.c.damaged_quantity,
            stock.c.disposal_pending_quantity,
            available_for_sale.label("available_for_sale_quantity"),
            unavailable.label("unavailable_quantity"),
            batch_is_sellable.label("is_sellable"),
            product_sort_key,
        )
        .select_from(stock)
        .join(ProductBatch, ProductBatch.id == stock.c.batch_id)
        .join(ProductVariant, ProductVariant.id == stock.c.product_variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .join(base_uom, base_uom.id == ProductVariant.base_uom_id)
        .outerjoin(
            InventoryStockPolicy,
            and_(
                InventoryStockPolicy.company_id == company_id,
                InventoryStockPolicy.location_id == location_id,
                InventoryStockPolicy.product_variant_id == ProductVariant.id,
                InventoryStockPolicy.is_active.is_(True),
            ),
        )
        .join(display_uom_one, true())
        .where(*filters)
        .order_by(*_ordering(sort=sort, unavailable_expression=unavailable))
        .limit(limit + 1)
        .prefix_with("/* warehouse_batch_index_cursor */")
    )

    rows = (await db.execute(stmt)).all()
    has_more = len(rows) > limit
    page_rows = rows[:limit]

    items = []
    for row in page_rows:
        minimum_days = int(row.minimum_remaining_shelf_life_days or 0)
        reasons = _reason_codes(
            as_of_date=as_of_date,
            expiry_control_mode=str(row.expiry_control_mode),
            production_date=row.production_date,
            expiry_date=row.expiry_date,
            minimum_remaining_shelf_life_days=minimum_days,
            is_active=bool(row.batch_is_active),
            disposition=str(row.disposition),
        )
        sellable = batch_metadata_is_sellable(
            as_of_date=as_of_date,
            expiry_control_mode=str(row.expiry_control_mode),
            production_date=row.production_date,
            expiry_date=row.expiry_date,
            minimum_remaining_shelf_life_days=minimum_days,
            is_active=bool(row.batch_is_active),
            disposition=str(row.disposition),
        )
        if bool(row.is_sellable) != sellable:
            raise RuntimeError("SQL/Python batch sellability parity failed.")

        if int(row.candidate_count or 0) == 1:
            display_uom_id = int(row.display_uom_id_raw)
            display_uom_code = str(row.display_uom_code_raw)
            display_uom_name = str(row.display_uom_name_raw)
            display_factor = Decimal(row.display_factor_to_base_raw)
        else:
            display_uom_id = int(row.base_uom_id)
            display_uom_code = str(row.base_uom_code)
            display_uom_name = str(row.base_uom_name)
            display_factor = Decimal("1")

        items.append(
            {
                "batch_id": int(row.batch_id),
                "batch_number": public_batch_number(row.batch_number),
                "product_variant_id": int(row.product_variant_id),
                "product_id": int(row.product_id),
                "product_name": str(row.product_name),
                "sku": str(row.sku) if row.sku is not None else None,
                "family_name": str(row.family_name),
                "lot_control_mode": str(row.lot_control_mode),
                "expiry_control_mode": str(row.expiry_control_mode),
                "production_date": row.production_date,
                "expiry_date": row.expiry_date,
                "days_to_expiry": (
                    (row.expiry_date - as_of_date).days
                    if row.expiry_date is not None
                    else None
                ),
                "minimum_remaining_shelf_life_days": minimum_days,
                "sellability_state": "SELLABLE" if sellable else "NOT_SELLABLE",
                "sellability_reason_codes": list(reasons),
                "disposition": str(row.disposition),
                "disposition_reason": (
                    str(row.disposition_reason)
                    if row.disposition_reason is not None
                    else None
                ),
                "disposition_revision": int(row.disposition_revision),
                "allowed_disposition_targets": list(
                    allowed_batch_disposition_targets(str(row.disposition))
                ),
                "base_uom_id": int(row.base_uom_id),
                "base_uom_code": str(row.base_uom_code),
                "base_uom_name": str(row.base_uom_name),
                "display_uom_id": display_uom_id,
                "display_uom_code": display_uom_code,
                "display_uom_name": display_uom_name,
                "display_factor_to_base": canonical_quantity(display_factor),
                "quantity_scale": int(row.quantity_scale),
                "quantity_step": canonical_quantity(Decimal(row.quantity_step)),
                "on_hand_quantity": canonical_quantity(Decimal(row.on_hand_quantity or 0)),
                "reserved_quantity": canonical_quantity(Decimal(row.reserved_quantity or 0)),
                "available_for_sale_quantity": canonical_quantity(
                    Decimal(row.available_for_sale_quantity or 0)
                ),
                "unavailable_quantity": canonical_quantity(
                    Decimal(row.unavailable_quantity or 0)
                ),
                "available_status_quantity": canonical_quantity(
                    Decimal(row.available_status_quantity or 0)
                ),
                "quarantined_quantity": canonical_quantity(
                    Decimal(row.quarantined_quantity or 0)
                ),
                "blocked_quantity": canonical_quantity(Decimal(row.blocked_quantity or 0)),
                "recalled_quantity": canonical_quantity(Decimal(row.recalled_quantity or 0)),
                "damaged_quantity": canonical_quantity(Decimal(row.damaged_quantity or 0)),
                "disposal_pending_quantity": canonical_quantity(
                    Decimal(row.disposal_pending_quantity or 0)
                ),
            }
        )

    next_cursor = None
    if has_more and page_rows:
        last = page_rows[-1]
        next_cursor = _encode_cursor(
            scope=scope,
            sort=sort,
            batch_id=int(last.batch_id),
            key=_cursor_key(last, sort=sort),
        )

    return {
        "location_id": int(location_id),
        "as_of_date": as_of_date,
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
    }


@router.get(
    "/warehouse/inventory/batches/summary",
    response_model=WarehouseInventoryBatchIndexSummaryResponse,
    status_code=200,
)
async def get_warehouse_inventory_batch_index_summary(
    location_id: Annotated[int, Query(gt=0)],
    expiry_warning_days: Annotated[
        int,
        Query(ge=1, le=_MAX_EXPIRY_WARNING_DAYS),
    ],
    search: Annotated[Optional[str], Query(max_length=200)] = None,
    family_id: Annotated[Optional[int], Query(gt=0)] = None,
    product_variant_id: Annotated[Optional[int], Query(gt=0)] = None,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(
        get_current_backoffice_capability_access
    ),
):
    company_id = access.company_id
    await _require_warehouse_inventory_read(
        db,
        company_id=company_id,
        location_id=location_id,
        access=access,
    )
    as_of_date = await _company_local_date(db, company_id=company_id)
    tokens = _search_tokens(search)

    stock, _, batch_is_sellable, _, _ = _batch_index_query_parts(
        company_id=company_id,
        location_id=location_id,
        as_of_date=as_of_date,
    )

    filters = [
        ProductBatch.company_id == company_id,
        ProductVariant.company_id == company_id,
        Product.company_id == company_id,
        ProductBatch.product_variant_id == ProductVariant.id,
        stock.c.product_variant_id == ProductVariant.id,
        stock.c.batch_id == ProductBatch.id,
        *_search_predicates(tokens),
    ]
    if family_id is not None:
        filters.append(Product.id == int(family_id))
    if product_variant_id is not None:
        filters.append(ProductVariant.id == int(product_variant_id))

    expiring_limit = as_of_date + timedelta(days=int(expiry_warning_days))
    attention = or_(
        stock.c.damaged_quantity > 0,
        stock.c.disposal_pending_quantity > 0,
    )

    stmt = (
        select(
            func.count(ProductBatch.id).label("total_relevant_batches"),
            func.count(ProductBatch.id)
            .filter(ProductBatch.expiry_date < as_of_date)
            .label("expired_count"),
            func.count(ProductBatch.id)
            .filter(
                and_(
                    ProductBatch.expiry_date > as_of_date,
                    ProductBatch.expiry_date <= expiring_limit,
                )
            )
            .label("expiring_soon_count"),
            func.count(ProductBatch.id)
            .filter(~batch_is_sellable)
            .label("non_sellable_count"),
            func.count(ProductBatch.id)
            .filter(ProductBatch.disposition == "QUARANTINED")
            .label("quarantined_count"),
            func.count(ProductBatch.id)
            .filter(ProductBatch.disposition == "BLOCKED")
            .label("blocked_count"),
            func.count(ProductBatch.id)
            .filter(ProductBatch.disposition == "RECALLED")
            .label("recalled_count"),
            func.count(ProductBatch.id)
            .filter(attention)
            .label("damaged_or_disposal_attention_count"),
        )
        .select_from(stock)
        .join(ProductBatch, ProductBatch.id == stock.c.batch_id)
        .join(ProductVariant, ProductVariant.id == stock.c.product_variant_id)
        .join(Product, Product.id == ProductVariant.product_id)
        .outerjoin(
            InventoryStockPolicy,
            and_(
                InventoryStockPolicy.company_id == company_id,
                InventoryStockPolicy.location_id == location_id,
                InventoryStockPolicy.product_variant_id == ProductVariant.id,
                InventoryStockPolicy.is_active.is_(True),
            ),
        )
        .where(*filters)
        .prefix_with("/* warehouse_batch_index_summary */")
    )

    row = (await db.execute(stmt)).one()
    return {
        "location_id": int(location_id),
        "as_of_date": as_of_date,
        "total_relevant_batches": int(row.total_relevant_batches or 0),
        "expired_count": int(row.expired_count or 0),
        "expiring_soon_count": int(row.expiring_soon_count or 0),
        "non_sellable_count": int(row.non_sellable_count or 0),
        "quarantined_count": int(row.quarantined_count or 0),
        "blocked_count": int(row.blocked_count or 0),
        "recalled_count": int(row.recalled_count or 0),
        "damaged_or_disposal_attention_count": int(
            row.damaged_or_disposal_attention_count or 0
        ),
    }
