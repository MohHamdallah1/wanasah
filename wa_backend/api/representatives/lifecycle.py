from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.representatives.contracts import (
    RepresentativeError,
    RepresentativeLifecycleCommand,
)
from domains.representatives.lifecycle import (
    deactivate_representative,
    reactivate_representative,
)
from models import Driver

from .schemas import RepresentativeLifecycleRequest


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


@router.post("/{representative_id}/deactivate", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_representative_endpoint(
    representative_id: int,
    payload: RepresentativeLifecycleRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_representative_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
) -> Response:
    if representative_id <= 0:
        raise _not_found()
    try:
        await deactivate_representative(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            representative_id=representative_id,
            command=RepresentativeLifecycleCommand(request_id=str(payload.request_id)),
        )
    except RepresentativeError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{representative_id}/reactivate", status_code=status.HTTP_204_NO_CONTENT)
async def reactivate_representative_endpoint(
    representative_id: int,
    payload: RepresentativeLifecycleRequest,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_representative_manage),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
) -> Response:
    if representative_id <= 0:
        raise _not_found()
    try:
        await reactivate_representative(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            representative_id=representative_id,
            command=RepresentativeLifecycleCommand(request_id=str(payload.request_id)),
        )
    except RepresentativeError as exc:
        raise _http_error(exc) from None
    return Response(status_code=status.HTTP_204_NO_CONTENT)


__all__ = ["router"]
