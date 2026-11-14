"""Bounded, tenant- and principal-scoped custody status/history reads."""
from __future__ import annotations
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from domains.identity.models import CompanyPrincipal
from domains.dispatch.route_execution.vehicle_custody_models import VehicleCustodyEpoch
from .handoffs_model import VehicleCustodyHandoff
from .handoffs_service import effective_state
from .service import _latest_handoff
from .proofs import CustodyRejected


async def public_handoff(db: AsyncSession, row: VehicleCustodyHandoff) -> dict:
    recipient = (await db.execute(select(CompanyPrincipal.full_name, CompanyPrincipal.username).where(
        CompanyPrincipal.company_id == row.company_id,
        CompanyPrincipal.id == row.recipient_principal_id,
    ))).one_or_none()
    if not recipient:
        raise CustodyRejected("CUSTODY_RECIPIENT_IDENTITY_MISSING")
    return {
        "handoff_id": int(row.id),
        "vehicle_id": int(row.vehicle_id),
        "vehicle_location_id": int(row.vehicle_location_id),
        "target_driver_id": int(row.target_driver_id),
        "recipient_label": f"{recipient.full_name} ({recipient.username})",
        "state": effective_state(row),
        "context_revision": int(row.expected_context_revision),
        "stock_snapshot": row.expected_stock_snapshot,
        "expires_at": row.expires_at.isoformat() + "Z",
        "receiver_confirmed_at": (
            None if row.confirmed_at is None else
            __import__("datetime").datetime.fromtimestamp(row.confirmed_at, __import__("datetime").timezone.utc).isoformat()
        ),
        "reason_code": row.decline_reason_code,
        "reason_text": row.decline_reason_text,
        "accepted_epoch_id": row.accepted_epoch_id,
    }


async def manager_current(db, *, company_id: int, vehicle_id: int):
    row = await _latest_handoff(db, company_id, vehicle_id)
    return None if row is None else await public_handoff(db, row)


async def field_pending(db, *, company_id: int, principal_id: int, rep_id: int, limit: int = 50):
    from .handoffs_service import now
    rows = (await db.scalars(select(VehicleCustodyHandoff).where(
        VehicleCustodyHandoff.company_id == company_id,
        VehicleCustodyHandoff.recipient_principal_id == principal_id,
        VehicleCustodyHandoff.recipient_rep_id == rep_id,
        VehicleCustodyHandoff.state.in_(("PENDING", "CONFIRMED")),
        VehicleCustodyHandoff.expires_at > now(),
    ).order_by(VehicleCustodyHandoff.id.desc()).limit(limit))).all()
    return {"items": [await public_handoff(db, row) for row in rows]}


async def field_record(db, *, company_id: int, principal_id: int, rep_id: int, handoff_id: int):
    row = await db.scalar(select(VehicleCustodyHandoff).where(
        VehicleCustodyHandoff.company_id == company_id,
        VehicleCustodyHandoff.recipient_principal_id == principal_id,
        VehicleCustodyHandoff.recipient_rep_id == rep_id,
        VehicleCustodyHandoff.id == handoff_id,
    ))
    if row is None:
        raise CustodyRejected("CUSTODY_HANDOFF_NOT_FOUND", 404)
    return row


async def custody_history(
    db: AsyncSession, *, company_id: int, vehicle_id: int, limit: int = 20,
) -> dict:
    recipient = aliased(CompanyPrincipal)
    approver = aliased(CompanyPrincipal)
    results = (await db.execute(
        select(VehicleCustodyEpoch, recipient.full_name, recipient.username, approver.full_name, approver.username)
        .outerjoin(recipient, (recipient.company_id == VehicleCustodyEpoch.company_id)
                   & (recipient.id == VehicleCustodyEpoch.custodian_principal_id))
        .outerjoin(approver, (approver.company_id == VehicleCustodyEpoch.company_id)
                   & (approver.id == VehicleCustodyEpoch.accepted_by_principal_id))
        .where(
            VehicleCustodyEpoch.company_id == company_id,
            VehicleCustodyEpoch.vehicle_id == vehicle_id,
        )
        .order_by(VehicleCustodyEpoch.context_revision.desc(), VehicleCustodyEpoch.id.desc())
        .limit(limit)
    )).all()
    return {"vehicle_id": vehicle_id, "items": [{
        "epoch_id": int(epoch.id),
        "context_revision": int(epoch.context_revision),
        "state": str(epoch.state),
        "custodian_kind": str(epoch.custodian_kind),
        "recipient_label": f"{recipient_name} ({recipient_username})"
                           if epoch.state == "ACCEPTED" and recipient_username else None,
        "approved_by_label": f"{approver_name} ({approver_username})"
                             if epoch.state == "ACCEPTED" and approver_username else None,
        "accepted_and_counted": epoch.state == "ACCEPTED" and bool(
            epoch.handoff_reference and epoch.request_id and epoch.payload_hash
            and epoch.accepted_by_principal_id and epoch.custodian_principal_id
        ),
        # An M01 legacy review timestamp is not a real acceptance/start time.
        "started_at": epoch.started_at.isoformat() + "Z"
                      if epoch.state == "ACCEPTED" and epoch.started_at else None,
        "ended_at": epoch.ended_at.isoformat() + "Z" if epoch.ended_at else None,
        "legacy_review_logged_at": epoch.created_at.isoformat() + "Z"
                                   if epoch.state == "NEEDS_REVIEW" else None,
        "request_id": epoch.request_id,
        "handoff_evidence_hash": epoch.handoff_reference,
        "evidence_origin": epoch.evidence_origin,
        "reason": epoch.reason,
        "legacy_unconfirmed": epoch.state == "NEEDS_REVIEW" or epoch.custodian_kind == "UNCONFIRMED",
    } for epoch, recipient_name, recipient_username, approver_name, approver_username in results]}
