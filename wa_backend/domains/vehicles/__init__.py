from .contracts import (
    CreateVehicleCommand,
    UpdateVehicleCommand,
    VehicleError,
    VehicleLifecycleCommand,
    VehiclePage,
    VehicleRecord,
)
from .custody import (
    resolve_vehicle_custody_location_id,
    resolve_vehicle_custody_location_ids,
    vehicle_custody_ready_predicate,
)
from .eligibility import (
    read_vehicle_operational_state,
    require_vehicle_operational_state,
    route_requires_operational_vehicle,
    vehicle_is_operational,
    vehicle_operational_predicate,
)
from .lifecycle import deactivate_vehicle, reactivate_vehicle
from .management import create_vehicle, update_vehicle
from .queries import get_vehicle, list_vehicles, vehicle_payload

__all__ = [
    "CreateVehicleCommand",
    "UpdateVehicleCommand",
    "VehicleError",
    "VehicleLifecycleCommand",
    "VehiclePage",
    "VehicleRecord",
    "create_vehicle",
    "deactivate_vehicle",
    "get_vehicle",
    "list_vehicles",
    "reactivate_vehicle",
    "resolve_vehicle_custody_location_id",
    "resolve_vehicle_custody_location_ids",
    "vehicle_custody_ready_predicate",
    "require_vehicle_operational_state",
    "vehicle_operational_predicate",
    "vehicle_is_operational",
    "read_vehicle_operational_state",
    "route_requires_operational_vehicle",
    "update_vehicle",
    "vehicle_payload",
]
