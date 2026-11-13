"""Thin HTTP adapters for signed vehicle-custody recovery; no stock writes."""
from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from api.authentication.field_authorization import require_field_capability
from api.authentication.dependencies import get_current_field_context
from database import get_db
from domains.dispatch.route_execution.custody.access import require_custody_vehicle_scope
from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.backoffice_access import BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected
from domains.dispatch.route_execution.custody.proofs import CustodyRejected
from domains.dispatch.route_execution.custody.service import (
    accept_custody, confirm_receiver, custody_readiness, issue_offer,
)
from models import Driver

router = APIRouter()
_field_work_session = require_field_capability("work_session.execute")

class CustodyOfferCommand(BaseModel):
    target_driver_id: int = Field(gt=0)
    expected_context_revision: int = Field(ge=0)
    expected_stock_snapshot: str = Field(min_length=64, max_length=64)

class CustodyConfirmCommand(BaseModel):
    offer_token: str = Field(min_length=50, max_length=2048)
    confirmed_stock_snapshot: str = Field(min_length=64, max_length=64)
    receiver_confirms_physical_count: StrictBool

class CustodyAcceptCommand(BaseModel):
    request_id: UUID
    receiver_proof: str = Field(min_length=50, max_length=2048)

def _error(exc: CustodyRejected, request_id: str | None = None):
    return HTTPException(status_code=exc.status, detail={
        "code": exc.code, "context": {}, "request_id": request_id,
    })

async def _manager_vehicle(access: BackofficeCapabilityAccess, vehicle_id: int):
    try:
        await access.require("vehicle.manage")
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(403, detail={"code": "CUSTODY_MANAGER_CAPABILITY_DENIED"}) from None
    await require_custody_vehicle_scope(access, vehicle_id)

@router.get("/vehicles/{vehicle_id}/custody/readiness")
async def read_vehicle_custody_recovery(
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _manager_vehicle(access, vehicle_id)
    try:
        return await custody_readiness(db, company_id=access.company_id, vehicle_id=vehicle_id)
    except CustodyRejected as exc:
        raise _error(exc) from exc

@router.post("/vehicles/{vehicle_id}/custody/offer")
async def offer_vehicle_custody_recovery(
    vehicle_id: int, command: CustodyOfferCommand,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _manager_vehicle(access, vehicle_id)
    try:
        return await issue_offer(
            db, company_id=access.company_id, vehicle_id=vehicle_id,
            target_driver_id=command.target_driver_id,
            expected_revision=command.expected_context_revision,
            expected_snapshot=command.expected_stock_snapshot,
            manager_principal_id=access.subject.principal_id,
        )
    except CustodyRejected as exc:
        await db.rollback()
        raise _error(exc) from exc

@router.post("/driver/vehicles/{vehicle_id}/custody/confirm", dependencies=[Depends(_field_work_session)])
async def confirm_field_vehicle_custody(
    vehicle_id: int, command: CustodyConfirmCommand,
    field: FieldRequestContext = Depends(get_current_field_context),
):
    try:
        return confirm_receiver(
            offer_token=command.offer_token, company_id=field.company_id,
            vehicle_id=vehicle_id, field_principal_id=field.principal_id,
            field_representative_id=field.representative_id,
            confirms_physical_count=command.receiver_confirms_physical_count,
            confirmed_stock_snapshot=command.confirmed_stock_snapshot,
            receiver_auth_revision=field.auth_revision,
        )
    except CustodyRejected as exc:
        raise _error(exc) from exc

@router.post("/vehicles/{vehicle_id}/custody/accept", status_code=201)
async def accept_vehicle_custody_recovery(
    vehicle_id: int, command: CustodyAcceptCommand,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    await _manager_vehicle(access, vehicle_id)
    request_id = str(command.request_id)
    try:
        return await accept_custody(
            db, company_id=access.company_id, vehicle_id=vehicle_id,
            manager_principal_id=access.subject.principal_id,
            legacy_actor_id=actor.id,
            request_id=request_id, receiver_proof=command.receiver_proof,
        )
    except CustodyRejected as exc:
        await db.rollback()
        raise _error(exc, request_id) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(409, detail={
            "code": "CUSTODY_CONCURRENT_CHANGE", "context": {},
            "request_id": request_id,
        }) from exc
