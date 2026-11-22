"""#1067 signed, durable demand and separately-authorized urgent promotion.

The legacy POST/PUT wire is intentionally unchanged; neither legacy path may
create an emergency Visit from a demand alone. The new versioned request is
client opt-in and has its own immutable company+actor+UUID receipt.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import ConfigDict, Field, model_validator
from sqlalchemy import and_, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError, DBAPIError

from database import get_db
from schemas import RequestModel, PositiveDbInt
from api.authentication.backoffice_authorization import require_backoffice_capability
from api.authentication.backoffice_compatibility import get_current_backoffice_legacy_driver
from domains.authorization.backoffice_access import BackofficeCapabilityAccess, BackofficeCapabilityAccessRejected
from domains.dispatch_shop_read_scope import company_shop_directory, visible_shop_filter
from dispatch_access import require_vehicle
from domains.dispatch_representatives import has_canonical_field_identity
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.dispatch.route_execution.custody.snapshot import read_vehicle_state
from domains.dispatch.route_execution.custody.proofs import CustodyRejected
from api.dispatch_shortage_availability import _sellable_by_variant
from product_lifecycle import (
    REPLENISHMENT_NEW, acquire_product_lifecycle_guards, evaluate_product_capability,
)
from models import (
    Driver, Shop, Zone, ProductVariant, ProductBatch, Visit, DispatchRoute,
    InventoryBalance, IdentityLegacyDriverMap, OperationIdempotency,
    ShortageRequest, ShortageUrgentAssignment, SystemAuditLog,
)
from services import (
    OperationIdempotencyError, begin_idempotent_operation,
    complete_idempotent_operation, get_company_local_date,
)
from domains.dispatch_shortage_visits import ensure_shortage_pending_visit

router = APIRouter(tags=["Dispatch shortage durable commands"])
_demand_create = require_backoffice_capability("shortage.create")
_demand_read = require_backoffice_capability("shortage.read")


class ShortageCommandLine(RequestModel):
    model_config = ConfigDict(extra="forbid")
    product_id: PositiveDbInt
    quantity_base: PositiveDbInt


class ShortageDemandCommand(RequestModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(..., ge=2, le=2)
    request_id: UUID
    shop_id: PositiveDbInt
    zone_id: PositiveDbInt
    requested_driver_id: PositiveDbInt | None = None
    lines: list[ShortageCommandLine] = Field(min_length=1, max_length=80)

    @model_validator(mode="after")
    def validate_command(self):
        if self.request_id.version != 4:
            raise ValueError("request_id must be UUID v4")
        ids = [int(line.product_id) for line in self.lines]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate product_id lines are forbidden")
        return self


class ShortageUrgentPromotion(RequestModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    driver_id: PositiveDbInt
    quantity_base: PositiveDbInt

    @model_validator(mode="after")
    def validate_uuid(self):
        if self.request_id.version != 4:
            raise ValueError("request_id must be UUID v4")
        return self


def _hash(payload: dict) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()


def _demand_hash(cmd: ShortageDemandCommand) -> str:
    return _hash({
        "version": cmd.version, "shop_id": int(cmd.shop_id), "zone_id": int(cmd.zone_id),
        "requested_driver_id": int(cmd.requested_driver_id) if cmd.requested_driver_id else None,
        "lines": sorted(
            (int(x.product_id), int(x.quantity_base)) for x in cmd.lines
        ),
    })


def _rejected(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "context": {}})


async def _authorize_shop(db: AsyncSession, access: BackofficeCapabilityAccess,
                          shop_id: int, zone_id: int) -> Shop:
    # The caller must have actual persisted Dispatch directory/route scope.
    try:
        await access.require("dispatch.read", any_location=True)
        directory = await company_shop_directory(access)
    except BackofficeCapabilityAccessRejected as exc:
        raise _rejected(403, "SHORTAGE_SHOP_SCOPE_DENIED", "Shop access denied.") from exc
    shop = (await db.execute(
        select(Shop).where(
            Shop.company_id == access.company_id,
            Shop.id == shop_id, visible_shop_filter(access, company_directory=directory),
        ).with_for_update()
    )).scalar_one_or_none()
    if shop is None or shop.is_archived or not shop.is_active:
        raise _rejected(404, "SHORTAGE_SHOP_UNAVAILABLE", "Shop not available to this user.")
    if int(shop.zone_id or 0) != int(zone_id):
        raise _rejected(409, "SHORTAGE_SHOP_ZONE_STALE", "Shop zone changed.")
    return shop


async def _lock_zone_shop(db: AsyncSession, access: BackofficeCapabilityAccess,
                          shop_id: int, zone_id: int) -> Shop:
    zone = await db.scalar(
        select(Zone).where(Zone.company_id == access.company_id, Zone.id == zone_id)
        .with_for_update(nowait=True)
    )
    if zone is None or not zone.is_active:
        raise _rejected(409, "SHORTAGE_ZONE_UNAVAILABLE", "Zone not active.")
    await db.execute(text(
        "SELECT pg_advisory_xact_lock(CAST(:company AS integer), hashtext(:key))"
    ), {"company": access.company_id, "key": f"dispatch-shop:{shop_id}"})
    return await _authorize_shop(db, access, shop_id, zone_id)


async def _driver_is_canonical(db: AsyncSession, company_id: int, driver_id: int) -> bool:
    driver = await db.scalar(
        select(Driver).where(
            Driver.company_id == company_id, Driver.id == driver_id,
            Driver.is_active.is_(True),
            has_canonical_field_identity(company_id=company_id, legacy_driver_id=Driver.id),
        ).with_for_update(nowait=True)
    )
    return driver is not None


async def _begin(db: AsyncSession, *, company: int, actor: int,
                 operation: str, uuid: UUID, digest: str):
    return await begin_idempotent_operation(
        db, company_id=company, actor_id=actor, operation=operation,
        request_id=str(uuid), request_hash=digest,
    )


def _map_error(exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, OperationIdempotencyError):
        raise _rejected(409, exc.code, str(exc)) from exc
    if isinstance(exc, (IntegrityError, DBAPIError)):
        raise _rejected(409, "SHORTAGE_CONCURRENT_CONFLICT", "Concurrent shortage mutation; retry original UUID.") from exc
    raise exc


@router.post("/dispatch/shortage-commands", status_code=201)
async def create_durable_shortage_demand(
    payload: ShortageDemandCommand,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_demand_create),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    company, actor_id = int(access.company_id), int(actor.id)
    try:
        record, replay = await _begin(
            db, company=company, actor=actor_id,
            operation="DISPATCH_SHORTAGE_DEMAND_V2", uuid=payload.request_id,
            digest=_demand_hash(payload),
        )
        if replay is not None:
            # Same user and persisted privilege rechecked before historical receipt.
            await _authorize_shop(db, access, int(payload.shop_id), int(payload.zone_id))
            await db.rollback()
            return replay
        product_ids = sorted(int(x.product_id) for x in payload.lines)
        await acquire_product_lifecycle_guards(db, company, product_ids, exclusive=False)
        if payload.requested_driver_id is not None and not await _driver_is_canonical(
            db, company, int(payload.requested_driver_id),
        ):
            raise _rejected(404, "SHORTAGE_DRIVER_UNAVAILABLE", "Representative unavailable.")
        shop = await _lock_zone_shop(db, access, int(payload.shop_id), int(payload.zone_id))
        variants = (await db.execute(
            select(ProductVariant).where(
                ProductVariant.company_id == company,
                ProductVariant.id.in_(product_ids),
            ).order_by(ProductVariant.id.asc())
        )).scalars().all()
        if {int(v.id) for v in variants} != set(product_ids):
            raise _rejected(404, "SHORTAGE_PRODUCT_NOT_FOUND", "Product unavailable.")
        for variant in variants:
            decision = evaluate_product_capability(
                variant.lifecycle_status, variant.operational_hold, REPLENISHMENT_NEW,
            )
            if not decision.allowed:
                raise _rejected(409, decision.code, "SKU cannot be newly replenished.")
        existing = (await db.scalars(
            select(ShortageRequest).where(
                ShortageRequest.company_id == company,
                ShortageRequest.shop_id == shop.id,
                ShortageRequest.product_variant_id.in_(product_ids),
                ShortageRequest.status == "pending",
            ).order_by(ShortageRequest.id.asc()).with_for_update()
        )).all()
        if existing:
            raise _rejected(409, "SHORTAGE_ALREADY_PENDING", "Pending demand for shop/SKU already exists.")
        rows = []
        for line in sorted(payload.lines, key=lambda x: int(x.product_id)):
            demand = ShortageRequest(
                company_id=company, shop_id=int(shop.id), zone_id=int(payload.zone_id),
                driver_id=int(payload.requested_driver_id) if payload.requested_driver_id else None,
                product_variant_id=int(line.product_id), quantity=int(line.quantity_base),
                fulfillment_version=1, fulfilled_base=0, status="pending",
            )
            db.add(demand)
            rows.append(demand)
        await db.flush()
        receipt = {
            "version": 2, "request_id": str(payload.request_id),
            "request_hash": _demand_hash(payload),
            "shop_id": int(shop.id), "zone_id": int(payload.zone_id),
            "requested_driver_id": int(payload.requested_driver_id) if payload.requested_driver_id else None,
            "status": "PENDING_REPLENISHMENT",
            "lines": [
                {"shortage_id": int(row.id), "product_id": int(row.product_variant_id),
                 "requested_base": int(row.quantity), "fulfilled_base": 0,
                 "outstanding_base": int(row.quantity)}
                for row in rows
            ],
        }
        db.add(SystemAuditLog(
            company_id=company, admin_id=actor_id,
            target_id=f"ShortageDemand_{shop.id}_{payload.request_id}",
            action_type="SHORTAGE_DEMAND_CREATED",
            old_value=None, new_value=json.dumps(receipt, sort_keys=True),
        ))
        complete_idempotent_operation(record, receipt)
        await db.commit()
        return receipt
    except Exception as exc:
        await db.rollback()
        _map_error(exc)


@router.get("/dispatch/shortage-commands/{request_id}", status_code=200)
async def read_shortage_command_receipt(
    request_id: UUID,
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_demand_read),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    # Read is historical proof, never inferred from current list GET.
    if request_id.version != 4:
        raise _rejected(422, "SHORTAGE_UUID_INVALID", "UUID v4 required.")
    record = await db.scalar(select(OperationIdempotency).where(
        OperationIdempotency.company_id == access.company_id,
        OperationIdempotency.created_by == actor.id,
        OperationIdempotency.operation == "DISPATCH_SHORTAGE_DEMAND_V2",
        OperationIdempotency.request_id == str(request_id),
        OperationIdempotency.state == "COMMITTED",
    ))
    if record is None or not isinstance(record.response_json, dict):
        raise _rejected(404, "SHORTAGE_RECEIPT_NOT_FOUND", "No confirmed receipt for this identity.")
    response = dict(record.response_json)
    await _authorize_shop(db, access, int(response["shop_id"]), int(response["zone_id"]))
    await db.rollback()
    return response


@router.post("/dispatch/shortages/{shortage_id}/promote-urgent", status_code=201)
async def promote_shortage_with_signed_stock(
    payload: ShortageUrgentPromotion,
    shortage_id: int = Path(..., gt=0),
    db: AsyncSession = Depends(get_db),
    access: BackofficeCapabilityAccess = Depends(_demand_create),
    actor: Driver = Depends(get_current_backoffice_legacy_driver),
):
    """Distinct manager mutation. No implicit stock transfer, no delivery promise.

    Exact current canonical FIELD custody, vehicle location grant and sellable
    physical free quantity are checked inside the locked transaction.
    """
    company, actor_id = int(access.company_id), int(actor.id)
    digest = _hash({
        "shortage_id": shortage_id, "driver_id": int(payload.driver_id),
        "quantity_base": int(payload.quantity_base),
    })
    try:
        await access.require("dispatch.execute", any_location=True)
        record, replay = await _begin(
            db, company=company, actor=actor_id,
            operation="DISPATCH_SHORTAGE_PROMOTE_V1", uuid=payload.request_id,
            digest=digest,
        )
        if replay is not None:
            await db.rollback()
            return replay
        # Probe identifiers only; real authority and scopes are checked after locks.
        pre = await db.scalar(
            select(ShortageRequest).where(
                ShortageRequest.company_id == company, ShortageRequest.id == shortage_id,
            )
        )
        if pre is None:
            raise _rejected(404, "SHORTAGE_NOT_FOUND", "No such demand.")
        shop = await _lock_zone_shop(db, access, int(pre.shop_id), int(pre.zone_id))
        shortage = await db.scalar(
            select(ShortageRequest).where(
                ShortageRequest.company_id == company, ShortageRequest.id == shortage_id,
            ).with_for_update()
        )
        if (shortage is None or shortage.status != "pending"
                or shortage.fulfillment_version != 1
                or shortage.fulfilled_base is None):
            raise _rejected(409, "SHORTAGE_LEGACY_OR_NOT_PENDING", "Demand is not an executable new request.")
        if shortage.driver_id is not None and shortage.driver_id != int(payload.driver_id):
            raise _rejected(409, "SHORTAGE_DRIVER_MISMATCH", "Manager must explicitly reassign before promotion.")
        if not await _driver_is_canonical(db, company, int(payload.driver_id)):
            raise _rejected(404, "SHORTAGE_DRIVER_UNAVAILABLE", "Representative unavailable.")
        representative_id = await db.scalar(
            select(IdentityLegacyDriverMap.field_representative_id).where(
                IdentityLegacyDriverMap.company_id == company,
                IdentityLegacyDriverMap.legacy_driver_id == payload.driver_id,
            )
        )
        if representative_id is None:
            raise _rejected(409, "SHORTAGE_SIGNED_CUSTODY_UNKNOWN", "No canonical FIELD identity.")
        epochs = (await db.scalars(
            select(VehicleCustodyEpoch).where(
                VehicleCustodyEpoch.company_id == company,
                VehicleCustodyEpoch.field_representative_id == representative_id,
                VehicleCustodyEpoch.custodian_kind == "FIELD_REPRESENTATIVE",
                VehicleCustodyEpoch.state == "ACCEPTED",
                VehicleCustodyEpoch.ended_at.is_(None),
            ).order_by(VehicleCustodyEpoch.id.desc()).limit(2).with_for_update()
        )).all()
        if len(epochs) != 1:
            raise _rejected(409, "SHORTAGE_SIGNED_CUSTODY_UNKNOWN", "Current accepted vehicle custody not unique.")
        epoch = epochs[0]
        await require_vehicle(access, "dispatch.execute", int(epoch.vehicle_id))
        await require_vehicle(access, "dispatch.read", int(epoch.vehicle_id))
        routes = (await db.scalars(
            select(DispatchRoute).where(
                DispatchRoute.company_id == company,
                DispatchRoute.driver_id == int(payload.driver_id),
                DispatchRoute.vehicle_id == int(epoch.vehicle_id),
                DispatchRoute.status == "active",
            ).order_by(DispatchRoute.id.asc()).limit(2).with_for_update(nowait=True)
        )).all()
        if len(routes) != 1:
            raise _rejected(409, "SHORTAGE_ROUTE_ASSIGNMENT_UNKNOWN", "No unique current route and vehicle.")
        # Match signed accepted epoch with the same authoritative stock reader as Phase A.
        try:
            state = await read_vehicle_state(db, company, int(epoch.vehicle_id))
        except CustodyRejected as exc:
            raise _rejected(409, "SHORTAGE_VEHICLE_UNVERIFIED", "Vehicle custody cannot be verified.") from exc
        if (
            state.epoch is None or int(state.epoch.id) != int(epoch.id)
            or state.epoch.state != "ACCEPTED"
            or state.epoch.custodian_kind != "FIELD_REPRESENTATIVE"
            or int(state.epoch.field_representative_id or 0) != int(representative_id)
            or int(state.location_id) != int(epoch.vehicle_location_id)
        ):
            raise _rejected(409, "SHORTAGE_CUSTODY_CHANGED", "Vehicle assignment changed.")
        product_id = int(shortage.product_variant_id)
        # Lock balances: any concurrent movement serialized through the same physical rows.
        await db.execute(
            select(InventoryBalance).where(
                InventoryBalance.company_id == company,
                InventoryBalance.location_id == int(state.location_id),
                InventoryBalance.product_variant_id == product_id,
            ).order_by(InventoryBalance.id.asc()).with_for_update()
        )
        selected_lines = [line for line in state.lines if int(line["variant_id"]) == product_id]
        batch_ids = {int(line["batch_id"]) for line in selected_lines}
        batch_rows = (await db.execute(
            select(ProductBatch.id, ProductBatch.product_variant_id,
                   ProductBatch.expiry_date, ProductBatch.disposition)
            .where(ProductBatch.company_id == company, ProductBatch.id.in_(batch_ids))
        )).all() if batch_ids else []
        batches = {int(r[0]): (int(r[1]), r[2], str(r[3])) for r in batch_rows}
        available = _sellable_by_variant(
            lines=selected_lines, batches=batches,
            today=await get_company_local_date(db, company), product_ids={product_id},
        )
        if available is None:
            raise _rejected(409, "SHORTAGE_STOCK_UNKNOWN", "Stock proof is unverified.")
        actual = available[product_id]
        if Decimal(int(payload.quantity_base)) > actual:
            raise _rejected(409, "SHORTAGE_STOCK_INSUFFICIENT", "Vehicle does not cover proposed urgent quantity.")
        assignments = (await db.scalars(
            select(ShortageUrgentAssignment).where(
                ShortageUrgentAssignment.company_id == company,
                ShortageUrgentAssignment.shortage_id == shortage_id,
            ).order_by(ShortageUrgentAssignment.id.asc()).with_for_update()
        )).all()
        remaining_unassigned = int(shortage.quantity) - sum(int(a.approved_base) for a in assignments)
        if int(payload.quantity_base) > remaining_unassigned:
            raise _rejected(409, "SHORTAGE_URGENT_EXCEEDS_OUTSTANDING", "Requested urgent amount exceeds unassigned demand.")
        await db.execute(text(
            "SELECT pg_advisory_xact_lock(CAST(:company AS integer), hashtext(:key))"
        ), {"company": company,
            "key": f"pending-visit:{int(payload.driver_id)}:{int(shop.id)}"})
        pending_visits = (await db.scalars(
            select(Visit).where(
                Visit.company_id == company, Visit.driver_id == int(payload.driver_id),
                Visit.shop_id == int(shop.id), Visit.status == "Pending",
            ).order_by(Visit.id.asc()).with_for_update()
        )).all()
        if len(pending_visits) > 1:
            raise _rejected(409, "SHORTAGE_PENDING_VISIT_AMBIGUOUS", "Duplicate pending visits.")
        visit = ensure_shortage_pending_visit(
            db, company_id=company, driver_id=int(payload.driver_id),
            shop=shop, operational_date=await get_company_local_date(db, company),
            existing=pending_visits[0] if pending_visits else None,
        )
        await db.flush()
        if any(int(a.visit_id) == int(visit.id) for a in assignments):
            raise _rejected(409, "SHORTAGE_ALREADY_ASSIGNED_TO_VISIT", "This Visit already owns this shortage.")
        assignment = ShortageUrgentAssignment(
            company_id=company, shortage_id=shortage_id, visit_id=int(visit.id),
            driver_id=int(payload.driver_id), vehicle_id=int(epoch.vehicle_id),
            custody_epoch_id=int(epoch.id), approved_base=int(payload.quantity_base),
        )
        db.add(assignment)
        await db.flush()
        response = {
            "request_id": str(payload.request_id), "shortage_id": shortage_id,
            "assignment_id": int(assignment.id), "visit_id": int(visit.id),
            "approved_base": int(payload.quantity_base),
            "outstanding_base": int(shortage.quantity) - int(shortage.fulfilled_base),
            "custody_epoch_id": int(epoch.id), "state": "URGENT_AUTHORIZED",
        }
        db.add(SystemAuditLog(
            company_id=company, admin_id=actor_id,
            target_id=f"ShortageUrgent_{shortage_id}_{payload.request_id}",
            action_type="SHORTAGE_URGENT_AUTHORIZED",
            old_value=None, new_value=json.dumps(response, sort_keys=True),
        ))
        complete_idempotent_operation(record, response)
        await db.commit()
        return response
    except BackofficeCapabilityAccessRejected as exc:
        await db.rollback()
        raise _rejected(403, "SHORTAGE_PROMOTION_SCOPE_DENIED", "Authorization denied.") from exc
    except Exception as exc:
        await db.rollback()
        _map_error(exc)
