"""No-token custody API. Authentic BACKOFFICE and FIELD bearer dependencies only."""
from __future__ import annotations
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from api.authentication.field_authorization import require_field_capability
from api.authentication.dependencies import get_current_field_context
from database import get_db
from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.dispatch.route_execution.custody.proofs import CustodyRejected
from domains.dispatch.route_execution.custody.handoffs_read import (
    manager_current, field_pending, field_record, public_handoff, custody_history,
)
from domains.dispatch.route_execution.custody.handoffs_service import (
    manager_create, manager_cancel, manager_approve, field_decide,
)
from models import Driver
from .custody import _manager_vehicle

router = APIRouter()
field_execute = require_field_capability("work_session.execute")


class CreateHandoff(BaseModel):
    request_id: UUID
    target_driver_id: int = Field(gt=0)
    expected_context_revision: int = Field(ge=0)
    expected_stock_snapshot: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class Operation(BaseModel):
    request_id: UUID


class Decision(BaseModel):
    request_id: UUID
    decision: Literal["CONFIRM", "DECLINE"]
    confirmed_stock_snapshot: str | None = Field(None, pattern=r"^[a-fA-F0-9]{64}$")
    receiver_confirms_physical_count: StrictBool = False
    reason_code: Literal["DIFFERENCE", "NOT_MY_GOODS", "VEHICLE_UNAVAILABLE", "OTHER"] | None = None
    reason_text: str | None = Field(None, max_length=300)


def _error(exc: CustodyRejected, request_id: str | None = None):
    return HTTPException(exc.status, detail={
        "code": exc.code,
        "context": {"next_action": "REFRESH_OR_REISSUE_HANDOFF"},
        "request_id": request_id,
    })


@router.get("/vehicles/{vehicle_id}/custody/handoffs/current")
async def get_current_handoff(
    vehicle_id: int, db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _manager_vehicle(access, vehicle_id)
    try:
        return await manager_current(db, company_id=access.company_id, vehicle_id=vehicle_id)
    except CustodyRejected as exc:
        raise _error(exc) from exc


@router.post("/vehicles/{vehicle_id}/custody/handoffs")
async def create_vehicle_handoff(
    vehicle_id: int, command: CreateHandoff, db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    await _manager_vehicle(access, vehicle_id)
    try:
        row = await manager_create(
            db, company_id=access.company_id, vehicle_id=vehicle_id,
            manager_id=access.subject.principal_id, actor_id=actor.id,
            request_id=command.request_id, target_driver_id=command.target_driver_id,
            expected_context_revision=command.expected_context_revision,
            expected_stock_snapshot=command.expected_stock_snapshot,
        )
        return await public_handoff(db, row)
    except CustodyRejected as exc:
        await db.rollback()
        raise _error(exc, str(command.request_id)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise _error(CustodyRejected("CUSTODY_CONCURRENT_REQUEST"), str(command.request_id)) from exc


@router.post("/vehicles/{vehicle_id}/custody/handoffs/{handoff_id}/cancel")
async def cancel_vehicle_handoff(
    vehicle_id: int, handoff_id: int, command: Operation,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    await _manager_vehicle(access, vehicle_id)
    try:
        row = await manager_cancel(
            db, company_id=access.company_id, vehicle_id=vehicle_id,
            handoff_id=handoff_id, manager_id=access.subject.principal_id,
            actor_id=actor.id, request_id=command.request_id,
        )
        return await public_handoff(db, row)
    except CustodyRejected as exc:
        await db.rollback()
        raise _error(exc, str(command.request_id)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise _error(CustodyRejected("CUSTODY_CONCURRENT_CHANGE"), str(command.request_id)) from exc


@router.post("/vehicles/{vehicle_id}/custody/handoffs/{handoff_id}/approve")
async def approve_vehicle_handoff(
    vehicle_id: int, handoff_id: int, command: Operation,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    await _manager_vehicle(access, vehicle_id)
    try:
        _row, receipt = await manager_approve(
            db, company_id=access.company_id, vehicle_id=vehicle_id,
            handoff_id=handoff_id, manager_id=access.subject.principal_id,
            actor_id=actor.id, request_id=command.request_id,
        )
        return receipt
    except CustodyRejected as exc:
        await db.rollback()
        raise _error(exc, str(command.request_id)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise _error(CustodyRejected("CUSTODY_CONCURRENT_CHANGE"), str(command.request_id)) from exc


@router.get("/driver/custody/handoffs/pending", dependencies=[Depends(field_execute)])
async def own_pending_handoffs(
    field: FieldRequestContext = Depends(get_current_field_context),
    db: AsyncSession = Depends(get_db),
):
    return await field_pending(
        db, company_id=field.company_id, principal_id=field.principal_id,
        rep_id=field.representative_id,
    )


@router.get("/driver/custody/handoffs/{handoff_id}", dependencies=[Depends(field_execute)])
async def own_handoff_detail(
    handoff_id: int, field: FieldRequestContext = Depends(get_current_field_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await field_record(
            db, company_id=field.company_id, principal_id=field.principal_id,
            rep_id=field.representative_id, handoff_id=handoff_id,
        )
        result = await public_handoff(db, row)
        if result["state"] not in {"PENDING", "CONFIRMED"}:
            return dict(result, stock_lines=[])
        # Presentation is non-authoritative; the server's signed snapshot
        # remains bound to the original, unaggregated physical balances.
        from .custody_review import _stock_display
        state, lines, plate = await _stock_display(db, field.company_id, row.vehicle_id)
        if (state.stock_snapshot != row.expected_stock_snapshot or
                state.revision != row.expected_context_revision or
                state.location_id != row.vehicle_location_id):
            raise CustodyRejected("CUSTODY_STOCK_SNAPSHOT_STALE")
        return dict(result, vehicle_plate=plate, stock_lines=lines)
    except CustodyRejected as exc:
        raise _error(exc) from exc


@router.post("/driver/custody/handoffs/{handoff_id}/decision", dependencies=[Depends(field_execute)])
async def decide_own_handoff(
    handoff_id: int, command: Decision,
    field: FieldRequestContext = Depends(get_current_field_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        row = await field_decide(
            db, field=field, handoff_id=handoff_id, request_id=command.request_id,
            decision=command.decision, stock_snapshot=command.confirmed_stock_snapshot,
            physical_count=command.receiver_confirms_physical_count,
            reason_code=command.reason_code, reason_text=command.reason_text,
        )
        return await public_handoff(db, row)
    except CustodyRejected as exc:
        await db.rollback()
        raise _error(exc, str(command.request_id)) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise _error(CustodyRejected("CUSTODY_CONCURRENT_CHANGE"), str(command.request_id)) from exc


@router.get("/vehicles/{vehicle_id}/custody/history")
async def vehicle_custody_history(
    vehicle_id: int, limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _manager_vehicle(access, vehicle_id)
    return await custody_history(
        db, company_id=access.company_id, vehicle_id=vehicle_id, limit=limit,
    )
