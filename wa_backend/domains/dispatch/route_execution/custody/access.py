"""Dispatch-specific per-vehicle scope, outside Vehicle API package.

The canonical require_vehicle guard verifies the tenant's real vehicle,
exactly one active vehicle location and dispatch.execute for that location.
"""
from __future__ import annotations
from dispatch_access import require_vehicle
from domains.authorization.backoffice_access import BackofficeCapabilityAccess


async def require_custody_vehicle_scope(
    access: BackofficeCapabilityAccess, vehicle_id: int,
) -> None:
    await require_vehicle(access, "dispatch.execute", vehicle_id)
