from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.representatives import (
    CreateRepresentativeCommand,
    RepresentativeError,
    UpdateRepresentativeCommand,
    create_representative,
    update_representative,
)
from models import Driver

from .schemas import (
    RepresentativeCreateRequest,
    RepresentativeResponse,
    RepresentativeUpdateRequest,
)


router = APIRouter()
_representative_manage = require_backoffice_capability("representative.manage")


def _http_error(exc: RepresentativeError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={"code": exc.code, "message": exc.message, "context": exc.context},
    )


def _not_found() -> HTTPException:
    return HTTPException(
        status_code=404,
        detail={
            "code": "REPRESENTATIVE_NOT_FOUND",
            "message": "Representative was not found.",
            "context": {},
        },
    )


@router.post("", response_model=RepresentativeResponse, status_code=201)
async def create_representative_endpoint(
    payload: RepresentativeCreateRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_representative_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    try:
        return await create_representative(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            command=CreateRepresentativeCommand(
                request_id=str(payload.request_id),
                full_name=payload.full_name,
                username=payload.username,
                password=payload.password,
                phone_number=payload.phone_number,
                can_allow_debt=payload.can_allow_debt,
                max_debt_limit=payload.max_debt_limit,
            ),
        )
    except RepresentativeError as exc:
        raise _http_error(exc) from None


@router.patch("/{representative_id}", response_model=RepresentativeResponse, status_code=200)
async def update_representative_endpoint(
    representative_id: int,
    payload: RepresentativeUpdateRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_representative_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    if representative_id <= 0:
        raise _not_found()
    fields = payload.model_dump(exclude={"request_id"}, exclude_unset=True)
    try:
        return await update_representative(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            representative_id=representative_id,
            command=UpdateRepresentativeCommand(
                request_id=str(payload.request_id),
                fields=fields,
            ),
        )
    except RepresentativeError as exc:
        raise _http_error(exc) from None


__all__ = ["router"]
