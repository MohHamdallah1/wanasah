"""Inventory read projection; unknown/hidden evidence never becomes a fake owner."""
from decimal import Decimal
from domains.batch_reservation_contracts import OWNER_PREVIEW_LIMIT, ReservationEvidence, ReservationOwner
from quantity import canonical_quantity


def reservation_evidence(reserved, owners):
    """Explain one location/status from rows read in the balance's SQL snapshot."""
    reserved = Decimal(reserved)
    evidence = ReservationEvidence(
        coverage="NONE" if reserved == 0 else "UNRESOLVED",
        reason=None if reserved == 0 else "OWNER_EVIDENCE_UNAVAILABLE",
        unattributed_quantity=canonical_quantity(reserved),
    )
    if not owners:
        return evidence
    first = owners[0]
    if Decimal(first["owner_quantity"]) > reserved:
        evidence.coverage = "UNRESOLVED"
        evidence.reason = "OWNER_EVIDENCE_MISMATCH"
        return evidence
    evidence.owners = [ReservationOwner(
        transfer_id=row["transfer_id"], reference_number=row["reference_number"],
        transfer_purpose=row["transfer_purpose"], work_session_id=row["work_session_id"],
        route_id=row["route_id"], expected_receiver_id=row["expected_receiver_id"],
        created_by=row["dispatched_by"], quantity=canonical_quantity(row["quantity"]),
        action="FORCE_CANCEL_HANDSHAKE" if row["can_cancel"] else None,
    ) for row in owners]
    remainder = reserved - sum((Decimal(row["quantity"]) for row in owners), Decimal(0))
    evidence.unattributed_quantity = canonical_quantity(remainder)
    evidence.owners_truncated = first["owner_count"] > OWNER_PREVIEW_LIMIT
    evidence.coverage = "COMPLETE" if remainder == 0 else "PARTIAL"
    evidence.reason = (
        "OWNER_PREVIEW_LIMIT" if evidence.owners_truncated else
        "OWNER_EVIDENCE_UNAVAILABLE" if remainder else None
    )
    return evidence
