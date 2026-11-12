"""Inventory port preserving the existing movement and reviewed-count authority.

The bounded legacy variance writer is injected by the existing settlement
adapter, never imported from an API module. Canonical stocktake approval remains
responsible for independent recount, permissions, valuation and posting.
"""
from sqlalchemy import or_, select

from models import InventoryLocation, InventoryLock, InventoryTransferHeader, StocktakeSession, SystemAuditLog
from services import apply_inventory_movements_batch

from .contracts import CustodyRejected
from .policy import line_key


class CanonicalInventoryCustody:
    def __init__(self, variance_writer):
        self.variance_writer = variance_writer

    async def require_clear_or_reviewed(self, db, *, work, snapshot):
        company_id, location_id = snapshot.company_id, snapshot.responsibility.location_id
        pending_transfer = await db.scalar(select(InventoryTransferHeader.id).where(
            InventoryTransferHeader.company_id == company_id,
            InventoryTransferHeader.status.in_(("DRAFT", "PENDING", "IN_TRANSIT")),
            or_(InventoryTransferHeader.source_location_id == location_id,
                InventoryTransferHeader.destination_location_id == location_id),
        ).limit(1))
        if pending_transfer is not None:
            raise CustodyRejected("VEHICLE_CUSTODY_TRANSFER_PENDING")
        blocked = await db.scalar(select(InventoryLock.id).where(
            InventoryLock.company_id == company_id, InventoryLock.location_id == location_id,
            InventoryLock.released_at.is_(None),
        ).limit(1))
        if blocked is not None:
            raise CustodyRejected("CUSTODY_RECONCILIATION_PENDING_REVIEW")
        recons = (await db.scalars(select(StocktakeSession).where(
            StocktakeSession.company_id == company_id,
            StocktakeSession.related_work_session_id == work.id,
            StocktakeSession.location_id == location_id,
            StocktakeSession.stocktake_type == "VEHICLE_RECON",
            StocktakeSession.status != "CANCELLED",
        ).limit(2))).all()
        if not recons:
            return None
        if len(recons) != 1 or recons[0].status != "POSTED":
            raise CustodyRejected("CUSTODY_RECONCILIATION_PENDING_REVIEW")
        recon = recons[0]
        posted_audit = await db.scalar(select(SystemAuditLog.id).where(
            SystemAuditLog.company_id == company_id,
            SystemAuditLog.target_id == f"Stocktake_{recon.id}",
            SystemAuditLog.action_type == "STOCKTAKE_APPROVED_AND_POSTED",
            SystemAuditLog.admin_id == recon.approved_by,
        ).limit(1))
        if (posted_audit is None or recon.approved_at is None or recon.posted_at is None
                or recon.approved_by is None):
            raise CustodyRejected("VEHICLE_RECON_REVIEW_EVIDENCE_REQUIRED")
        return int(recon.id)

    async def submit_variance(self, db, *, work, snapshot, actual, actor_id, notes):
        # Reuse the existing VEHICLE_RECON attempt/threshold writer unchanged.
        # The ordered M04 migration must first replace its session-only unique
        # key with the company/session/location key; never bypass that guard.
        rows = {}
        for row in snapshot.rows:
            key = line_key(snapshot, row)
            rows[key] = {
                "line_key": key, "variant_id": row.variant_id, "batch_id": row.batch_id,
                "stock_status": row.stock_status, "expected_quantity": row.quantity,
                "sku": row.sku, "batch_number": row.lot,
            }
        return await self.variance_writer(
            db, company_id=snapshot.company_id, work=work,
            vehicle_location_id=snapshot.responsibility.location_id,
            actor_id=actor_id, rows=rows, actual=actual, notes=notes,
        )

    async def physical_handoff(self, db, *, work, snapshot, destination_id, actor_id, request_id):
        destination = await db.scalar(select(InventoryLocation.id).where(
            InventoryLocation.company_id == snapshot.company_id,
            InventoryLocation.id == destination_id,
            InventoryLocation.location_type == "WAREHOUSE", InventoryLocation.is_active.is_(True),
        ))
        if destination is None:
            raise CustodyRejected("RECEIVING_WAREHOUSE_NOT_FOUND", status=404)
        movements = [{
            "product_variant_id": row.variant_id, "batch_id": row.batch_id,
            "quantity": row.quantity, "movement_kind": "PHYSICAL",
            "reference_type": "REPRESENTATIVE_CUSTODY_RECEIPT", "reference_id": str(work.id),
            "idempotency_key": f"M04-HANDOFF-{request_id}-{line_key(snapshot, row)}",
            "source_location_id": snapshot.responsibility.location_id,
            "destination_location_id": destination_id,
            "source_stock_status": row.stock_status, "destination_stock_status": row.stock_status,
            "work_session_id": work.id,
            "notes": f"Receiver {actor_id}; explicit physical vehicle handoff",
        } for row in snapshot.rows if row.quantity > 0]
        if movements:
            posted = await apply_inventory_movements_batch(
                db, company_id=snapshot.company_id, performed_by=actor_id, movements=movements,
            )
            if len(posted) != len(movements):
                raise CustodyRejected("CUSTODY_HANDOFF_MOVEMENT_EVIDENCE_INCOMPLETE")
        return len(movements)
