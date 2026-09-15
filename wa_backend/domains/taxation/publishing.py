from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.taxation.core import (
    TAX_JURISDICTION_MAX_DEPTH,
    TaxError,
    jurisdiction_chain,
    lock_company,
    maker_checker_enabled,
    next_tenant_revision,
)
from domains.taxation.models import (
    TaxJurisdiction,
    TaxRuleComponent,
    TaxRuleScope,
    TaxRuleSet,
    TaxRuleSetVersion,
)
from domains.taxation.schemas import (
    TaxComponentInput,
    TaxScopeInput,
    validate_jurisdiction_shape,
)
from domains.taxation.validation import validate_tax_configuration
from models import ProductVariant, Shop


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _jurisdiction(
    db: AsyncSession,
    company_id: int,
    jurisdiction_id: int,
    *,
    lock: bool = False,
) -> TaxJurisdiction:
    stmt = select(TaxJurisdiction).where(
        TaxJurisdiction.company_id == company_id,
        TaxJurisdiction.id == jurisdiction_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise TaxError(
            "TAX_JURISDICTION_NOT_FOUND",
            "Tax jurisdiction was not found.",
            status_code=404,
        )
    return row


async def _rule_set(
    db: AsyncSession,
    company_id: int,
    rule_set_id: int,
    *,
    lock: bool = False,
) -> TaxRuleSet:
    stmt = select(TaxRuleSet).where(
        TaxRuleSet.company_id == company_id,
        TaxRuleSet.id == rule_set_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise TaxError(
            "TAX_RULE_SET_NOT_FOUND",
            "Tax rule set was not found.",
            status_code=404,
        )
    return row


async def _version(
    db: AsyncSession,
    company_id: int,
    version_id: int,
    *,
    lock: bool = False,
) -> TaxRuleSetVersion:
    stmt = select(TaxRuleSetVersion).where(
        TaxRuleSetVersion.company_id == company_id,
        TaxRuleSetVersion.id == version_id,
    )
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise TaxError(
            "TAX_VERSION_NOT_FOUND",
            "Tax version was not found.",
            status_code=404,
        )
    return row


def _expect_version(row: Any, expected_version: int) -> None:
    if int(row.version) != int(expected_version):
        raise TaxError(
            "TAX_VERSION_CONFLICT",
            "The record changed since it was loaded.",
            context={
                "expected_version": int(expected_version),
                "actual_version": int(row.version),
            },
        )


async def _validate_parent(
    db: AsyncSession,
    company_id: int,
    parent_id: int | None,
    *,
    country_code: str,
) -> None:
    if parent_id is None:
        return
    parent = await _jurisdiction(db, company_id, parent_id)
    if not parent.is_active:
        raise TaxError(
            "TAX_JURISDICTION_PARENT_INACTIVE",
            "A new or moved jurisdiction requires an active parent.",
        )
    if parent.country_code != country_code:
        raise TaxError(
            "TAX_JURISDICTION_COUNTRY_MISMATCH",
            "Parent and child jurisdictions must belong to the same country.",
            status_code=422,
        )


async def _validate_prospective_parent_chain(
    db: AsyncSession,
    *,
    company_id: int,
    parent_id: int | None,
    jurisdiction_id: int | None = None,
) -> set[int]:
    if parent_id is None:
        return set()

    distances = await jurisdiction_chain(
        db,
        company_id=company_id,
        jurisdiction_id=parent_id,
    )
    if (
        jurisdiction_id is not None
        and int(jurisdiction_id) in distances
    ):
        raise TaxError(
            "TAX_JURISDICTION_CYCLE",
            "A jurisdiction cannot be moved below its own descendant.",
            status_code=422,
        )

    if (
        max(distances.values(), default=-1)
        >= TAX_JURISDICTION_MAX_DEPTH - 1
    ):
        raise TaxError(
            "TAX_JURISDICTION_DEPTH_EXCEEDED",
            "The requested parent would exceed the supported jurisdiction depth.",
            status_code=422,
            context={
                "max_depth": TAX_JURISDICTION_MAX_DEPTH,
            },
        )
    return set(distances)


async def _ensure_topology_move_safe(
    db: AsyncSession,
    *,
    company_id: int,
    old_ancestors: set[int],
    new_ancestors: set[int],
) -> None:
    affected = sorted(
        old_ancestors ^ new_ancestors
    )
    if not affected:
        return

    referenced = await db.scalar(
        select(TaxRuleScope.id)
        .join(
            TaxRuleSetVersion,
            (
                TaxRuleSetVersion.company_id
                == TaxRuleScope.company_id
            )
            & (
                TaxRuleSetVersion.id
                == TaxRuleScope.tax_rule_set_version_id
            ),
        )
        .where(
            TaxRuleScope.company_id
            == int(company_id),
            TaxRuleScope.scope_type
            == "JURISDICTION",
            TaxRuleScope.jurisdiction_id.in_(
                affected
            ),
            TaxRuleSetVersion.status.in_(
                (
                    "PENDING_APPROVAL",
                    "PUBLISHED",
                    "SUPERSEDED",
                )
            ),
        )
        .limit(1)
    )
    if referenced is not None:
        raise TaxError(
            "TAX_JURISDICTION_TOPOLOGY_IN_USE",
            "Moving this jurisdiction would change immutable tax-version applicability.",
        )


async def create_jurisdiction(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    code: str,
    name: str,
    jurisdiction_type: str,
    country_code: str,
    subdivision_code: str | None,
    locality_code: str | None,
    parent_jurisdiction_id: int | None,
) -> TaxJurisdiction:
    await lock_company(db, company_id)
    try:
        validate_jurisdiction_shape(
            jurisdiction_type,
            parent_jurisdiction_id,
            subdivision_code,
            locality_code,
        )
    except ValueError as exc:
        raise TaxError(
            "TAX_JURISDICTION_SHAPE_INVALID",
            str(exc),
            status_code=422,
        ) from exc
    await _validate_parent(
        db,
        company_id,
        parent_jurisdiction_id,
        country_code=country_code,
    )
    await _validate_prospective_parent_chain(
        db,
        company_id=company_id,
        parent_id=parent_jurisdiction_id,
    )
    row = TaxJurisdiction(
        company_id=company_id,
        code=code,
        name=name,
        jurisdiction_type=jurisdiction_type,
        country_code=country_code,
        subdivision_code=subdivision_code,
        locality_code=locality_code,
        parent_jurisdiction_id=parent_jurisdiction_id,
        created_by=actor_id,
    )
    db.add(row)
    await db.flush()
    return row


async def update_jurisdiction(
    db: AsyncSession,
    *,
    company_id: int,
    jurisdiction_id: int,
    expected_version: int,
    values: dict[str, Any],
) -> TaxJurisdiction:
    await lock_company(db, company_id)
    row = await _jurisdiction(db, company_id, jurisdiction_id, lock=True)
    _expect_version(row, expected_version)

    structural = {
        "code",
        "jurisdiction_type",
        "country_code",
        "subdivision_code",
        "locality_code",
        "parent_jurisdiction_id",
    }
    if structural & values.keys():
        referenced = await db.scalar(
            select(TaxRuleScope.id)
            .where(
                TaxRuleScope.company_id == company_id,
                TaxRuleScope.jurisdiction_id == jurisdiction_id,
            )
            .limit(1)
        )
        if referenced is not None:
            raise TaxError(
                "TAX_JURISDICTION_IN_USE",
                "Structural jurisdiction identity cannot change after a tax version references it.",
            )

    merged_type = values.get("jurisdiction_type", row.jurisdiction_type)
    merged_country = values.get("country_code", row.country_code)
    merged_subdivision = values.get("subdivision_code", row.subdivision_code)
    merged_locality = values.get("locality_code", row.locality_code)
    merged_parent = (
        values["parent_jurisdiction_id"]
        if "parent_jurisdiction_id" in values
        else row.parent_jurisdiction_id
    )
    try:
        validate_jurisdiction_shape(
            merged_type,
            merged_parent,
            merged_subdivision,
            merged_locality,
        )
    except ValueError as exc:
        raise TaxError(
            "TAX_JURISDICTION_SHAPE_INVALID",
            str(exc),
            status_code=422,
        ) from exc

    if merged_parent == jurisdiction_id:
        raise TaxError(
            "TAX_JURISDICTION_CYCLE",
            "A jurisdiction cannot be its own parent.",
            status_code=422,
        )
    await _validate_parent(
        db,
        company_id,
        merged_parent,
        country_code=merged_country,
    )

    new_ancestors = (
        await _validate_prospective_parent_chain(
            db,
            company_id=company_id,
            parent_id=merged_parent,
            jurisdiction_id=jurisdiction_id,
        )
    )
    if (
        merged_parent
        != row.parent_jurisdiction_id
    ):
        old_ancestors = (
            await _validate_prospective_parent_chain(
                db,
                company_id=company_id,
                parent_id=row.parent_jurisdiction_id,
                jurisdiction_id=jurisdiction_id,
            )
        )
        await _ensure_topology_move_safe(
            db,
            company_id=company_id,
            old_ancestors=old_ancestors,
            new_ancestors=new_ancestors,
        )

    if merged_country != row.country_code:
        mismatched_child = await db.scalar(
            select(TaxJurisdiction.id)
            .where(
                TaxJurisdiction.company_id
                == company_id,
                TaxJurisdiction.parent_jurisdiction_id
                == jurisdiction_id,
                TaxJurisdiction.country_code
                != merged_country,
            )
            .limit(1)
        )
        if mismatched_child is not None:
            raise TaxError(
                "TAX_JURISDICTION_CHILD_COUNTRY_MISMATCH",
                "Country cannot change while child jurisdictions belong to another country.",
                status_code=422,
            )

    if values.get("is_active") is False:
        active_child = await db.scalar(
            select(TaxJurisdiction.id)
            .where(
                TaxJurisdiction.company_id == company_id,
                TaxJurisdiction.parent_jurisdiction_id == jurisdiction_id,
                TaxJurisdiction.is_active.is_(True),
            )
            .limit(1)
        )
        if active_child is not None:
            raise TaxError(
                "TAX_JURISDICTION_HAS_ACTIVE_CHILDREN",
                "Deactivate child jurisdictions before deactivating their parent.",
            )
        published_reference = await db.scalar(
            select(TaxRuleScope.id)
            .join(
                TaxRuleSetVersion,
                (TaxRuleSetVersion.company_id == TaxRuleScope.company_id)
                & (TaxRuleSetVersion.id == TaxRuleScope.tax_rule_set_version_id),
            )
            .where(
                TaxRuleScope.company_id == company_id,
                TaxRuleScope.jurisdiction_id == jurisdiction_id,
                TaxRuleSetVersion.status == "PUBLISHED",
            )
            .limit(1)
        )
        if published_reference is not None:
            raise TaxError(
                "TAX_JURISDICTION_PUBLISHED_REFERENCE",
                "A jurisdiction used by a currently published tax version cannot be deactivated.",
            )

    for field, value in values.items():
        setattr(row, field, value)
    row.version += 1
    row.updated_at = _now()
    await db.flush()
    return row


async def delete_jurisdiction(
    db: AsyncSession,
    *,
    company_id: int,
    jurisdiction_id: int,
    expected_version: int,
) -> None:
    await lock_company(db, company_id)
    row = await _jurisdiction(db, company_id, jurisdiction_id, lock=True)
    _expect_version(row, expected_version)
    child = await db.scalar(
        select(TaxJurisdiction.id)
        .where(
            TaxJurisdiction.company_id == company_id,
            TaxJurisdiction.parent_jurisdiction_id == jurisdiction_id,
        )
        .limit(1)
    )
    referenced = await db.scalar(
        select(TaxRuleScope.id)
        .where(
            TaxRuleScope.company_id == company_id,
            TaxRuleScope.jurisdiction_id == jurisdiction_id,
        )
        .limit(1)
    )
    if child is not None or referenced is not None:
        raise TaxError(
            "TAX_JURISDICTION_IN_USE",
            "Jurisdiction cannot be deleted while it has children or tax references.",
        )
    await db.delete(row)
    await db.flush()


async def create_rule_set(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    code: str,
    name: str,
    description: str | None,
) -> TaxRuleSet:
    row = TaxRuleSet(
        company_id=company_id,
        code=code,
        name=name,
        description=description,
        created_by=actor_id,
    )
    db.add(row)
    await db.flush()
    return row


async def update_rule_set(
    db: AsyncSession,
    *,
    company_id: int,
    rule_set_id: int,
    expected_version: int,
    values: dict[str, Any],
) -> TaxRuleSet:
    row = await _rule_set(db, company_id, rule_set_id, lock=True)
    _expect_version(row, expected_version)
    for field, value in values.items():
        setattr(row, field, value)
    row.version += 1
    row.updated_at = _now()
    await db.flush()
    return row


async def delete_rule_set(
    db: AsyncSession,
    *,
    company_id: int,
    rule_set_id: int,
    expected_version: int,
) -> None:
    row = await _rule_set(db, company_id, rule_set_id, lock=True)
    _expect_version(row, expected_version)
    exists = await db.scalar(
        select(TaxRuleSetVersion.id)
        .where(
            TaxRuleSetVersion.company_id == company_id,
            TaxRuleSetVersion.tax_rule_set_id == rule_set_id,
        )
        .limit(1)
    )
    if exists is not None:
        raise TaxError(
            "TAX_RULE_SET_IN_USE",
            "A tax rule set with version history cannot be deleted.",
        )
    await db.delete(row)
    await db.flush()


async def _validate_scope_targets(
    db: AsyncSession,
    company_id: int,
    scopes: list[TaxScopeInput],
    *,
    require_active_jurisdiction: bool = True,
) -> None:
    jurisdiction_ids = {
        int(item.jurisdiction_id)
        for item in scopes
        if item.scope_type == "JURISDICTION" and item.jurisdiction_id is not None
    }
    variant_ids = {
        int(item.product_variant_id)
        for item in scopes
        if item.scope_type == "PRODUCT_VARIANT" and item.product_variant_id is not None
    }
    customer_ids = {
        int(item.customer_id)
        for item in scopes
        if item.scope_type == "CUSTOMER" and item.customer_id is not None
    }

    if jurisdiction_ids:
        jurisdiction_stmt = select(TaxJurisdiction.id).where(
            TaxJurisdiction.company_id == company_id,
            TaxJurisdiction.id.in_(jurisdiction_ids),
        )
        if require_active_jurisdiction:
            jurisdiction_stmt = jurisdiction_stmt.where(
                TaxJurisdiction.is_active.is_(True)
            )
        found = set((await db.scalars(jurisdiction_stmt)).all())
        if found != jurisdiction_ids:
            raise TaxError(
                "TAX_SCOPE_JURISDICTION_NOT_FOUND",
                "One or more active jurisdictions do not belong to this company.",
                status_code=404,
            )

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
            raise TaxError(
                "TAX_SCOPE_VARIANT_NOT_FOUND",
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
            raise TaxError(
                "TAX_SCOPE_CUSTOMER_NOT_FOUND",
                "One or more customers do not belong to this company.",
                status_code=404,
            )


async def _children(
    db: AsyncSession,
    company_id: int,
    version_id: int,
) -> tuple[list[TaxRuleComponent], list[TaxRuleScope]]:
    components = list(
        (
            await db.scalars(
                select(TaxRuleComponent)
                .where(
                    TaxRuleComponent.company_id == company_id,
                    TaxRuleComponent.tax_rule_set_version_id == version_id,
                )
                .order_by(TaxRuleComponent.sequence, TaxRuleComponent.id)
            )
        ).all()
    )
    scopes = list(
        (
            await db.scalars(
                select(TaxRuleScope)
                .where(
                    TaxRuleScope.company_id == company_id,
                    TaxRuleScope.tax_rule_set_version_id == version_id,
                )
                .order_by(TaxRuleScope.id)
            )
        ).all()
    )
    return components, scopes


def _inputs(
    components: list[TaxRuleComponent],
    scopes: list[TaxRuleScope],
) -> tuple[list[TaxComponentInput], list[TaxScopeInput]]:
    return (
        [
            TaxComponentInput(
                component_code=item.component_code,
                name=item.name,
                sequence=item.sequence,
                rate=item.rate,
                basis_mode=item.basis_mode,
                reporting_code=item.reporting_code,
            )
            for item in components
        ],
        [
            TaxScopeInput(
                scope_type=item.scope_type,
                jurisdiction_id=item.jurisdiction_id,
                product_variant_id=item.product_variant_id,
                customer_id=item.customer_id,
                document_type_code=item.document_type_code,
            )
            for item in scopes
        ],
    )


async def _replace_children(
    db: AsyncSession,
    row: TaxRuleSetVersion,
    components: list[TaxComponentInput],
    scopes: list[TaxScopeInput],
) -> None:
    validate_tax_configuration(components=components, scopes=scopes)
    await _validate_scope_targets(db, row.company_id, scopes)
    await db.execute(
        delete(TaxRuleComponent).where(
            TaxRuleComponent.company_id == row.company_id,
            TaxRuleComponent.tax_rule_set_version_id == row.id,
        )
    )
    await db.execute(
        delete(TaxRuleScope).where(
            TaxRuleScope.company_id == row.company_id,
            TaxRuleScope.tax_rule_set_version_id == row.id,
        )
    )
    await db.flush()

    db.add_all(
        [
            TaxRuleComponent(
                company_id=row.company_id,
                tax_rule_set_version_id=row.id,
                component_code=item.component_code,
                name=item.name,
                sequence=item.sequence,
                rate=item.rate,
                basis_mode=item.basis_mode,
                reporting_code=item.reporting_code,
            )
            for item in components
        ]
    )
    db.add_all(
        [
            TaxRuleScope(
                company_id=row.company_id,
                tax_rule_set_version_id=row.id,
                scope_type=item.scope_type,
                jurisdiction_id=item.jurisdiction_id,
                product_variant_id=item.product_variant_id,
                customer_id=item.customer_id,
                document_type_code=item.document_type_code,
            )
            for item in scopes
        ]
    )
    await db.flush()


async def create_draft_version(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    rule_set_id: int,
    expected_rule_set_version: int,
    request_id: UUID,
    priority: int,
    price_mode: str,
    effective_from: datetime,
    effective_to: datetime | None,
    components: list[TaxComponentInput],
    scopes: list[TaxScopeInput],
) -> TaxRuleSetVersion:
    await lock_company(db, company_id)
    rule_set = await _rule_set(db, company_id, rule_set_id, lock=True)
    _expect_version(rule_set, expected_rule_set_version)
    validate_tax_configuration(components=components, scopes=scopes)
    await _validate_scope_targets(db, company_id, scopes)

    revision = await next_tenant_revision(db, company_id)
    definition_version = int(
        await db.scalar(
            select(func.max(TaxRuleSetVersion.definition_version)).where(
                TaxRuleSetVersion.company_id == company_id,
                TaxRuleSetVersion.tax_rule_set_id == rule_set_id,
            )
        )
        or 0
    ) + 1

    row = TaxRuleSetVersion(
        company_id=company_id,
        tax_rule_set_id=rule_set_id,
        revision=revision,
        definition_version=definition_version,
        status="DRAFT",
        priority=priority,
        price_mode=price_mode,
        effective_from=effective_from,
        effective_to=effective_to,
        request_id=request_id,
        created_by=actor_id,
    )
    db.add(row)
    await db.flush()
    await _replace_children(db, row, components, scopes)
    return row


async def update_draft_version(
    db: AsyncSession,
    *,
    company_id: int,
    version_id: int,
    expected_version: int,
    priority: int,
    price_mode: str,
    effective_from: datetime,
    effective_to: datetime | None,
    components: list[TaxComponentInput],
    scopes: list[TaxScopeInput],
) -> TaxRuleSetVersion:
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "DRAFT":
        raise TaxError("TAX_VERSION_NOT_DRAFT", "Only a draft tax version can be edited.")
    validate_tax_configuration(components=components, scopes=scopes)
    await _validate_scope_targets(db, company_id, scopes)
    row.priority = priority
    row.price_mode = price_mode
    row.effective_from = effective_from
    row.effective_to = effective_to
    row.version += 1
    row.updated_at = _now()
    await db.flush()
    await _replace_children(db, row, components, scopes)
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
        raise TaxError("TAX_VERSION_NOT_DRAFT", "Only a draft tax version can be deleted.")
    await db.delete(row)
    await db.flush()


async def validate_version(
    db: AsyncSession,
    *,
    company_id: int,
    version_id: int,
) -> dict[str, int]:
    row = await _version(db, company_id, version_id)
    components, scopes = await _children(db, company_id, version_id)
    component_inputs, scope_inputs = _inputs(components, scopes)
    validate_tax_configuration(components=component_inputs, scopes=scope_inputs)
    await _validate_scope_targets(
        db,
        company_id,
        scope_inputs,
        require_active_jurisdiction=row.status in {"DRAFT", "PENDING_APPROVAL"},
    )
    return {"components": len(components), "scopes": len(scopes)}


async def submit_version(
    db: AsyncSession,
    *,
    company_id: int,
    version_id: int,
    expected_version: int,
) -> TaxRuleSetVersion:
    if not await maker_checker_enabled(db, company_id):
        raise TaxError(
            "TAX_APPROVAL_NOT_ENABLED",
            "Maker/checker approval is not enabled for taxation.",
        )
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "DRAFT":
        raise TaxError(
            "TAX_VERSION_STATE_INVALID",
            "Only a draft tax version can be submitted.",
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
    row: TaxRuleSetVersion,
    actor_id: int,
) -> TaxRuleSetVersion:
    await validate_version(db, company_id=row.company_id, version_id=row.id)
    prior = await db.scalar(
        select(TaxRuleSetVersion)
        .where(
            TaxRuleSetVersion.company_id == row.company_id,
            TaxRuleSetVersion.tax_rule_set_id == row.tax_rule_set_id,
            TaxRuleSetVersion.status == "PUBLISHED",
            TaxRuleSetVersion.id != row.id,
        )
        .with_for_update()
    )
    if prior is not None:
        prior.status = "SUPERSEDED"
        prior.version += 1
        prior.updated_at = _now()
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
) -> TaxRuleSetVersion:
    if await maker_checker_enabled(db, company_id):
        raise TaxError(
            "TAX_APPROVAL_REQUIRED",
            "This company requires tax approval before publication.",
        )
    await lock_company(db, company_id)
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "DRAFT":
        raise TaxError(
            "TAX_VERSION_STATE_INVALID",
            "Only a draft tax version can be published.",
        )
    return await _publish_locked(db, row=row, actor_id=actor_id)


async def approve_version(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    version_id: int,
    expected_version: int,
) -> TaxRuleSetVersion:
    if not await maker_checker_enabled(db, company_id):
        raise TaxError(
            "TAX_APPROVAL_NOT_ENABLED",
            "Maker/checker approval is not enabled for taxation.",
        )
    await lock_company(db, company_id)
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status != "PENDING_APPROVAL":
        raise TaxError(
            "TAX_VERSION_STATE_INVALID",
            "Only a pending tax version can be approved.",
        )
    if int(row.created_by) == int(actor_id):
        raise TaxError(
            "TAX_SEPARATION_OF_DUTIES",
            "The creator cannot approve the same tax version.",
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
) -> TaxRuleSetVersion:
    row = await _version(db, company_id, version_id, lock=True)
    _expect_version(row, expected_version)
    if row.status not in {"DRAFT", "PENDING_APPROVAL"}:
        raise TaxError(
            "TAX_VERSION_STATE_INVALID",
            "Only draft or pending tax versions can be cancelled.",
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
