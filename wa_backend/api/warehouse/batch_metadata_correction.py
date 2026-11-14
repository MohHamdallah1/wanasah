"""#773 manager-only, reauthenticated, current descriptive Batch correction."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected,
)
from domains.identity.authentication import verify_existing_password
from domains.identity.models import CompanyPrincipal
from domains.identity.types import PrincipalType
from domains.inventory_batch_metadata.service import (
    BatchCorrectionRejected, correction_history, correct_current_metadata, inspect_batch,
)
from models import Driver, InventoryMovement, SystemAuditLog
from services import (
    acquire_inventory_location_guard, OperationIdempotencyError,
    begin_idempotent_operation, complete_idempotent_operation, get_company_local_date,
)

router = APIRouter()


class CorrectBatchMetadata(BaseModel):
    request_id: UUID
    expected_revision: int = Field(ge=1)
    location_id: int = Field(gt=0)
    batch_number: str = Field(min_length=1, max_length=100)
    production_date: date | None
    expiry_date: date | None
    reason: str = Field(min_length=8, max_length=500)
    password: str = Field(min_length=1, max_length=128)


def _error(code: str, status: int = 409) -> HTTPException:
    return HTTPException(status, detail={
        "code": code,
        "message": "لا يمكن تعديل هذه التشغيلة مباشرة لأنها استُخدمت في حركة مخزون؛ اعزلها واطلب مراجعة المسؤول",
        "context": {"next_action": "QUARANTINE_AND_MANAGER_REVIEW"},
    })


async def _access(access: BackofficeCapabilityAccess, location_id: int) -> None:
    try:
        # A company-level manager capability PLUS the actual warehouse scope
        # are both mandatory. FIELD and ordinary inbound-only employees fail.
        await access.require("batch.disposition")
        await access.require("inbound.create", location_id)
    except BackofficeCapabilityAccessRejected as exc:
        raise _error("BATCH_CORRECTION_ACCESS_DENIED", 403) from exc


async def _source_at_location(
    db: AsyncSession, *, company_id: int, batch_id: int, location_id: int,
) -> None:
    source = await db.scalar(select(InventoryMovement.id).where(
        InventoryMovement.company_id == company_id,
        InventoryMovement.batch_id == batch_id,
        InventoryMovement.reference_type == "INBOUND_SUPPLIER",
        InventoryMovement.source_location_id.is_(None),
        InventoryMovement.destination_location_id == location_id,
    ).limit(1))
    if source is None:
        raise _error("BATCH_CORRECTION_SOURCE_NOT_FOUND", 404)


@router.get("/warehouse/batches/{batch_id}/metadata-correction")
async def preview_batch_metadata_correction(
    batch_id: int, location_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _access(access, location_id)
    await _source_at_location(db, company_id=access.company_id,
                              batch_id=batch_id, location_id=location_id)
    try:
        return await inspect_batch(db, company_id=access.company_id,
                                   batch_id=batch_id, location_id=location_id)
    except BatchCorrectionRejected as exc:
        raise _error(exc.code, exc.status) from exc


@router.get("/warehouse/batches/{batch_id}/metadata-corrections/history")
async def read_batch_metadata_corrections(
    batch_id: int, location_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _access(access, location_id)
    await _source_at_location(db, company_id=access.company_id,
                              batch_id=batch_id, location_id=location_id)
    return {"items": await correction_history(
        db, company_id=access.company_id, batch_id=batch_id, limit=50,
    )}


@router.post("/warehouse/batches/{batch_id}/metadata-correction")
async def save_batch_metadata_correction(
    batch_id: int, command: CorrectBatchMetadata,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    await _access(access, command.location_id)
    company_id = access.company_id
    # Signed active canonical BACKOFFICE credential, not legacy Driver password.
    principal = await db.scalar(select(CompanyPrincipal).where(
        CompanyPrincipal.company_id == company_id,
        CompanyPrincipal.id == access.subject.principal_id,
        CompanyPrincipal.principal_type == PrincipalType.BACKOFFICE.value,
        CompanyPrincipal.is_active.is_(True),
    ))
    valid_password = bool(principal is not None and await verify_existing_password(
        command.password, principal.password_hash,
    ))
    if not valid_password:
        # Rejected attempt is audited without storing plaintext or a password hash.
        db.add(SystemAuditLog(
            company_id=company_id, admin_id=actor.id, target_id=f"Batch_{batch_id}",
            action_type="BATCH_METADATA_CORRECTION_REAUTH_REJECTED",
            old_value="BACKOFFICE_REQUIRED", new_value="PASSWORD_INVALID",
        ))
        await db.commit()
        raise _error("BATCH_CORRECTION_PASSWORD_INVALID", 403)

    # Password intentionally excluded from persistent request hashes and events.
    payload = {
        "batch_id": batch_id, "location_id": command.location_id,
        "expected_revision": command.expected_revision,
        "batch_number": command.batch_number.strip(),
        "production_date": command.production_date.isoformat() if command.production_date else None,
        "expiry_date": command.expiry_date.isoformat() if command.expiry_date else None,
        "reason": command.reason.strip(),
        "principal_id": principal.id, "auth_revision": principal.auth_revision,
    }
    digest = hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    try:
        operation, replay = await begin_idempotent_operation(
            db, company_id=company_id, actor_id=actor.id,
            operation="BATCH_METADATA_CORRECTION",
            request_id=str(command.request_id), request_hash=digest,
        )
        if replay is not None:
            await db.rollback()
            return replay
        # Stock movement writers use shared location advisory guards. Take the
        # EXCLUSIVE variant so no stock mutation can pass during reclassification.
        await acquire_inventory_location_guard(
            db, company_id, command.location_id, exclusive=True,
        )
        await _source_at_location(
            db, company_id=company_id, batch_id=batch_id,
            location_id=command.location_id,
        )
        result = await correct_current_metadata(
            db, company_id=company_id, batch_id=batch_id,
            location_id=command.location_id,
            expected_revision=command.expected_revision,
            request_id=str(command.request_id),
            actor_principal_id=int(principal.id),
            actor_username=str(principal.username),
            actor_auth_revision=int(principal.auth_revision),
            reason=command.reason, new_batch_number=command.batch_number,
            new_production_date=command.production_date,
            new_expiry_date=command.expiry_date,
            local_today=await get_company_local_date(db, company_id),
        )
        complete_idempotent_operation(operation, result)
        await db.commit()
        return result
    except BatchCorrectionRejected as exc:
        await db.rollback()
        raise _error(exc.code, exc.status) from exc
    except OperationIdempotencyError as exc:
        await db.rollback()
        raise _error(exc.code) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise _error("BATCH_CORRECTION_CONCURRENT_OR_DUPLICATE") from exc
    except DBAPIError as exc:
        await db.rollback()
        raise _error("BATCH_CORRECTION_RETRY_OR_REFRESH") from exc
    except HTTPException:
        await db.rollback()
        raise
