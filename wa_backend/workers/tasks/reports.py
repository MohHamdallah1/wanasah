# HEAVY_REPORTS_FOUNDATION_V1
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select, text

from models import (
    InventoryMovement,
    InventoryTransferHeader,
    Visit,
    WorkSession,
)
from workers.app import REPORTS_QUEUE, app
from workers.tenant import tenant_session


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.task(
    name="wanasah.report_foundation_probe",
    queue=REPORTS_QUEUE,
)
async def report_foundation_probe(
    company_id: int,
) -> dict:
    """
    Infrastructure-only report probe.

    Business data is strictly read-only. The PostgreSQL transaction itself is
    switched to READ ONLY before report queries, so an accidental future write
    in this task fails at the database layer.
    """
    company_id = int(company_id)
    if company_id <= 0:
        raise ValueError("company_id must be a positive integer.")

    async with tenant_session(company_id) as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))

        session_count = int(
            (
                await db.execute(
                    select(func.count(WorkSession.id)).where(
                        WorkSession.company_id == company_id
                    )
                )
            ).scalar_one()
            or 0
        )
        visit_count = int(
            (
                await db.execute(
                    select(func.count(Visit.id)).where(
                        Visit.company_id == company_id
                    )
                )
            ).scalar_one()
            or 0
        )
        transfer_count = int(
            (
                await db.execute(
                    select(func.count(InventoryTransferHeader.id)).where(
                        InventoryTransferHeader.company_id == company_id
                    )
                )
            ).scalar_one()
            or 0
        )
        movement_count = int(
            (
                await db.execute(
                    select(func.count(InventoryMovement.id)).where(
                        InventoryMovement.company_id == company_id
                    )
                )
            ).scalar_one()
            or 0
        )

        await db.rollback()

        return {
            "report": "FOUNDATION_PROBE",
            "company_id": company_id,
            "generated_at_utc": _utc_now_iso(),
            "counts": {
                "work_sessions": session_count,
                "visits": visit_count,
                "inventory_transfers": transfer_count,
                "inventory_movements": movement_count,
            },
        }
