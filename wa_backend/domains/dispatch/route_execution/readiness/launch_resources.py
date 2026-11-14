"""Bounded canonical M05 launch resource availability; read-only advisory.

No old DispatchRoute driver/car is used after canonical conversion. A postponed
route reserves its zone but not its former driver/car; WAITING/ACTIVE reserve
the last signed assignment even after daily WorkSession END. The original
route-create writer remains the final locked authority for actual admission.
"""
from __future__ import annotations

from sqlalchemy import and_, func, or_, select

from dispatch_access import route_filter, vehicle_filter
from domains.dispatch_shop_read_scope import company_shop_directory, visible_zone_filter
from domains.dispatch.route_execution.models import DispatchRouteExecutionPeriod
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.dispatch.route_execution.readiness.custody_codes import custody_blocker
from domains.dispatch_representatives import has_canonical_field_identity
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.vehicles.eligibility import vehicle_operational_predicate
from domains.vehicles.repository import vehicle_custody_ready_predicate
from models import (
    DispatchRoute, Driver, InventoryBalance, InventoryLocation, InventoryLock,
    Vehicle, WorkSession, Zone,
)

MAX_LAUNCH_CHOICES = 1024


class LaunchAvailabilityRejected(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _guard(rows, label):
    if len(rows) > MAX_LAUNCH_CHOICES:
        raise LaunchAvailabilityRejected("M05_LAUNCH_" + label + "_WINDOW_EXCEEDED")
    return rows


async def read_launch_resource_availability(
    db, *, access, selected_driver_id: int | None = None,
    selected_vehicle_id: int | None = None,
) -> dict:
    cid = access.company_id
    company_directory = await company_shop_directory(access)
    zone_scope = visible_zone_filter(access, company_directory=company_directory)

    zones = _guard((await db.scalars(
        select(Zone).where(Zone.company_id == cid, zone_scope)
        .order_by(Zone.id).limit(MAX_LAUNCH_CHOICES + 1)
    )).all(), "ZONE")
    if company_directory:
        drivers_stmt = select(
            Driver, has_canonical_field_identity(
                company_id=cid, legacy_driver_id=Driver.id,
            ).label("field_verified")
        ).where(Driver.company_id == cid)
    else:
        # Route-restricted readers must not enumerate all representatives.
        drivers_stmt = select(
            Driver, has_canonical_field_identity(
                company_id=cid, legacy_driver_id=Driver.id,
            ).label("field_verified")
        ).where(Driver.company_id == cid, Driver.id.in_(
            select(DispatchRoute.driver_id).where(
                DispatchRoute.company_id == cid,
                DispatchRoute.status.in_(("active", "waiting")),
                route_filter(access, "dispatch.read"),
            )
        ))
    drivers = _guard((await db.execute(
        drivers_stmt.order_by(Driver.id).limit(MAX_LAUNCH_CHOICES + 1),
    )).all(), "DRIVER")
    vehicles = _guard((await db.execute(select(
        Vehicle,
        vehicle_operational_predicate(Vehicle).label("operational"),
        vehicle_custody_ready_predicate(Vehicle).label("custody_ready"),
        vehicle_filter(access, "dispatch.execute", Vehicle.id).label("may_execute"),
    ).where(
        Vehicle.company_id == cid, vehicle_filter(access, "dispatch.read", Vehicle.id),
    ).order_by(Vehicle.id).limit(MAX_LAUNCH_CHOICES + 1))).all(), "VEHICLE")
    warehouses = _guard((await db.execute(select(
        InventoryLocation, access.location_filter(
            "dispatch.execute", InventoryLocation.id,
        ).label("may_execute"),
    ).where(
        InventoryLocation.company_id == cid,
        InventoryLocation.location_type == "WAREHOUSE",
        access.location_filter("dispatch.read", InventoryLocation.id),
    ).order_by(InventoryLocation.id).limit(MAX_LAUNCH_CHOICES + 1))).all(), "WAREHOUSE")
    route_rows = _guard((await db.scalars(select(DispatchRoute).where(
        DispatchRoute.company_id == cid,
        DispatchRoute.status.in_(("active", "waiting", "postponed")),
    ).order_by(DispatchRoute.id).limit(MAX_LAUNCH_CHOICES + 1))).all(), "ROUTE")

    zone_busy = {int(r.zone_id): ("ZONE_POSTPONED_RESERVED" if r.status == "postponed"
                                  else "ZONE_ROUTE_RESERVED") for r in route_rows}
    # Canonical latest period is the signed current assignment even if End Work
    # closed the DAILY period. Do not revive old historical route columns.
    active = [r for r in route_rows if r.status in ("active", "waiting")]
    active_ids = [int(r.id) for r in active]
    latest_by_route = {}
    if active_ids:
        period = DispatchRouteExecutionPeriod
        ranked = select(
            period.route_id.label("route_id"),
            period.driver_id.label("driver_id"),
            period.vehicle_id.label("vehicle_id"),
            period.context_revision.label("revision"),
            period.evidence_origin.label("origin"),
            period.request_id.label("request_id"),
            period.payload_hash.label("payload_hash"),
            period.started_by_principal_id.label("signed_by"),
            func.row_number().over(
                partition_by=period.route_id,
                order_by=period.id.desc(),
            ).label("rank"),
        ).join(
            DispatchRoute,
            and_(DispatchRoute.company_id == period.company_id,
                 DispatchRoute.id == period.route_id),
        ).where(
            period.company_id == cid,
            period.route_id.in_(active_ids),
            period.context_revision == DispatchRoute.assignment_context_revision,
        ).subquery()
        found = (await db.execute(select(ranked).where(
            ranked.c.rank == 1,
        ))).mappings().all()
        latest_by_route = {int(p["route_id"]): p for p in found}

    held_drivers: set[int] = set()
    held_vehicles: set[int] = set()
    for route in active:
        current = latest_by_route.get(int(route.id))
        if current is not None:
            if (current["origin"] != "CANONICAL" or not current["request_id"]
                    or not current["payload_hash"] or not current["signed_by"]
                    or int(current["revision"]) != int(route.assignment_context_revision)):
                raise LaunchAvailabilityRejected("M05_LAUNCH_CURRENT_ASSIGNMENT_UNVERIFIED")
            held_drivers.add(int(current["driver_id"]))
            held_vehicles.add(int(current["vehicle_id"]))
        elif int(route.assignment_context_revision) == 1:
            if route.driver_id is not None:
                held_drivers.add(int(route.driver_id))
            if route.vehicle_id is not None:
                held_vehicles.add(int(route.vehicle_id))
        else:
            # Ambiguous live custody cannot become a false available choice.
            raise LaunchAvailabilityRejected("M05_LAUNCH_CURRENT_ASSIGNMENT_MISSING")

    driver_ids = [int(row[0].id) for row in drivers]
    vehicle_ids = [int(row[0].id) for row in vehicles]
    # An OPEN S1 is reusable for M03 A→B→A and must not falsely reserve the
    # representative after POSTPONE. Only a prior ENDED-but-unsettled S1 blocks
    # any new S2, exactly as the owner policy requires.
    unsettled: set[int] = set()
    if driver_ids:
        unsettled = set((await db.scalars(select(WorkSession.driver_id).where(
            WorkSession.company_id == cid,
            WorkSession.driver_id.in_(driver_ids),
            WorkSession.end_time.is_not(None),
            or_(WorkSession.is_settled.is_(False),
                WorkSession.inventory_reconciled_at.is_(None)),
        ))).all())

    # A current accepted epoch is tied to a FIELD principal, not merely a car.
    # A selected driver with a different identity cannot take it implicitly.
    principal_by_driver = {}
    if driver_ids:
        maps = (await db.execute(select(
            IdentityLegacyDriverMap.legacy_driver_id,
            IdentityLegacyDriverMap.field_representative_id,
            IdentityLegacyDriverMap.field_principal_id,
        ).where(
            IdentityLegacyDriverMap.company_id == cid,
            IdentityLegacyDriverMap.legacy_driver_id.in_(driver_ids),
        ))).all()
        for legacy, rep, principal in maps:
            if int(legacy) in principal_by_driver:
                raise LaunchAvailabilityRejected("M05_LAUNCH_DRIVER_IDENTITY_AMBIGUOUS")
            principal_by_driver[int(legacy)] = (rep, principal)
    current_epochs = {}
    if vehicle_ids:
        epochs = (await db.scalars(select(VehicleCustodyEpoch).where(
            VehicleCustodyEpoch.company_id == cid,
            VehicleCustodyEpoch.vehicle_id.in_(vehicle_ids),
            VehicleCustodyEpoch.ended_at.is_(None),
        ).order_by(VehicleCustodyEpoch.vehicle_id)
        .limit(MAX_LAUNCH_CHOICES + 1))).all()
        _guard(epochs, "CUSTODY")
        for epoch in epochs:
            if int(epoch.vehicle_id) in current_epochs:
                raise LaunchAvailabilityRejected("M05_LAUNCH_CUSTODY_AMBIGUOUS")
            current_epochs[int(epoch.vehicle_id)] = epoch

    # Missing M01 epoch is safe only for a genuinely empty new car. A legacy
    # stocked vehicle without an epoch must never be advertised as assignable.
    stocked_vehicle_ids = set()
    if vehicle_ids:
        stocked_vehicle_ids = set((await db.scalars(select(
            InventoryLocation.vehicle_id
        ).join(
            InventoryBalance,
            and_(InventoryBalance.company_id == InventoryLocation.company_id,
                 InventoryBalance.location_id == InventoryLocation.id),
        ).where(
            InventoryLocation.company_id == cid,
            InventoryLocation.vehicle_id.in_(vehicle_ids),
            InventoryLocation.location_type == "VEHICLE",
            InventoryBalance.on_hand_quantity > 0,
        ).distinct())).all())

    warehouse_ids = [int(row[0].id) for row in warehouses]
    locked_warehouses = set()
    if warehouse_ids:
        locked_warehouses = set((await db.scalars(select(InventoryLock.location_id).where(
            InventoryLock.company_id == cid,
            InventoryLock.location_id.in_(warehouse_ids),
            InventoryLock.released_at.is_(None),
            InventoryLock.product_variant_id.is_(None),
        ))).all())

    may_execute = bool(await db.scalar(select(
        access.allows("dispatch.execute", any_location=True),
    )))
    result_drivers = []
    for driver, verified in drivers:
        reason = (
            "REPRESENTATIVE_INACTIVE" if not driver.is_active else
            "REPRESENTATIVE_FIELD_UNVERIFIED" if not verified else
            "REPRESENTATIVE_ON_ROUTE" if int(driver.id) in held_drivers else
            "PREVIOUS_SESSION_UNSETTLED" if int(driver.id) in unsettled else
            "NO_EXECUTE_PERMISSION" if not may_execute else "AVAILABLE"
        )
        if reason == "AVAILABLE" and selected_vehicle_id is not None:
            epoch = current_epochs.get(int(selected_vehicle_id))
            if epoch is not None:
                rep, principal = principal_by_driver.get(int(driver.id), (None, None))
                reason = custody_blocker(
                    epoch, representative_id=rep, principal_id=principal,
                ) or reason
            elif int(selected_vehicle_id) in stocked_vehicle_ids:
                reason = "CUSTODY_STOCK_WITHOUT_EPOCH"
        result_drivers.append(dict(
            id=str(driver.id), label=driver.full_name,
            available=reason == "AVAILABLE", code=reason,
        ))

    result_vehicles = []
    for vehicle, operational, custody_ready, execute in vehicles:
        reason = (
            "VEHICLE_NOT_OPERATIONAL" if not operational else
            "VEHICLE_LOCATION_INVALID" if not custody_ready else
            "VEHICLE_ON_ROUTE" if int(vehicle.id) in held_vehicles else
            "NO_EXECUTE_PERMISSION" if not execute else "AVAILABLE"
        )
        epoch = current_epochs.get(int(vehicle.id))
        if reason == "AVAILABLE":
            rep, principal = principal_by_driver.get(
                int(selected_driver_id), (None, None),
            ) if selected_driver_id is not None else (None, None)
            reason = (
                custody_blocker(
                    epoch, representative_id=rep, principal_id=principal,
                ) or "AVAILABLE"
            ) if epoch is not None else (
                "CUSTODY_STOCK_WITHOUT_EPOCH"
                if int(vehicle.id) in stocked_vehicle_ids else "AVAILABLE"
            )
        result_vehicles.append(dict(
            id=str(vehicle.id),
            label=(vehicle.vehicle_type or "Vehicle") + " - " + vehicle.plate_number,
            available=reason == "AVAILABLE", code=reason,
        ))

    return dict(
        advisory=True,
        zones=[dict(id=str(zone.id), label=zone.name, available=bool(
            zone.is_active and may_execute and int(zone.id) not in zone_busy),
            code=("ZONE_INACTIVE" if not zone.is_active else
                  zone_busy[int(zone.id)] if int(zone.id) in zone_busy else
                  "NO_EXECUTE_PERMISSION" if not may_execute else "AVAILABLE"),
        ) for zone in zones],
        drivers=result_drivers,
        vehicles=result_vehicles,
        warehouses=[dict(
            id=str(w.id), label=f"{w.name} ({w.code})",
            available=bool(w.is_active and can_execute and int(w.id) not in locked_warehouses),
            code=("WAREHOUSE_INACTIVE" if not w.is_active else
                  "NO_EXECUTE_PERMISSION" if not can_execute else
                  "WAREHOUSE_AUDIT_LOCK" if int(w.id) in locked_warehouses else
                  "AVAILABLE"),
        ) for w, can_execute in warehouses],
    )
