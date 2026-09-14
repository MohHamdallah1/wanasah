from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.offers.core import OfferError, maker_checker_enabled
from domains.offers.service import preview_offer_basket
from domains.pricing.core import PricingError
from domains.uom_authority import UomAuthorityError, load_variant_uom_authorities
from domains.offers.models import (
    OfferDefinition,
    OfferVersion,
    OfferVersionProduct,
    OfferVersionScope,
)
from domains.offers.publishing import (
    approve_version,
    cancel_version,
    create_definition,
    create_draft_version,
    delete_definition,
    delete_draft_version,
    publish_version,
    submit_version,
    update_definition,
    update_draft_version,
    validate_version,
)
from domains.offers.schemas import (
    DefinitionCreate,
    DefinitionDelete,
    DefinitionUpdate,
    VersionCommand,
    VersionCreate,
    VersionDelete,
    VersionUpdate,
    PreviewRequest,
)
from inventory_access import InventoryAccess
from models import Driver, ProductVariant, SystemAuditLog, UOM
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter(prefix="/offers", tags=["Offers"])
MAX_PAGE_SIZE = 200


def _hash(payload: BaseModel, **scope: Any) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    body.update(scope)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _cursor(value: Optional[str]) -> int:
    if value is None:
        return 0
    try:
        raw = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)).decode("ascii")
        parsed = int(raw)
    except Exception as exc:
        raise HTTPException(
            400,
            detail={"code": "INVALID_CURSOR", "message": "Invalid offer cursor.", "context": {}},
        ) from exc
    if parsed <= 0:
        raise HTTPException(
            400,
            detail={"code": "INVALID_CURSOR", "message": "Invalid offer cursor.", "context": {}},
        )
    return parsed


def _next_cursor(value: int) -> str:
    return base64.urlsafe_b64encode(str(value).encode("ascii")).decode("ascii").rstrip("=")


async def _require(db: AsyncSession, actor: Driver, permission: str) -> None:
    await InventoryAccess(db, actor).require(permission, any_location=True)


def _offer_http_error(exc: OfferError) -> HTTPException:
    return HTTPException(exc.status_code, detail=exc.as_detail())


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
            new_value=json.dumps(payload, ensure_ascii=False, default=str, sort_keys=True),
        )
    )


def _definition_row(row: OfferDefinition) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "code": row.code,
        "name": row.name,
        "description": row.description,
        "version": int(row.version),
        "created_by": int(row.created_by),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


class ReferenceVariantResolveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ids: list[int] = Field(min_length=1, max_length=1000)

    @field_validator("ids")
    @classmethod
    def validate_ids(cls, values: list[int]) -> list[int]:
        if any(type(value) is not int or value <= 0 for value in values):
            raise ValueError("Product variant IDs must be positive integers.")
        if len(values) != len(set(values)):
            raise ValueError("Product variant IDs must be unique.")
        return values


def _uom_authority_http_error(exc: UomAuthorityError) -> HTTPException:
    return HTTPException(
        409,
        detail={
            "code": exc.code,
            "message": exc.message,
            "context": exc.context,
        },
    )


async def _reference_variant_rows(
    db: AsyncSession,
    *,
    company_id: int,
    variants: list[ProductVariant],
) -> list[dict[str, Any]]:
    if not variants:
        return []
    ids = [int(row.id) for row in variants]
    try:
        authorities = await load_variant_uom_authorities(
            db, company_id=company_id, variant_ids=ids
        )
    except UomAuthorityError as exc:
        raise _uom_authority_http_error(exc) from exc

    uom_ids = {
        int(uom_id)
        for authority in authorities.values()
        for uom_id in authority.factors_to_base
    }
    uom_rows = list(
        (await db.scalars(select(UOM).where(UOM.id.in_(uom_ids)))).all()
    ) if uom_ids else []
    uoms = {int(row.id): row for row in uom_rows}
    missing_uoms = sorted(uom_ids - set(uoms))
    if missing_uoms:
        raise HTTPException(
            409,
            detail={
                "code": "OFFER_REFERENCE_UOM_NOT_FOUND",
                "message": "A reachable offer UOM is missing from master data.",
                "context": {"uom_ids": missing_uoms},
            },
        )

    result: list[dict[str, Any]] = []
    for row in variants:
        authority = authorities[int(row.id)]
        ordered_uom_ids = sorted(
            authority.factors_to_base,
            key=lambda uom_id: (
                0 if int(uom_id) == int(authority.base_uom_id) else 1,
                uoms[int(uom_id)].code,
                int(uom_id),
            ),
        )
        available_uoms = [
            {
                "id": int(uoms[int(uom_id)].id),
                "code": uoms[int(uom_id)].code,
                "name": uoms[int(uom_id)].name,
            }
            for uom_id in ordered_uom_ids
        ]
        base_uom = uoms[int(authority.base_uom_id)]
        result.append(
            {
                "id": int(row.id),
                "product_id": int(row.product_id),
                "sku": row.sku,
                "name": row.name,
                "base_uom": {
                    "id": int(base_uom.id),
                    "code": base_uom.code,
                    "name": base_uom.name,
                },
                "uoms": available_uoms,
                "quantity_scale": int(row.quantity_scale),
                "quantity_step": str(row.quantity_step),
                "lifecycle_status": row.lifecycle_status,
                "operational_hold": row.operational_hold,
                "version": int(row.version),
            }
        )
    return result


def _version_dict(
    row: OfferVersion,
    scopes: list[OfferVersionScope],
    products: list[OfferVersionProduct],
) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "offer_definition_id": int(row.offer_definition_id),
        "revision": int(row.revision),
        "definition_version": int(row.definition_version),
        "status": row.status,
        "offer_type": row.offer_type,
        "payload": dict(row.validated_payload or {}),
        "currency_code": row.currency_code,
        "priority": int(row.priority),
        "stacking_mode": row.stacking_mode,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": (
            row.effective_to.isoformat()
            if row.effective_to
            else None
        ),
        "request_id": str(row.request_id),
        "created_by": int(row.created_by),
        "approved_by": (
            int(row.approved_by)
            if row.approved_by is not None
            else None
        ),
        "approved_at": (
            row.approved_at.isoformat()
            if row.approved_at
            else None
        ),
        "published_at": (
            row.published_at.isoformat()
            if row.published_at
            else None
        ),
        "cancelled_by": (
            int(row.cancelled_by)
            if row.cancelled_by is not None
            else None
        ),
        "cancelled_at": (
            row.cancelled_at.isoformat()
            if row.cancelled_at
            else None
        ),
        "cancel_reason": row.cancel_reason,
        "version": int(row.version),
        "scopes": [
            {
                "scope_type": item.scope_type,
                "product_variant_id": item.product_variant_id,
                "uom_id": item.uom_id,
                "customer_id": item.customer_id,
                "branch_id": item.branch_id,
                "channel_code": item.channel_code,
            }
            for item in scopes
        ],
        "products": [
            {
                "role": item.role,
                "product_variant_id": int(
                    item.product_variant_id
                ),
                "uom_id": int(item.uom_id),
                "quantity_per_application": (
                    str(item.quantity_per_application)
                    if item.quantity_per_application is not None
                    else None
                ),
            }
            for item in products
        ],
    }


async def _serialize_versions(
    db: AsyncSession, rows: list[OfferVersion]
) -> list[dict[str, Any]]:
    """Two bounded child queries for the whole page; never query per version."""
    if not rows:
        return []
    company_id = int(rows[0].company_id)
    if any(int(row.company_id) != company_id for row in rows):
        raise RuntimeError("Cross-tenant version serialization is forbidden.")
    ids = [int(row.id) for row in rows]
    scopes = list(
        (
            await db.scalars(
                select(OfferVersionScope)
                .where(
                    OfferVersionScope.company_id == company_id,
                    OfferVersionScope.offer_version_id.in_(ids),
                )
                .order_by(OfferVersionScope.offer_version_id, OfferVersionScope.id)
            )
        ).all()
    )
    products = list(
        (
            await db.scalars(
                select(OfferVersionProduct)
                .where(
                    OfferVersionProduct.company_id == company_id,
                    OfferVersionProduct.offer_version_id.in_(ids),
                )
                .order_by(OfferVersionProduct.offer_version_id, OfferVersionProduct.id)
            )
        ).all()
    )
    scope_map: dict[int, list[OfferVersionScope]] = defaultdict(list)
    product_map: dict[int, list[OfferVersionProduct]] = defaultdict(list)
    for item in scopes:
        scope_map[int(item.offer_version_id)].append(item)
    for item in products:
        product_map[int(item.offer_version_id)].append(item)
    return [
        _version_dict(row, scope_map[int(row.id)], product_map[int(row.id)])
        for row in rows
    ]


async def _mutation(
    *,
    db: AsyncSession,
    actor: Driver,
    payload: BaseModel,
    operation: str,
    scope: dict[str, Any],
    target: str,
    action_name: str,
    fn: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation=operation,
            request_id=str(payload.request_id),
            request_hash=_hash(payload, **scope),
        )
        if replay is not None:
            await db.rollback()
            return replay
        response = await fn()
        _audit(
            db,
            actor,
            target,
            action_name,
            {
                "request": payload.model_dump(mode="json"),
                "scope": scope,
                "response": response,
            },
        )
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except OfferError as exc:
        await db.rollback()
        raise _offer_http_error(exc) from exc
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={"code": "IDEMPOTENCY_CONFLICT", "message": str(exc), "context": {}},
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "OFFER_CONSTRAINT_CONFLICT",
                "message": "Offer data conflicts with an existing record or tenant boundary.",
                "context": {},
            },
        ) from exc


@router.get("/policy")
async def get_policy(
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.view")
    try:
        enabled = await maker_checker_enabled(db, actor.company_id)
    except OfferError as exc:
        raise _offer_http_error(exc) from exc
    return {"maker_checker_enabled": enabled}


@router.get("/references/variants")
async def list_reference_variants(
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(100, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    rows = list(
        (
            await db.scalars(
                select(ProductVariant)
                .where(
                    ProductVariant.company_id == actor.company_id,
                    ProductVariant.id > _cursor(cursor),
                )
                .order_by(ProductVariant.id)
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": await _reference_variant_rows(
            db, company_id=int(actor.company_id), variants=page
        ),
        "next_cursor": _next_cursor(page[-1].id) if has_more and page else None,
        "has_more": has_more,
    }


@router.post("/references/variants/resolve")
async def resolve_reference_variants(
    payload: ReferenceVariantResolveRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "catalog.read")
    rows = list(
        (
            await db.scalars(
                select(ProductVariant)
                .where(
                    ProductVariant.company_id == actor.company_id,
                    ProductVariant.id.in_(payload.ids),
                )
                .order_by(ProductVariant.id)
            )
        ).all()
    )
    found = {int(row.id) for row in rows}
    missing = sorted(set(payload.ids) - found)
    if missing:
        raise HTTPException(
            404,
            detail={
                "code": "OFFER_REFERENCE_VARIANT_NOT_FOUND",
                "message": "One or more product variants are not available inside this company.",
                "context": {"product_variant_ids": missing},
            },
        )
    return {
        "items": await _reference_variant_rows(
            db, company_id=int(actor.company_id), variants=rows
        ),
        "next_cursor": None,
        "has_more": False,
    }


@router.get("/definitions")
async def list_definitions(
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.view")
    rows = list(
        (
            await db.scalars(
                select(OfferDefinition)
                .where(
                    OfferDefinition.company_id == actor.company_id,
                    OfferDefinition.id > _cursor(cursor),
                )
                .order_by(OfferDefinition.id)
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_definition_row(row) for row in page],
        "next_cursor": _next_cursor(page[-1].id) if has_more and page else None,
        "has_more": has_more,
    }


@router.post("/definitions", status_code=201)
async def add_definition(
    payload: DefinitionCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.manage")

    async def run():
        row = await create_definition(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
        )
        return {"definition": _definition_row(row)}

    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation="OFFER_DEFINITION_CREATE",
        scope={},
        target="OfferDefinition",
        action_name="OFFER_DEFINITION_CREATED",
        fn=run,
    )


@router.patch("/definitions/{definition_id}")
async def edit_definition(
    definition_id: int,
    payload: DefinitionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.manage")

    async def run():
        row = await update_definition(
            db,
            company_id=actor.company_id,
            definition_id=definition_id,
            expected_version=payload.expected_version,
            code=payload.code,
            name=payload.name,
            description=payload.description,
            description_supplied="description" in payload.model_fields_set,
        )
        return {"definition": _definition_row(row)}

    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation="OFFER_DEFINITION_UPDATE",
        scope={"definition_id": definition_id},
        target=f"OfferDefinition_{definition_id}",
        action_name="OFFER_DEFINITION_UPDATED",
        fn=run,
    )


@router.delete("/definitions/{definition_id}")
async def remove_definition(
    definition_id: int,
    payload: DefinitionDelete,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.manage")

    async def run():
        await delete_definition(
            db,
            company_id=actor.company_id,
            definition_id=definition_id,
            expected_version=payload.expected_version,
        )
        return {"deleted": True, "definition_id": definition_id}

    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation="OFFER_DEFINITION_DELETE",
        scope={"definition_id": definition_id},
        target=f"OfferDefinition_{definition_id}",
        action_name="OFFER_DEFINITION_DELETED",
        fn=run,
    )


@router.get("/definitions/{definition_id}/versions")
async def list_versions(
    definition_id: int,
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.view")
    definition_exists = await db.scalar(
        select(OfferDefinition.id).where(
            OfferDefinition.company_id == actor.company_id,
            OfferDefinition.id == definition_id,
        )
    )
    if definition_exists is None:
        raise HTTPException(
            404,
            detail={
                "code": "OFFER_DEFINITION_NOT_FOUND",
                "message": "Offer definition was not found.",
                "context": {},
            },
        )
    rows = list(
        (
            await db.scalars(
                select(OfferVersion)
                .where(
                    OfferVersion.company_id == actor.company_id,
                    OfferVersion.offer_definition_id == definition_id,
                    OfferVersion.id > _cursor(cursor),
                )
                .order_by(OfferVersion.id)
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": await _serialize_versions(db, page),
        "next_cursor": _next_cursor(page[-1].id) if has_more and page else None,
        "has_more": has_more,
    }


@router.get("/versions/{version_id}")
async def get_version(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.view")
    row = await db.scalar(
        select(OfferVersion).where(
            OfferVersion.company_id == actor.company_id,
            OfferVersion.id == version_id,
        )
    )
    if row is None:
        raise HTTPException(
            404,
            detail={
                "code": "OFFER_VERSION_NOT_FOUND",
                "message": "Offer version was not found.",
                "context": {},
            },
        )
    return {"version": (await _serialize_versions(db, [row]))[0]}


@router.post("/definitions/{definition_id}/versions", status_code=201)
async def add_version(
    definition_id: int,
    payload: VersionCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.manage")

    async def run():
        row = await create_draft_version(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            definition_id=definition_id,
            expected_definition_version=payload.expected_definition_version,
            request_id=payload.request_id,
            offer_type=payload.offer_type,
            payload=payload.payload,
            currency_code=payload.currency_code,
            priority=payload.priority,
            stacking_mode=payload.stacking_mode,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            scopes=payload.scopes,
            products=payload.products,
        )
        return {"version": (await _serialize_versions(db, [row]))[0]}

    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation="OFFER_VERSION_CREATE",
        scope={"definition_id": definition_id},
        target=f"OfferDefinition_{definition_id}",
        action_name="OFFER_VERSION_CREATED",
        fn=run,
    )


@router.put("/versions/{version_id}")
async def edit_version(
    version_id: int,
    payload: VersionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.manage")

    async def run():
        row = await update_draft_version(
            db,
            company_id=actor.company_id,
            version_id=version_id,
            expected_version=payload.expected_version,
            offer_type=payload.offer_type,
            payload=payload.payload,
            currency_code=payload.currency_code,
            priority=payload.priority,
            stacking_mode=payload.stacking_mode,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            scopes=payload.scopes,
            products=payload.products,
        )
        return {"version": (await _serialize_versions(db, [row]))[0]}

    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation="OFFER_VERSION_UPDATE",
        scope={"version_id": version_id},
        target=f"OfferVersion_{version_id}",
        action_name="OFFER_VERSION_UPDATED",
        fn=run,
    )


@router.delete("/versions/{version_id}")
async def remove_version(
    version_id: int,
    payload: VersionDelete,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.manage")

    async def run():
        await delete_draft_version(
            db,
            company_id=actor.company_id,
            version_id=version_id,
            expected_version=payload.expected_version,
        )
        return {"deleted": True, "version_id": version_id}

    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation="OFFER_VERSION_DELETE",
        scope={"version_id": version_id},
        target=f"OfferVersion_{version_id}",
        action_name="OFFER_VERSION_DELETED",
        fn=run,
    )


@router.post("/preview")
async def preview_basket(
    payload: PreviewRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.view")
    try:
        return await preview_offer_basket(
            db,
            company_id=actor.company_id,
            payload=payload,
        )
    except OfferError as exc:
        raise _offer_http_error(exc) from exc
    except PricingError as exc:
        raise HTTPException(exc.status_code, detail=exc.as_detail()) from exc


@router.post("/versions/{version_id}/validate")
async def validate_offer_version(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "offers.view")
    try:
        canonical = await validate_version(
            db, company_id=actor.company_id, version_id=version_id
        )
    except OfferError as exc:
        raise _offer_http_error(exc) from exc
    return {"valid": True, "canonical_payload": canonical}


async def _command(
    *,
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession,
    actor: Driver,
    operation: str,
    action_name: str,
    permission: str,
    fn: Callable[..., Awaitable[OfferVersion]],
):
    await _require(db, actor, permission)

    async def run():
        kwargs: dict[str, Any] = {
            "db": db,
            "company_id": actor.company_id,
            "version_id": version_id,
            "expected_version": payload.expected_version,
        }
        if operation in {"OFFER_VERSION_PUBLISH", "OFFER_VERSION_APPROVE", "OFFER_VERSION_CANCEL"}:
            kwargs["actor_id"] = actor.id
        if operation == "OFFER_VERSION_CANCEL":
            kwargs["reason"] = payload.reason
        row = await fn(**kwargs)
        return {"version": (await _serialize_versions(db, [row]))[0]}

    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation=operation,
        scope={"version_id": version_id},
        target=f"OfferVersion_{version_id}",
        action_name=action_name,
        fn=run,
    )


@router.post("/versions/{version_id}/submit")
async def submit(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _command(
        version_id=version_id,
        payload=payload,
        db=db,
        actor=actor,
        operation="OFFER_VERSION_SUBMIT",
        action_name="OFFER_VERSION_SUBMITTED",
        permission="offers.manage",
        fn=submit_version,
    )


@router.post("/versions/{version_id}/publish")
async def publish(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _command(
        version_id=version_id,
        payload=payload,
        db=db,
        actor=actor,
        operation="OFFER_VERSION_PUBLISH",
        action_name="OFFER_VERSION_PUBLISHED",
        permission="offers.manage",
        fn=publish_version,
    )


@router.post("/versions/{version_id}/approve")
async def approve(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _command(
        version_id=version_id,
        payload=payload,
        db=db,
        actor=actor,
        operation="OFFER_VERSION_APPROVE",
        action_name="OFFER_VERSION_APPROVED",
        permission="offers.approve",
        fn=approve_version,
    )


@router.post("/versions/{version_id}/cancel")
async def cancel(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _command(
        version_id=version_id,
        payload=payload,
        db=db,
        actor=actor,
        operation="OFFER_VERSION_CANCEL",
        action_name="OFFER_VERSION_CANCELLED",
        permission="offers.manage",
        fn=cancel_version,
    )
