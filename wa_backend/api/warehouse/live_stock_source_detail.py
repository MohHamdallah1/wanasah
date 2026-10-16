from __future__ import annotations

from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
)
from database import get_db
from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.batch_reservation_contracts import (
    OWNER_PREVIEW_LIMIT,
    ReservationEvidence,
)
from domains.batch_reservation_evidence import reservation_evidence
from domains.dispatch_reservations import reservation_owner_projection
from models import InventoryBalance, InventoryLocation, ProductBatch
from quantity import canonical_quantity
from services import inventory_business_error

from .live_stock import _require_live_stock_warehouse_read


router = APIRouter()


class LiveStockWarehouseSourceStatus(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    stock_status: Literal[
        "AVAILABLE",
        "QUARANTINED",
        "BLOCKED",
        "RECALLED",
        "DAMAGED",
        "DISPOSAL_PENDING",
    ]
    on_hand_quantity: str
    reserved_quantity: str
    movable_quantity: str
    reservation_evidence: ReservationEvidence


class LiveStockWarehouseSourceResponse(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    location_id: int = Field(gt=0)
    location_name: str = Field(min_length=1, max_length=200)
    product_variant_id: int = Field(gt=0)
    batch_id: int = Field(gt=0)
    statuses: list[LiveStockWarehouseSourceStatus] = Field(max_length=6)


@router.get(
    "/warehouse/inventory/{product_variant_id}/batches/{batch_id}/source",
    response_model=LiveStockWarehouseSourceResponse,
    status_code=200,
)
async def get_live_stock_batch_source(
    product_variant_id: int,
    batch_id: int,
    location_id: int = Query(gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(
        get_current_backoffice_capability_access
    ),
):
    """Return read-only source evidence for one batch at the selected warehouse.

    The selected warehouse is authorized before any batch/source query. This
    route deliberately does not expose other readable warehouses or vehicles;
    the existing cross-location stock-sources read remains a separate Batches /
    Quality authority.
    """
    if product_variant_id <= 0 or batch_id <= 0:
        raise HTTPException(status_code=422, detail="Invalid inventory identity.")

    company_id = access.company_id
    await _require_live_stock_warehouse_read(
        db,
        company_id=company_id,
        location_id=location_id,
        access=access,
    )

    batch_exists = await db.scalar(
        select(ProductBatch.id).where(
            ProductBatch.company_id == company_id,
            ProductBatch.id == batch_id,
            ProductBatch.product_variant_id == product_variant_id,
        )
    )
    if batch_exists is None:
        raise HTTPException(
            status_code=404,
            detail=inventory_business_error(
                "LIVE_STOCK_BATCH_NOT_FOUND",
                "The selected batch is unavailable.",
            ),
        )

    owners = reservation_owner_projection(
        access,
        batch_id=batch_id,
        variant_id=product_variant_id,
        preview_limit=OWNER_PREVIEW_LIMIT,
    )
    rows = (
        await db.execute(
            select(
                InventoryLocation.id.label("location_id"),
                InventoryLocation.name.label("location_name"),
                InventoryBalance.stock_status,
                InventoryBalance.on_hand_quantity,
                InventoryBalance.reserved_quantity,
                *owners.c,
            )
            .select_from(InventoryBalance)
            .join(
                InventoryLocation,
                and_(
                    InventoryLocation.company_id == InventoryBalance.company_id,
                    InventoryLocation.id == InventoryBalance.location_id,
                ),
            )
            .outerjoin(
                owners,
                and_(
                    owners.c.owner_location_id == InventoryBalance.location_id,
                    owners.c.owner_stock_status == InventoryBalance.stock_status,
                    InventoryBalance.reserved_quantity > 0,
                ),
            )
            .where(
                InventoryBalance.company_id == company_id,
                InventoryBalance.location_id == location_id,
                InventoryBalance.product_variant_id == product_variant_id,
                InventoryBalance.batch_id == batch_id,
                InventoryBalance.on_hand_quantity > 0,
                InventoryLocation.company_id == company_id,
                InventoryLocation.id == location_id,
                InventoryLocation.location_type == "WAREHOUSE",
                InventoryLocation.is_active.is_(True),
            )
            .order_by(
                InventoryBalance.stock_status.asc(),
                owners.c.transfer_id.asc(),
            )
        )
    ).all()

    if not rows:
        raise HTTPException(
            status_code=404,
            detail=inventory_business_error(
                "LIVE_STOCK_BATCH_NOT_FOUND",
                "The selected batch is unavailable.",
            ),
        )

    status_rows: dict[str, object] = {}
    owner_rows: dict[str, list] = {}
    for row in rows:
        key = str(row.stock_status).upper()
        if row.transfer_id is not None:
            owner_rows.setdefault(key, []).append(row._mapping)
        if key in status_rows:
            continue

        on_hand = Decimal(row.on_hand_quantity or 0)
        reserved = Decimal(row.reserved_quantity or 0)
        movable = on_hand - reserved
        if movable < 0:
            raise RuntimeError(
                "Inventory reservation exceeds on-hand quantity for "
                f"company_id={company_id}, location_id={location_id}, "
                f"product_variant_id={product_variant_id}, batch_id={batch_id}."
            )
        status_rows[key] = {
            "stock_status": key,
            "on_hand_quantity": canonical_quantity(on_hand),
            "reserved_quantity": canonical_quantity(reserved),
            "movable_quantity": canonical_quantity(movable),
        }

    statuses = []
    for key, status in status_rows.items():
        status["reservation_evidence"] = reservation_evidence(
            status["reserved_quantity"],
            owner_rows.get(key, []),
        )
        statuses.append(status)

    first = rows[0]
    return {
        "location_id": int(first.location_id),
        "location_name": str(first.location_name),
        "product_variant_id": product_variant_id,
        "batch_id": batch_id,
        "statuses": statuses,
    }
