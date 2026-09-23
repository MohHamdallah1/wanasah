"""Tenant-scoped product tracking authority.

This module owns product lot/expiry tracking defaults, normalization, the
reserved internal identity used for non-lot-tracked inventory, and the guard
that prevents unsafe tracking-mode changes after batch history exists.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Final
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import ProductBatch, ProductVariant, SystemSetting
from product_lifecycle import (
    acquire_product_lifecycle_guards,
    record_domain_event,
)


TRACKING_MODES: Final[frozenset[str]] = frozenset(
    {"NONE", "OPTIONAL", "REQUIRED"}
)

PRODUCT_DEFAULT_LOT_CONTROL_MODE_KEY: Final[str] = (
    "product.default_lot_control_mode"
)
PRODUCT_DEFAULT_EXPIRY_CONTROL_MODE_KEY: Final[str] = (
    "product.default_expiry_control_mode"
)

# Backward-compatible fail-closed platform fallback. A tenant may override
# either value explicitly through its own SystemSetting rows.
PLATFORM_DEFAULT_LOT_CONTROL_MODE: Final[str] = "REQUIRED"
PLATFORM_DEFAULT_EXPIRY_CONTROL_MODE: Final[str] = "REQUIRED"

# This namespace is reserved for system-generated ProductBatch identities.
# User-entered lot numbers must never be allowed to collide with it.
INTERNAL_NO_LOT_PREFIX: Final[str] = "__WANASAH_NOLOT__:"


class ProductTrackingError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 409,
        context: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.context = dict(context or {})


@dataclass(frozen=True)
class ProductTrackingDefaults:
    lot_control_mode: str
    expiry_control_mode: str


@dataclass(frozen=True)
class ProductTrackingDefaultsState:
    lot_control_mode: str
    expiry_control_mode: str
    lot_control_source: str
    expiry_control_source: str


@dataclass(frozen=True)
class ProductTrackingMutationResult:
    product_variant_id: int
    version: int
    lot_control_mode: str
    expiry_control_mode: str
    changed: bool
    before_snapshot: dict[str, object]
    after_snapshot: dict[str, object]


def _positive_id(value: object, *, field_name: str) -> int:
    if type(value) is not int or value <= 0:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_ID_INVALID",
            f"{field_name} must be a positive integer.",
            status_code=422,
            context={"field": field_name},
        )
    return value


def _optional_plain_date(
    value: date | None,
    *,
    field_name: str,
) -> date | None:
    if value is None:
        return None
    if type(value) is not date:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_DATE_INVALID",
            f"{field_name} must be a date.",
            status_code=422,
            context={"field": field_name},
        )
    return value


def normalize_tracking_mode(
    value: object,
    *,
    field_name: str,
) -> str:
    normalized = str(value or "").strip().upper()
    if normalized not in TRACKING_MODES:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_MODE_INVALID",
            f"{field_name} must be NONE, OPTIONAL, or REQUIRED.",
            status_code=422,
            context={
                "field": field_name,
                "value": normalized or None,
            },
        )
    return normalized


async def load_company_product_tracking_defaults_state(
    db: AsyncSession,
    *,
    company_id: int,
) -> ProductTrackingDefaultsState:
    company_id = _positive_id(
        company_id,
        field_name="company_id",
    )

    rows = (
        await db.execute(
            select(
                SystemSetting.setting_key,
                SystemSetting.setting_value,
            ).where(
                SystemSetting.company_id == company_id,
                SystemSetting.setting_key.in_(
                    (
                        PRODUCT_DEFAULT_LOT_CONTROL_MODE_KEY,
                        PRODUCT_DEFAULT_EXPIRY_CONTROL_MODE_KEY,
                    )
                ),
            )
        )
    ).all()
    values = {
        str(row.setting_key): str(row.setting_value)
        for row in rows
    }

    # Invalid stored tenant configuration must fail closed. Silently falling
    # back would hide corrupt operational policy.
    lot_is_company = (
        PRODUCT_DEFAULT_LOT_CONTROL_MODE_KEY in values
    )
    expiry_is_company = (
        PRODUCT_DEFAULT_EXPIRY_CONTROL_MODE_KEY in values
    )
    lot_mode = normalize_tracking_mode(
        values.get(
            PRODUCT_DEFAULT_LOT_CONTROL_MODE_KEY,
            PLATFORM_DEFAULT_LOT_CONTROL_MODE,
        ),
        field_name="default_lot_control_mode",
    )
    expiry_mode = normalize_tracking_mode(
        values.get(
            PRODUCT_DEFAULT_EXPIRY_CONTROL_MODE_KEY,
            PLATFORM_DEFAULT_EXPIRY_CONTROL_MODE,
        ),
        field_name="default_expiry_control_mode",
    )
    return ProductTrackingDefaultsState(
        lot_control_mode=lot_mode,
        expiry_control_mode=expiry_mode,
        lot_control_source=(
            "COMPANY"
            if lot_is_company
            else "PLATFORM_FALLBACK"
        ),
        expiry_control_source=(
            "COMPANY"
            if expiry_is_company
            else "PLATFORM_FALLBACK"
        ),
    )


async def load_company_product_tracking_defaults(
    db: AsyncSession,
    *,
    company_id: int,
) -> ProductTrackingDefaults:
    state = await load_company_product_tracking_defaults_state(
        db,
        company_id=company_id,
    )
    return ProductTrackingDefaults(
        lot_control_mode=state.lot_control_mode,
        expiry_control_mode=state.expiry_control_mode,
    )


async def resolve_product_tracking_modes(
    db: AsyncSession,
    *,
    company_id: int,
    lot_control_mode: str | None,
    expiry_control_mode: str | None,
) -> ProductTrackingDefaults:
    defaults = await load_company_product_tracking_defaults(
        db,
        company_id=company_id,
    )
    return ProductTrackingDefaults(
        lot_control_mode=(
            normalize_tracking_mode(
                lot_control_mode,
                field_name="lot_control_mode",
            )
            if lot_control_mode is not None
            else defaults.lot_control_mode
        ),
        expiry_control_mode=(
            normalize_tracking_mode(
                expiry_control_mode,
                field_name="expiry_control_mode",
            )
            if expiry_control_mode is not None
            else defaults.expiry_control_mode
        ),
    )


async def save_company_product_tracking_defaults(
    db: AsyncSession,
    *,
    company_id: int,
    lot_control_mode: str,
    expiry_control_mode: str,
) -> ProductTrackingDefaults:
    company_id = _positive_id(
        company_id,
        field_name="company_id",
    )
    resolved = ProductTrackingDefaults(
        lot_control_mode=normalize_tracking_mode(
            lot_control_mode,
            field_name="default_lot_control_mode",
        ),
        expiry_control_mode=normalize_tracking_mode(
            expiry_control_mode,
            field_name="default_expiry_control_mode",
        ),
    )

    values = (
        (
            PRODUCT_DEFAULT_LOT_CONTROL_MODE_KEY,
            resolved.lot_control_mode,
            "Default lot tracking mode for newly created product variants.",
        ),
        (
            PRODUCT_DEFAULT_EXPIRY_CONTROL_MODE_KEY,
            resolved.expiry_control_mode,
            "Default expiry tracking mode for newly created product variants.",
        ),
    )
    for key, value, description in values:
        await db.execute(
            pg_insert(SystemSetting)
            .values(
                company_id=company_id,
                setting_key=key,
                setting_value=value,
                description=description,
            )
            .on_conflict_do_update(
                index_elements=["company_id", "setting_key"],
                set_={
                    "setting_value": value,
                    "description": description,
                },
            )
        )

    return resolved


async def save_company_product_tracking_defaults_serialized(
    db: AsyncSession,
    *,
    company_id: int,
    lot_control_mode: str,
    expiry_control_mode: str,
) -> ProductTrackingDefaultsState:
    company_id = _positive_id(
        company_id,
        field_name="company_id",
    )
    await db.execute(
        select(
            func.pg_advisory_xact_lock(
                company_id,
                func.hashtext(
                    "product-tracking-defaults"
                ),
            )
        )
    )
    resolved = await save_company_product_tracking_defaults(
        db,
        company_id=company_id,
        lot_control_mode=lot_control_mode,
        expiry_control_mode=expiry_control_mode,
    )
    return ProductTrackingDefaultsState(
        lot_control_mode=resolved.lot_control_mode,
        expiry_control_mode=resolved.expiry_control_mode,
        lot_control_source="COMPANY",
        expiry_control_source="COMPANY",
    )


def is_reserved_internal_batch_number(value: object) -> bool:
    return str(value or "").strip().upper().startswith(
        INTERNAL_NO_LOT_PREFIX
    )


def build_internal_no_lot_batch_number(
    *,
    production_date: date | None,
    expiry_date: date | None,
) -> str:
    """Build deterministic hidden identity for a non-lot-tracked batch.

    ProductBatch remains the inventory identity required by InventoryBalance.
    For lot_control_mode=NONE the user must not invent a lot number, so the
    system groups stock by the metadata that still affects batch semantics.
    The ProductBatch uniqueness constraint is already variant-scoped.
    """

    production_date = _optional_plain_date(
        production_date,
        field_name="production_date",
    )
    expiry_date = _optional_plain_date(
        expiry_date,
        field_name="expiry_date",
    )

    production_token = (
        production_date.isoformat().replace("-", "")
        if production_date is not None
        else "-"
    )
    expiry_token = (
        expiry_date.isoformat().replace("-", "")
        if expiry_date is not None
        else "-"
    )
    value = (
        f"{INTERNAL_NO_LOT_PREFIX}"
        f"P{production_token}:E{expiry_token}"
    )
    if len(value) > 100:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_INTERNAL_BATCH_INVALID",
            "Internal non-lot batch identity exceeds the storage contract.",
            status_code=500,
        )
    return value


async def assert_tracking_mode_change_allowed(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    current_lot_control_mode: str,
    current_expiry_control_mode: str,
    requested_lot_control_mode: str,
    requested_expiry_control_mode: str,
) -> None:
    company_id = _positive_id(
        company_id,
        field_name="company_id",
    )
    product_variant_id = _positive_id(
        product_variant_id,
        field_name="product_variant_id",
    )
    current_lot = normalize_tracking_mode(
        current_lot_control_mode,
        field_name="current_lot_control_mode",
    )
    current_expiry = normalize_tracking_mode(
        current_expiry_control_mode,
        field_name="current_expiry_control_mode",
    )
    requested_lot = normalize_tracking_mode(
        requested_lot_control_mode,
        field_name="lot_control_mode",
    )
    requested_expiry = normalize_tracking_mode(
        requested_expiry_control_mode,
        field_name="expiry_control_mode",
    )

    if (
        current_lot == requested_lot
        and current_expiry == requested_expiry
    ):
        return

    existing_batch_id = await db.scalar(
        select(ProductBatch.id)
        .where(
            ProductBatch.company_id == company_id,
            ProductBatch.product_variant_id
            == product_variant_id,
        )
        .limit(1)
    )
    if existing_batch_id is not None:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_LOCKED",
            (
                "Tracking modes cannot be changed through the normal edit "
                "workflow after batch history exists."
            ),
            context={
                "product_variant_id": product_variant_id,
            },
        )


def _tracking_snapshot(
    variant: ProductVariant,
) -> dict[str, object]:
    return {
        "product_variant_id": int(variant.id),
        "version": int(variant.version),
        "lot_control_mode": str(
            variant.lot_control_mode
        ),
        "expiry_control_mode": str(
            variant.expiry_control_mode
        ),
    }


async def update_product_tracking_modes(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    product_variant_id: int,
    expected_version: int,
    lot_control_mode: str,
    expiry_control_mode: str,
) -> ProductTrackingMutationResult:
    company_id = _positive_id(
        company_id,
        field_name="company_id",
    )
    actor_id = _positive_id(
        actor_id,
        field_name="actor_id",
    )
    product_variant_id = _positive_id(
        product_variant_id,
        field_name="product_variant_id",
    )
    expected_version = _positive_id(
        expected_version,
        field_name="expected_version",
    )
    requested_lot = normalize_tracking_mode(
        lot_control_mode,
        field_name="lot_control_mode",
    )
    requested_expiry = normalize_tracking_mode(
        expiry_control_mode,
        field_name="expiry_control_mode",
    )

    # Inbound acquires this same guard shared. Taking it exclusive closes the
    # race between "no batch history yet" and a concurrent first receipt.
    await acquire_product_lifecycle_guards(
        db,
        company_id,
        [product_variant_id],
        exclusive=True,
    )

    variant = await db.scalar(
        select(ProductVariant)
        .where(
            ProductVariant.company_id == company_id,
            ProductVariant.id == product_variant_id,
        )
        .with_for_update()
    )
    if variant is None:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_VARIANT_NOT_FOUND",
            "Product was not found.",
            status_code=404,
        )
    if int(variant.version) != expected_version:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_VERSION_CONFLICT",
            "Product changed. Refresh and retry.",
            context={
                "product_variant_id": product_variant_id,
                "current_version": int(variant.version),
            },
        )
    if str(variant.lifecycle_status) not in {
        "DRAFT",
        "ACTIVE",
    }:
        raise ProductTrackingError(
            "PRODUCT_TRACKING_LIFECYCLE_BLOCKED",
            (
                "Tracking modes cannot be edited through the normal workflow "
                "for a retiring or archived product."
            ),
            context={
                "product_variant_id": product_variant_id,
                "lifecycle_status": str(
                    variant.lifecycle_status
                ),
            },
        )

    before = _tracking_snapshot(variant)
    await assert_tracking_mode_change_allowed(
        db,
        company_id=company_id,
        product_variant_id=product_variant_id,
        current_lot_control_mode=str(
            variant.lot_control_mode
        ),
        current_expiry_control_mode=str(
            variant.expiry_control_mode
        ),
        requested_lot_control_mode=requested_lot,
        requested_expiry_control_mode=requested_expiry,
    )

    changed = (
        str(variant.lot_control_mode) != requested_lot
        or str(variant.expiry_control_mode)
        != requested_expiry
    )
    if changed:
        variant.lot_control_mode = requested_lot
        variant.expiry_control_mode = requested_expiry
        variant.version = int(variant.version) + 1
        await db.flush()

        after = _tracking_snapshot(variant)
        record_domain_event(
            db,
            company_id=company_id,
            actor_id=actor_id,
            request_id=request_id,
            event_type="PRODUCT_TRACKING_UPDATED",
            entity_type="ProductVariant",
            entity_id=product_variant_id,
            reason="Product inventory tracking modes updated.",
            before=before,
            after=after,
        )

    after = _tracking_snapshot(variant)
    return ProductTrackingMutationResult(
        product_variant_id=product_variant_id,
        version=int(variant.version),
        lot_control_mode=str(
            variant.lot_control_mode
        ),
        expiry_control_mode=str(
            variant.expiry_control_mode
        ),
        changed=changed,
        before_snapshot=before,
        after_snapshot=after,
    )
