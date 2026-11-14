"""C03 read-only custody handoff: proof-bound stock presentation and reconciliation.

No inventory mutation; no authorization from product labels, JWT claims, or
unsigned client vehicle IDs. The manager and recipient use separate principals.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import get_current_backoffice_capability_access
from api.authentication.field_authorization import require_field_capability
from api.authentication.dependencies import get_current_field_context
from database import get_db
from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected,
)
from domains.dispatch.route_execution.custody.access import require_custody_vehicle_scope
from domains.dispatch.route_execution.custody.proofs import CustodyRejected, verify
from domains.dispatch.route_execution.custody.snapshot import read_vehicle_state
from domains.dispatch_route_load import route_load_uom_metadata
from domains.uom_authority import UomAuthorityError
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from models import ProductBatch, ProductVariant, UOM, Vehicle

router = APIRouter()
_field_auth = require_field_capability("work_session.execute")
MAX_DISPLAY_LINES = 1000


class CustodyOfferPreviewCommand(BaseModel):
    offer_token: str = Field(min_length=50, max_length=2048)


async def _manager(access: BackofficeCapabilityAccess, vehicle_id: int) -> None:
    try:
        await access.require("vehicle.manage")
    except BackofficeCapabilityAccessRejected as exc:
        raise HTTPException(403, detail={"code": "CUSTODY_MANAGER_CAPABILITY_DENIED"}) from exc
    await require_custody_vehicle_scope(access, vehicle_id)


def _error(exc: CustodyRejected) -> HTTPException:
    return HTTPException(exc.status, detail={"code": exc.code, "context": {}})


async def _stock_display(db: AsyncSession, company_id: int, vehicle_id: int):
    state = await read_vehicle_state(db, company_id, vehicle_id)
    if len(state.lines) > MAX_DISPLAY_LINES:
        raise CustodyRejected("CUSTODY_DISPLAY_TOO_LARGE")
    plate = await db.scalar(select(Vehicle.plate_number).where(
        Vehicle.company_id == company_id, Vehicle.id == vehicle_id,
    ))
    if not plate:
        raise CustodyRejected("CUSTODY_VEHICLE_NOT_OPERATIONAL")
    if not state.lines:
        return state, [], plate
    # Single tenant-bound join for every line, avoiding per-batch DB reads.
    variants = {row[0]: (row[1], row[2], row[3]) for row in
        (await db.execute(select(
            ProductVariant.id, ProductVariant.name, ProductVariant.sku, UOM.code,
        ).join(UOM, UOM.id == ProductVariant.base_uom_id).where(
            ProductVariant.company_id == company_id,
            ProductVariant.id.in_({line["variant_id"] for line in state.lines}),
        ))).all()}
    batches = {row[0]: (row[1], str(row[2]) if row[2] else None) for row in
        (await db.execute(select(
            ProductBatch.id, ProductBatch.batch_number, ProductBatch.expiry_date,
        ).where(
            ProductBatch.company_id == company_id,
            ProductBatch.id.in_({line["batch_id"] for line in state.lines}),
        ))).all()}
    # The exact, unique commercial UOM is display-only; it never changes the
    # signed base-quantity snapshot. Broken/ambiguous conversions fall back to
    # the real base UOM rather than inventing a carton size.
    try:
        display_units = await route_load_uom_metadata(
            db, company_id=company_id, variant_ids=list(variants),
        )
    except UomAuthorityError:
        display_units = {}
    display = []
    for line in state.lines:
        variant = variants.get(line["variant_id"])
        batch = batches.get(line["batch_id"])
        if variant is None or batch is None:
            raise CustodyRejected("CUSTODY_STOCK_DISPLAY_UNVERIFIED")
        display.append({
            "product_name": variant[0], "sku": variant[1],
            "base_uom": variant[2],
            "base_uom_name": display_units.get(line["variant_id"], {}).get(
                "base_uom_name", variant[2],
            ),
            "display_uom_name": display_units.get(line["variant_id"], {}).get(
                "display_uom_name",
            ),
            "display_factor_to_base": display_units.get(line["variant_id"], {}).get(
                "display_factor_to_base",
            ),
            # __WANASAH_NOLOT__ is an internal accounting identity, not a real
            # printed production lot. Never expose this technical key to users.
            "batch_number": "" if str(batch[0]).startswith("__WANASAH_NOLOT__:")
            else batch[0],
            "expiry_date": batch[1],
            "stock_status": line["status"],
            "on_hand_base": line["on_hand"],
            "reserved_base": line["reserved"],
        })
    return state, display, plate


@router.get("/vehicles/{vehicle_id}/custody/stock-review")
async def manager_custody_stock_review(
    vehicle_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _manager(access, vehicle_id)
    try:
        state, rows, plate = await _stock_display(db, access.company_id, vehicle_id)
    except CustodyRejected as exc:
        raise _error(exc) from exc
    return {
        "vehicle_id": vehicle_id, "vehicle_plate": plate,
        "context_revision": state.revision,
        "stock_snapshot": state.stock_snapshot,
        "stock_lines": rows,
    }


@router.post(
    "/driver/vehicles/{vehicle_id}/custody/offer-preview",
    dependencies=[Depends(_field_auth)],
)
async def field_custody_offer_preview(
    vehicle_id: int, command: CustodyOfferPreviewCommand,
    field: FieldRequestContext = Depends(get_current_field_context),
    db: AsyncSession = Depends(get_db),
):
    try:
        offer = verify("OFFER", command.offer_token)
        if (offer.get("company") != field.company_id
                or offer.get("vehicle") != vehicle_id
                or offer.get("receiver") != field.principal_id
                or offer.get("representative") != field.representative_id):
            raise CustodyRejected("CUSTODY_RECEIVER_CONFIRMATION_DENIED", 403)
        state, rows, plate = await _stock_display(db, field.company_id, vehicle_id)
        if (offer.get("location") != state.location_id
                or offer.get("revision") != state.revision
                or offer.get("epoch_id") != (
                    int(state.epoch.id) if state.epoch is not None else None)
                or offer.get("snapshot") != state.stock_snapshot):
            raise CustodyRejected("CUSTODY_STOCK_SNAPSHOT_STALE")
        return {
            "vehicle_id": vehicle_id, "vehicle_plate": plate,
            "stock_snapshot": state.stock_snapshot,
            "stock_lines": rows,
            "expires_in_seconds": 900,
        }
    except CustodyRejected as exc:
        raise _error(exc) from exc


@router.get("/vehicles/{vehicle_id}/custody/accept-operations/{request_id}")
async def manager_custody_accept_operation(
    vehicle_id: int, request_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(get_current_backoffice_capability_access),
):
    await _manager(access, vehicle_id)
    accepted = await db.scalar(select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == access.company_id,
        VehicleCustodyEpoch.vehicle_id == vehicle_id,
        VehicleCustodyEpoch.request_id == str(request_id),
        VehicleCustodyEpoch.accepted_by_principal_id == access.subject.principal_id,
        VehicleCustodyEpoch.state == "ACCEPTED",
    ))
    if accepted is None:
        return {"state": "UNKNOWN"}
    return {
        "state": "COMMITTED",
        "context_revision": int(accepted.context_revision),
        "epoch_id": int(accepted.id),
    }
