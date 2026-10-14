from __future__ import annotations

import hashlib
import json

from sqlalchemy.ext.asyncio import AsyncSession

from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)

from .contracts import VehicleError, VehicleLifecycleCommand
from .custody import lock_vehicle_custody
from .lifecycle_guards import assert_vehicle_deactivation_safe
from .repository import (
    add_vehicle_audit,
    guard_vehicle_request_identity,
    load_vehicle,
)


_DEACTIVATE = "VEHICLE_DEACTIVATE"
_REACTIVATE = "VEHICLE_REACTIVATE"


def _request_hash(operation: str, vehicle_id: int, expected_version: int) -> str:
    body = json.dumps(
        {
            "operation": operation,
            "vehicle_id": vehicle_id,
            "expected_version": expected_version,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _version_check(vehicle, expected_version: int) -> None:
    if expected_version <= 0:
        raise VehicleError(
            "VEHICLE_VERSION_INVALID",
            "Vehicle expected version is invalid.",
            status_code=422,
        )
    if int(vehicle.version) != int(expected_version):
        raise VehicleError(
            "VEHICLE_VERSION_CONFLICT",
            "Vehicle was changed. Refresh before changing state.",
            status_code=409,
        )


async def deactivate_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    vehicle_id: int,
    command: VehicleLifecycleCommand,
) -> dict:
    try:
        request_id = await guard_vehicle_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation=_DEACTIVATE,
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation=_DEACTIVATE,
            request_id=request_id,
            request_hash=_request_hash(
                _DEACTIVATE,
                vehicle_id,
                command.expected_version,
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay

        vehicle = await load_vehicle(
            db,
            company_id=company_id,
            vehicle_id=vehicle_id,
            for_update=True,
        )
        _version_check(vehicle, command.expected_version)
        if not vehicle.is_active:
            raise VehicleError(
                "VEHICLE_ALREADY_INACTIVE",
                "Vehicle is already inactive.",
                status_code=409,
            )

        location = await lock_vehicle_custody(
            db,
            company_id=company_id,
            vehicle_id=vehicle_id,
        )
        if not location.is_active:
            raise VehicleError(
                "VEHICLE_CUSTODY_LOCATION_INCONSISTENT",
                "Active Vehicle has inactive custody location.",
                status_code=409,
            )

        await assert_vehicle_deactivation_safe(
            db,
            company_id=company_id,
            vehicle_id=vehicle_id,
            location_id=int(location.id),
        )

        previous_version = int(vehicle.version)
        vehicle.is_active = False
        vehicle.version = previous_version + 1
        location.is_active = False
        location.version = int(location.version) + 1
        await db.flush()

        response = {
            "vehicle_id": vehicle_id,
            "state": "INACTIVE",
            "version": int(vehicle.version),
        }
        add_vehicle_audit(
            db,
            company_id=company_id,
            actor_id=actor_id,
            vehicle_id=vehicle_id,
            action="VEHICLE_DEACTIVATED",
            before={"is_active": True, "version": previous_version},
            after={**response, "request_id": request_id},
        )
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except VehicleError:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise VehicleError(
            "VEHICLE_IDEMPOTENCY_CONFLICT",
            "The request identity conflicts with a previous vehicle command.",
            status_code=409,
        ) from exc
    except Exception:
        await db.rollback()
        raise


async def reactivate_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    vehicle_id: int,
    command: VehicleLifecycleCommand,
) -> dict:
    try:
        request_id = await guard_vehicle_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation=_REACTIVATE,
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation=_REACTIVATE,
            request_id=request_id,
            request_hash=_request_hash(
                _REACTIVATE,
                vehicle_id,
                command.expected_version,
            ),
        )
        if replay is not None:
            await db.rollback()
            return replay

        vehicle = await load_vehicle(
            db,
            company_id=company_id,
            vehicle_id=vehicle_id,
            for_update=True,
        )
        _version_check(vehicle, command.expected_version)
        if vehicle.is_active:
            raise VehicleError(
                "VEHICLE_ALREADY_ACTIVE",
                "Vehicle is already active.",
                status_code=409,
            )

        location = await lock_vehicle_custody(
            db,
            company_id=company_id,
            vehicle_id=vehicle_id,
        )
        if location.is_active:
            raise VehicleError(
                "VEHICLE_CUSTODY_LOCATION_INCONSISTENT",
                "Inactive Vehicle has active custody location.",
                status_code=409,
            )

        previous_version = int(vehicle.version)
        vehicle.is_active = True
        vehicle.version = previous_version + 1
        location.is_active = True
        location.version = int(location.version) + 1
        await db.flush()

        response = {
            "vehicle_id": vehicle_id,
            "state": "ACTIVE",
            "version": int(vehicle.version),
        }
        add_vehicle_audit(
            db,
            company_id=company_id,
            actor_id=actor_id,
            vehicle_id=vehicle_id,
            action="VEHICLE_REACTIVATED",
            before={"is_active": False, "version": previous_version},
            after={
                **response,
                "maintenance_status": vehicle.maintenance_status,
                "request_id": request_id,
            },
        )
        complete_idempotent_operation(idem, response)
        await db.commit()
        return response
    except VehicleError:
        await db.rollback()
        raise
    except InventoryMutationError as exc:
        await db.rollback()
        raise VehicleError(
            "VEHICLE_IDEMPOTENCY_CONFLICT",
            "The request identity conflicts with a previous vehicle command.",
            status_code=409,
        ) from exc
    except Exception:
        await db.rollback()
        raise


__all__ = ["deactivate_vehicle", "reactivate_vehicle"]
