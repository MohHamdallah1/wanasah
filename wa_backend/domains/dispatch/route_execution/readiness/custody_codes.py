"""Explain accepted/unknown custody without guessing the FIELD owner.

Operational readiness is advisory. Mutating adapters independently row-lock and
recheck this evidence against current vehicle/location/epoch authority.
"""
from __future__ import annotations


def custody_blocker(epoch, *, principal_id: int | None = None,
                    representative_id: int | None = None) -> str | None:
    if epoch is None:
        return None  # An empty newly-created car may still use V1 assignment.
    if epoch.state == "NEEDS_REVIEW" and epoch.custodian_kind == "UNCONFIRMED":
        return "CUSTODY_NEEDS_REVIEW"
    if (epoch.state != "ACCEPTED" or
            epoch.accepted_by_principal_id is None or
            not epoch.request_id or not epoch.payload_hash):
        return "VEHICLE_CUSTODY_UNACCEPTED"
    if epoch.custodian_kind != "FIELD_REPRESENTATIVE":
        return "CUSTODY_NON_FIELD_CUSTODIAN"
    if epoch.custodian_principal_id is None or epoch.field_representative_id is None:
        return "VEHICLE_CUSTODY_UNACCEPTED"
    if principal_id is None and representative_id is None:
        return None
    if (principal_id is None or representative_id is None or
            epoch.custodian_principal_id != principal_id or
            epoch.field_representative_id != representative_id):
        return "CUSTODY_REQUIRES_REASSIGNMENT"
    return None
