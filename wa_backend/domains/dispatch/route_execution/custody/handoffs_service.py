"""Durable two-principal custody handshake. No changes to physical or financial stock."""
from __future__ import annotations

from datetime import datetime, timezone
from time import time
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.context import FieldRequestContext
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.identity.models import CompanyPrincipal
from models import SystemAuditLog
from .handoffs_model import VehicleCustodyHandoff
from .proofs import CustodyRejected, digest, signed
from .service import (
    _latest_handoff, _revision_mode, accept_custody, resolve_field_recipient,
)
from .snapshot import read_vehicle_state, require_quiescent_vehicle

TTL = 900
DECLINE_REASONS = frozenset({"DIFFERENCE", "NOT_MY_GOODS", "VEHICLE_UNAVAILABLE", "OTHER"})


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _uuid(value: UUID | str) -> str:
    return str(UUID(str(value)))


def _expired(row: VehicleCustodyHandoff) -> bool:
    return row.state in {"PENDING", "CONFIRMED"} and row.expires_at <= now()


def effective_state(row: VehicleCustodyHandoff) -> str:
    return "EXPIRED" if _expired(row) else str(row.state)


def _audit(db, row, *, actor_id: int, event: str, old: str, new: str) -> None:
    # Legacy Driver is an audit FK, NOT the identity or authorization authority.
    import json
    db.add(SystemAuditLog(
        company_id=row.company_id, admin_id=actor_id,
        target_id=f"Vehicle_{row.vehicle_id}",
        action_type=f"CUSTODY_HANDOFF_{event}",
        old_value=json.dumps({"handoff_id": row.id, "state": old}, sort_keys=True),
        new_value=json.dumps({
            "handoff_id": row.id, "state": new,
            "recipient_principal": row.recipient_principal_id,
            "manager_principal": row.manager_principal_id,
            "request_id": row.request_id,
            "decision_request_id": row.decision_request_id,
            "confirmed_at": row.confirmed_at,
            "decline_reason_code": row.decline_reason_code,
            "decline_reason_text": row.decline_reason_text,
            "cancel_request_id": row.cancel_request_id,
            "approve_request_id": row.approve_request_id,
            "snapshot_sha256": row.expected_stock_snapshot,
        }, sort_keys=True),
    ))


def _offer_data(row: VehicleCustodyHandoff) -> dict:
    return {
        "company": int(row.company_id), "vehicle": int(row.vehicle_id),
        "location": int(row.vehicle_location_id),
        "revision": int(row.expected_context_revision),
        "epoch_id": int(row.prior_epoch_id) if row.prior_epoch_id else None,
        "snapshot": str(row.expected_stock_snapshot),
        "mode": str(row.mode), "manager": int(row.manager_principal_id),
        "receiver": int(row.recipient_principal_id),
        "representative": int(row.recipient_rep_id),
        "fence": int(row.id), "handoff_id": int(row.id),
    }


def receiver_proof_from_record(row: VehicleCustodyHandoff) -> str:
    """Only internal synthesis; never returned or stored as raw HMAC."""
    if row.confirmed_at is None or row.confirmed_auth_revision is None:
        raise CustodyRejected("CUSTODY_RECEIVER_CONFIRMATION_REQUIRED")
    offer = signed("OFFER", _offer_data(row), issued_at=int(row.offer_issued_at))
    return signed("RECEIVER", {
        "offer": offer, "receiver": int(row.recipient_principal_id),
        "representative": int(row.recipient_rep_id),
        "auth_revision": int(row.confirmed_auth_revision),
        "physical_count_confirmed": True,
    }, issued_at=int(row.confirmed_at))


async def _expire(db: AsyncSession, row: VehicleCustodyHandoff, *, actor_id: int) -> bool:
    if not _expired(row):
        return False
    old = row.state
    row.state = "EXPIRED"
    row.updated_at = now()
    _audit(db, row, actor_id=actor_id, event="EXPIRED", old=old, new="EXPIRED")
    await db.flush()
    return True


async def manager_create(
    db: AsyncSession, *, company_id: int, vehicle_id: int, manager_id: int,
    actor_id: int, request_id: UUID, target_driver_id: int,
    expected_context_revision: int, expected_stock_snapshot: str,
) -> VehicleCustodyHandoff:
    identity = _uuid(request_id)
    fingerprint = digest({
        "vehicle_id": vehicle_id, "manager_id": manager_id,
        "target_driver_id": target_driver_id,
        "expected_context_revision": expected_context_revision,
        "expected_stock_snapshot": expected_stock_snapshot,
    })
    prior = await db.scalar(select(VehicleCustodyHandoff).where(
        VehicleCustodyHandoff.company_id == company_id,
        VehicleCustodyHandoff.request_id == identity,
    ))
    if prior is not None:
        if (prior.vehicle_id != vehicle_id or prior.request_hash != fingerprint
                or prior.manager_principal_id != manager_id):
            raise CustodyRejected("CUSTODY_REQUEST_ID_REUSED_WITH_DIFFERENT_BODY")
        return prior
    state = await read_vehicle_state(db, company_id, vehicle_id, lock=True)
    await require_quiescent_vehicle(db, company_id, vehicle_id)
    latest = await _latest_handoff(db, company_id, vehicle_id)
    if latest is not None:
        await _expire(db, latest, actor_id=actor_id)
        if latest.state in {"PENDING", "CONFIRMED"}:
            raise CustodyRejected("CUSTODY_HANDOFF_PENDING")
    if state.revision != expected_context_revision:
        raise CustodyRejected("CUSTODY_REVISION_STALE")
    if state.stock_snapshot != expected_stock_snapshot:
        raise CustodyRejected("CUSTODY_STOCK_SNAPSHOT_STALE")
    rep_id, receiver_id = await resolve_field_recipient(
        db, company_id=company_id, driver_id=target_driver_id,
    )
    mode = _revision_mode(state.epoch, state.stocked, receiver_id)
    issued = int(time())
    row = VehicleCustodyHandoff(
        company_id=company_id, vehicle_id=vehicle_id, manager_principal_id=manager_id,
        vehicle_location_id=state.location_id, target_driver_id=target_driver_id,
        recipient_rep_id=rep_id, recipient_principal_id=receiver_id,
        prior_epoch_id=int(state.epoch.id) if state.epoch is not None else None,
        mode=mode, expected_context_revision=state.revision,
        expected_stock_snapshot=state.stock_snapshot,
        request_id=identity, request_hash=fingerprint,
        offer_issued_at=issued, expires_at=datetime.fromtimestamp(issued + TTL, timezone.utc).replace(tzinfo=None),
        state="PENDING",
    )
    db.add(row)
    await db.flush()  # its non-reusable ID fences old signed HMAC offers
    _audit(db, row, actor_id=actor_id, event="REQUESTED", old="NONE", new="PENDING")
    await db.commit()
    return row


async def manager_cancel(
    db: AsyncSession, *, company_id: int, vehicle_id: int, handoff_id: int,
    manager_id: int, actor_id: int, request_id: UUID,
) -> VehicleCustodyHandoff:
    # Vehicle / stock lock first, then request row, matching create/approve.
    await read_vehicle_state(db, company_id, vehicle_id, lock=True)
    row = await _owned(db, company_id, handoff_id, vehicle_id, lock=True)
    if row.manager_principal_id != manager_id:
        raise CustodyRejected("CUSTODY_MANAGER_MISMATCH", 403)
    identity = _uuid(request_id)
    if row.state == "CANCELLED" and row.cancel_request_id == identity:
        return row
    if await _expire(db, row, actor_id=actor_id):
        await db.commit()
        raise CustodyRejected("CUSTODY_HANDOFF_EXPIRED")
    if row.state not in {"PENDING", "CONFIRMED"}:
        raise CustodyRejected("CUSTODY_HANDOFF_NOT_CANCELLABLE")
    old = row.state
    row.state = "CANCELLED"
    row.cancel_request_id = identity
    row.updated_at = now()
    _audit(db, row, actor_id=actor_id, event="CANCELLED", old=old, new="CANCELLED")
    await db.commit()
    return row


async def _owned(db, company_id, handoff_id, vehicle_id=None, *, lock=False):
    stmt = select(VehicleCustodyHandoff).where(
        VehicleCustodyHandoff.company_id == company_id,
        VehicleCustodyHandoff.id == handoff_id,
    )
    if vehicle_id is not None:
        stmt = stmt.where(VehicleCustodyHandoff.vehicle_id == vehicle_id)
    if lock:
        stmt = stmt.with_for_update()
    row = await db.scalar(stmt)
    if row is None:
        raise CustodyRejected("CUSTODY_HANDOFF_NOT_FOUND", 404)
    return row


async def field_decide(
    db: AsyncSession, *, field: FieldRequestContext, handoff_id: int,
    request_id: UUID, decision: str, stock_snapshot: str | None,
    physical_count: bool, reason_code: str | None, reason_text: str | None,
) -> VehicleCustodyHandoff:
    row = await _owned(db, field.company_id, handoff_id)
    if (row.recipient_principal_id != field.principal_id
            or row.recipient_rep_id != field.representative_id):
        raise CustodyRejected("CUSTODY_HANDOFF_NOT_FOUND", 404)
    await read_vehicle_state(db, field.company_id, row.vehicle_id, lock=True)
    row = await _owned(db, field.company_id, handoff_id, lock=True)
    if (row.recipient_principal_id != field.principal_id
            or row.recipient_rep_id != field.representative_id):
        raise CustodyRejected("CUSTODY_HANDOFF_NOT_FOUND", 404)
    identity = _uuid(request_id)
    value = digest({
        "decision": decision, "stock_snapshot": stock_snapshot,
        "physical_count": physical_count,
        "reason_code": reason_code, "reason_text": reason_text,
    })
    if row.decision_request_id == identity:
        if row.decision_hash != value:
            raise CustodyRejected("CUSTODY_REQUEST_ID_REUSED_WITH_DIFFERENT_BODY")
        return row
    if await _expire(db, row, actor_id=row.target_driver_id):
        await db.commit()
        raise CustodyRejected("CUSTODY_HANDOFF_EXPIRED")
    if row.state != "PENDING":
        raise CustodyRejected("CUSTODY_HANDOFF_ALREADY_DECIDED")
    if decision not in {"CONFIRM", "DECLINE"}:
        raise CustodyRejected("CUSTODY_DECISION_INVALID", 422)
    if decision == "CONFIRM":
        if not physical_count or stock_snapshot != row.expected_stock_snapshot:
            raise CustodyRejected("CUSTODY_PHYSICAL_COUNT_REQUIRED", 409)
        actual = await read_vehicle_state(db, field.company_id, row.vehicle_id)
        await require_quiescent_vehicle(db, field.company_id, row.vehicle_id)
        if (actual.stock_snapshot != row.expected_stock_snapshot
                or actual.revision != row.expected_context_revision
                or actual.location_id != row.vehicle_location_id
                or (actual.epoch.id if actual.epoch else None) != row.prior_epoch_id):
            raise CustodyRejected("CUSTODY_STOCK_SNAPSHOT_STALE")
        # The bearer context is principal/role/revision checked by the FIELD dependency.
        row.state = "CONFIRMED"
        row.confirmed_at = int(time())
        row.confirmed_auth_revision = field.auth_revision
    else:
        if reason_code not in DECLINE_REASONS or (reason_text and len(reason_text) > 300):
            raise CustodyRejected("CUSTODY_DECLINE_REASON_REQUIRED", 422)
        row.state = "DECLINED"
        row.decline_reason_code = reason_code
        row.decline_reason_text = reason_text
    row.decision_request_id = identity
    row.decision_hash = value
    row.updated_at = now()
    _audit(db, row, actor_id=row.target_driver_id, event=row.state, old="PENDING", new=row.state)
    await db.commit()
    return row


async def manager_approve(
    db: AsyncSession, *, company_id: int, vehicle_id: int, handoff_id: int,
    manager_id: int, actor_id: int, request_id: UUID,
) -> tuple[VehicleCustodyHandoff, dict]:
    identity = _uuid(request_id)
    await read_vehicle_state(db, company_id, vehicle_id, lock=True)
    row = await _owned(db, company_id, handoff_id, vehicle_id, lock=True)
    if row.manager_principal_id != manager_id:
        raise CustodyRejected("CUSTODY_MANAGER_MISMATCH", 403)
    if row.state == "COMMITTED":
        if row.approve_request_id != identity:
            raise CustodyRejected("CUSTODY_HANDOFF_ALREADY_COMMITTED")
        persisted_epoch = await db.scalar(select(VehicleCustodyEpoch).where(
            VehicleCustodyEpoch.company_id == company_id,
            VehicleCustodyEpoch.id == row.accepted_epoch_id,
            VehicleCustodyEpoch.vehicle_id == vehicle_id,
            VehicleCustodyEpoch.state == "ACCEPTED",
        ))
        if persisted_epoch is None:
            raise CustodyRejected("CUSTODY_COMMITTED_EPOCH_MISSING")
        return row, {
            "state": "COMMITTED", "vehicle_id": vehicle_id, "handoff_id": row.id,
            "epoch_id": row.accepted_epoch_id,
            "context_revision": int(persisted_epoch.context_revision),
            "replayed": True, "stock_movements": 0,
        }
    if await _expire(db, row, actor_id=actor_id):
        await db.commit()
        raise CustodyRejected("CUSTODY_HANDOFF_EXPIRED")
    if row.state != "CONFIRMED":
        raise CustodyRejected("CUSTODY_RECEIVER_CONFIRMATION_REQUIRED")
    # Legacy receiver token cannot be supplied by the manager. Reconstruct
    # both HMAC layers ONLY INSIDE the server from two independent identities,
    # saved timestamps, locked evidence and the canonical current secret.
    proof = receiver_proof_from_record(row)
    accepted = await accept_custody(
        db, company_id=company_id, vehicle_id=vehicle_id,
        manager_principal_id=manager_id, legacy_actor_id=actor_id,
        request_id=identity, receiver_proof=proof,
        allowed_handoff_id=handoff_id, commit=False,
    )
    row.accepted_epoch_id = accepted["epoch_id"]
    row.approve_request_id = identity
    row.state = "COMMITTED"
    row.updated_at = now()
    _audit(db, row, actor_id=actor_id, event="COMMITTED", old="CONFIRMED", new="COMMITTED")
    await db.commit()  # Single transaction with signed VehicleCustodyEpoch and audit.
    return row, {
        "state": "COMMITTED", "vehicle_id": vehicle_id, "handoff_id": row.id,
        "epoch_id": row.accepted_epoch_id, "context_revision": accepted["context_revision"],
        "replayed": False, "stock_movements": 0,
    }
