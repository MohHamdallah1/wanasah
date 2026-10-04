"""Public, read-only Dispatch reservation evidence for Inventory consumers.

Only pending HANDSHAKE allocations with matching, unreleased movement evidence
are supported. This projection grants no authority to execute a command.
"""
from sqlalchemy import and_, func, select

from dispatch_access import route_filter
from models import DispatchRoute, InventoryMovement, InventoryTransferHeader, InventoryTransferLine


def reservation_owner_projection(access, *, batch_id, variant_id, preview_limit):
    """Public SQL read projection, joined to Inventory sources in one snapshot.

    Permissions apply before the bounded preview. Current Dispatch creates only
    ROUTE_LOAD/ROUTE_RETURN reservations; custody/shortage/transit are physical
    evidence, not independent reservation owners. Unsupported/inconsistent
    evidence is deliberately left for Inventory's unattributed quantity.
    """
    if type(preview_limit) is not int or not 1 <= preview_limit <= 100:
        raise ValueError("Expected a bounded reservation owner preview")
    h, line, movement = InventoryTransferHeader, InventoryTransferLine, InventoryMovement
    route = DispatchRoute
    evidence_scope = (
        movement.company_id == access.company_id,
        movement.transfer_header_id == h.id,
        movement.product_variant_id == line.product_variant_id,
        movement.batch_id == line.batch_id,
        movement.source_location_id == h.source_location_id,
        movement.source_stock_status == line.source_stock_status,
        movement.destination_location_id == h.source_location_id,
        movement.destination_stock_status == line.source_stock_status,
        movement.movement_kind == "RESERVATION",
    )
    reserved = select(1).where(
        *evidence_scope,
        movement.reservation_action == "RESERVE",
        movement.reference_type == "HANDSHAKE_RESERVE",
        movement.reference_id == h.reference_number,
        movement.quantity == line.quantity,
        movement.work_session_id == h.work_session_id,
    ).correlate(h, line).exists()
    released = select(1).where(
        *evidence_scope, movement.reservation_action == "RELEASE",
    ).correlate(h, line).exists()
    bucket = (h.source_location_id, line.source_stock_status)
    candidates = select(
        h.source_location_id.label("owner_location_id"),
        line.source_stock_status.label("owner_stock_status"),
        h.id.label("transfer_id"), h.reference_number,
        h.transfer_purpose, h.work_session_id, h.expected_receiver_id,
        h.dispatched_by, route.id.label("route_id"), line.quantity,
        access.allows("transfer.cancel", h.source_location_id).label("can_cancel"),
        func.row_number().over(partition_by=bucket, order_by=h.id).label("position"),
        func.count().over(partition_by=bucket).label("owner_count"),
        func.sum(line.quantity).over(partition_by=bucket).label("owner_quantity"),
    ).select_from(line).join(h, and_(
        h.company_id == line.company_id, h.id == line.transfer_header_id,
    )).join(route, and_(
        route.company_id == h.company_id,
        route.work_session_id == h.work_session_id,
        route.driver_id == h.expected_receiver_id,
    )).where(
        line.company_id == access.company_id,
        line.batch_id == batch_id, line.product_variant_id == variant_id,
        h.workflow_type == "HANDSHAKE", h.status == "PENDING",
        h.transfer_purpose.in_(("ROUTE_LOAD", "ROUTE_RETURN")),
        line.source_stock_status == "AVAILABLE",
        route.vehicle_id.is_not(None),
        access.location_filter("inventory.read", h.source_location_id),
        route_filter(access, "dispatch.read"), reserved, ~released,
    ).subquery("dispatch_reservation_candidates")
    return select(candidates).where(
        candidates.c.position <= preview_limit,
    ).subquery("dispatch_reservation_owners")
