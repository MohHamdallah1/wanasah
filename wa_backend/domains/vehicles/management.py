from __future__ import annotations

import hashlib
import json
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from models import Vehicle
from services import (
    InventoryMutationError,
    begin_idempotent_operation,
    complete_idempotent_operation,
)

from .contracts import (
    CreateVehicleCommand,
    UpdateVehicleCommand,
    VehicleError,
)
from .custody import create_custody_for_vehicle, lock_vehicle_custody
from .lifecycle_guards import assert_vehicle_maintenance_transition_safe
from .queries import get_vehicle, vehicle_payload
from .repository import (
    add_vehicle_audit,
    guard_vehicle_request_identity,
    load_vehicle,
    plate_exists,
)


from .validation import (
    nonnegative_int,
    normalize_maintenance_status,
    normalize_plate,
    normalize_vehicle_type,
    validated_update_fields,
)


async def create_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    command: CreateVehicleCommand,
) -> dict:
    plate = normalize_plate(command.plate_number)
    vehicle_type = normalize_vehicle_type(command.vehicle_type)
    mileage = nonnegative_int(command.current_mileage, "current_mileage")
    next_oil = nonnegative_int(
        command.next_oil_change,
        "next_oil_change",
        optional=True,
    )
    maintenance = normalize_maintenance_status(command.maintenance_status)
    request_hash = _stable_hash(
        "VEHICLE_CREATE",
        {
            "plate_number": plate,
            "vehicle_type": vehicle_type,
            "current_mileage": mileage,
            "next_oil_change": next_oil,
            "license_expiry_date": command.license_expiry_date,
            "maintenance_status": maintenance,
        },
    )
    try:
        request_id = await guard_vehicle_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation="VEHICLE_CREATE",
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation="VEHICLE_CREATE",
            request_id=request_id,
            request_hash=request_hash,
        )
        if replay is not None:
            await db.rollback()
            return replay

        if await plate_exists(
            db,
            company_id=company_id,
            plate_number=plate,
        ):
            raise VehicleError(
                "VEHICLE_PLATE_CONFLICT",
                "Vehicle plate number already exists in this company.",
                status_code=409,
            )

        vehicle = Vehicle(
            company_id=company_id,
            plate_number=plate,
            vehicle_type=vehicle_type,
            current_mileage=mileage,
            next_oil_change=next_oil,
            license_expiry_date=command.license_expiry_date,
            maintenance_status=maintenance,
            is_active=True,
            version=1,
        )
        db.add(vehicle)
        await db.flush()
        await create_custody_for_vehicle(
            db,
            company_id=company_id,
            vehicle=vehicle,
        )
        payload = vehicle_payload(
            await get_vehicle(
                db,
                company_id=company_id,
                vehicle_id=int(vehicle.id),
            )
        )
        add_vehicle_audit(
            db,
            company_id=company_id,
            actor_id=actor_id,
            vehicle_id=int(vehicle.id),
            action="VEHICLE_CREATED",
            before=None,
            after={**payload, "request_id": request_id},
        )
        complete_idempotent_operation(idem, payload)
        await db.commit()
        return payload
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
    except IntegrityError as exc:
        await db.rollback()
        raise VehicleError(
            "VEHICLE_CREATE_CONFLICT",
            "Vehicle could not be created because of a concurrent conflict.",
            status_code=409,
        ) from exc
    except Exception:
        await db.rollback()
        raise


async def update_vehicle(
    db: AsyncSession,
    *,
    company_id: int,
    actor_id: int,
    vehicle_id: int,
    command: UpdateVehicleCommand,
) -> dict:
    fields = validated_update_fields(command)
    request_hash = _stable_hash(
        "VEHICLE_UPDATE",
        {
            "vehicle_id": vehicle_id,
            "expected_version": command.expected_version,
            "fields": fields,
        },
    )
    try:
        request_id = await guard_vehicle_request_identity(
            db,
            company_id=company_id,
            request_id=command.request_id,
            operation="VEHICLE_UPDATE",
        )
        idem, replay = await begin_idempotent_operation(
            db,
            company_id=company_id,
            actor_id=actor_id,
            operation="VEHICLE_UPDATE",
            request_id=request_id,
            request_hash=request_hash,
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
        if int(vehicle.version) != int(command.expected_version):
            raise VehicleError(
                "VEHICLE_VERSION_CONFLICT",
                "Vehicle was changed. Refresh before editing.",
                status_code=409,
            )
        location = await lock_vehicle_custody(
            db,
            company_id=company_id,
            vehicle_id=vehicle_id,
        )
        before = vehicle_payload(
            await get_vehicle(
                db,
                company_id=company_id,
                vehicle_id=vehicle_id,
            )
        )

        if (
            "plate_number" in fields
            and fields["plate_number"] != vehicle.plate_number
            and await plate_exists(
                db,
                company_id=company_id,
                plate_number=str(fields["plate_number"]),
                exclude_vehicle_id=vehicle_id,
            )
        ):
            raise VehicleError(
                "VEHICLE_PLATE_CONFLICT",
                "Vehicle plate number already exists in this company.",
                status_code=409,
            )
        if (
            fields.get("maintenance_status") == "In_Maintenance"
            and vehicle.maintenance_status != "In_Maintenance"
        ):
            await assert_vehicle_maintenance_transition_safe(
                db,
                company_id=company_id,
                vehicle_id=vehicle_id,
            )

        changed = False
        for field, value in fields.items():
            if getattr(vehicle, field) != value:
                setattr(vehicle, field, value)
                changed = True

        if "plate_number" in fields:
            desired_name = f"Vehicle {vehicle.plate_number}"
            if location.name != desired_name:
                location.name = desired_name
                location.version = int(location.version) + 1

        if changed:
            vehicle.version = int(vehicle.version) + 1
            await db.flush()

        after = vehicle_payload(
            await get_vehicle(
                db,
                company_id=company_id,
                vehicle_id=vehicle_id,
            )
        )
        if after != before:
            add_vehicle_audit(
                db,
                company_id=company_id,
                actor_id=actor_id,
                vehicle_id=vehicle_id,
                action="VEHICLE_UPDATED",
                before=before,
                after={**after, "request_id": request_id},
            )
        complete_idempotent_operation(idem, after)
        await db.commit()
        return after
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
    except IntegrityError as exc:
        await db.rollback()
        raise VehicleError(
            "VEHICLE_UPDATE_CONFLICT",
            "Vehicle could not be updated because of a concurrent conflict.",
            status_code=409,
        ) from exc
    except Exception:
        await db.rollback()
        raise


__all__ = ["create_vehicle", "update_vehicle"]
