"""Public Operations read projection for the financial stage of custody.

Inventory reconciliation is not financial settlement. This resolves snapshot
identity only; Operations' debrief/report remains the readiness authority.
"""
from sqlalchemy import and_, select

from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from inventory_access import InventoryAccess
from models import SessionInventorySnapshot, WorkSession


def _archive_access(db, access_or_actor):
    """Prefer canonical Backoffice access; retain the old Catalog caller temporarily."""
    if isinstance(access_or_actor, (BackofficeCapabilityAccess, InventoryAccess)):
        return access_or_actor
    return InventoryAccess(db, access_or_actor)


def operations_archive_target_query(access_or_actor, variant_id, samples):
    if not samples.get("OPEN_CUSTODY"):
        return None
    access = _archive_access(None, access_or_actor)
    snapshot, session = SessionInventorySnapshot, WorkSession
    return select(session.id.label("operation_id")).select_from(snapshot).join(
        session, and_(session.company_id == snapshot.company_id, session.id == snapshot.work_session_id),
    ).where(
        snapshot.company_id == access.company_id, snapshot.id == samples["OPEN_CUSTODY"],
        snapshot.product_variant_id == variant_id,
        session.end_time.is_not(None), session.inventory_reconciled_at.is_not(None),
        session.is_settled.is_(False),
        access.allows("settlement.read", any_location=True),
    )


async def operations_archive_targets(db, access_or_actor, variant_id, blockers):
    access = _archive_access(db, access_or_actor)
    query = operations_archive_target_query(
        access,
        variant_id,
        {row["code"]: row["sample_id"] for row in blockers},
    )
    if query is None:
        return {}
    session_id = await db.scalar(query)
    return {"OPEN_CUSTODY": {"kind": "settlement", "operation_id": session_id}} if session_id is not None else {}
