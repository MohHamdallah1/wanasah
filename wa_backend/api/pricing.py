from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from domains.pricing.core import PricingError, maker_checker_enabled
from domains.pricing.publishing import (
    approve_publication,
    cancel_publication,
    create_assignment,
    create_draft_entry,
    create_price_book,
    create_publication,
    delete_draft_entry,
    publish_publication,
    submit_publication,
    update_draft_entry,
)
from domains.pricing.resolver import resolve_price
from inventory_access import InventoryAccess
from models import (
    Driver,
    PriceBook,
    PriceBookAssignment,
    PriceBookEntry,
    PricePublication,
    SystemAuditLog,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter(prefix="/pricing", tags=["Pricing"])


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _request_hash(payload: BaseModel, **scope: Any) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    body.update(scope)
    encoded = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _cursor(value: Optional[str]) -> int:
    if value is None:
        return 0
    try:
        raw = base64.urlsafe_b64decode(
            value + "=" * (-len(value) % 4)
        ).decode("ascii")
        parsed = int(raw)
    except Exception as exc:
        raise HTTPException(
            400,
            detail={
                "code": "INVALID_CURSOR",
                "message": "Cursor التسعير غير صالح.",
                "context": {},
            },
        ) from exc
    if parsed <= 0:
        raise HTTPException(
            400,
            detail={
                "code": "INVALID_CURSOR",
                "message": "Cursor التسعير غير صالح.",
                "context": {},
            },
        )
    return parsed


def _next_cursor(value: int) -> str:
    return base64.urlsafe_b64encode(str(value).encode("ascii")).decode(
        "ascii"
    ).rstrip("=")


def _canonical_money(value: Decimal) -> str:
    return format(Decimal(value), ".6f")


async def _require(
    db: AsyncSession, actor: Driver, permission: str
) -> None:
    await InventoryAccess(db, actor).require(permission, any_location=True)


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
                payload, ensure_ascii=False, default=str, sort_keys=True
            ),
        )
    )


def _pricing_http_error(exc: PricingError) -> HTTPException:
    return HTTPException(exc.status_code, detail=exc.as_detail())


def _book_row(row: PriceBook) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "code": row.code,
        "name": row.name,
        "currency_code": row.currency_code,
        "status": row.status,
        "applicability_metadata": dict(row.applicability_metadata or {}),
        "version": int(row.version),
        "created_by": int(row.created_by),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _publication_row(row: PricePublication) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "price_book_id": int(row.price_book_id),
        "revision": int(row.revision),
        "status": row.status,
        "effective_at": row.effective_at.isoformat()
        if row.effective_at
        else None,
        "created_by": int(row.created_by),
        "approved_by": int(row.approved_by)
        if row.approved_by is not None
        else None,
        "approved_at": row.approved_at.isoformat()
        if row.approved_at
        else None,
        "published_at": row.published_at.isoformat()
        if row.published_at
        else None,
        "request_id": str(row.request_id),
        "version": int(row.version),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def _entry_row(row: PriceBookEntry) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "price_book_id": int(row.price_book_id),
        "publication_id": int(row.publication_id),
        "product_variant_id": int(row.product_variant_id),
        "uom_id": int(row.uom_id),
        "amount": _canonical_money(row.amount),
        "effective_from": row.effectivity.lower.isoformat(),
        "effective_to": row.effectivity.upper.isoformat()
        if row.effectivity.upper is not None
        else None,
        "priority": int(row.priority),
        "metadata": dict(row.entry_metadata or {}),
        "is_published": bool(row.is_published),
        "version": int(row.version),
    }


def _assignment_row(row: PriceBookAssignment) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "price_book_id": int(row.price_book_id),
        "scope_type": row.scope_type,
        "scope_id": int(row.scope_id) if row.scope_id is not None else None,
        "priority": int(row.priority),
        "effective_from": row.effectivity.lower.isoformat(),
        "effective_to": row.effectivity.upper.isoformat()
        if row.effectivity.upper is not None
        else None,
        "revision": int(row.revision),
        "version": int(row.version),
        "created_by": int(row.created_by),
    }


class PriceBookCreate(StrictRequest):
    request_id: UUID
    code: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=150)
    currency_code: str = Field(min_length=3, max_length=10)
    applicability_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("code", "currency_code", mode="before")
    @classmethod
    def normalize_codes(cls, value: Any) -> str:
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("القيمة النصية غير صالحة.")
        clean = value.strip().upper()
        if not clean:
            raise ValueError("القيمة مطلوبة.")
        return clean

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, value: Any) -> str:
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("name غير صالح.")
        clean = value.strip()
        if not clean:
            raise ValueError("name مطلوب.")
        return clean


class PublicationCreate(StrictRequest):
    request_id: UUID
    expected_book_version: int = Field(gt=0)
    effective_at: datetime


class EntryCreate(StrictRequest):
    request_id: UUID
    expected_publication_version: int = Field(gt=0)
    product_variant_id: int = Field(gt=0)
    uom_id: int = Field(gt=0)
    amount: Decimal
    effective_from: datetime
    effective_to: Optional[datetime] = None
    priority: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntryUpdate(StrictRequest):
    request_id: UUID
    expected_entry_version: int = Field(gt=0)
    expected_publication_version: int = Field(gt=0)
    amount: Decimal
    effective_from: datetime
    effective_to: Optional[datetime] = None
    priority: int = Field(default=0, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class EntryDelete(StrictRequest):
    request_id: UUID
    expected_entry_version: int = Field(gt=0)
    expected_publication_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)


class PublicationCommand(StrictRequest):
    request_id: UUID
    expected_version: int = Field(gt=0)
    reason: str = Field(min_length=3, max_length=1000)


class AssignmentCreate(StrictRequest):
    request_id: UUID
    price_book_id: int = Field(gt=0)
    scope_type: Literal[
        "CUSTOMER",
        "BRANCH",
        "COMPANY_DEFAULT",
        "CUSTOMER_GROUP",
        "CHANNEL",
    ]
    scope_id: Optional[int] = Field(None, gt=0)
    priority: int = Field(default=0, ge=0)
    effective_from: datetime
    effective_to: Optional[datetime] = None


class ResolvePreview(StrictRequest):
    product_variant_id: int = Field(gt=0)
    uom_id: int = Field(gt=0)
    customer_id: Optional[int] = Field(None, gt=0)
    branch_id: Optional[int] = Field(None, gt=0)
    as_of: Optional[datetime] = None
    price_publication_revision: Optional[int] = Field(None, gt=0)
    assignment_revision: Optional[int] = Field(None, gt=0)


@router.get("/policy")
async def get_pricing_policy(
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.view")
    try:
        enabled = await maker_checker_enabled(db, actor.company_id)
    except PricingError as exc:
        raise _pricing_http_error(exc) from exc
    return {"maker_checker_enabled": enabled}


@router.get("/books")
async def list_books(
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.view")
    rows = list(
        (
            await db.scalars(
                select(PriceBook)
                .where(
                    PriceBook.company_id == actor.company_id,
                    PriceBook.id > _cursor(cursor),
                )
                .order_by(PriceBook.id.asc())
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_book_row(row) for row in page],
        "next_cursor": _next_cursor(page[-1].id)
        if has_more and page
        else None,
        "has_more": has_more,
    }


@router.post("/books", status_code=201)
async def add_book(
    payload: PriceBookCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRICING_BOOK_CREATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await create_price_book(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            code=payload.code,
            name=payload.name,
            currency_code=payload.currency_code,
            applicability_metadata=payload.applicability_metadata,
        )
        response = {"price_book": _book_row(row)}
        _audit(db, actor, f"PriceBook_{row.id}", "PRICE_BOOK_CREATED", response)
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "PRICE_BOOK_CONFLICT",
                "message": "كود دفتر الأسعار مستخدم داخل الشركة.",
                "context": {},
            },
        ) from exc


@router.get("/books/{book_id}/publications")
async def list_publications(
    book_id: int,
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.view")
    if await db.scalar(
        select(PriceBook.id).where(
            PriceBook.company_id == actor.company_id,
            PriceBook.id == book_id,
        )
    ) is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRICE_BOOK_NOT_FOUND",
                "message": "دفتر الأسعار غير موجود.",
                "context": {},
            },
        )
    rows = list(
        (
            await db.scalars(
                select(PricePublication)
                .where(
                    PricePublication.company_id == actor.company_id,
                    PricePublication.price_book_id == book_id,
                    PricePublication.id > _cursor(cursor),
                )
                .order_by(PricePublication.id.asc())
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_publication_row(row) for row in page],
        "next_cursor": _next_cursor(page[-1].id)
        if has_more and page
        else None,
        "has_more": has_more,
    }


@router.post("/books/{book_id}/publications", status_code=201)
async def add_publication(
    book_id: int,
    payload: PublicationCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRICING_PUBLICATION_CREATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload, book_id=book_id),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await create_publication(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            book_id=book_id,
            expected_book_version=payload.expected_book_version,
            effective_at=payload.effective_at,
            request_id=payload.request_id,
        )
        response = {"publication": _publication_row(row)}
        _audit(
            db,
            actor,
            f"PricePublication_{row.id}",
            "PRICE_PUBLICATION_CREATED",
            response,
        )
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except (InventoryMutationError, IntegrityError) as exc:
        await db.rollback()
        if isinstance(exc, InventoryMutationError):
            code = "IDEMPOTENCY_CONFLICT"
            message = str(exc)
        else:
            code = "PRICE_PUBLICATION_CONFLICT"
            message = "تعارض أثناء إنشاء نسخة النشر."
        raise HTTPException(
            409,
            detail={"code": code, "message": message, "context": {}},
        ) from exc


@router.get("/publications/{publication_id}/entries")
async def list_entries(
    publication_id: int,
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.view")
    if await db.scalar(
        select(PricePublication.id).where(
            PricePublication.company_id == actor.company_id,
            PricePublication.id == publication_id,
        )
    ) is None:
        raise HTTPException(
            404,
            detail={
                "code": "PRICE_PUBLICATION_NOT_FOUND",
                "message": "نسخة النشر غير موجودة.",
                "context": {},
            },
        )
    rows = list(
        (
            await db.scalars(
                select(PriceBookEntry)
                .where(
                    PriceBookEntry.company_id == actor.company_id,
                    PriceBookEntry.publication_id == publication_id,
                    PriceBookEntry.id > _cursor(cursor),
                )
                .order_by(PriceBookEntry.id.asc())
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_entry_row(row) for row in page],
        "next_cursor": _next_cursor(page[-1].id)
        if has_more and page
        else None,
        "has_more": has_more,
    }


@router.post("/publications/{publication_id}/entries", status_code=201)
async def add_entry(
    publication_id: int,
    payload: EntryCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRICING_ENTRY_CREATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(
                payload, publication_id=publication_id
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await create_draft_entry(
            db,
            company_id=actor.company_id,
            publication_id=publication_id,
            expected_publication_version=payload.expected_publication_version,
            product_variant_id=payload.product_variant_id,
            uom_id=payload.uom_id,
            amount=payload.amount,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            priority=payload.priority,
            metadata=payload.metadata,
        )
        response = {"entry": _entry_row(row)}
        _audit(db, actor, f"PriceEntry_{row.id}", "PRICE_ENTRY_CREATED", response)
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except (InventoryMutationError, IntegrityError) as exc:
        await db.rollback()
        if isinstance(exc, InventoryMutationError):
            code = "IDEMPOTENCY_CONFLICT"
            message = str(exc)
        else:
            code = "PRICE_EFFECTIVITY_CONFLICT"
            message = "تعارض في فترة سعر الإدخال."
        raise HTTPException(
            409,
            detail={"code": code, "message": message, "context": {}},
        ) from exc


@router.patch("/entries/{entry_id}")
async def edit_entry(
    entry_id: int,
    payload: EntryUpdate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRICING_ENTRY_UPDATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload, entry_id=entry_id),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await update_draft_entry(
            db,
            company_id=actor.company_id,
            entry_id=entry_id,
            expected_entry_version=payload.expected_entry_version,
            expected_publication_version=payload.expected_publication_version,
            amount=payload.amount,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
            priority=payload.priority,
            metadata=payload.metadata,
        )
        response = {"entry": _entry_row(row)}
        _audit(db, actor, f"PriceEntry_{row.id}", "PRICE_ENTRY_UPDATED", response)
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except (InventoryMutationError, IntegrityError) as exc:
        await db.rollback()
        if isinstance(exc, InventoryMutationError):
            code = "IDEMPOTENCY_CONFLICT"
            message = str(exc)
        else:
            code = "PRICE_ENTRY_CONFLICT"
            message = "تعارض أثناء تحديث إدخال السعر."
        raise HTTPException(
            409,
            detail={"code": code, "message": message, "context": {}},
        ) from exc


@router.delete("/entries/{entry_id}")
async def remove_entry(
    entry_id: int,
    payload: EntryDelete,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRICING_ENTRY_DELETE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload, entry_id=entry_id),
        )
        if replay is not None:
            await db.rollback()
            return replay
        publication_version = await delete_draft_entry(
            db,
            company_id=actor.company_id,
            entry_id=entry_id,
            expected_entry_version=payload.expected_entry_version,
            expected_publication_version=payload.expected_publication_version,
        )
        response = {
            "deleted_entry_id": entry_id,
            "publication_version": publication_version,
        }
        _audit(db, actor, f"PriceEntry_{entry_id}", "PRICE_ENTRY_DELETED", response)
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc


async def _publication_command(
    *,
    operation: str,
    action_type: str,
    permission: str,
    fn,
    publication_id: int,
    payload: PublicationCommand,
    db: AsyncSession,
    actor: Driver,
):
    await _require(db, actor, permission)
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation=operation,
            request_id=str(payload.request_id),
            request_hash=_request_hash(
                payload, publication_id=publication_id
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await fn(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            publication_id=publication_id,
            expected_version=payload.expected_version,
        )
        response = {"publication": _publication_row(row)}
        _audit(
            db,
            actor,
            f"PricePublication_{row.id}",
            action_type,
            {"reason": payload.reason, **response},
        )
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "PRICE_EFFECTIVITY_CONFLICT",
                "message": "تعارض زمني أثناء نشر الأسعار.",
                "context": {},
            },
        ) from exc


@router.post("/publications/{publication_id}/submit")
async def submit(
    publication_id: int,
    payload: PublicationCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _publication_command(
        operation="PRICING_PUBLICATION_SUBMIT",
        action_type="PRICE_PUBLICATION_SUBMITTED",
        permission="pricing.manage",
        fn=submit_publication,
        publication_id=publication_id,
        payload=payload,
        db=db,
        actor=actor,
    )


@router.post("/publications/{publication_id}/approve")
async def approve(
    publication_id: int,
    payload: PublicationCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _publication_command(
        operation="PRICING_PUBLICATION_APPROVE",
        action_type="PRICE_PUBLICATION_APPROVED",
        permission="pricing.approve",
        fn=approve_publication,
        publication_id=publication_id,
        payload=payload,
        db=db,
        actor=actor,
    )


@router.post("/publications/{publication_id}/publish")
async def publish(
    publication_id: int,
    payload: PublicationCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    return await _publication_command(
        operation="PRICING_PUBLICATION_PUBLISH",
        action_type="PRICE_PUBLICATION_PUBLISHED",
        permission="pricing.manage",
        fn=publish_publication,
        publication_id=publication_id,
        payload=payload,
        db=db,
        actor=actor,
    )


@router.post("/publications/{publication_id}/cancel")
async def cancel(
    publication_id: int,
    payload: PublicationCommand,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRICING_PUBLICATION_CANCEL",
            request_id=str(payload.request_id),
            request_hash=_request_hash(
                payload, publication_id=publication_id
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await cancel_publication(
            db,
            company_id=actor.company_id,
            publication_id=publication_id,
            expected_version=payload.expected_version,
        )
        response = {"publication": _publication_row(row)}
        _audit(
            db,
            actor,
            f"PricePublication_{row.id}",
            "PRICE_PUBLICATION_CANCELLED",
            {"reason": payload.reason, **response},
        )
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(
            409,
            detail={
                "code": "IDEMPOTENCY_CONFLICT",
                "message": str(exc),
                "context": {},
            },
        ) from exc


@router.get("/assignments")
async def list_assignments(
    cursor: Optional[str] = Query(None, max_length=512),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.view")
    rows = list(
        (
            await db.scalars(
                select(PriceBookAssignment)
                .where(
                    PriceBookAssignment.company_id == actor.company_id,
                    PriceBookAssignment.id > _cursor(cursor),
                )
                .order_by(PriceBookAssignment.id.asc())
                .limit(limit + 1)
            )
        ).all()
    )
    page, has_more = rows[:limit], len(rows) > limit
    return {
        "items": [_assignment_row(row) for row in page],
        "next_cursor": _next_cursor(page[-1].id)
        if has_more and page
        else None,
        "has_more": has_more,
    }


@router.post("/assignments", status_code=201)
async def add_assignment(
    payload: AssignmentCreate,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.manage")
    try:
        record, replay = await begin_idempotent_operation(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            operation="PRICING_ASSIGNMENT_CREATE",
            request_id=str(payload.request_id),
            request_hash=_request_hash(payload),
        )
        if replay is not None:
            await db.rollback()
            return replay
        row = await create_assignment(
            db,
            company_id=actor.company_id,
            actor_id=actor.id,
            price_book_id=payload.price_book_id,
            scope_type=payload.scope_type,
            scope_id=payload.scope_id,
            priority=payload.priority,
            effective_from=payload.effective_from,
            effective_to=payload.effective_to,
        )
        response = {"assignment": _assignment_row(row)}
        _audit(
            db,
            actor,
            f"PriceBookAssignment_{row.id}",
            "PRICE_ASSIGNMENT_CREATED",
            response,
        )
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except PricingError as exc:
        await db.rollback()
        raise _pricing_http_error(exc)
    except (InventoryMutationError, IntegrityError) as exc:
        await db.rollback()
        if isinstance(exc, InventoryMutationError):
            code = "IDEMPOTENCY_CONFLICT"
            message = str(exc)
        else:
            code = "PRICE_EFFECTIVITY_CONFLICT"
            message = "تعارض زمني في PriceBook Assignment."
        raise HTTPException(
            409,
            detail={"code": code, "message": message, "context": {}},
        ) from exc


@router.post("/resolve-preview")
async def resolve_preview(
    payload: ResolvePreview,
    db: AsyncSession = Depends(get_db),
    actor: Driver = Depends(get_current_driver),
):
    await _require(db, actor, "pricing.view")
    try:
        row = await resolve_price(
            db,
            company_id=actor.company_id,
            product_variant_id=payload.product_variant_id,
            uom_id=payload.uom_id,
            customer_id=payload.customer_id,
            branch_id=payload.branch_id,
            as_of=payload.as_of,
            publication_revision_ceiling=payload.price_publication_revision,
            assignment_revision_ceiling=payload.assignment_revision,
        )
        return {
            "price_book_id": row.price_book_id,
            "assignment": {
                "id": row.assignment_id,
                "revision": row.assignment_revision,
                "scope_type": row.assignment_scope_type,
                "priority": row.assignment_priority,
            },
            "price": {
                "entry_id": row.price_entry_id,
                "publication_id": row.price_publication_id,
                "publication_revision": row.price_publication_revision,
                "product_variant_id": row.product_variant_id,
                "uom_id": row.uom_id,
                "amount": _canonical_money(row.amount),
                "currency_code": row.currency_code,
            },
            "resolved_at": row.resolved_at.isoformat(),
        }
    except PricingError as exc:
        raise _pricing_http_error(exc)
