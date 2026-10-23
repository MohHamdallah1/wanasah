"""Additive FIELD prerequisite routes. Existing legacy URLs remain mounted."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.dependencies import get_current_field_context
from api.authentication.field_authorization import require_field_capabilities
from api.authentication.field_compatibility import get_current_field_legacy_driver
from api.field_visit_contracts import run_field_query
from database import get_db
from domains.auth_sessions.context import FieldRequestContext
from domains.field_operations.contracts import InvoicePreviewRequest, ReturnResolutionRequest
from domains.field_operations.context import assigned_visit, shop_commercial_state
from domains.field_operations.custody import read_custody
from domains.field_operations.invoice import preview_invoice, read_invoice
from domains.field_operations.returns import resolve_return
from models import Driver

router = APIRouter(tags=["Field contracts"])


@router.post("/visits/{visit_id}/return-resolution", dependencies=[Depends(require_field_capabilities(("visit.execute",)))])
async def resolve_visit_return(
    visit_id: int, payload: ReturnResolutionRequest,
    db: AsyncSession = Depends(get_db),
    field_context: FieldRequestContext = Depends(get_current_field_context),
    legacy_actor: Driver = Depends(get_current_field_legacy_driver),
):
    return await run_field_query(
        resolve_return, db, context=field_context, driver_id=legacy_actor.id,
        visit_id=visit_id, request=payload,
    )


@router.get("/visits/{visit_id}/commercial-state", dependencies=[Depends(require_field_capabilities(("visit.read",)))])
async def get_visit_commercial_state(
    visit_id: int, db: AsyncSession = Depends(get_db),
    field_context: FieldRequestContext = Depends(get_current_field_context),
    legacy_actor: Driver = Depends(get_current_field_legacy_driver),
):
    _visit, shop, _work = await run_field_query(
        assigned_visit, db, context=field_context, driver_id=legacy_actor.id, visit_id=visit_id,
    )
    return {"commercial_readiness": await run_field_query(
        shop_commercial_state, db, company_id=field_context.company_id, shop=shop,
    )}


@router.post("/visits/{visit_id}/invoice-preview", dependencies=[Depends(require_field_capabilities(("visit.execute", "pricing.view",)))])
async def preview_visit_invoice(
    visit_id: int, payload: InvoicePreviewRequest,
    db: AsyncSession = Depends(get_db),
    field_context: FieldRequestContext = Depends(get_current_field_context),
    legacy_actor: Driver = Depends(get_current_field_legacy_driver),
):
    return await run_field_query(
        preview_invoice, db, context=field_context, driver_id=legacy_actor.id,
        visit_id=visit_id, request=payload,
    )


@router.get("/visits/{visit_id}/invoice", dependencies=[Depends(require_field_capabilities(("visit.read", "pricing.view",)))])
async def get_visit_invoice(
    visit_id: int, db: AsyncSession = Depends(get_db),
    field_context: FieldRequestContext = Depends(get_current_field_context),
    legacy_actor: Driver = Depends(get_current_field_legacy_driver),
):
    return await run_field_query(
        read_invoice, db, context=field_context, driver_id=legacy_actor.id, visit_id=visit_id,
    )


@router.get("/driver/custody", dependencies=[Depends(require_field_capabilities(("inventory.read",)))])
async def get_field_custody(
    limit: int = Query(default=100, ge=1, le=200), cursor: str | None = Query(default=None, max_length=8192),
    db: AsyncSession = Depends(get_db),
    field_context: FieldRequestContext = Depends(get_current_field_context),
    legacy_actor: Driver = Depends(get_current_field_legacy_driver),
):
    return await run_field_query(
        read_custody, db, context=field_context, driver_id=legacy_actor.id, limit=limit, cursor=cursor,
    )
