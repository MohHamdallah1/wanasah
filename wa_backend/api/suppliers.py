"""Supplier HTTP adapter. Business commands and persistence remain module-owned."""
from functools import wraps
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from api.authentication.backoffice_compatibility import (
    get_current_backoffice_legacy_driver,
)
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from models import Driver
from domains.suppliers.application import mutate_supplier
from domains.suppliers.contracts import SupplierCreate, SupplierPage, SupplierState, SupplierUpdate, SupplierView
from domains.suppliers.public import SupplierError, require_supplier_permission
from domains.suppliers.repository import list_suppliers, load_supplier, supplier_view

router = APIRouter(prefix="/suppliers", tags=["Suppliers"])


def supplier_errors(handler):
    @wraps(handler)
    async def adapter(*args, **kwargs):
        try:
            return await handler(*args, **kwargs)
        except SupplierError as exc:
            raise HTTPException(exc.status_code, detail=exc.as_detail()) from exc
    return adapter


@router.get("", response_model=SupplierPage)
@supplier_errors
async def suppliers(search: str | None = Query(None, min_length=2, max_length=100),
                    active: bool | None = Query(None), cursor: str | None = Query(None, max_length=512),
                    limit: int = Query(30, ge=1, le=100),
                    db: AsyncSession = Depends(get_db),
                    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access)):
    await require_supplier_permission(access)
    return await list_suppliers(db, access.company_id, search=search, active=active, cursor=cursor, limit=limit)


@router.get("/{supplier_id}", response_model=SupplierView)
@supplier_errors
async def supplier(supplier_id: int, db: AsyncSession = Depends(get_db),
                   access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access)):
    await require_supplier_permission(access)
    return supplier_view(await load_supplier(db, access.company_id, supplier_id))


@router.post("", response_model=SupplierView, status_code=201)
@supplier_errors
async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db),
                          access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
                          legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver)):
    return await mutate_supplier(db, access, legacy_actor.id, payload)


@router.put("/{supplier_id}", response_model=SupplierView)
@supplier_errors
async def update_supplier(supplier_id: int, payload: SupplierUpdate, db: AsyncSession = Depends(get_db),
                          access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
                          legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver)):
    return await mutate_supplier(db, access, legacy_actor.id, payload, supplier_id=supplier_id)


@router.patch("/{supplier_id}/state", response_model=SupplierView)
@supplier_errors
async def supplier_state(supplier_id: int, payload: SupplierState, db: AsyncSession = Depends(get_db),
                         access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
                         legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver)):
    return await mutate_supplier(db, access, legacy_actor.id, payload, supplier_id=supplier_id, state=True)
