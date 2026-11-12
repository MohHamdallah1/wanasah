"""Canonical Vehicle Recon first count, using bounded batch persistence.

The existing stocktake threshold/recount policy is injected unchanged. This
creates review evidence and a location lock; it never approves or moves stock.
"""
import json
from uuid import uuid4

from models import (
    InventoryLock, StocktakeCountAttempt, StocktakeCountAttemptLine,
    StocktakeLine, StocktakeSession, SystemAuditLog, utc_now,
)
from quantity import canonical_quantity

from .contracts import MAX_LINES, CustodyRejected


async def persist_variance(db, *, company_id, work, vehicle_location_id, actor_id,
                           rows, actual, notes, requires_independent_recount):
    if len(rows) > MAX_LINES or set(actual) != set(rows):
        raise CustodyRejected("CUSTODY_COUNT_INCOMPLETE_OR_STALE", status=422)
    await db.flush()
    reference = f"VREC-{uuid4().hex[:12].upper()}"
    recon = StocktakeSession(
        company_id=company_id, location_id=vehicle_location_id, reference_number=reference,
        stocktake_type="VEHICLE_RECON", status="PENDING_REVIEW", related_work_session_id=work.id,
        started_by=actor_id, snapshot_cutoff_at=utc_now(), notes=notes,
    )
    db.add(recon)
    await db.flush()
    attempt = StocktakeCountAttempt(company_id=company_id, stocktake_session_id=recon.id,
                                    attempt_number=1, counted_by=actor_id)
    db.add(attempt)
    db.add(InventoryLock(company_id=company_id, stocktake_session_id=recon.id,
                         location_id=vehicle_location_id, created_by=actor_id))
    lines = [StocktakeLine(
        company_id=company_id, stocktake_session_id=recon.id, product_variant_id=row["variant_id"],
        batch_id=row["batch_id"], stock_status=row["stock_status"], line_origin="SNAPSHOT",
        expected_quantity=row["expected_quantity"],
    ) for row in rows.values()]
    db.add_all(lines)
    await db.flush()
    pairs, counted_lines = [], []
    for row, line in zip(rows.values(), lines, strict=True):
        quantity = actual[row["line_key"]]
        variance = quantity - row["expected_quantity"]
        counted_lines.append(StocktakeCountAttemptLine(
            company_id=company_id, stocktake_session_id=recon.id, count_attempt_id=attempt.id,
            stocktake_line_id=line.id, expected_quantity=row["expected_quantity"],
            actual_quantity=quantity, variance_quantity=variance,
        ))
        pairs.append((row["expected_quantity"], variance))
    db.add_all(counted_lines)
    attempt.requires_independent_recount = await requires_independent_recount(db, company_id, pairs)
    db.add(SystemAuditLog(
        company_id=company_id, admin_id=actor_id, target_id=f"WorkSession_{work.id}",
        action_type="REPRESENTATIVE_CUSTODY_VARIANCE",
        old_value=f"expected_vehicle_location={vehicle_location_id}",
        new_value=json.dumps({
            "reconciliation_reference": reference, "actor": actor_id, "driver": work.driver_id,
            "differences": [{"sku": r["sku"], "lot": r["batch_number"], "stock_status": r["stock_status"],
                             "expected": canonical_quantity(r["expected_quantity"]),
                             "actual": canonical_quantity(actual[r["line_key"]])}
                            for r in rows.values() if actual[r["line_key"]] != r["expected_quantity"]],
        }, ensure_ascii=False)[:4000],
    ))
    return {"status": "REVIEW_REQUIRED", "review_required": True,
            "reconciliation_reference": reference,
            "requires_independent_recount": bool(attempt.requires_independent_recount), "movement_count": 0}
