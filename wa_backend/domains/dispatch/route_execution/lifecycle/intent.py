"""Strict, retry-safe M02 route lifecycle command input.

A route assignment is not a stock command. No legacy inventory/quantity key is
accepted, even an empty one. The caller must preserve request_id after timeout.
"""
from __future__ import annotations

from hashlib import sha256
import json
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, PositiveInt, model_validator


class RouteLifecycleIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: Literal["POSTPONE", "RESUME", "CLOSE"]
    request_id: UUID
    expected_context_revision: PositiveInt
    # Required when a currently open execution period must be ended.
    expected_period_id: PositiveInt | None = None
    # The current vehicle responsibility epoch must be independently verified
    # whenever a new period is opened, including a "same vehicle" resume.
    expected_vehicle_custody_revision: PositiveInt | None = None
    target_driver_id: PositiveInt | None = None
    target_vehicle_id: PositiveInt | None = None

    @model_validator(mode="after")
    def require_exact_shape(self) -> "RouteLifecycleIntent":
        if self.action == "RESUME":
            if self.target_driver_id is None or self.target_vehicle_id is None:
                raise ValueError("RESUME requires BOTH target_driver_id and target_vehicle_id")
            if self.expected_vehicle_custody_revision is None:
                raise ValueError("RESUME requires the vehicle custody revision")
        elif self.target_driver_id is not None or self.target_vehicle_id is not None:
            raise ValueError("POSTPONE/CLOSE cannot silently reassign a driver or a vehicle")
        elif self.expected_vehicle_custody_revision is not None:
            raise ValueError("POSTPONE/CLOSE must never change vehicle custody")
        if self.action == "POSTPONE" and self.expected_period_id is None:
            raise ValueError("POSTPONE requires the exact current execution period")
        return self


def lifecycle_request_hash(route_id: int, payload: RouteLifecycleIntent) -> str:
    """Stable content fingerprint; the same UUID with different intent is 409.

    Route identity is included so a UUID replay cannot silently target a
    different route within the same company.
    """
    if isinstance(route_id, bool) or route_id <= 0:
        raise ValueError("Invalid route identity")
    body = {
        "route_id": route_id,
        **payload.model_dump(mode="json", exclude={"request_id"}),
    }
    canonical = json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    return sha256(canonical.encode("utf-8")).hexdigest()
