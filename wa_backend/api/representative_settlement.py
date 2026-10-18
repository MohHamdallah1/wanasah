"""Operations-owned receiving of ended-session vehicle custody.

Only a business-facing count is submitted.  The existing Vehicle Recon stocktake
authority owns discrepancies and recount/approval; Unified Inventory Movement
owns physical handoff.  No financial or ending-snapshot quantity is client-owned.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api.authentication.backoffice_authorization import (
    get_current_backoffice_capability_access,
    require_backoffice_capability,
)
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from database import get_db
from domains.authorization.backoffice_access import (
    BackofficeCapabilityAccess,
    BackofficeCapabilityAccessRejected,
)
from domains.product_tracking import public_batch_number
from domains.vehicles import VehicleError, resolve_vehicle_custody_location_id
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation, InventoryLock,
    ProductBatch, ProductVariant, StocktakeCountAttempt, StocktakeCountAttemptLine,
    StocktakeLine, StocktakeSession, SystemAuditLog, UOM, WorkSession,
)
from quantity import QuantityError, canonical_quantity, validate_variant_quantity
from services import (
    InventoryMutationError, _seal_vehicle_inventory_reconciliation,
    acquire_inventory_location_guard, apply_inventory_movements_batch,
    begin_idempotent_operation, complete_idempotent_operation,
)

logger = logging.getLogger("wanasah_logger")
router = APIRouter(tags=["Representative settlement"])
_READ = require_backoffice_capability("settlement.read")
_EXECUTE = require_backoffice_capability("settlement.execute")
_MAX_LINES = 1000
_STATUS = frozenset(("AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING"))
_COMPLETE = "REPRESENTATIVE_CUSTODY_RECEIVED"


class CustodyCount(BaseModel):
    line_key: str = Field(min_length=24, max_length=24)
    actual_quantity: str = Field(min_length=1, max_length=50)


class CustodyConfirm(BaseModel):
    request_id: UUID
    destination_location_id: int = Field(gt=0)
    receiver_confirms_handoff: bool
    items: list[CustodyCount] = Field(max_length=_MAX_LINES)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def confirm(self):
        if not self.receiver_confirms_handoff:
            raise ValueError("The receiver must explicitly confirm physical handoff")
        if len({item.line_key for item in self.items}) != len(self.items):
            raise ValueError("Duplicate counted custody line")
        return self


def _line_key(session_id: int, variant_id: int, batch_id: int, status: str) -> str:
    # Opaque UI-only reference, never a business identity or authorization fact.
    raw = f"{session_id}:{variant_id}:{batch_id}:{status}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:24]


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def _capability(access: BackofficeCapabilityAccess, code: str, location: int | None = None):
    try:
        await access.require(code, location)
    except BackofficeCapabilityAccessRejected:
        raise HTTPException(status_code=403, detail={"code": "AUTHORIZATION_DENIED"}) from None


async def _session_and_vehicle(db: AsyncSession, company_id: int, session_id: int, *, lock: bool):
    query = select(WorkSession).where(
        WorkSession.company_id == company_id, WorkSession.id == session_id
    )
    if lock:
        query = query.with_for_update()
    work = (await db.execute(query)).scalar_one_or_none()
    if work is None:
        raise HTTPException(status_code=404, detail={"code": "SETTLEMENT_SESSION_NOT_FOUND"})
    if work.end_time is None:
        raise HTTPException(status_code=409, detail={"code": "WORK_SESSION_NOT_ENDED"})
    if work.is_settled:
        raise HTTPException(status_code=409, detail={"code": "FINANCIAL_SETTLEMENT_ALREADY_CLOSED"})
    route = (await db.execute(
        select(DispatchRoute).where(
            DispatchRoute.company_id == company_id,
            DispatchRoute.work_session_id == work.id,
            DispatchRoute.driver_id == work.driver_id,
            DispatchRoute.vehicle_id.is_not(None),
        ).order_by(DispatchRoute.id.desc()).limit(1)
    )).scalar_one_or_none()
    if route is None:
        raise HTTPException(status_code=409, detail={"code": "SESSION_HAS_NO_VEHICLE"})
    location_id = await resolve_vehicle_custody_location_id(
        db, company_id=company_id, vehicle_id=int(route.vehicle_id),
        require_active=True,
    )
    # A later session must not return stock that belongs to a newer custody shift.
    later = (await db.execute(select(DispatchRoute.id).where(
        DispatchRoute.company_id == company_id,
        DispatchRoute.vehicle_id == route.vehicle_id,
        DispatchRoute.work_session_id.is_not(None),
        DispatchRoute.work_session_id != work.id,
        DispatchRoute.id > route.id,
    ).limit(1))).scalar_one_or_none()
    if later is not None:
        raise HTTPException(status_code=409, detail={"code": "VEHICLE_CUSTODY_ASSIGNED_TO_LATER_SESSION"})
    return work, int(location_id)


async def _lines(db: AsyncSession, company_id: int, session_id: int, location_id: int, *, lock: bool):
    query = (
        select(
            InventoryBalance, ProductVariant.name, ProductVariant.sku,
            ProductVariant.base_uom_id, ProductVariant.quantity_scale,
            ProductVariant.quantity_step, UOM.code, ProductBatch.batch_number,
            ProductBatch.expiry_date,
        )
        .join(ProductVariant, and_(
            ProductVariant.company_id == InventoryBalance.company_id,
            ProductVariant.id == InventoryBalance.product_variant_id))
        .join(UOM, UOM.id == ProductVariant.base_uom_id)
        .join(ProductBatch, and_(
            ProductBatch.company_id == InventoryBalance.company_id,
            ProductBatch.id == InventoryBalance.batch_id,
            ProductBatch.product_variant_id == InventoryBalance.product_variant_id))
        .where(
            InventoryBalance.company_id == company_id,
            InventoryBalance.location_id == location_id,
            or_(InventoryBalance.on_hand_quantity > 0, InventoryBalance.reserved_quantity > 0),
        )
        .order_by(InventoryBalance.product_variant_id, InventoryBalance.batch_id,
                  InventoryBalance.stock_status, InventoryBalance.id)
        .limit(_MAX_LINES + 1)
    )
    if lock:
        query = query.with_for_update(of=InventoryBalance)
    found = (await db.execute(query)).all()
    if len(found) > _MAX_LINES:
        raise HTTPException(status_code=409, detail={"code": "SETTLEMENT_CUSTODY_TOO_LARGE"})
    result = {}
    for balance, name, sku, uom_id, scale, step, uom, lot, expiry in found:
        if balance.stock_status not in _STATUS or Decimal(balance.reserved_quantity or 0) != 0:
            raise HTTPException(status_code=409, detail={"code": "VEHICLE_CUSTODY_RESERVED_OR_INVALID"})
        key = _line_key(session_id, balance.product_variant_id, balance.batch_id, balance.stock_status)
        if key in result:
            raise HTTPException(status_code=409, detail={"code": "DUPLICATE_CUSTODY_IDENTITY"})
        result[key] = {
            "line_key": key, "variant_id": int(balance.product_variant_id),
            "batch_id": int(balance.batch_id), "stock_status": str(balance.stock_status),
            "product_name": str(name), "sku": str(sku), "batch_number": public_batch_number(lot),
            "expiry_date": expiry.isoformat() if expiry else None,
            "uom": str(uom), "uom_id": int(uom_id), "quantity_scale": int(scale),
            "quantity_step": step, "expected_quantity": Decimal(balance.on_hand_quantity),
        }
    return result


async def _recon(db: AsyncSession, company_id: int, session_id: int):
    return (await db.execute(select(StocktakeSession).where(
        StocktakeSession.company_id == company_id,
        StocktakeSession.related_work_session_id == session_id,
        StocktakeSession.stocktake_type == "VEHICLE_RECON",
        StocktakeSession.status != "CANCELLED",
    ).order_by(StocktakeSession.id.desc()).limit(1))).scalar_one_or_none()


async def _received(db: AsyncSession, company_id: int, session_id: int):
    return (await db.execute(select(SystemAuditLog.id).where(
        SystemAuditLog.company_id == company_id,
        SystemAuditLog.target_id == f"WorkSession_{session_id}",
        SystemAuditLog.action_type == _COMPLETE,
    ).limit(1))).scalar_one_or_none() is not None


@router.get("/admin/sessions/{session_id}/inventory-custody")
async def read_representative_custody(
    session_id: int,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_READ),
):
    work, vehicle_location_id = await _session_and_vehicle(db, access.company_id, session_id, lock=False)
    await _capability(access, "inventory.read", vehicle_location_id)
    rows = await _lines(db, access.company_id, session_id, vehicle_location_id, lock=False)
    recon = await _recon(db, access.company_id, session_id)
    received = await _received(db, access.company_id, session_id)
    return {
        "work_session_id": work.id, "vehicle_location_id": vehicle_location_id,
        "inventory_reconciled": work.inventory_reconciled_at is not None,
        "custody_received": received,
        "review_required": recon is not None and recon.status != "POSTED",
        "reconciliation_reference": recon.reference_number if recon is not None else None,
        "lines": [{
            key: (canonical_quantity(value) if key == "expected_quantity" else value)
            for key, value in row.items() if key not in (
                "variant_id", "batch_id", "uom_id", "quantity_scale", "quantity_step")
        } for row in rows.values()],
    }


async def _persist_variance(
    db: AsyncSession, *, company_id: int, work: WorkSession, vehicle_location_id: int,
    actor_id: int, rows: dict, actual: dict, notes: str | None,
):
    # Use the canonical Stocktake session/attempt schema; its existing approval
    # posts DRIVER_SHORTAGE/DRIVER_SURPLUS and enforces independent recount.
    from api.warehouse.stocktake import _requires_independent_stocktake_recount
    await db.flush()
    reference = f"VREC-{uuid4().hex[:12].upper()}"
    session = StocktakeSession(
        company_id=company_id, location_id=vehicle_location_id,
        reference_number=reference, stocktake_type="VEHICLE_RECON",
        status="PENDING_REVIEW", related_work_session_id=work.id,
        started_by=actor_id, snapshot_cutoff_at=_now(), notes=notes,
    )
    db.add(session)
    await db.flush()
    db.add(InventoryLock(
        company_id=company_id, stocktake_session_id=session.id,
        location_id=vehicle_location_id, created_by=actor_id,
    ))
    attempt = StocktakeCountAttempt(
        company_id=company_id, stocktake_session_id=session.id,
        attempt_number=1, counted_by=actor_id,
    )
    db.add(attempt)
    await db.flush()
    pairs = []
    for row in rows.values():
        line = StocktakeLine(
            company_id=company_id, stocktake_session_id=session.id,
            product_variant_id=row["variant_id"], batch_id=row["batch_id"],
            stock_status=row["stock_status"], line_origin="SNAPSHOT",
            expected_quantity=row["expected_quantity"],
        )
        db.add(line)
        await db.flush()
        quantity = actual[row["line_key"]]
        variance = quantity - row["expected_quantity"]
        db.add(StocktakeCountAttemptLine(
            company_id=company_id, stocktake_session_id=session.id,
            count_attempt_id=attempt.id, stocktake_line_id=line.id,
            expected_quantity=row["expected_quantity"],
            actual_quantity=quantity, variance_quantity=variance,
        ))
        pairs.append((row["expected_quantity"], variance))
    attempt.requires_independent_recount = await _requires_independent_stocktake_recount(
        db, company_id, pairs
    )
    db.add(SystemAuditLog(
        company_id=company_id, admin_id=actor_id,
        target_id=f"WorkSession_{work.id}",
        action_type="REPRESENTATIVE_CUSTODY_VARIANCE",
        old_value=f"expected_vehicle_location={vehicle_location_id}",
        new_value=json.dumps({
            "reconciliation_reference": reference,
            "actor": actor_id, "driver": work.driver_id,
            "differences": [{
                "sku": r["sku"], "lot": r["batch_number"],
                "stock_status": r["stock_status"],
                "expected": canonical_quantity(r["expected_quantity"]),
                "actual": canonical_quantity(actual[r["line_key"]]),
            } for r in rows.values() if actual[r["line_key"]] != r["expected_quantity"]],
        }, ensure_ascii=False)[:4000],
    ))
    return {
        "status": "REVIEW_REQUIRED",
        "review_required": True,
        "reconciliation_reference": reference,
        "reconciliation_session_id": int(session.id),  # transport-only, never operator input
        "requires_independent_recount": bool(attempt.requires_independent_recount),
        "movement_count": 0,
    }


@router.post("/admin/sessions/{session_id}/inventory-custody/receive")
async def receive_representative_custody(
    session_id: int,
    payload: CustodyConfirm,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_EXECUTE),
    legacy_actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    company_id = access.company_id
    actor_id = int(legacy_actor.id)
    if session_id <= 0:
        raise HTTPException(status_code=422, detail={"code": "INVALID_SESSION"})
    work, vehicle_location_id = await _session_and_vehicle(db, company_id, session_id, lock=False)
    await _capability(access, "inventory.read", vehicle_location_id)
    await _capability(access, "transfer.send", vehicle_location_id)
    await _capability(access, "transfer.destination", payload.destination_location_id)
    await _capability(access, "settlement.execute")
    destination = (await db.execute(select(InventoryLocation).where(
        InventoryLocation.company_id == company_id,
        InventoryLocation.id == payload.destination_location_id,
        InventoryLocation.location_type == "WAREHOUSE",
        InventoryLocation.is_active.is_(True),
    ))).scalar_one_or_none()
    if destination is None:
        raise HTTPException(status_code=404, detail={"code": "RECEIVING_WAREHOUSE_NOT_FOUND"})

    try:
        request_hash = hashlib.sha256(json.dumps(
            {"session_id": session_id, **payload.model_dump(mode="json")},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        record, replay = await begin_idempotent_operation(
            db, company_id=company_id, actor_id=actor_id,
            operation="REP_SETTLEMENT_CUSTODY_RECEIVE",
            request_id=str(payload.request_id), request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        work, checked_vehicle_id = await _session_and_vehicle(db, company_id, session_id, lock=True)
        if checked_vehicle_id != vehicle_location_id:
            raise HTTPException(status_code=409, detail={"code": "CUSTODY_CHANGED"})
        # Canonical order for all cross-location handoff guards.
        for location_id in sorted({vehicle_location_id, payload.destination_location_id}):
            await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)
        if await _received(db, company_id, session_id):
            raise HTTPException(status_code=409, detail={"code": "CUSTODY_ALREADY_RECEIVED"})
        rows = await _lines(db, company_id, session_id, vehicle_location_id, lock=True)
        supplied = {item.line_key: item for item in payload.items}
        if set(supplied) != set(rows):
            raise HTTPException(status_code=422, detail={"code": "CUSTODY_COUNT_INCOMPLETE_OR_STALE"})
        actual = {}
        for key, row in rows.items():
            try:
                actual[key] = validate_variant_quantity(
                    supplied[key].actual_quantity, quantity_scale=row["quantity_scale"],
                    quantity_step=row["quantity_step"], field_name="actual_quantity",
                    allow_zero=True,
                )
            except QuantityError as exc:
                raise HTTPException(status_code=422, detail={"code": "INVALID_PHYSICAL_QUANTITY", "message": str(exc)}) from exc

        existing_recon = await _recon(db, company_id, session_id)
        if existing_recon is not None and existing_recon.status != "POSTED":
            raise HTTPException(status_code=409, detail={"code": "CUSTODY_RECONCILIATION_PENDING_REVIEW"})
        mismatch = any(actual[key] != row["expected_quantity"] for key, row in rows.items())
        if mismatch:
            if work.inventory_reconciled_at is not None or existing_recon is not None:
                raise HTTPException(status_code=409, detail={"code": "SEALED_CUSTODY_COUNT_MISMATCH"})
            for code in ("stocktake.start", "stocktake.count"):
                await _capability(access, code, vehicle_location_id)
            response = await _persist_variance(
                db, company_id=company_id, work=work,
                vehicle_location_id=vehicle_location_id, actor_id=actor_id,
                rows=rows, actual=actual, notes=payload.notes,
            )
        else:
            if work.inventory_reconciled_at is None:
                await _seal_vehicle_inventory_reconciliation(
                    db, company_id=company_id, work_session=work,
                    vehicle_location_id=vehicle_location_id, settled_by=actor_id,
                )
            elif work.inventory_reconciled_by is None:
                raise HTTPException(status_code=409, detail={"code": "INCOMPLETE_INVENTORY_SEAL"})
            movements = [{
                "product_variant_id": row["variant_id"], "batch_id": row["batch_id"],
                "quantity": row["expected_quantity"], "movement_kind": "PHYSICAL",
                "reference_type": "REPRESENTATIVE_CUSTODY_RECEIPT",
                "reference_id": str(work.id),
                "idempotency_key": f"REP-HANDOFF-{work.id}-{key}",
                "source_location_id": vehicle_location_id,
                "destination_location_id": payload.destination_location_id,
                "source_stock_status": row["stock_status"],
                "destination_stock_status": row["stock_status"],
                "work_session_id": work.id,
                "notes": f"Receiver {actor_id}; representative {work.driver_id}; ended session custody",
            } for key, row in rows.items() if row["expected_quantity"] > 0]
            if movements:
                await apply_inventory_movements_batch(
                    db, company_id=company_id, performed_by=actor_id, movements=movements,
                )
            db.add(SystemAuditLog(
                company_id=company_id, admin_id=actor_id,
                target_id=f"WorkSession_{work.id}", action_type=_COMPLETE,
                old_value=f"vehicle={vehicle_location_id},driver={work.driver_id}",
                new_value=json.dumps({
                    "receiver": actor_id, "work_session": work.id,
                    "destination_warehouse": payload.destination_location_id,
                    "movement_count": len(movements), "request_id": str(payload.request_id),
                    "notes": payload.notes,
                    "items": [{
                        "sku": r["sku"], "lot": r["batch_number"],
                        "status": r["stock_status"],
                        "quantity": canonical_quantity(r["expected_quantity"]),
                    } for r in rows.values()],
                }, ensure_ascii=False)[:4000],
            ))
            response = {
                "status": "CUSTODY_RECEIVED", "review_required": False,
                "inventory_reconciled": True,
                "movement_count": len(movements), "financial_ready": True,
            }
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except HTTPException:
        await db.rollback()
        raise
    except (InventoryMutationError, VehicleError) as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "CUSTODY_RECEIPT_CONFLICT", "message": str(exc)}) from exc
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail={"code": "CUSTODY_CONCURRENT_CONFLICT"}) from exc
    except Exception:
        await db.rollback()
        logger.exception("Representative custody receiving failed")
        raise HTTPException(status_code=500, detail={"code": "CUSTODY_RECEIPT_FAILED"}) from None
