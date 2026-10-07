"""Supplier HTTP adapter. Business commands and persistence remain module-owned."""
from functools import wraps
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from api.dependencies import get_current_driver
from database import get_db
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
                    db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await require_supplier_permission(db, actor)
    return await list_suppliers(db, actor.company_id, search=search, active=active, cursor=cursor, limit=limit)


@router.get("/{supplier_id}", response_model=SupplierView)
@supplier_errors
async def supplier(supplier_id: int, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    await require_supplier_permission(db, actor)
    return supplier_view(await load_supplier(db, actor.company_id, supplier_id))


@router.post("", response_model=SupplierView, status_code=201)
@supplier_errors
async def create_supplier(payload: SupplierCreate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await mutate_supplier(db, actor, payload)


@router.put("/{supplier_id}", response_model=SupplierView)
@supplier_errors
async def update_supplier(supplier_id: int, payload: SupplierUpdate, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await mutate_supplier(db, actor, payload, supplier_id=supplier_id)


@router.patch("/{supplier_id}/state", response_model=SupplierView)
@supplier_errors
async def supplier_state(supplier_id: int, payload: SupplierState, db: AsyncSession = Depends(get_db), actor: Driver = Depends(get_current_driver)):
    return await mutate_supplier(db, actor, payload, supplier_id=supplier_id, state=True)
