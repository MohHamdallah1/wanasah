"""Strict transport and immutable evidence contracts for vehicle counts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_PERIODS = 256
MAX_EPOCHS = 128
MAX_LINES = 1000
STOCK_STATUSES = frozenset((
    "AVAILABLE", "QUARANTINED", "BLOCKED", "RECALLED", "DAMAGED", "DISPOSAL_PENDING",
))


class CustodyRejected(Exception):
    def __init__(self, code: str, *, status: int = 409, context: dict | None = None):
        self.code, self.status, self.context = code, status, context or {}
        super().__init__(code)


class CountLine(BaseModel):
    model_config = ConfigDict(extra="forbid")
    line_key: str = Field(pattern=r"^[a-f0-9]{24}$")
    actual_quantity: str = Field(min_length=1, max_length=50)


class VehicleCountCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    mode: Literal["COUNT_IN_PLACE", "PHYSICAL_HANDOFF"]
    snapshot_token: str = Field(pattern=r"^[a-f0-9]{64}$")
    receiver_confirms_count: Literal[True]
    destination_location_id: int | None = Field(default=None, gt=0)
    receiver_confirms_handoff: bool = False
    items: list[CountLine] = Field(max_length=MAX_LINES)
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def distinct_evidence(self):
        if len({line.line_key for line in self.items}) != len(self.items):
            raise ValueError("Duplicate count line")
        if self.mode == "COUNT_IN_PLACE":
            if self.destination_location_id is not None or self.receiver_confirms_handoff:
                raise ValueError("Count in place has no physical destination or handoff")
        elif self.destination_location_id is None or not self.receiver_confirms_handoff:
            raise ValueError("Physical handoff requires a destination and receiver confirmation")
        return self


@dataclass(frozen=True)
class PeriodEvidence:
    id: int
    company_id: int
    session_id: int
    driver_id: int
    representative_id: int | None
    vehicle_id: int
    location_id: int | None
    revision: int
    state: str
    started_at: datetime | None
    ended_at: datetime | None
    canonical: bool


@dataclass(frozen=True)
class EpochEvidence:
    id: int
    company_id: int
    session_id: int | None
    representative_id: int | None
    vehicle_id: int
    location_id: int
    revision: int
    state: str
    started_at: datetime | None
    ended_at: datetime | None
    accepted_by: int | None
    canonical: bool


@dataclass(frozen=True)
class VehicleResponsibility:
    vehicle_id: int
    location_id: int
    period_ids: tuple[int, ...]
    epoch_ids: tuple[int, ...]
    # Full evidence is hashed: A -> B -> A cannot resurrect an old token.
    context_digest: str


@dataclass(frozen=True)
class BalanceEvidence:
    variant_id: int
    batch_id: int
    stock_status: str
    quantity: Decimal
    reserved: Decimal
    quantity_scale: int
    quantity_step: Decimal
    product_name: str = ""
    sku: str = ""
    lot: str | None = None
    expiry: str | None = None
    uom: str = ""


@dataclass(frozen=True)
class VehicleSnapshot:
    company_id: int
    session_id: int
    responsibility: VehicleResponsibility
    latest_epoch_id: int
    latest_epoch_revision: int
    movement_watermark: int
    rows: tuple[BalanceEvidence, ...]
