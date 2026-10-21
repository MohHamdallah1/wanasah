"""Thin Dashboard transport for reference-only reads and manual commands."""
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess

from .public import ManualReferenceWrite, PurchaseReferenceError, read_reference, write_manual_reference

router = APIRouter(prefix="/purchase-cost-references", tags=["Purchase Cost Reference"])


@router.get("/{product_variant_id}")
async def get_reference(
    product_variant_id: int = Path(gt=0),
    quote_uom_id: int | None = Query(default=None, gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    try:
        return await read_reference(db, access=access, product_variant_id=product_variant_id,
                                    quote_uom_id=quote_uom_id)
    except PurchaseReferenceError as exc:
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc


@router.put("/{product_variant_id}")
async def put_reference(
    payload: ManualReferenceWrite,
    product_variant_id: int = Path(gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    try:
        response = await write_manual_reference(
            db, access=access, product_variant_id=product_variant_id, payload=payload,
        )
        await db.commit()
        return response
    except PurchaseReferenceError as exc:
        await db.rollback()
        raise HTTPException(exc.status_code, detail=exc.detail()) from exc
    except DBAPIError as exc:
        await db.rollback()
        if getattr(exc.orig, "sqlstate", None) in {"55P03", "40P01", "40001", "23505"}:
            raise HTTPException(409, detail={
                "code": "PURCHASE_REFERENCE_CONCURRENT_CONFLICT",
                "message": "Retry the same request after reconciling its result.", "context": {},
            }) from exc
        raise  # canonical global handler hides internals and exposes request id
    except BaseException:
        await db.rollback()
        raise
