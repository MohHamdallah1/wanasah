"""Tenant-scoped branch administration and bounded warehouse branch options."""

import base64
import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_admin, get_current_driver
from database import get_db
from inventory_access import InventoryAccess
from models import Branch, Driver, SystemAuditLog
from schemas import (
    BranchCreateRequest,
    BranchCursorPage,
    BranchMutationResponse,
    BranchStateRequest,
    BranchUpdateRequest,
)
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)


router = APIRouter(prefix="/warehouse/branches", tags=["Warehouse Branches"])
logger = logging.getLogger("wanasah_logger")


def _stable_request_hash(payload, *, branch_id: Optional[int] = None) -> str:
    body = payload.model_dump(mode="json", exclude={"request_id"})
    if branch_id is not None:
        body["branch_id"] = int(branch_id)
    canonical = json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _escape_like(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _cursor_scope_hash(scope: str) -> str:
    return hashlib.sha256(scope.encode("utf-8")).hexdigest()[:24]


def _encode_cursor(branch_id: int, *, scope: str) -> str:
    raw = json.dumps(
        {
            "v": 1,
            "kind": "branch",
            "scope": _cursor_scope_hash(scope),
            "id": int(branch_id),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, *, expected_scope: str) -> int:
    try:
        padding = "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode((cursor + padding).encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
        if (
            not isinstance(payload, dict)
            or payload.get("v") != 1
            or payload.get("kind") != "branch"
            or payload.get("scope") != _cursor_scope_hash(expected_scope)
        ):
            raise ValueError
        branch_id = payload.get("id")
        if type(branch_id) is not int or branch_id <= 0:
            raise ValueError
        return branch_id
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Cursor الفروع غير صالح أو لا يطابق نطاق البحث الحالي.",
        ) from exc


def _as_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def _branch_payload(branch: Branch) -> dict:
    return {
        "id": int(branch.id),
        "name": str(branch.name),
        "code": str(branch.branch_code),
        "is_active": bool(branch.is_active),
        "created_at": _as_iso(branch.created_at),
    }


async def _load_locked_branch(
    db: AsyncSession,
    *,
    company_id: int,
    branch_id: int,
) -> Branch:
    branch = await db.scalar(
        select(Branch)
        .where(Branch.company_id == company_id, Branch.id == branch_id)
        .with_for_update()
    )
    if branch is None:
        raise HTTPException(status_code=404, detail="الفرع غير موجود أو لا يتبع شركتك.")
    return branch


async def _list_branches(
    db: AsyncSession,
    *,
    company_id: int,
    search: Optional[str],
    include_inactive: bool,
    cursor: Optional[str],
    limit: int,
    mode: str,
) -> dict:
    clean_search = (search or "").strip().lower()
    scope = f"branches|{company_id}|{mode}|{1 if include_inactive else 0}|{clean_search}"
    stmt = select(Branch).where(Branch.company_id == company_id)

    if not include_inactive:
        stmt = stmt.where(Branch.is_active.is_(True))
    if clean_search:
        pattern = f"%{_escape_like(clean_search)}%"
        stmt = stmt.where(
            or_(
                func.lower(Branch.name).like(pattern, escape="\\"),
                func.lower(Branch.branch_code).like(pattern, escape="\\"),
            )
        )

    total = None
    if cursor is None:
        total = int(
            await db.scalar(
                select(func.count()).select_from(
                    stmt.with_only_columns(Branch.id, maintain_column_froms=True)
                    .order_by(None)
                    .subquery()
                )
            )
            or 0
        )
    else:
        stmt = stmt.where(Branch.id > _decode_cursor(cursor, expected_scope=scope))

    rows = list((await db.scalars(stmt.order_by(Branch.id.asc()).limit(limit + 1))).all())
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {
        "items": [_branch_payload(branch) for branch in rows],
        "next_cursor": _encode_cursor(rows[-1].id, scope=scope) if has_more and rows else None,
        "has_more": has_more,
        "total": total,
    }


@router.get("/options", response_model=BranchCursorPage, status_code=200)
async def list_branch_options(
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_driver: Driver = Depends(get_current_driver),
):
    access = InventoryAccess(db, current_driver)
    await access.require(("location.create", "location.update"), any_location=True)
    return await _list_branches(
        db,
        company_id=current_driver.company_id,
        search=search,
        include_inactive=False,
        cursor=cursor,
        limit=limit,
        mode="options",
    )


@router.get("/manage", response_model=BranchCursorPage, status_code=200)
async def manage_branches(
    search: Optional[str] = Query(default=None, min_length=2, max_length=100),
    include_inactive: bool = Query(default=True),
    cursor: Optional[str] = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    return await _list_branches(
        db,
        company_id=current_admin.company_id,
        search=search,
        include_inactive=include_inactive,
        cursor=cursor,
        limit=limit,
        mode="manage",
    )


@router.post("", response_model=BranchMutationResponse, status_code=201)
async def create_branch(
    payload: BranchCreateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    try:
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="BRANCH_CREATE",
            request_id=str(payload.request_id),
            request_hash=_stable_request_hash(payload),
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        duplicate = await db.scalar(
            select(Branch.id).where(
                Branch.company_id == company_id,
                Branch.branch_code == payload.code,
            ).limit(1)
        )
        if duplicate is not None:
            raise HTTPException(status_code=409, detail="كود الفرع مستخدم مسبقاً داخل شركتك.")

        branch = Branch(
            company_id=company_id,
            name=payload.name,
            branch_code=payload.code,
            is_active=True,
        )
        db.add(branch)
        await db.flush()
        branch_data = _branch_payload(branch)
        db.add(SystemAuditLog(
            company_id=company_id,
            admin_id=current_admin.id,
            target_id=f"Branch_{branch.id}",
            action_type="BRANCH_CREATED",
            old_value=None,
            new_value=json.dumps(branch_data, sort_keys=True, ensure_ascii=False),
        ))
        response = {"message": "تم إنشاء الفرع بنجاح.", "branch": branch_data}
        complete_idempotent_operation(idempotency_record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="تعذر إنشاء الفرع بسبب تعارض متزامن أو كود مكرر.")
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في إنشاء الفرع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء إنشاء الفرع.")


@router.patch("/{branch_id}", response_model=BranchMutationResponse, status_code=200)
async def update_branch(
    branch_id: int,
    payload: BranchUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    company_id = current_admin.company_id
    try:
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation="BRANCH_UPDATE",
            request_id=str(payload.request_id),
            request_hash=_stable_request_hash(payload, branch_id=branch_id),
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        branch = await _load_locked_branch(
            db,
            company_id=company_id,
            branch_id=branch_id,
        )
        old_data = _branch_payload(branch)

        if "code" in payload.model_fields_set:
            duplicate = await db.scalar(
                select(Branch.id).where(
                    Branch.company_id == company_id,
                    Branch.branch_code == payload.code,
                    Branch.id != branch.id,
                ).limit(1)
            )
            if duplicate is not None:
                raise HTTPException(status_code=409, detail="كود الفرع مستخدم مسبقاً داخل شركتك.")
            branch.branch_code = payload.code
        if "name" in payload.model_fields_set:
            branch.name = payload.name

        await db.flush()
        branch_data = _branch_payload(branch)
        if branch_data != old_data:
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"Branch_{branch.id}",
                action_type="BRANCH_UPDATED",
                old_value=json.dumps(old_data, sort_keys=True, ensure_ascii=False),
                new_value=json.dumps(branch_data, sort_keys=True, ensure_ascii=False),
            ))
        response = {"message": "تم تحديث الفرع بنجاح.", "branch": branch_data}
        complete_idempotent_operation(idempotency_record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="تعذر تحديث الفرع بسبب تعارض متزامن أو كود مكرر.")
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تحديث الفرع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تحديث الفرع.")


async def _change_branch_state(
    *,
    branch_id: int,
    payload: BranchStateRequest,
    activate: bool,
    db: AsyncSession,
    current_admin: Driver,
) -> dict:
    company_id = current_admin.company_id
    reason = (payload.reason or "").strip()
    if not activate and not reason:
        raise HTTPException(status_code=422, detail="سبب تعطيل الفرع مطلوب للتدقيق.")

    operation = "BRANCH_ACTIVATE" if activate else "BRANCH_DEACTIVATE"
    try:
        idempotency_record, replay_response = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=current_admin.id,
            operation=operation,
            request_id=str(payload.request_id),
            request_hash=_stable_request_hash(payload, branch_id=branch_id),
        )
        if replay_response is not None:
            await db.rollback()
            return replay_response

        branch = await _load_locked_branch(
            db,
            company_id=company_id,
            branch_id=branch_id,
        )
        old_state = bool(branch.is_active)
        branch.is_active = activate
        await db.flush()
        branch_data = _branch_payload(branch)
        if old_state != activate:
            db.add(SystemAuditLog(
                company_id=company_id,
                admin_id=current_admin.id,
                target_id=f"Branch_{branch.id}",
                action_type="BRANCH_ACTIVATED" if activate else "BRANCH_DEACTIVATED",
                old_value="active" if old_state else "inactive",
                new_value=reason or ("active" if activate else "inactive"),
            ))
        response = {
            "message": "تم تفعيل الفرع بنجاح." if activate else "تم تعطيل الفرع بنجاح.",
            "branch": branch_data,
        }
        complete_idempotent_operation(idempotency_record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        await db.rollback()
        logger.error(f"خطأ في تغيير حالة الفرع: {str(exc)}", exc_info=True)
        raise HTTPException(status_code=500, detail="خطأ داخلي أثناء تغيير حالة الفرع.")


@router.post("/{branch_id}/activate", response_model=BranchMutationResponse, status_code=200)
async def activate_branch(
    branch_id: int,
    payload: BranchStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    return await _change_branch_state(
        branch_id=branch_id,
        payload=payload,
        activate=True,
        db=db,
        current_admin=current_admin,
    )


@router.post("/{branch_id}/deactivate", response_model=BranchMutationResponse, status_code=200)
async def deactivate_branch(
    branch_id: int,
    payload: BranchStateRequest,
    db: AsyncSession = Depends(get_db),
    current_admin: Driver = Depends(get_current_admin),
):
    return await _change_branch_state(
        branch_id=branch_id,
        payload=payload,
        activate=False,
        db=db,
        current_admin=current_admin,
    )

