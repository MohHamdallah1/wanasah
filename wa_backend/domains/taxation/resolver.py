from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from typing import Optional, Sequence

from sqlalchemy import exists, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from domains.taxation.contracts import TaxComponentSnapshot, TaxResolution
from domains.taxation.core import (
    TaxError,
    current_tax_revision_ceiling,
    require_aware_datetime,
    utc_now,
)
from domains.taxation.models import (
    TaxJurisdiction,
    TaxRuleComponent,
    TaxRuleScope,
    TaxRuleSetVersion,
)
from models import ProductVariant, Shop


_DOCUMENT_CODE_RE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,79}$")
_MAX_JURISDICTION_DEPTH = 64


def _normalize_document_type(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str) or "\x00" in value:
        raise TaxError(
            "TAX_DOCUMENT_TYPE_INVALID",
            "document_type_code is invalid.",
            status_code=422,
        )
    clean = value.strip().upper()
    if not _DOCUMENT_CODE_RE.fullmatch(clean):
        raise TaxError(
            "TAX_DOCUMENT_TYPE_INVALID",
            "document_type_code must be a stable code.",
            status_code=422,
        )
    return clean


async def _validate_context(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_ids: set[int],
    customer_id: Optional[int],
) -> None:
    if customer_id is not None:
        exists_customer = await db.scalar(
            select(Shop.id).where(
                Shop.company_id == company_id,
                Shop.id == int(customer_id),
            )
        )
        if exists_customer is None:
            raise TaxError(
                "TAX_CUSTOMER_NOT_FOUND",
                "Customer is not available inside this company.",
                status_code=404,
            )

    found_products = set(
        (
            await db.scalars(
                select(ProductVariant.id).where(
                    ProductVariant.company_id == company_id,
                    ProductVariant.id.in_(sorted(product_variant_ids)),
                )
            )
        ).all()
    )
    missing = sorted(product_variant_ids - {int(value) for value in found_products})
    if missing:
        raise TaxError(
            "TAX_PRODUCT_NOT_FOUND",
            "One or more products are not available inside this company.",
            status_code=404,
            context={"product_variant_ids": missing},
        )


async def _jurisdiction_chain(
    db: AsyncSession,
    *,
    company_id: int,
    jurisdiction_id: int,
) -> dict[int, int]:
    anchor = (
        select(
            TaxJurisdiction.id.label("id"),
            TaxJurisdiction.parent_jurisdiction_id.label("parent_id"),
            literal(0).label("distance"),
        )
        .where(
            TaxJurisdiction.company_id == company_id,
            TaxJurisdiction.id == int(jurisdiction_id),
        )
    )
    chain = anchor.cte("tax_jurisdiction_chain", recursive=True)
    parent = aliased(TaxJurisdiction)
    chain = chain.union_all(
        select(
            parent.id,
            parent.parent_jurisdiction_id,
            (chain.c.distance + 1).label("distance"),
        )
        .select_from(parent)
        .join(chain, parent.id == chain.c.parent_id)
        .where(
            parent.company_id == company_id,
            chain.c.distance < _MAX_JURISDICTION_DEPTH - 1,
        )
    )

    rows = (
        await db.execute(
            select(chain.c.id, chain.c.parent_id, chain.c.distance)
            .order_by(chain.c.distance)
        )
    ).all()
    if not rows:
        raise TaxError(
            "TAX_JURISDICTION_NOT_FOUND",
            "Tax jurisdiction is not available inside this company.",
            status_code=404,
        )

    last = rows[-1]
    if int(last.distance) >= _MAX_JURISDICTION_DEPTH - 1 and last.parent_id is not None:
        raise TaxError(
            "TAX_JURISDICTION_DEPTH_EXCEEDED",
            "Tax jurisdiction hierarchy exceeds the supported depth.",
        )
    return {int(row.id): int(row.distance) for row in rows}


def _scope_exists(alias, *, company_id: int, scope_type: str, extra=None):
    predicates = [
        alias.company_id == company_id,
        alias.tax_rule_set_version_id == TaxRuleSetVersion.id,
        alias.scope_type == scope_type,
    ]
    if extra is not None:
        predicates.append(extra)
    return exists(select(1).select_from(alias).where(*predicates))


def _pick_candidate(
    product_variant_id: int,
    candidates: list[TaxResolution],
) -> TaxResolution:
    if not candidates:
        raise TaxError(
            "TAX_NOT_RESOLVED",
            "No published tax rule resolves for the requested context.",
            context={"product_variant_id": product_variant_id},
        )

    max_dimensions = max(len(row.scope_types) for row in candidates)
    top = [row for row in candidates if len(row.scope_types) == max_dimensions]

    max_priority = max(row.priority for row in top)
    top = [row for row in top if row.priority == max_priority]
    if len(top) == 1:
        return top[0]

    scope_shapes = {row.scope_types for row in top}
    if len(scope_shapes) == 1 and "JURISDICTION" in next(iter(scope_shapes)):
        distances = [
            row.jurisdiction_distance
            for row in top
            if row.jurisdiction_distance is not None
        ]
        if distances:
            best_distance = min(distances)
            nearest = [
                row for row in top
                if row.jurisdiction_distance == best_distance
            ]
            if len(nearest) == 1:
                return nearest[0]
            top = nearest

    raise TaxError(
        "TAX_RULE_TIE",
        "Tax rule precedence is ambiguous for the requested context.",
        context={
            "product_variant_id": product_variant_id,
            "tax_rule_set_version_ids": sorted(
                row.tax_rule_set_version_id for row in top
            ),
            "priority": max_priority,
            "scope_types": [list(row.scope_types) for row in top],
        },
    )


async def resolve_tax_rules_bulk(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_ids: Sequence[int],
    jurisdiction_id: int,
    customer_id: Optional[int] = None,
    document_type_code: Optional[str] = None,
    as_of: Optional[datetime] = None,
    revision_ceiling: Optional[int] = None,
) -> tuple[dict[int, TaxResolution], int]:
    if int(company_id) <= 0:
        raise TaxError(
            "TAX_TENANT_INVALID",
            "company_id must be positive.",
            status_code=422,
        )

    product_ids = sorted({int(value) for value in product_variant_ids})
    if not product_ids or any(value <= 0 for value in product_ids):
        raise TaxError(
            "TAX_RESOLVE_INPUT_INVALID",
            "At least one positive product_variant_id is required.",
            status_code=422,
        )
    if int(jurisdiction_id) <= 0:
        raise TaxError(
            "TAX_RESOLVE_INPUT_INVALID",
            "jurisdiction_id must be positive.",
            status_code=422,
        )
    if customer_id is not None and int(customer_id) <= 0:
        raise TaxError(
            "TAX_RESOLVE_INPUT_INVALID",
            "customer_id must be positive when supplied.",
            status_code=422,
        )

    when = require_aware_datetime(as_of or utc_now(), "as_of")
    document_code = _normalize_document_type(document_type_code)

    explicit_ceiling = revision_ceiling is not None
    ceiling = (
        int(revision_ceiling)
        if explicit_ceiling
        else await current_tax_revision_ceiling(db, company_id)
    )
    if explicit_ceiling and ceiling <= 0:
        raise TaxError(
            "TAX_REVISION_INVALID",
            "Tax revision ceiling must be positive.",
            status_code=422,
        )
    if ceiling <= 0:
        raise TaxError(
            "TAX_NOT_RESOLVED",
            "No published tax revision exists for this company.",
        )

    ancestor_distance = await _jurisdiction_chain(
        db,
        company_id=company_id,
        jurisdiction_id=int(jurisdiction_id),
    )
    await _validate_context(
        db,
        company_id=company_id,
        product_variant_ids=set(product_ids),
        customer_id=customer_id,
    )

    latest = (
        select(
            TaxRuleSetVersion.tax_rule_set_id.label("tax_rule_set_id"),
            func.max(TaxRuleSetVersion.revision).label("revision"),
        )
        .where(
            TaxRuleSetVersion.company_id == company_id,
            TaxRuleSetVersion.status.in_(("PUBLISHED", "SUPERSEDED")),
            TaxRuleSetVersion.published_at.is_not(None),
            TaxRuleSetVersion.published_at <= when,
            TaxRuleSetVersion.revision <= ceiling,
            TaxRuleSetVersion.effective_from <= when,
            or_(
                TaxRuleSetVersion.effective_to.is_(None),
                TaxRuleSetVersion.effective_to > when,
            ),
        )
        .group_by(TaxRuleSetVersion.tax_rule_set_id)
        .subquery()
    )

    customer_any_alias = aliased(TaxRuleScope)
    customer_match_alias = aliased(TaxRuleScope)
    product_any_alias = aliased(TaxRuleScope)
    product_match_alias = aliased(TaxRuleScope)
    document_any_alias = aliased(TaxRuleScope)
    document_match_alias = aliased(TaxRuleScope)
    jurisdiction_any_alias = aliased(TaxRuleScope)
    jurisdiction_match_alias = aliased(TaxRuleScope)

    customer_any = _scope_exists(
        customer_any_alias,
        company_id=company_id,
        scope_type="CUSTOMER",
    )
    product_any = _scope_exists(
        product_any_alias,
        company_id=company_id,
        scope_type="PRODUCT_VARIANT",
    )
    document_any = _scope_exists(
        document_any_alias,
        company_id=company_id,
        scope_type="DOCUMENT_TYPE",
    )
    jurisdiction_any = _scope_exists(
        jurisdiction_any_alias,
        company_id=company_id,
        scope_type="JURISDICTION",
    )

    match_predicates = [
        or_(
            ~product_any,
            _scope_exists(
                product_match_alias,
                company_id=company_id,
                scope_type="PRODUCT_VARIANT",
                extra=product_match_alias.product_variant_id.in_(product_ids),
            ),
        ),
        or_(
            ~jurisdiction_any,
            _scope_exists(
                jurisdiction_match_alias,
                company_id=company_id,
                scope_type="JURISDICTION",
                extra=jurisdiction_match_alias.jurisdiction_id.in_(
                    sorted(ancestor_distance)
                ),
            ),
        ),
    ]
    if customer_id is None:
        match_predicates.append(~customer_any)
    else:
        match_predicates.append(
            or_(
                ~customer_any,
                _scope_exists(
                    customer_match_alias,
                    company_id=company_id,
                    scope_type="CUSTOMER",
                    extra=customer_match_alias.customer_id == int(customer_id),
                ),
            )
        )
    if document_code is None:
        match_predicates.append(~document_any)
    else:
        match_predicates.append(
            or_(
                ~document_any,
                _scope_exists(
                    document_match_alias,
                    company_id=company_id,
                    scope_type="DOCUMENT_TYPE",
                    extra=document_match_alias.document_type_code == document_code,
                ),
            )
        )

    versions = list(
        (
            await db.scalars(
                select(TaxRuleSetVersion)
                .join(
                    latest,
                    (latest.c.tax_rule_set_id == TaxRuleSetVersion.tax_rule_set_id)
                    & (latest.c.revision == TaxRuleSetVersion.revision),
                )
                .where(
                    TaxRuleSetVersion.company_id == company_id,
                    *match_predicates,
                )
                .order_by(
                    TaxRuleSetVersion.priority.desc(),
                    TaxRuleSetVersion.revision.desc(),
                    TaxRuleSetVersion.id.asc(),
                )
            )
        ).all()
    )

    if not versions:
        raise TaxError(
            "TAX_NOT_RESOLVED",
            "No published tax rule resolves for the requested context.",
            context={
                "product_variant_ids": product_ids,
                "jurisdiction_id": int(jurisdiction_id),
                "customer_id": customer_id,
                "document_type_code": document_code,
                "tax_revision_ceiling": ceiling,
            },
        )

    version_ids = [int(row.id) for row in versions]
    scopes = list(
        (
            await db.scalars(
                select(TaxRuleScope)
                .where(
                    TaxRuleScope.company_id == company_id,
                    TaxRuleScope.tax_rule_set_version_id.in_(version_ids),
                )
                .order_by(
                    TaxRuleScope.tax_rule_set_version_id,
                    TaxRuleScope.scope_type,
                    TaxRuleScope.id,
                )
            )
        ).all()
    )
    components = list(
        (
            await db.scalars(
                select(TaxRuleComponent)
                .where(
                    TaxRuleComponent.company_id == company_id,
                    TaxRuleComponent.tax_rule_set_version_id.in_(version_ids),
                )
                .order_by(
                    TaxRuleComponent.tax_rule_set_version_id,
                    TaxRuleComponent.sequence,
                    TaxRuleComponent.id,
                )
            )
        ).all()
    )

    scope_map: dict[int, list[TaxRuleScope]] = defaultdict(list)
    component_map: dict[int, list[TaxRuleComponent]] = defaultdict(list)
    for scope in scopes:
        scope_map[int(scope.tax_rule_set_version_id)].append(scope)
    for component in components:
        component_map[int(component.tax_rule_set_version_id)].append(component)

    by_product: dict[int, list[TaxResolution]] = {
        product_id: [] for product_id in product_ids
    }
    for version in versions:
        version_id = int(version.id)
        version_scopes = scope_map[version_id]
        version_components = component_map[version_id]
        if not version_components:
            raise TaxError(
                "TAX_CONFIGURATION_INVALID",
                "A published tax version has no tax components.",
                context={"tax_rule_set_version_id": version_id},
            )

        sequences = [int(item.sequence) for item in version_components]
        if sequences != list(range(1, len(version_components) + 1)):
            raise TaxError(
                "TAX_CONFIGURATION_INVALID",
                "Published tax component sequence is not contiguous.",
                context={
                    "tax_rule_set_version_id": version_id,
                    "sequences": sequences,
                },
            )

        by_type: dict[str, list[TaxRuleScope]] = defaultdict(list)
        for scope in version_scopes:
            by_type[str(scope.scope_type)].append(scope)

        customer_scopes = {
            int(scope.customer_id)
            for scope in by_type["CUSTOMER"]
            if scope.customer_id is not None
        }
        if customer_scopes and (
            customer_id is None or int(customer_id) not in customer_scopes
        ):
            continue

        document_scopes = {
            str(scope.document_type_code)
            for scope in by_type["DOCUMENT_TYPE"]
            if scope.document_type_code is not None
        }
        if document_scopes and (
            document_code is None or document_code not in document_scopes
        ):
            continue

        jurisdiction_scopes = {
            int(scope.jurisdiction_id)
            for scope in by_type["JURISDICTION"]
            if scope.jurisdiction_id is not None
        }
        matched_jurisdiction_id: int | None = None
        jurisdiction_distance: int | None = None
        if jurisdiction_scopes:
            matches = sorted(
                (
                    ancestor_distance[target_id],
                    target_id,
                )
                for target_id in jurisdiction_scopes
                if target_id in ancestor_distance
            )
            if not matches:
                continue
            jurisdiction_distance, matched_jurisdiction_id = matches[0]

        product_scopes = {
            int(scope.product_variant_id)
            for scope in by_type["PRODUCT_VARIANT"]
            if scope.product_variant_id is not None
        }
        scope_types = tuple(sorted(key for key, value in by_type.items() if value))
        snapshots = tuple(
            TaxComponentSnapshot(
                component_id=int(item.id),
                component_code=str(item.component_code),
                name=str(item.name),
                sequence=int(item.sequence),
                rate=Decimal(item.rate),
                basis_mode=str(item.basis_mode),
                reporting_code=(
                    str(item.reporting_code)
                    if item.reporting_code is not None
                    else None
                ),
            )
            for item in version_components
        )

        for product_id in product_ids:
            if product_scopes and product_id not in product_scopes:
                continue
            by_product[product_id].append(
                TaxResolution(
                    product_variant_id=product_id,
                    tax_rule_set_id=int(version.tax_rule_set_id),
                    tax_rule_set_version_id=version_id,
                    tax_revision=int(version.revision),
                    definition_version=int(version.definition_version),
                    priority=int(version.priority),
                    price_mode=str(version.price_mode),
                    scope_types=scope_types,
                    matched_jurisdiction_id=matched_jurisdiction_id,
                    jurisdiction_distance=jurisdiction_distance,
                    components=snapshots,
                    resolved_at=when,
                )
            )

    result = {
        product_id: _pick_candidate(product_id, by_product[product_id])
        for product_id in product_ids
    }
    return result, ceiling


async def resolve_tax_rule(
    db: AsyncSession,
    *,
    company_id: int,
    product_variant_id: int,
    jurisdiction_id: int,
    customer_id: Optional[int] = None,
    document_type_code: Optional[str] = None,
    as_of: Optional[datetime] = None,
    revision_ceiling: Optional[int] = None,
) -> TaxResolution:
    rows, _ = await resolve_tax_rules_bulk(
        db,
        company_id=company_id,
        product_variant_ids=[product_variant_id],
        jurisdiction_id=jurisdiction_id,
        customer_id=customer_id,
        document_type_code=document_type_code,
        as_of=as_of,
        revision_ceiling=revision_ceiling,
    )
    return rows[int(product_variant_id)]
