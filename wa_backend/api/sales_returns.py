from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from models import Driver
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.sales_returns.core import SalesReturnError
from domains.sales_returns.schemas import SalesReturnCreate
from domains.sales_returns.service import (
    create_sales_return,
    get_sales_return,
    list_returnable_sales,
    list_sales_returns,
    source_summary,
)


router = APIRouter(prefix="/sales-returns", tags=["Sales Returns"])
# V1 support reads share the creation capability and require a company grant.
_sales_return_access = require_backoffice_capability("sales_return.create")


def _http(exc: SalesReturnError) -> HTTPException:
    # The app-wide HTTPException handler surfaces detail under "message".
    # Keep this boundary human-readable for dashboard/clients; the domain code
    # remains available in server-side exception context and tests.
    return HTTPException(status_code=exc.status_code, detail=exc.message)


@router.get("")
async def list_returns(
    limit: int = Query(50, ge=1, le=100),
    before_id: int | None = Query(None, gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_sales_return_access),
):
    try:
        return await list_sales_returns(
            db,
            company_id=access.company_id,
            limit=limit,
            before_id=before_id,
        )
    except SalesReturnError as exc:
        raise _http(exc) from exc


@router.get("/sources")
async def returnable_sales(
    search: str | None = Query(None, max_length=100),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    before_revision_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_sales_return_access),
):
    try:
        return await list_returnable_sales(
            db,
            company_id=access.company_id,
            search=search,
            date_from=date_from,
            date_to=date_to,
            before_revision_id=before_revision_id,
            limit=limit,
        )
    except SalesReturnError as exc:
        raise _http(exc) from exc


@router.get("/source/{visit_id}")
async def return_source(
    visit_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_sales_return_access),
):
    try:
        return await source_summary(
            db,
            company_id=access.company_id,
            visit_id=visit_id,
        )
    except SalesReturnError as exc:
        raise _http(exc) from exc


@router.get("/{return_id}")
async def return_detail(
    return_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_sales_return_access),
):
    try:
        return await get_sales_return(
            db,
            company_id=access.company_id,
            return_id=return_id,
        )
    except SalesReturnError as exc:
        raise _http(exc) from exc


@router.post("", status_code=201)
async def post_return(
    payload: SalesReturnCreate,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_sales_return_access),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    try:
        result = await create_sales_return(
            db,
            company_id=access.company_id,
            actor_id=int(legacy_actor.id),
            payload=payload,
        )
        await db.commit()
        return result
    except SalesReturnError as exc:
        await db.rollback()
        raise _http(exc) from exc
    except Exception:
        await db.rollback()
        raise