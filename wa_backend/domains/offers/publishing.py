from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.offers.core import (
    OfferError,
    lock_company,
    maker_checker_enabled,
    next_tenant_revision,
)
from domains.offers.models import (
    OfferDefinition,
    OfferVersion,
    OfferVersionProduct,
    OfferVersionScope,
)
from domains.offers.schemas import OfferProductInput, OfferScopeInput
from domains.offers.validation import validate_offer_configuration
from models import Branch, ProductVariant, Shop


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _definition(
    db: AsyncSession,
    company_id: int,
    definition_id: int,
    *,
    lock: bool = False,
) -> OfferDefinition:
    stmt = select(OfferDefinition).where(
        OfferDefinition.company_id == company_id,
        OfferDefinition.id == definition_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise OfferError(
            "OFFER_DEFINITION_NOT_FOUND",
            "Offer definition was not found.",
            status_code=404,
        )
    return row


async def _version(
    db: AsyncSession,
    company_id: int,
    version_id: int,
    *,
    lock: bool = False,
) -> OfferVersion:
    stmt = select(OfferVersion).where(
        OfferVersion.company_id == company_id,
        OfferVersion.id == version_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise OfferError(
            "OFFER_VERSION_NOT_FOUND",
            "Offer version was not found.",
            status_code=404,
        )
    return row


def _expect_version(row: Any, expected_version: int) -> None:
    if int(row.version) != int(expected_version):
        raise OfferError(
            "OFFER_VERSION_CONFLICT",
            "The record changed since it was loaded.",
            context={
                "expected_version": int(expected_version),
                "actual_version": int(row.version),
            },
        )


async def _validate_entity_targets(
    db: AsyncSession,
    company_id: int,
    scopes: list[OfferScopeInput],
    products: list[OfferProductInput],
) -> None:
    # Bounded set validation: at most one query per tenant-owned entity type, never N+1.
    variant_ids = {
        int(item.product_variant_id)
        for item in scopes
        if item.scope_type == "PRODUCT_VARIANT" and item.product_variant_id is not None
    }
    variant_ids.update(int(item.product_variant_id) for item in products)
    customer_ids = {
        int(item.customer_id)
        for item in scopes
        if item.scope_type == "CUSTOMER" and item.customer_id is not None
    }
    branch_ids = {
        int(item.branch_id)
        for item in scopes
        if item.scope_type == "BRANCH" and item.branch_id is not None
    }

    if variant_ids:
        found = set(
            (
                await db.scalars(
                    select(ProductVariant.id).where(
                        ProductVariant.company_id == company_id,
                        ProductVariant.id.in_(variant_ids),
                    )
                )
            ).all()
        )
        if found != variant_ids:
            raise OfferError(
                "OFFER_SCOPE_VARIANT_NOT_FOUND",
                "One or more product variants do not belong to this company.",
                status_code=404,
            )

    if customer_ids:
        found = set(
            (
                await db.scalars(
                    select(Shop.id).where(
                        Shop.company_id == company_id,
                        Shop.id.in_(customer_ids),
                    )
                )
            ).all()
        )
        if found != customer_ids:
            raise OfferError(
                "OFFER_SCOPE_CUSTOMER_NOT_FOUND",
                "One or more customers do not belong to this company.",
                status_code=404,
            )

    if branch_ids:
        found = set(
            (
                await db.scalars(
                    select(Branch.id).where(
                        Branch.company_id == company_id,
                        Branch.id.in_(branch_ids),
                    )
                )
            ).all()
        )
        if found != branch_ids:
            raise OfferError(
                "OFFER_SCOPE_BRANCH_NOT_FOUND",
                "One or more branches do not belong to this company.",
                status_code=404,
            )


async def _children(
    db: AsyncSession,
    company_id: int,
    version_id: int,
) -> tuple[list[OfferVersionScope], list[OfferVersionProduct]]:
    scopes = list(
        (
            await db.scalars(
                select(OfferVersionScope)
                .where(
                    OfferVersionScope.company_id == company_id,
                    OfferVersionScope.offer_version_id == version_id,
                )
                .order_by(OfferVersionScope.id)
            )
        ).all()
    )
    products = list(
        (
            await db.scalars(
                select(OfferVersionProduct)
                .where(
                    OfferVersionProduct.company_id == company_id,
                    OfferVersionProduct.offer_version_id == version_id,
                )
                .order_by(OfferVersionProduct.id)
            )
        ).all()
    )
    return scopes, products


async def _replace_children(
    db: AsyncSession,
    row: OfferVersion,
    scopes: list[OfferScopeInput],
    products: list[OfferProductInput],
) -> None:
    await _validate_entity_targets(db, row.company_id, scopes, products)
    await db.execute(
        delete(OfferVersionScope).where(
            OfferVersionScope.company_id == row.company_id,
            OfferVersionScope.offer_version_id == row.id,
        )
    )
    await db.execute(
        delete(OfferVersionProduct).where(
            OfferVersionProduct.company_id == row.company_id,
            OfferVersionProduct.offer_version_id == row.id,
        )
    )
    # Make delete ordering explicit before reinserting potentially identical keys.
    await db.flush()

    db.add_all(
        [
            OfferVersionScope(
                company_id=row.company_id,
                offer_version_id=row.id,
                scope_type=item.scope_type,
                product_variant_id=item.product_variant_id,
                customer_id=item.customer_id,
                branch_id=item.branch_id,
                channel_code=item.channel_code,
            )
            for item in scopes
        ]
    )
    db.add_all(
        [
            OfferVersionProduct(
                company_id=row.company_id,
                offer_version_id=row.id,
                role=item.role,
                product_variant_id=item.product_variant_id,
            )
            for item in products
        ]
    )
    await db.flush()


async def create_definition(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    code: str,
    name: str,
    description: str | None,
) -> OfferDefinition:
    row = OfferDefinition(
        company_id=company_id,
        code=code,
        name=name,
        description=description,
        created_by=actor_id,
    )
    db.add(row)
    await db.flush()
    return row


async def update_definition(
    db: AsyncSession,
    *,
    company_id: int,
    definition_id: int,
    expected_version: int,
    code: str | None,
    name: str | None,
    description: str | None,
    description_supplied: bool,
) -> OfferDefinition:
    row = await _definition(db, company_id, definition_id, lock=True)
    _expect_version(row, expected_version)
    if code is not None:
        row.code = code
    if name is not None:
        row.name = name
    if description_supplied:
        row.description = description
    row.version += 1
    row.updated_at = _now()
    await db.flush()
    return row


async def delete_definition(
    db: AsyncSession,
    *,
    company_id: int,
    definition_id: int,
    expected_version: int,
) -> None:
    row = await _definition(db, company_id, definition_id, lock=True)
    _expect_version(row, expected_version)
    has_versions = await db.scalar(
        select(OfferVersion.id)
        .where(
            OfferVersion.company_id == company_id,
            OfferVersion.offer_definition_id == definition_id,
        )
        .limit(1)
    )
    if has_versions is not None:
        raise OfferError(
            "OFFER_DEFINITION_IN_USE",
            "An offer definition with version history cannot be deleted.",
        )
    await db.delete(row)
    await db.flush()


async def create_draft_version(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    definition_id: int,
    expected_definition_version: int,
    request_id: UUID,
    offer_type: str,
    payload: dict[str, Any],
    currency_code: str | None,
    priority: int,
    stacking_mode: str,
    effective_from: datetime,
    effective_to: datetime | None,
    scopes: list[OfferScopeInput],
    products: list[OfferProductInput],
) -> OfferVersion:
    # Tenant lock serializes tenant-global revisions and establishes a consistent lock order.
    await lock_company(db, company_id)
    definition = await _definition(db, company_id, definition_id, lock=True)
    _expect_version(definition, expected_definition_version)

    canonical = validate_offer_configuration(
        offer_type=offer_type,
        payload=payload,
        currency_code=currency_code,
        scopes=scopes,
        products=products,
    )
    revision = await next_tenant_revision(db, company_id)
    number = int(
        await db.scalar(
            select(func.max(OfferVersion.definition_version)).where(
                OfferVersion.company_id == company_id,
                OfferVersion.offer_definition_id == definition_id,
            )
        )
        or 0
    ) + 1
    row = OfferVersion(
        company_id=company_id,
        offer_definition_id=definition_id,
        revision=revision,
        definition_version=number,
        status="DRAFT",
        offer_type=offer_type,
        validated_payload=canonical,
        currency_code=currency_code,
        priority=priority,
        stacking_mode=stacking_mode,
        effective_from=effective_from,
        effective_to=effective_to,
        request_id=request_id,
        created_by=actor_id,
    )
    db.add(row)
    await db.flush()
    await _replace_children(db, row, scopes, products)
    return row


async def update_draft_version(
    db: AsyncSession,
    *,
    company_id: int,
    version_id: int,
    expected_version: int,
    offer_type: str,
    payload: dict[str, Any],
    currency_code: str | None,
    priority: int,
    stacking_mode: str,
    effective_from: datetime,
    effective_to: datetime | None,
    scopes: list[OfferScopeInput],
    products: list[OfferProductInput],
) -> OfferVersion:
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "DRAFT":
        raise OfferError(
            "OFFER_VERSION_NOT_DRAFT", "Only a draft offer version can be edited."
        )
    canonical = validate_offer_configuration(
        offer_type=offer_type,
        payload=payload,
        currency_code=currency_code,
        scopes=scopes,
        products=products,
    )
    row.offer_type = offer_type
    row.validated_payload = canonical
    row.currency_code = currency_code
    row.priority = priority
    row.stacking_mode = stacking_mode
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.version += 1
    row.updated_at = _now()
    await db.flush()
    await _replace_children(db, row, scopes, products)
    return row


async def delete_draft_version(
    db: AsyncSession,
    *,
    company_id: int,
    version_id: int,
    expected_version: int,
) -> None:
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "DRAFT":
        raise OfferError(
            "OFFER_VERSION_NOT_DRAFT", "Only a draft offer version can be deleted."
        )
    await db.delete(row)
    await db.flush()


async def validate_version(
    db: AsyncSession,
    *,
    company_id: int,
    version_id: int,
) -> dict[str, Any]:
    row = await _version(db, company_id, version_id)
    scopes, products = await _children(db, company_id, version_id)
    scope_inputs = [
        OfferScopeInput(
            scope_type=item.scope_type,
            product_variant_id=item.product_variant_id,
            customer_id=item.customer_id,
            branch_id=item.branch_id,
            channel_code=item.channel_code,
        )
        for item in scopes
    ]
    product_inputs = [
        OfferProductInput(role=item.role, product_variant_id=item.product_variant_id)
        for item in products
    ]
    canonical = validate_offer_configuration(
        offer_type=row.offer_type,
        payload=dict(row.validated_payload or {}),
        currency_code=row.currency_code,
        scopes=scope_inputs,
        products=product_inputs,
    )
    await _validate_entity_targets(db, company_id, scope_inputs, product_inputs)
    return canonical


async def submit_version(
    db: AsyncSession,
    *,
    company_id: int,
    version_id: int,
    expected_version: int,
) -> OfferVersion:
    if not await maker_checker_enabled(db, company_id):
        raise OfferError(
            "OFFER_APPROVAL_NOT_ENABLED",
            "Maker/checker approval is not enabled for offers.",
        )
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "DRAFT":
        raise OfferError(
            "OFFER_VERSION_STATE_INVALID", "Only a draft offer version can be submitted."
        )
    await validate_version(db, company_id=company_id, version_id=version_id)
    row.status = "PENDING_APPROVAL"
    row.version += 1
    row.updated_at = _now()
    await db.flush()
    return row


async def _publish_locked(
    db: AsyncSession,
    *,
    row: OfferVersion,
    actor_id: int,
) -> OfferVersion:
    await validate_version(db, company_id=row.company_id, version_id=row.id)
    prior = await db.scalar(
        select(OfferVersion)
        .where(
            OfferVersion.company_id == row.company_id,
            OfferVersion.offer_definition_id == row.offer_definition_id,
            OfferVersion.status == "PUBLISHED",
            OfferVersion.id != row.id,
        )
        .with_for_update()
    )
    if prior is not None:
        prior.status = "SUPERSEDED"
        prior.version += 1
        prior.updated_at = _now()
        # Avoid transient violation of the partial one-PUBLISHED unique index.
        await db.flush()

    now = _now()
    row.status = "PUBLISHED"
    row.approved_by = actor_id
    row.approved_at = now
    row.published_at = now
    row.version += 1
    row.updated_at = now
    await db.flush()
    return row


async def publish_version(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    version_id: int,
    expected_version: int,
) -> OfferVersion:
    if await maker_checker_enabled(db, company_id):
        raise OfferError(
            "OFFER_APPROVAL_REQUIRED",
            "This company requires offer approval before publication.",
        )
    await lock_company(db, company_id)
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "DRAFT":
        raise OfferError(
            "OFFER_VERSION_STATE_INVALID",
            "Only a draft offer version can be published directly.",
        )
    return await _publish_locked(db, row=row, actor_id=actor_id)


async def approve_version(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    version_id: int,
    expected_version: int,
) -> OfferVersion:
    if not await maker_checker_enabled(db, company_id):
        raise OfferError(
            "OFFER_APPROVAL_NOT_ENABLED",
            "Maker/checker approval is not enabled for offers.",
        )
    await lock_company(db, company_id)
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "PENDING_APPROVAL":
        raise OfferError(
            "OFFER_VERSION_STATE_INVALID",
            "Only a pending offer version can be approved.",
        )
    if int(row.created_by) == int(actor_id):
        raise OfferError(
            "OFFER_SEPARATION_OF_DUTIES",
            "The creator cannot approve their own offer version.",
        )
    return await _publish_locked(db, row=row, actor_id=actor_id)


async def cancel_version(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    version_id: int,
    expected_version: int,
    reason: str,
) -> OfferVersion:
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status not in {"DRAFT", "PENDING_APPROVAL"}:
        raise OfferError(
            "OFFER_VERSION_STATE_INVALID",
            "Only draft or pending offer versions can be cancelled.",
        )
    now = _now()
    row.status = "CANCELLED"
    row.cancelled_by = actor_id
    row.cancelled_at = now
    row.cancel_reason = reason.strip()
    row.version += 1
    row.updated_at = now
    await db.flush()
    return row
