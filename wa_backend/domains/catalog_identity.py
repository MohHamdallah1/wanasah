"""Catalog-owned identity commands that remain safe after publication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import Product, ProductBatch, ProductVariant
from product_lifecycle import (
    acquire_product_lifecycle_guards,
    record_domain_event,
    variant_snapshot,
)


class CatalogIdentityError(ValueError):
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
class ProductNameMutationResult:
    product_variant_id: int
    name: str
    version: int
    changed: bool


@dataclass(frozen=True)
class ProductFamilyMutationResult:
    product_variant_id: int
    family_id: int
    family_name: str
    version: int
    changed: bool


def normalize_product_name(value: object) -> str:
    if not isinstance(value, str):
        raise CatalogIdentityError(
            "PRODUCT_NAME_INVALID",
            "Product name must be text.",
            status_code=422,
        )
    clean = value.strip()
    if not clean or "\x00" in clean or len(clean) > 200:
        raise CatalogIdentityError(
            "PRODUCT_NAME_INVALID",
            "Product name is invalid.",
            status_code=422,
        )
    return clean


async def rename_published_product(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    product_variant_id: int,
    expected_version: int,
    name: str,
) -> ProductNameMutationResult:
    clean_name = normalize_product_name(name)

    row = await db.scalar(
        select(ProductVariant)
        .where(
            ProductVariant.company_id == int(company_id),
            ProductVariant.id == int(product_variant_id),
        )
        .with_for_update()
    )
    if row is None:
        raise CatalogIdentityError(
            "VARIANT_NOT_FOUND",
            "Product was not found.",
            status_code=404,
        )
    if int(row.version) != int(expected_version):
        raise CatalogIdentityError(
            "VARIANT_VERSION_CONFLICT",
            "Product changed. Refresh and retry.",
            context={
                "product_variant_id": int(product_variant_id),
                "current_version": int(row.version),
            },
        )
    if str(row.lifecycle_status) not in {"ACTIVE", "RETIRING"}:
        raise CatalogIdentityError(
            "PRODUCT_NAME_EDIT_LIFECYCLE_BLOCKED",
            "Published product names can only be edited while active or retiring.",
            context={
                "product_variant_id": int(product_variant_id),
                "lifecycle_status": str(row.lifecycle_status),
            },
        )

    changed = str(row.name) != clean_name
    if not changed:
        return ProductNameMutationResult(
            product_variant_id=int(row.id),
            name=str(row.name),
            version=int(row.version),
            changed=False,
        )

    before = variant_snapshot(row)
    row.name = clean_name
    row.version = int(row.version) + 1
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()

    after = variant_snapshot(row)
    record_domain_event(
        db,
        company_id=int(company_id),
        actor_id=int(actor_id),
        request_id=request_id,
        event_type="ProductVariantRenamed",
        entity_type="ProductVariant",
        entity_id=int(row.id),
        reason="Product display name changed.",
        before=before,
        after=after,
    )

    return ProductNameMutationResult(
        product_variant_id=int(row.id),
        name=str(row.name),
        version=int(row.version),
        changed=True,
    )

async def reassign_published_product_family(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    request_id: UUID,
    product_variant_id: int,
    expected_version: int,
    family_id: int,
) -> ProductFamilyMutationResult:
    await acquire_product_lifecycle_guards(
        db,
        int(company_id),
        [int(product_variant_id)],
        exclusive=True,
    )

    row = await db.scalar(
        select(ProductVariant)
        .where(
            ProductVariant.company_id == int(company_id),
            ProductVariant.id == int(product_variant_id),
        )
        .with_for_update()
    )
    if row is None:
        raise CatalogIdentityError(
            "VARIANT_NOT_FOUND",
            "Product was not found.",
            status_code=404,
        )
    if int(row.version) != int(expected_version):
        raise CatalogIdentityError(
            "VARIANT_VERSION_CONFLICT",
            "Product changed. Refresh and retry.",
            context={
                "product_variant_id": int(product_variant_id),
                "current_version": int(row.version),
            },
        )
    if str(row.lifecycle_status) not in {"ACTIVE", "RETIRING"}:
        raise CatalogIdentityError(
            "PRODUCT_FAMILY_REASSIGN_LIFECYCLE_BLOCKED",
            (
                "Published product family can only be changed while "
                "active or retiring."
            ),
            context={
                "product_variant_id": int(product_variant_id),
                "lifecycle_status": str(row.lifecycle_status),
            },
        )

    target_family = await db.scalar(
        select(Product)
        .where(
            Product.company_id == int(company_id),
            Product.id == int(family_id),
        )
        .with_for_update()
    )
    if target_family is None:
        raise CatalogIdentityError(
            "PRODUCT_FAMILY_REASSIGN_TARGET_NOT_FOUND",
            "Target product family was not found.",
            status_code=404,
            context={
                "family_id": int(family_id),
            },
        )

    if int(row.product_id) == int(target_family.id):
        return ProductFamilyMutationResult(
            product_variant_id=int(row.id),
            family_id=int(target_family.id),
            family_name=str(target_family.name),
            version=int(row.version),
            changed=False,
        )

    existing_batch_id = await db.scalar(
        select(ProductBatch.id)
        .where(
            ProductBatch.company_id == int(company_id),
            ProductBatch.product_variant_id == int(product_variant_id),
        )
        .limit(1)
    )
    if existing_batch_id is not None:
        raise CatalogIdentityError(
            "PRODUCT_FAMILY_REASSIGN_HISTORY_LOCKED",
            (
                "Product family cannot be changed after batch history "
                "exists."
            ),
            context={
                "product_variant_id": int(product_variant_id),
                "sample_batch_id": int(existing_batch_id),
            },
        )

    before = variant_snapshot(row)
    row.product_id = int(target_family.id)
    row.version = int(row.version) + 1
    row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.flush()

    after = variant_snapshot(row)
    record_domain_event(
        db,
        company_id=int(company_id),
        actor_id=int(actor_id),
        request_id=request_id,
        event_type="ProductVariantFamilyReassigned",
        entity_type="ProductVariant",
        entity_id=int(row.id),
        reason="Product family changed before operational history existed.",
        before=before,
        after=after,
    )

    return ProductFamilyMutationResult(
        product_variant_id=int(row.id),
        family_id=int(target_family.id),
        family_name=str(target_family.name),
        version=int(row.version),
        changed=True,
    )

