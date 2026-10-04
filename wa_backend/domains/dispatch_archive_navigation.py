"""Public Dispatch read-only archive navigation projection.

Legacy custody snapshots are not route IDs. They deliberately have no generic
Dispatch target: physical reconciliation and financial settlement are separate.
"""
from sqlalchemy import Integer, and_, cast, literal, select, union_all

from dispatch_access import route_filter
from inventory_access import InventoryAccess
from models import DispatchLoadPlanLine, DispatchRoute, InventoryTransferHeader, InventoryTransferLine, ShortageRequest


def dispatch_archive_target_query(access, variant_id, samples):
    route = DispatchRoute
    statements = []

    def columns(code, kind, operation_id, route_id=None):
        return (literal(code).label("code"), literal(kind).label("kind"),
                operation_id.label("operation_id"),
                (route_id if route_id is not None else cast(literal(None), Integer)).label("route_id"))

    if samples.get("ACTIVE_ROUTE_LOAD"):
        statements.append(select(*columns("ACTIVE_ROUTE_LOAD", "route-load", route.id, route.id)).where(
            route.company_id == access.company_id, route.id == samples["ACTIVE_ROUTE_LOAD"],
            route.status.in_(("active", "waiting", "postponed")),
            route_filter(access, "dispatch.read"), route_filter(access, "dispatch.execute"),
            select(1).where(DispatchLoadPlanLine.company_id == access.company_id,
                            DispatchLoadPlanLine.dispatch_route_id == route.id,
                            DispatchLoadPlanLine.product_variant_id == variant_id).correlate(route).exists(),
        ))
    if samples.get("OPEN_TRANSFER"):
        header = InventoryTransferHeader
        statements.append(select(*columns("OPEN_TRANSFER", "handshake", header.id, route.id)).join(
            route, and_(route.company_id == header.company_id, route.work_session_id == header.work_session_id),
        ).where(
            header.company_id == access.company_id, header.id == samples["OPEN_TRANSFER"],
            header.workflow_type == "HANDSHAKE", header.status == "PENDING",
            route.status.in_(("active", "waiting", "postponed")), route_filter(access, "dispatch.read"),
            access.allows("transfer.cancel", header.source_location_id),
            select(1).where(InventoryTransferLine.company_id == access.company_id,
                            InventoryTransferLine.transfer_header_id == header.id,
                            InventoryTransferLine.product_variant_id == variant_id).correlate(header).exists(),
        ))
    if samples.get("OPEN_SHORTAGE") and access.actor.is_admin:
        shortage = ShortageRequest
        statements.append(select(*columns("OPEN_SHORTAGE", "shortage", shortage.id)).where(
            shortage.company_id == access.company_id, shortage.id == samples["OPEN_SHORTAGE"],
            shortage.product_variant_id == variant_id, shortage.status == "pending",
        ))
    return union_all(*statements) if statements else None


async def dispatch_archive_targets(db, actor, variant_id, blockers):
    samples = {row["code"]: row["sample_id"] for row in blockers}
    query = dispatch_archive_target_query(InventoryAccess(db, actor), variant_id, samples)
    if query is None:
        return {}
    return {row["code"]: {key: value for key, value in row.items() if key != "code"}
            for row in (await db.execute(query)).mappings()}
