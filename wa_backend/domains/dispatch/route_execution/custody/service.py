"""Signed, tenant-bound vehicle custody reconciliation commands."""
from __future__ import annotations
from datetime import datetime, timezone
import json
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from domains.auth_sessions.context import FieldRequestContext
from domains.authorization.field_access import FieldCapabilityAccess, FieldCapabilityAccessRejected
from domains.dispatch_representatives import has_canonical_field_identity
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from domains.identity.migration.models import IdentityLegacyDriverMap
from domains.identity.models import CompanyPrincipal
from models import Driver, SystemAuditLog

from .proofs import CustodyRejected, digest, signed, verify
from .snapshot import read_vehicle_state, require_quiescent_vehicle


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _revision_mode(epoch, stocked: bool, principal_id: int) -> str:
    if epoch is None:
        # A valid single vehicle location with logged physical stock but no
        # M01 epoch cannot launch. It CAN be explicitly counted and signed
        # through the same two-party initial acceptance, not silently stuck.
        return "FIRST_ACCEPT"
    if epoch.state == "NEEDS_REVIEW" and epoch.custodian_kind == "UNCONFIRMED":
        return "FIRST_ACCEPT"
    if (epoch.state != "ACCEPTED" or epoch.accepted_by_principal_id is None
            or not epoch.request_id or not epoch.payload_hash):
        raise CustodyRejected("CUSTODY_EVIDENCE_UNVERIFIED")
    if epoch.custodian_kind not in ("FIELD_REPRESENTATIVE", "BACKOFFICE"):
        raise CustodyRejected("CUSTODY_EVIDENCE_UNVERIFIED")
    if epoch.custodian_principal_id == principal_id:
        raise CustodyRejected("CUSTODY_ALREADY_ACCEPTED_BY_TARGET")
    return "REASSIGN"


async def resolve_field_recipient(
    db: AsyncSession, *, company_id: int, driver_id: int,
) -> tuple[int, int]:
    rows = (await db.execute(select(
        IdentityLegacyDriverMap.field_representative_id,
        IdentityLegacyDriverMap.field_principal_id,
    ).join(
        Driver, (Driver.id == IdentityLegacyDriverMap.legacy_driver_id)
        & (Driver.company_id == IdentityLegacyDriverMap.company_id),
    ).where(
        IdentityLegacyDriverMap.company_id == company_id,
        IdentityLegacyDriverMap.legacy_driver_id == driver_id,
        Driver.is_active.is_(True),
        has_canonical_field_identity(
            company_id=company_id, legacy_driver_id=driver_id,
        ),
    ))).all()
    if len(rows) != 1 or rows[0][0] is None or rows[0][1] is None:
        raise CustodyRejected("CUSTODY_TARGET_FIELD_IDENTITY_INVALID", 409)
    rep_id, principal_id = map(int, rows[0])
    principal = await db.scalar(select(CompanyPrincipal).where(
        CompanyPrincipal.company_id == company_id,
        CompanyPrincipal.id == principal_id,
        CompanyPrincipal.principal_type == "FIELD_REPRESENTATIVE",
        CompanyPrincipal.is_active.is_(True),
    ))
    if principal is None:
        raise CustodyRejected("CUSTODY_TARGET_FIELD_PRINCIPAL_INACTIVE")
    try:
        await FieldCapabilityAccess(
            db, FieldRequestContext(
                company_id=company_id, principal_id=principal_id,
                representative_id=rep_id,
                auth_revision=int(principal.auth_revision),
            ),
        ).require_all(("work_session.execute", "visit.execute"))
    except FieldCapabilityAccessRejected as exc:
        raise CustodyRejected("CUSTODY_TARGET_FIELD_CAPABILITY_MISSING") from exc
    return rep_id, principal_id


async def custody_readiness(
    db: AsyncSession, *, company_id: int, vehicle_id: int,
) -> dict:
    state = await read_vehicle_state(db, company_id, vehicle_id)
    e = state.epoch
    return {
        "vehicle_id": vehicle_id, "vehicle_location_id": state.location_id,
        "context_revision": state.revision,
        "state": e.state if e is not None else "NO_EPOCH",
        "custodian_kind": e.custodian_kind if e else None,
        "stocked": state.stocked, "stock_snapshot": state.stock_snapshot,
        "stock_line_count": len(state.lines),
        "recovery_action": (
            "CUSTODY_FIRST_ACCEPT" if (
                e is None or e.state == "NEEDS_REVIEW"
            ) else
            "CUSTODY_REASSIGN" if e is not None and e.state == "ACCEPTED"
            else "CUSTODY_INVESTIGATE"
        ),
    }


async def issue_offer(
    db: AsyncSession, *, company_id: int, vehicle_id: int,
    target_driver_id: int, expected_revision: int,
    expected_snapshot: str, manager_principal_id: int,
) -> dict:
    rep_id, recipient_id = await resolve_field_recipient(
        db, company_id=company_id, driver_id=target_driver_id,
    )
    state = await read_vehicle_state(db, company_id, vehicle_id, lock=True)
    await require_quiescent_vehicle(db, company_id, vehicle_id)
    if state.revision != expected_revision:
        raise CustodyRejected("CUSTODY_REVISION_STALE")
    if state.stock_snapshot != expected_snapshot:
        raise CustodyRejected("CUSTODY_STOCK_SNAPSHOT_STALE")
    mode = _revision_mode(state.epoch, state.stocked, recipient_id)
    data = {
        "company": company_id, "vehicle": vehicle_id,
        "location": state.location_id, "revision": state.revision,
        "epoch_id": int(state.epoch.id) if state.epoch else None,
        "snapshot": state.stock_snapshot, "mode": mode,
        "manager": manager_principal_id, "receiver": recipient_id,
        "representative": rep_id,
    }
    return {
        "offer_token": signed("OFFER", data),
        "expires_in_seconds": 900, "action": mode,
        "vehicle_location_id": state.location_id,
        "stock_snapshot": state.stock_snapshot,
        "stock_line_count": len(state.lines),
        # Exact actual batches, statuses and quantities let the receiver
        # physically count what the signed fingerprint represents.
        "stock_lines": state.lines,
        "next_step": "FIELD_RECEIVER_CONFIRMATION_REQUIRED",
    }


def confirm_receiver(
    *, offer_token: str, company_id: int, vehicle_id: int,
    field_principal_id: int, field_representative_id: int,
    confirms_physical_count: bool, confirmed_stock_snapshot: str,
    receiver_auth_revision: int,
) -> dict:
    data = verify("OFFER", offer_token)
    if (not confirms_physical_count
            or confirmed_stock_snapshot != data.get("snapshot") or
            data["company"] != company_id or data["vehicle"] != vehicle_id
            or data["receiver"] != field_principal_id
            or data["representative"] != field_representative_id):
        raise CustodyRejected("CUSTODY_RECEIVER_CONFIRMATION_DENIED", 403)
    proof = signed("RECEIVER", {
        "offer": offer_token, "receiver": field_principal_id,
        "representative": field_representative_id,
        "auth_revision": receiver_auth_revision,
        "physical_count_confirmed": True,
    })
    return {"receiver_proof": proof, "confirmed": True,
            "stock_snapshot": data["snapshot"]}


async def accept_custody(
    db: AsyncSession, *, company_id: int, vehicle_id: int,
    manager_principal_id: int, legacy_actor_id: int,
    request_id: str, receiver_proof: str,
) -> dict:
    try:
        operation = str(UUID(request_id))
    except (TypeError, ValueError) as exc:
        raise CustodyRejected("CUSTODY_REQUEST_ID_INVALID", 422) from exc
    payload_hash = digest({
        "request_id": operation, "vehicle_id": vehicle_id,
        "receiver_proof": receiver_proof,
    })
    # Serialize the *same UUID* before any state checks: lost-response replay
    # remains available even if the vehicle subsequently changed status or
    # the original short-lived receiver proof has expired. A different UUID
    # continues to serialize on the real Vehicle/location row locks.
    await db.scalar(select(func.pg_advisory_xact_lock(
        int(company_id), func.hashtext("custody-accept:" + operation),
    )))
    prior = await db.scalar(select(VehicleCustodyEpoch).where(
        VehicleCustodyEpoch.company_id == company_id,
        VehicleCustodyEpoch.request_id == operation,
    ).with_for_update())
    if prior is not None:
        if (int(prior.vehicle_id) != vehicle_id
                or prior.payload_hash != payload_hash
                or prior.state != "ACCEPTED"):
            raise CustodyRejected("CUSTODY_REQUEST_ID_REUSED_WITH_DIFFERENT_BODY")
        await db.commit()  # Release the UUID advisory lock on exact replay.
        return {
            "vehicle_id": vehicle_id, "epoch_id": int(prior.id),
            "context_revision": int(prior.context_revision),
            "state": "ACCEPTED", "replayed": True, "stock_movements": 0,
        }
    state = await read_vehicle_state(db, company_id, vehicle_id, lock=True)
    receipt = verify("RECEIVER", receiver_proof)
    if receipt.get("physical_count_confirmed") is not True:
        raise CustodyRejected("CUSTODY_RECEIVER_CONFIRMATION_REQUIRED")
    offer = verify("OFFER", receipt["offer"])
    if (offer.get("company") != company_id or
            offer.get("vehicle") != vehicle_id or
            offer.get("location") != state.location_id or
            offer.get("manager") != manager_principal_id or
            offer.get("receiver") != receipt.get("receiver") or
            offer.get("representative") != receipt.get("representative")):
        raise CustodyRejected("CUSTODY_HANDOFF_EVIDENCE_MISMATCH")
    await require_quiescent_vehicle(db, company_id, vehicle_id)
    if (offer["revision"] != state.revision
            or offer["epoch_id"] != (int(state.epoch.id) if state.epoch else None)):
        raise CustodyRejected("CUSTODY_REVISION_STALE")
    if offer["snapshot"] != state.stock_snapshot:
        raise CustodyRejected("CUSTODY_STOCK_SNAPSHOT_STALE")
    target = await db.scalar(select(CompanyPrincipal).where(
        CompanyPrincipal.company_id == company_id,
        CompanyPrincipal.id == receipt["receiver"],
        CompanyPrincipal.principal_type == "FIELD_REPRESENTATIVE",
        CompanyPrincipal.is_active.is_(True),
    ))
    if (target is None or
            int(target.auth_revision) != receipt.get("auth_revision")):
        raise CustodyRejected("CUSTODY_TARGET_IDENTITY_REVOKED")
    # Revalidate the canonical target bridge + dynamic FIELD grants at commit
    # time. A revoked role or changed mapping cannot reuse an old offer.
    mapping = await db.scalar(select(IdentityLegacyDriverMap).where(
        IdentityLegacyDriverMap.company_id == company_id,
        IdentityLegacyDriverMap.field_principal_id == receipt["receiver"],
        IdentityLegacyDriverMap.field_representative_id == receipt["representative"],
    ))
    if mapping is None:
        raise CustodyRejected("CUSTODY_TARGET_IDENTITY_REVOKED")
    rep_id, principal_id = await resolve_field_recipient(
        db, company_id=company_id, driver_id=int(mapping.legacy_driver_id),
    )
    if (rep_id != receipt["representative"]
            or principal_id != receipt["receiver"]):
        raise CustodyRejected("CUSTODY_TARGET_IDENTITY_REVOKED")
    mode = _revision_mode(state.epoch, state.stocked, principal_id)
    if offer["mode"] != mode:
        raise CustodyRejected("CUSTODY_MODE_CHANGED")
    if state.revision >= 2**63 - 1:
        raise CustodyRejected("CUSTODY_REVISION_EXHAUSTED")
    now = _now()
    old = state.epoch
    if old is not None:
        # Migration's UNKNOWN epoch did not know a real handoff/start time.
        # Its created_at records the historical review-log beginning, not a
        # fictional custodian acceptance. We never set accepted_by on it.
        if old.started_at is None:
            if old.state != "NEEDS_REVIEW":
                raise CustodyRejected("CUSTODY_HISTORY_INVALID")
            old.started_at = old.created_at or now
        old.ended_at = now
        await db.flush()
    accepted = VehicleCustodyEpoch(
        company_id=company_id, vehicle_id=vehicle_id,
        vehicle_location_id=state.location_id,
        custodian_kind="FIELD_REPRESENTATIVE",
        custodian_principal_id=principal_id,
        field_representative_id=rep_id,
        accepted_by_principal_id=manager_principal_id,
        state="ACCEPTED", context_revision=state.revision + 1,
        started_at=now, reason=mode,
        handoff_reference=digest(receiver_proof),
        evidence_origin="CANONICAL", request_id=operation,
        payload_hash=payload_hash,
    )
    db.add(accepted)
    await db.flush()
    db.add(SystemAuditLog(
        company_id=company_id, admin_id=legacy_actor_id,
        target_id=f"Vehicle_{vehicle_id}", action_type="VEHICLE_CUSTODY_"+mode,
        old_value=None if old is None else json.dumps({
            "epoch_id": old.id, "state": old.state,
            "kind": old.custodian_kind,
            "principal": old.custodian_principal_id,
        }, sort_keys=True),
        new_value=json.dumps({
            "epoch_id": accepted.id, "request_id": operation,
            "stock_snapshot": state.stock_snapshot,
            "receiver_proof_sha256": accepted.handoff_reference,
            "recipient_principal": principal_id,
            "accepted_by_principal": manager_principal_id,
            "stock_movements": 0,
        }, sort_keys=True),
    ))
    await db.commit()
    return {
        "vehicle_id": vehicle_id, "epoch_id": int(accepted.id),
        "context_revision": int(accepted.context_revision),
        "state": "ACCEPTED", "replayed": False, "stock_movements": 0,
    }
