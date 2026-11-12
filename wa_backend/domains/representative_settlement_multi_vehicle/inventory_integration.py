"""Canonical Vehicle Recon membership and per-location ending snapshots.

The two approved Inventory helpers delegate here only for canonical sessions.
Stocktake still owns review/posting; no balance or price is written here.
An approved variance seals one location, never the entire financial day.
"""
from decimal import Decimal

from sqlalchemy import or_, select

from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from models import InventoryBalance, SessionInventorySnapshot, Vehicle, utc_now
from quantity import QUANTITY_MAX

from .contracts import MAX_LINES, CustodyRejected
from .resolution import session_responsibilities


async def canonical_session(db, *, company_id, session_id):
    return (await db.execute(select(DispatchRouteExecutionPeriod.id).where(
        DispatchRouteExecutionPeriod.company_id == company_id,
        DispatchRouteExecutionPeriod.work_session_id == session_id,
        DispatchRouteExecutionPeriod.evidence_origin == "CANONICAL",
    ).limit(1))).scalar_one_or_none() is not None


async def lock_canonical_recon_vehicles(db, *, company_id, session_id):
    """Caller invokes after WorkSession and BEFORE any location guard."""
    if not await canonical_session(db, company_id=company_id, session_id=session_id):
        return
    _, vehicles = await session_responsibilities(
        db, company_id=company_id, session_id=session_id, lock_session=True,
    )
    locked = (await db.scalars(select(Vehicle.id).where(
        Vehicle.company_id == company_id, Vehicle.id.in_([v.vehicle_id for v in vehicles]),
    ).order_by(Vehicle.id).with_for_update())).all()
    if len(locked) != len(vehicles):
        raise CustodyRejected("CUSTODY_CHANGED")
    await session_responsibilities(db, company_id=company_id, session_id=session_id, lock=True)


async def validate_canonical_recon(db, *, company_id, session_id, vehicle_id):
    from .activation import require_m04_schema
    await require_m04_schema(db)
    work, vehicles = await session_responsibilities(
        db, company_id=company_id, session_id=session_id, lock_session=True,
    )
    if work.is_settled:
        raise CustodyRejected("FINANCIAL_SETTLEMENT_ALREADY_CLOSED")
    if work.inventory_reconciled_at is not None:
        raise CustodyRejected("SESSION_INVENTORY_ALREADY_SEALED")
    vehicle = next((v for v in vehicles if v.vehicle_id == vehicle_id), None)
    if vehicle is None:
        raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND")
    # Check the current custody as well as historical session membership. A
    # late correction must not consume a later custodian's physical inventory.
    from .snapshots import load_vehicle_snapshot
    await load_vehicle_snapshot(db, company_id=company_id, session_id=session_id,
                                responsibility=vehicle)
    return work


async def seal_canonical_location(db, *, company_id, work, location_id, actor_id):
    from .activation import require_m04_schema
    await require_m04_schema(db)
    from services import acquire_inventory_location_guard
    checked, vehicles = await session_responsibilities(
        db, company_id=company_id, session_id=work.id, lock_session=True,
    )
    if checked.is_settled:
        raise CustodyRejected("FINANCIAL_SETTLEMENT_ALREADY_CLOSED")
    if not any(v.location_id == location_id for v in vehicles):
        raise CustodyRejected("SESSION_VEHICLE_NOT_FOUND")
    await acquire_inventory_location_guard(db, company_id, location_id, exclusive=True)
    balances = (await db.scalars(select(InventoryBalance).where(
        InventoryBalance.company_id == company_id, InventoryBalance.location_id == location_id,
        or_(InventoryBalance.on_hand_quantity > 0, InventoryBalance.reserved_quantity > 0),
    ).order_by(InventoryBalance.id).limit(MAX_LINES + 1).with_for_update())).all()
    if len(balances) > MAX_LINES:
        raise CustodyRejected("SETTLEMENT_CUSTODY_TOO_LARGE")
    totals = {}
    for balance in balances:
        quantity = Decimal(balance.on_hand_quantity)
        if Decimal(balance.reserved_quantity) != 0 or not quantity.is_finite() or quantity < 0:
            raise CustodyRejected("VEHICLE_CUSTODY_RESERVED_OR_INVALID")
        key = (balance.product_variant_id, balance.stock_status)
        totals[key] = totals.get(key, Decimal(0)) + quantity
        if totals[key] > QUANTITY_MAX:
            raise CustodyRejected("VEHICLE_CUSTODY_QUANTITY_OVERFLOW")
    rows = (await db.scalars(select(SessionInventorySnapshot).where(
        SessionInventorySnapshot.company_id == company_id,
        SessionInventorySnapshot.work_session_id == work.id,
        SessionInventorySnapshot.location_id == location_id,
    ).order_by(SessionInventorySnapshot.id).limit(MAX_LINES + 1).with_for_update())).all()
    if len(rows) > MAX_LINES:
        raise CustodyRejected("SETTLEMENT_CUSTODY_TOO_LARGE")
    known = {(r.product_variant_id, r.stock_status): r for r in rows}
    if len(known) != len(rows):
        raise CustodyRejected("DUPLICATE_CUSTODY_IDENTITY")
    now = utc_now()
    for key in sorted(set(known) | set(totals)):
        quantity = totals.get(key, Decimal(0))
        row = known.get(key)
        if row is not None and row.ending_quantity is not None:
            if (Decimal(row.ending_quantity) != quantity or row.settled_at is None
                    or row.settled_by is None):
                raise CustodyRejected("SEALED_CUSTODY_SNAPSHOT_STALE")
            continue
        if row is not None and (row.settled_by is not None or row.settled_at is not None):
            raise CustodyRejected("INCOMPLETE_INVENTORY_SEAL")
        if row is None:
            row = SessionInventorySnapshot(
                company_id=company_id, work_session_id=work.id, location_id=location_id,
                product_variant_id=key[0], stock_status=key[1], starting_quantity=Decimal(0),
                # CHECK settled_at >= created_at applies also to new rows:
                # use the exact same timestamp as their signed settlement.
                created_at=now,
            )
            db.add(row)
        row.ending_quantity, row.settled_at, row.settled_by = quantity, now, actor_id
    # The global seal belongs to all signed vehicle checkpoints, not to this
    # per-location stocktake callback. is_settled remains finance-owned.
    await db.flush()
    return work
