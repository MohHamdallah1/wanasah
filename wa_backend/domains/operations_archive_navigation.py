"""Public Operations read projection for the financial stage of custody.

Inventory reconciliation is not financial settlement. This resolves snapshot
identity only; Operations' debrief/report remains the readiness authority.
"""
from sqlalchemy import and_, select

from models import SessionInventorySnapshot, WorkSession


def operations_archive_target_query(actor, variant_id, samples):
    if not actor.is_admin or not samples.get("OPEN_CUSTODY"):
        return None
    snapshot, session = SessionInventorySnapshot, WorkSession
    return select(session.id.label("operation_id")).select_from(snapshot).join(
        session, and_(session.company_id == snapshot.company_id, session.id == snapshot.work_session_id),
    ).where(
        snapshot.company_id == actor.company_id, snapshot.id == samples["OPEN_CUSTODY"],
        snapshot.product_variant_id == variant_id,
        session.end_time.is_not(None), session.inventory_reconciled_at.is_not(None),
        session.is_settled.is_(False),
    )


async def operations_archive_targets(db, actor, variant_id, blockers):
    query = operations_archive_target_query(actor, variant_id, {row["code"]: row["sample_id"] for row in blockers})
    if query is None:
        return {}
    session_id = await db.scalar(query)
    return {"OPEN_CUSTODY": {"kind": "settlement", "operation_id": session_id}} if session_id is not None else {}
