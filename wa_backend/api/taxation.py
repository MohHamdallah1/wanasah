from __future__ import annotations

import base64
import hashlib
import json
from collections import defaultdict
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.taxation.core import TaxError, maker_checker_enabled
from domains.taxation.service import preview_tax_document
from domains.taxation.models import (
    TaxJurisdiction,
    TaxRuleComponent,
    TaxRuleScope,
    TaxRuleSet,
    TaxRuleSetVersion,
)
from domains.taxation.publishing import (
    approve_version,
    cancel_version,
    create_draft_version,
    create_jurisdiction,
    create_rule_set,
    delete_draft_version,
    delete_jurisdiction,
    delete_rule_set,
    publish_version,
    submit_version,
    update_draft_version,
    update_jurisdiction,
    update_rule_set,
    validate_version,
)
from domains.taxation.schemas import (
    DeleteCommand,
    JurisdictionCreate,
    JurisdictionUpdate,
    RuleSetCreate,
    RuleSetUpdate,
    VersionCommand,
    VersionCreate,
    VersionDelete,
    VersionUpdate,
    TaxPreviewRequest,
)
from inventory_access import InventoryAccess
from models import Driver, SystemAuditLog
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter(prefix="/taxation", tags=["Taxation"])
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
            detail={"code": "INVALID_CURSOR", "message": "Invalid tax cursor.", "context": {}},
        ) from exc
    if parsed <= 0:
        raise HTTPException(
            400,
            detail={"code": "INVALID_CURSOR", "message": "Invalid tax cursor.", "context": {}},
        )
    return parsed


def _next_cursor(value: int) -> str:
    return base64.urlsafe_b64encode(str(value).encode("ascii")).decode("ascii").rstrip("=")


async def _require(db: AsyncSession, actor: Driver, permission: str) -> None:
    await InventoryAccess(db, actor).require(permission, any_location=True)


def _http_error(exc: TaxError) -> HTTPException:
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
    except TaxError as exc:
        await db.rollback()
        raise _http_error(exc) from exc
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
                "code": "TAX_CONSTRAINT_CONFLICT",
                "message": "Tax data conflicts with an existing record or tenant boundary.",
                "context": {},
            },
        ) from exc


def _jurisdiction_row(row: TaxJurisdiction) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "code": row.code,
        "name": row.name,
        "jurisdiction_type": row.jurisdiction_type,
        "country_code": row.country_code,
        "subdivision_code": row.subdivision_code,
        "locality_code": row.locality_code,
        "parent_jurisdiction_id": row.parent_jurisdiction_id,
        "is_active": bool(row.is_active),
        "version": int(row.version),
        "created_by": int(row.created_by),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _rule_set_row(row: TaxRuleSet) -> dict[str, Any]:
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


def _version_row(
    row: TaxRuleSetVersion,
    components: list[TaxRuleComponent],
    scopes: list[TaxRuleScope],
) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "tax_rule_set_id": int(row.tax_rule_set_id),
        "revision": int(row.revision),
        "definition_version": int(row.definition_version),
        "status": row.status,
        "priority": int(row.priority),
        "price_mode": row.price_mode,
        "effective_from": row.effective_from.isoformat(),
        "effective_to": row.effective_to.isoformat() if row.effective_to else None,
        "request_id": str(row.request_id),
        "created_by": int(row.created_by),
        "approved_by": int(row.approved_by) if row.approved_by is not None else None,
        "approved_at": row.approved_at.isoformat() if row.approved_at else None,
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "cancelled_by": int(row.cancelled_by) if row.cancelled_by is not None else None,
        "cancelled_at": row.cancelled_at.isoformat() if row.cancelled_at else None,
        "cancel_reason": row.cancel_reason,
        "version": int(row.version),
        "components": [
            {
                "component_code": item.component_code,
                "name": item.name,
                "sequence": int(item.sequence),
                "rate": format(item.rate, "f"),
                "basis_mode": item.basis_mode,
                "reporting_code": item.reporting_code,
            }
            for item in components
        ],
        "scopes": [
            {
                "scope_type": item.scope_type,
                "jurisdiction_id": item.jurisdiction_id,
                "product_variant_id": item.product_variant_id,
                "customer_id": item.customer_id,
                "document_type_code": item.document_type_code,
            }
            for item in scopes
        ],
    }


async def _serialize_versions(
    db: AsyncSession,
    rows: list[TaxRuleSetVersion],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    company_id = int(rows[0].company_id)
    if any(int(row.company_id) != company_id for row in rows):
        raise RuntimeError("Cross-tenant tax serialization is forbidden.")
    ids = [int(row.id) for row in rows]
    components = list(
        (
            await db.scalars(
                select(TaxRuleComponent)
                .where(
                    TaxRuleComponent.company_id == company_id,
                    TaxRuleComponent.tax_rule_set_version_id.in_(ids),
                )
                .order_by(
                    TaxRuleComponent.tax_rule_set_version_id,
                    TaxRuleComponent.sequence,
                    TaxRuleComponent.id,
                )
            )
        ).all()
    )
    scopes = list(
        (
            await db.scalars(
                select(TaxRuleScope)
                .where(
                    TaxRuleScope.company_id == company_id,
                    TaxRuleScope.tax_rule_set_version_id.in_(ids),
                )
                .order_by(TaxRuleScope.tax_rule_set_version_id, TaxRuleScope.id)
            )
        ).all()
    )
    component_map: dict[int, list[TaxRuleComponent]] = defaultdict(list)
    scope_map: dict[int, list[TaxRuleScope]] = defaultdict(list)
    for item in components:
        component_map[int(item.tax_rule_set_version_id)].append(item)
    for item in scopes:
        scope_map[int(item.tax_rule_set_version_id)].append(item)
    return [
        _version_row(row, component_map[int(row.id)], scope_map[int(row.id)])
        for row in rows
    ]


@router.get("/policy")
async def get_policy(
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.view")
    try:
        enabled = await maker_checker_enabled(db, actor.company_id)
    except TaxError as exc:
        raise _http_error(exc) from exc
    return {"maker_checker_enabled": enabled}


@router.post("/preview")
async def preview_tax(
    payload: TaxPreviewRequest,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.view")
    try:
        return await preview_tax_document(
            db,
            company_id=actor.company_id,
            payload=payload,
        )
    except TaxError as exc:
        raise _http_error(exc) from exc


@router.get("/jurisdictions")
async def list_jurisdictions(
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.view")
    rows = list(
        (
            await db.scalars(
                select(TaxJurisdiction)
                .where(
                    TaxJurisdiction.company_id == actor.company_id,
                    TaxJurisdiction.id > _cursor(cursor),
                )
                .order_by(TaxJurisdiction.id)
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_jurisdiction_row(row) for row in page],
        "next_cursor": _next_cursor(page[-1].id) if has_more and page else None,
        "has_more": has_more,
    }


@router.post("/jurisdictions", status_code=201)
async def add_jurisdiction(
    payload: JurisdictionCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        row = await create_jurisdiction(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            code=payload.code,
            name=payload.name,
            jurisdiction_type=payload.jurisdiction_type,
            country_code=payload.country_code,
            subdivision_code=payload.subdivision_code,
            locality_code=payload.locality_code,
            parent_jurisdiction_id=payload.parent_jurisdiction_id,
        )
        return {"jurisdiction": _jurisdiction_row(row)}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_JURISDICTION_CREATE", scope={},
        target="TaxJurisdiction", action_name="TAX_JURISDICTION_CREATED", fn=run,
    )


@router.patch("/jurisdictions/{jurisdiction_id}")
async def edit_jurisdiction(
    jurisdiction_id: int,
    payload: JurisdictionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        values = payload.model_dump(
            exclude={"request_id", "expected_version"},
            exclude_unset=True,
        )
        row = await update_jurisdiction(
            db,
            company_id=actor.company_id,
            jurisdiction_id=jurisdiction_id,
            expected_version=payload.expected_version,
            values=values,
        )
        return {"jurisdiction": _jurisdiction_row(row)}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_JURISDICTION_UPDATE",
        scope={"jurisdiction_id": jurisdiction_id},
        target=f"TaxJurisdiction_{jurisdiction_id}",
        action_name="TAX_JURISDICTION_UPDATED", fn=run,
    )


@router.delete("/jurisdictions/{jurisdiction_id}")
async def remove_jurisdiction(
    jurisdiction_id: int,
    payload: DeleteCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        await delete_jurisdiction(
            db,
            company_id=actor.company_id,
            jurisdiction_id=jurisdiction_id,
            expected_version=payload.expected_version,
        )
        return {"deleted": True, "jurisdiction_id": jurisdiction_id}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_JURISDICTION_DELETE",
        scope={"jurisdiction_id": jurisdiction_id},
        target=f"TaxJurisdiction_{jurisdiction_id}",
        action_name="TAX_JURISDICTION_DELETED", fn=run,
    )


@router.get("/rule-sets")
async def list_rule_sets(
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.view")
    rows = list(
        (
            await db.scalars(
                select(TaxRuleSet)
                .where(
                    TaxRuleSet.company_id == actor.company_id,
                    TaxRuleSet.id > _cursor(cursor),
                )
                .order_by(TaxRuleSet.id)
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_rule_set_row(row) for row in page],
        "next_cursor": _next_cursor(page[-1].id) if has_more and page else None,
        "has_more": has_more,
    }


@router.post("/rule-sets", status_code=201)
async def add_rule_set(
    payload: RuleSetCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        row = await create_rule_set(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            code=payload.code,
            name=payload.name,
            description=payload.description,
        )
        return {"rule_set": _rule_set_row(row)}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_RULE_SET_CREATE", scope={},
        target="TaxRuleSet", action_name="TAX_RULE_SET_CREATED", fn=run,
    )


@router.patch("/rule-sets/{rule_set_id}")
async def edit_rule_set(
    rule_set_id: int,
    payload: RuleSetUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        values = payload.model_dump(
            exclude={"request_id", "expected_version"},
            exclude_unset=True,
        )
        row = await update_rule_set(
            db,
            company_id=actor.company_id,
            rule_set_id=rule_set_id,
            expected_version=payload.expected_version,
            values=values,
        )
        return {"rule_set": _rule_set_row(row)}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_RULE_SET_UPDATE",
        scope={"rule_set_id": rule_set_id},
        target=f"TaxRuleSet_{rule_set_id}",
        action_name="TAX_RULE_SET_UPDATED", fn=run,
    )


@router.delete("/rule-sets/{rule_set_id}")
async def remove_rule_set(
    rule_set_id: int,
    payload: DeleteCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        await delete_rule_set(
            db,
            company_id=actor.company_id,
            rule_set_id=rule_set_id,
            expected_version=payload.expected_version,
        )
        return {"deleted": True, "rule_set_id": rule_set_id}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_RULE_SET_DELETE",
        scope={"rule_set_id": rule_set_id},
        target=f"TaxRuleSet_{rule_set_id}",
        action_name="TAX_RULE_SET_DELETED", fn=run,
    )


@router.get("/rule-sets/{rule_set_id}/versions")
async def list_versions(
    rule_set_id: int,
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=MAX_PAGE_SIZE),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.view")
    exists = await db.scalar(
        select(TaxRuleSet.id).where(
            TaxRuleSet.company_id == actor.company_id,
            TaxRuleSet.id == rule_set_id,
        )
    )
    if exists is None:
        raise HTTPException(
            404,
            detail={
                "code": "TAX_RULE_SET_NOT_FOUND",
                "message": "Tax rule set was not found.",
                "context": {},
            },
        )
    rows = list(
        (
            await db.scalars(
                select(TaxRuleSetVersion)
                .where(
                    TaxRuleSetVersion.company_id == actor.company_id,
                    TaxRuleSetVersion.tax_rule_set_id == rule_set_id,
                    TaxRuleSetVersion.id > _cursor(cursor),
                )
                .order_by(TaxRuleSetVersion.id)
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
    await _require(db, actor, "tax.view")
    row = await db.scalar(
        select(TaxRuleSetVersion).where(
            TaxRuleSetVersion.company_id == actor.company_id,
            TaxRuleSetVersion.id == version_id,
        )
    )
    if row is None:
        raise HTTPException(
            404,
            detail={
                "code": "TAX_VERSION_NOT_FOUND",
                "message": "Tax version was not found.",
                "context": {},
            },
        )
    return {"version": (await _serialize_versions(db, [row]))[0]}


@router.post("/rule-sets/{rule_set_id}/versions", status_code=201)
async def add_version(
    rule_set_id: int,
    payload: VersionCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        row = await create_draft_version(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            rule_set_id=rule_set_id,
            expected_rule_set_version=payload.expected_rule_set_version,
            request_id=payload.request_id,
            priority=payload.priority,
            price_mode=payload.price_mode,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            components=payload.components,
            scopes=payload.scopes,
        )
        return {"version": (await _serialize_versions(db, [row]))[0]}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_VERSION_CREATE",
        scope={"rule_set_id": rule_set_id},
        target=f"TaxRuleSet_{rule_set_id}",
        action_name="TAX_VERSION_CREATED", fn=run,
    )


@router.put("/versions/{version_id}")
async def edit_version(
    version_id: int,
    payload: VersionUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        row = await update_draft_version(
            db,
            company_id=actor.company_id,
            version_id=version_id,
            expected_version=payload.expected_version,
            priority=payload.priority,
            price_mode=payload.price_mode,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            components=payload.components,
            scopes=payload.scopes,
        )
        return {"version": (await _serialize_versions(db, [row]))[0]}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_VERSION_UPDATE",
        scope={"version_id": version_id},
        target=f"TaxVersion_{version_id}",
        action_name="TAX_VERSION_UPDATED", fn=run,
    )


@router.delete("/versions/{version_id}")
async def remove_version(
    version_id: int,
    payload: VersionDelete,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.manage")

    async def run():
        await delete_draft_version(
            db,
            company_id=actor.company_id,
            version_id=version_id,
            expected_version=payload.expected_version,
        )
        return {"deleted": True, "version_id": version_id}

    return await _mutation(
        db=db, actor=actor, payload=payload,
        operation="TAX_VERSION_DELETE",
        scope={"version_id": version_id},
        target=f"TaxVersion_{version_id}",
        action_name="TAX_VERSION_DELETED", fn=run,
    )


@router.post("/versions/{version_id}/validate")
async def validate_tax_version(
    version_id: int,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "tax.view")
    try:
        result = await validate_version(
            db,
            company_id=actor.company_id,
            version_id=version_id,
        )
    except TaxError as exc:
        raise _http_error(exc) from exc
    return {"valid": True, **result}


async def _version_command(
    *,
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession,
    actor: Driver,
    action: str,
) -> dict[str, Any]:
    permission = "tax.approve" if action == "approve" else "tax.manage"
    await _require(db, actor, permission)

    async def run():
        if action == "submit":
            row = await submit_version(
                db,
                company_id=actor.company_id,
                version_id=version_id,
                expected_version=payload.expected_version,
            )
        elif action == "publish":
            row = await publish_version(
                db,
                company_id=actor.company_id,
                actor_id=actor.id,
                version_id=version_id,
                expected_version=payload.expected_version,
            )
        elif action == "approve":
            row = await approve_version(
                db,
                company_id=actor.company_id,
                actor_id=actor.id,
                version_id=version_id,
                expected_version=payload.expected_version,
            )
        elif action == "cancel":
            row = await cancel_version(
                db,
                company_id=actor.company_id,
                actor_id=actor.id,
                version_id=version_id,
                expected_version=payload.expected_version,
                reason=payload.reason,
            )
        else:
            raise RuntimeError("Unknown tax version command.")
        return {"version": (await _serialize_versions(db, [row]))[0]}

    action_names = {
        "submit": "TAX_VERSION_SUBMITTED",
        "publish": "TAX_VERSION_PUBLISHED",
        "approve": "TAX_VERSION_APPROVED",
        "cancel": "TAX_VERSION_CANCELLED",
    }
    return await _mutation(
        db=db,
        actor=actor,
        payload=payload,
        operation=f"TAX_VERSION_{action.upper()}",
        scope={"version_id": version_id},
        target=f"TaxVersion_{version_id}",
        action_name=action_names[action],
        fn=run,
    )


@router.post("/versions/{version_id}/submit")
async def submit_tax_version(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _version_command(
        version_id=version_id, payload=payload, db=db, actor=actor, action="submit"
    )


@router.post("/versions/{version_id}/publish")
async def publish_tax_version(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _version_command(
        version_id=version_id, payload=payload, db=db, actor=actor, action="publish"
    )


@router.post("/versions/{version_id}/approve")
async def approve_tax_version(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _version_command(
        version_id=version_id, payload=payload, db=db, actor=actor, action="approve"
    )


@router.post("/versions/{version_id}/cancel")
async def cancel_tax_version_endpoint(
    version_id: int,
    payload: VersionCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _version_command(
        version_id=version_id, payload=payload, db=db, actor=actor, action="cancel"
    )
