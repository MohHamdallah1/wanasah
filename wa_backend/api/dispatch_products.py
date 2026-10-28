"""Read-only, purpose-specific Dispatch product discovery transport."""
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.dispatch_product_schemas import DispatchProductPageResponse
from database import get_db
from dispatch_access import require_location, require_route, require_vehicle
from domains.authorization.backoffice_access import BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected
from domains.dispatch_product_discovery import dispatch_product_page
from domains.dispatch_product_cursor import DispatchProductCursorError
from domains.uom_authority import UomAuthorityError
from domains.vehicles import resolve_vehicle_custody_location_id, VehicleError
from models import DispatchRoute, InventoryLocation


router = APIRouter(tags=["Dispatch product discovery"])


@router.get("/dispatch/products", response_model=DispatchProductPageResponse)
async def search_dispatch_products(
    purpose: Literal["LOAD", "SHORTAGE"], search: str = Query(default="", max_length=100),
    cursor: str | None = Query(default=None, max_length=2048), limit: int = Query(default=80, ge=1, le=80),
    route_id: int | None = Query(default=None, ge=1), warehouse_id: int | None = Query(default=None, ge=1),
    vehicle_id: int | None = Query(default=None, ge=1), db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    try:
        context = {}
        if purpose == "SHORTAGE":
            await access.require("shortage.create")
        else:
            route = None
            if route_id is not None:
                await require_route(access, "dispatch.read", route_id)
                route = await db.scalar(select(DispatchRoute).where(DispatchRoute.company_id == access.company_id, DispatchRoute.id == route_id))
                if route is None:
                    raise HTTPException(status_code=404, detail="Route not available.")
                warehouse_id = route.source_location_id
                vehicle_id = vehicle_id or route.vehicle_id
            if warehouse_id is None or vehicle_id is None:
                raise HTTPException(status_code=422, detail={"code": "DISPATCH_PRODUCT_CONTEXT_REQUIRED", "message": "Select a source warehouse and vehicle."})
            await require_vehicle(access, "dispatch.read", vehicle_id)
            await require_location(access, "dispatch.read", warehouse_id)
            warehouse = await db.scalar(select(InventoryLocation.id).where(InventoryLocation.company_id == access.company_id,
                InventoryLocation.id == warehouse_id, InventoryLocation.location_type == "WAREHOUSE", InventoryLocation.is_active.is_(True)))
            if warehouse is None:
                raise HTTPException(status_code=404, detail="Warehouse not available.")
            location = await resolve_vehicle_custody_location_id(db, company_id=access.company_id, vehicle_id=vehicle_id, require_active=True)
            same_vehicle = route is not None and route.vehicle_id == vehicle_id
            context = dict(route_id=route_id, warehouse_id=warehouse_id, vehicle_id=vehicle_id, vehicle_location_id=location,
                work_session_id=route.work_session_id if same_vehicle else None, driver_id=route.driver_id if same_vehicle else None)
        return await dispatch_product_page(db, company_id=access.company_id, purpose=purpose, search=search, cursor=cursor, limit=limit, **context)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(status_code=403, detail="Authorization denied.") from None
    except DispatchProductCursorError as exc:
        raise HTTPException(status_code=400, detail={"code": exc.code, "message": exc.message, "context": {}}) from exc
    except (UomAuthorityError, VehicleError) as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc), "context": getattr(exc, "context", {})}) from exc
