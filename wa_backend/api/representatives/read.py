from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.representatives import RepresentativeError, get_representative, list_representatives
from domains.representatives.queries import representative_payload

from .schemas import RepresentativeCursorPage, RepresentativeResponse, RepresentativeStatus


router = APIRouter()
_representative_read = require_backoffice_capability("representative.read")


def _http_error(exc: RepresentativeError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message, "context": exc.context})


@router.get("", response_model=RepresentativeCursorPage, status_code=200)
async def read_representatives(
    search: str | None = Query(default=None, min_length=1, max_length=120),
    status: RepresentativeStatus = Query(default="all"),
    cursor: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_representative_read),
):
    try:
        page = await list_representatives(db, company_id=access.company_id, search=search, status=status, cursor=cursor, limit=limit)
    except RepresentativeError as exc:
        raise _http_error(exc) from None
    return {"items": [representative_payload(item) for item in page.items], "next_cursor": page.next_cursor, "has_more": page.has_more}


@router.get("/{representative_id}", response_model=RepresentativeResponse, status_code=200)
async def read_representative_detail(
    representative_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_representative_read),
):
    if representative_id <= 0:
        raise HTTPException(status_code=404, detail="Representative was not found.")
    try:
        record = await get_representative(db, company_id=access.company_id, representative_id=representative_id)
    except RepresentativeError as exc:
        raise _http_error(exc) from None
    return representative_payload(record)


__all__ = ["router"]
