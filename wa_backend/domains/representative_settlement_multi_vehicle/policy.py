"""Pure custody identity, exact counts and ABA-resistant snapshot rules.

These rules do not authorize actors or mutate stock. Application services must
hold the session and Inventory location guards while checking their evidence.
"""
from __future__ import annotations

import hashlib
import json
from collections import defaultdict

from quantity import QuantityError, canonical_quantity, validate_variant_quantity

from .contracts import (
    MAX_EPOCHS, MAX_LINES, MAX_PERIODS, STOCK_STATUSES, CustodyRejected,
    EpochEvidence, PeriodEvidence, VehicleCountCommand, VehicleResponsibility,
    VehicleSnapshot,
)


def digest(value) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def resolve_responsibilities(*, company_id: int, session_id: int, driver_id: int,
                             periods: tuple[PeriodEvidence, ...],
                             epochs: tuple[EpochEvidence, ...]) -> tuple[VehicleResponsibility, ...]:
    """Use only explicit canonical session periods/epochs, never route last links.

    A later count may cover A's repeated epochs in S1, provided no foreign
    responsibility intervened. Earlier signed checkpoints must instead be used
    when a different session has already taken over a vehicle.
    """
    if not periods or len(periods) > MAX_PERIODS or len(epochs) > MAX_EPOCHS:
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    if len({p.id for p in periods}) != len(periods) or len({e.id for e in epochs}) != len(epochs):
        raise CustodyRejected("DUPLICATE_CUSTODY_EVIDENCE")
    by_vehicle = defaultdict(list)
    for epoch in epochs:
        if (epoch.company_id != company_id or epoch.session_id not in (None, session_id)
                or epoch.state != "ACCEPTED" or not epoch.canonical
                or epoch.accepted_by is None or epoch.started_at is None
                or (epoch.ended_at is not None and epoch.ended_at < epoch.started_at)
                or epoch.revision <= 0):
            raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
        by_vehicle[(epoch.vehicle_id, epoch.location_id)].append(epoch)
    period_groups = defaultdict(list)
    used_epochs = set()
    for period in periods:
        if (period.company_id != company_id or period.session_id != session_id
                or period.driver_id != driver_id or period.representative_id is None
                or not period.canonical or period.state != "CLOSED"
                or period.started_at is None or period.ended_at is None
                or period.ended_at < period.started_at or period.revision <= 0):
            raise CustodyRejected("SESSION_EXECUTION_REVIEW_REQUIRED")
        key = (period.vehicle_id, period.location_id)
        candidates = [e for e in by_vehicle[key]
                      if e.representative_id == period.representative_id
                      and e.started_at <= period.started_at
                      and (e.ended_at is None or e.ended_at >= period.ended_at)]
        if len(candidates) != 1:
            raise CustodyRejected("PERIOD_CUSTODY_EVIDENCE_AMBIGUOUS")
        used_epochs.add(candidates[0].id)
        period_groups[key].append(period)
    if any(e.session_id is None and e.id not in used_epochs for e in epochs):
        raise CustodyRejected("SESSION_CUSTODY_REVIEW_REQUIRED")
    locations = [key[1] for key in by_vehicle]
    vehicles = [key[0] for key in by_vehicle]
    if len(set(locations)) != len(locations) or len(set(vehicles)) != len(vehicles):
        raise CustodyRejected("VEHICLE_LOCATION_EVIDENCE_AMBIGUOUS")
    result = []
    for (vehicle_id, location_id), vehicle_epochs in sorted(by_vehicle.items()):
        vehicle_periods = period_groups[(vehicle_id, location_id)]
        context = {
            "company": company_id, "session": session_id, "vehicle": vehicle_id,
            "location": location_id,
            "periods": sorted((p.id, p.revision, p.started_at.isoformat(), p.ended_at.isoformat())
                              for p in vehicle_periods),
            # Closing the same accepted responsibility later does not rewrite
            # its original signature. A successor is fenced by id/revision and
            # the financial gate verifies the actual signed takeover chain.
            "epochs": sorted((e.id, e.revision, e.started_at.isoformat(),
                              e.accepted_by, e.representative_id) for e in vehicle_epochs),
        }
        result.append(VehicleResponsibility(
            vehicle_id, location_id, tuple(sorted(p.id for p in vehicle_periods)),
            tuple(sorted(e.id for e in vehicle_epochs)), digest(context),
        ))
    return tuple(result)


def line_key(snapshot: VehicleSnapshot, row) -> str:
    return digest((snapshot.company_id, snapshot.session_id,
                   snapshot.responsibility.location_id,
                   snapshot.responsibility.context_digest,
                   row.variant_id, row.batch_id, row.stock_status))[:24]


def snapshot_token(snapshot: VehicleSnapshot) -> str:
    if len(snapshot.rows) > MAX_LINES:
        raise CustodyRejected("SETTLEMENT_CUSTODY_TOO_LARGE")
    identities = [(r.variant_id, r.batch_id, r.stock_status) for r in snapshot.rows]
    if len(set(identities)) != len(identities):
        raise CustodyRejected("DUPLICATE_CUSTODY_IDENTITY")
    for row in snapshot.rows:
        if (row.stock_status not in STOCK_STATUSES or row.reserved != 0
                or not row.quantity.is_finite() or row.quantity < 0):
            raise CustodyRejected("VEHICLE_CUSTODY_RESERVED_OR_INVALID")
    return digest({
        "company": snapshot.company_id, "session": snapshot.session_id,
        "vehicle": snapshot.responsibility.vehicle_id,
        "location": snapshot.responsibility.location_id,
        "context": snapshot.responsibility.context_digest,
        "latest_epoch": (snapshot.latest_epoch_id, snapshot.latest_epoch_revision),
        "movement_watermark": snapshot.movement_watermark,
        "balances": sorted((r.variant_id, r.batch_id, r.stock_status,
                            canonical_quantity(r.quantity), canonical_quantity(r.reserved),
                            r.quantity_scale, canonical_quantity(r.quantity_step))
                           for r in snapshot.rows),
    })


def validate_count(snapshot: VehicleSnapshot, command: VehicleCountCommand) -> dict:
    if command.snapshot_token != snapshot_token(snapshot):
        raise CustodyRejected("CUSTODY_SNAPSHOT_STALE")
    supplied = {r.line_key: r.actual_quantity for r in command.items}
    expected = {line_key(snapshot, row): row for row in snapshot.rows}
    if set(supplied) != set(expected):
        raise CustodyRejected("CUSTODY_COUNT_INCOMPLETE_OR_STALE", status=422)
    result = {}
    for key, row in expected.items():
        try:
            result[key] = validate_variant_quantity(
                supplied[key], quantity_scale=row.quantity_scale,
                quantity_step=row.quantity_step, field_name="actual_quantity", allow_zero=True,
            )
        except QuantityError:
            raise CustodyRejected("INVALID_PHYSICAL_QUANTITY", status=422) from None
    return result


def command_hash(session_id: int, vehicle_id: int, command: VehicleCountCommand) -> str:
    payload = command.model_dump(mode="json")
    payload["items"] = sorted(payload["items"], key=lambda r: r["line_key"])
    return digest({"session": session_id, "vehicle": vehicle_id, **payload})
