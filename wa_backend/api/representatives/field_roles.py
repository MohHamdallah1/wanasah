"""Owner-only FIELD role administration; no business FIELD endpoint enforcement."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.field_role_management import FieldRoleCommand, change_field_role, list_field_roles
from domains.authorization.field_role_policy import FieldRoleError
from models import Driver
from domains.representatives.repository import guard_representative_request_identity
from domains.representatives.contracts import RepresentativeError

router = APIRouter()


class GrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    role_id: int = Field(gt=0, le=2147483647, strict=True)


class RevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID


def http_error(exc):
    return HTTPException(exc.status, detail={"code":exc.code,
        "message":"The FIELD role operation could not be completed.", "context":{}})


@router.get("/{representative_id}/field-roles")
async def roles(
    representative_id: int = Path(gt=0, le=2147483647),
    after_id: int = Query(0, ge=0, le=2147483647),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    try:
        return await list_field_roles(db, access, representative_id, after_id, limit)
    except FieldRoleError as exc:
        raise http_error(exc) from None
    except RepresentativeError:
        raise http_error(FieldRoleError("FIELD_ROLE_REQUEST_CONFLICT")) from None


@router.post("/{representative_id}/field-roles")
async def grant(
    payload: GrantRequest,
    representative_id: int = Path(gt=0, le=2147483647),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    try:
        return await change_field_role(db, access, legacy_actor.id, FieldRoleCommand(
            str(payload.request_id), representative_id, payload.role_id, True),
            request_identity_guard=guard_representative_request_identity)
    except FieldRoleError as exc:
        raise http_error(exc) from None
    except RepresentativeError:
        raise http_error(FieldRoleError("FIELD_ROLE_REQUEST_CONFLICT")) from None


@router.post("/{representative_id}/field-roles/{role_id}/revoke")
async def revoke(
    payload: RevokeRequest,
    representative_id: int = Path(gt=0, le=2147483647),
    role_id: int = Path(gt=0, le=2147483647),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    try:
        return await change_field_role(db, access, legacy_actor.id, FieldRoleCommand(
            str(payload.request_id), representative_id, role_id, False),
            request_identity_guard=guard_representative_request_identity)
    except FieldRoleError as exc:
        raise http_error(exc) from None
    except RepresentativeError:
        raise http_error(FieldRoleError("FIELD_ROLE_REQUEST_CONFLICT")) from None
