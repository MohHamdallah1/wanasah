"""Immutable review/count fences and original-attempt recovery after response loss."""
from sqlalchemy import select

from models import OperationIdempotency, StocktakeCountAttempt, StocktakeCountAttemptLine
from quantity import canonical_quantity

from .contracts import MAX_LINES, CustodyRejected
from .policy import digest


async def previous_command(db, *, company_id, actor_id, request_id, operation):
    record = await db.scalar(select(OperationIdempotency).where(
        OperationIdempotency.company_id == company_id, OperationIdempotency.created_by == actor_id,
        OperationIdempotency.request_id == str(request_id), OperationIdempotency.operation == operation,
    ))
    return record if record is not None and record.state == "COMMITTED" else None


async def attempt_for_command(db, *, recon, prior=None, response_key="attempt_id", parent=False):
    query = select(StocktakeCountAttempt).where(
        StocktakeCountAttempt.company_id == recon.company_id,
        StocktakeCountAttempt.stocktake_session_id == recon.id,
    )
    if prior is not None:
        value = (prior.response_json or {}).get(response_key)
        if type(value) is not int:
            raise CustodyRejected("CUSTODY_COMMAND_EVIDENCE_INCOMPLETE")
        query = query.where(StocktakeCountAttempt.id == value)
    else:
        query = query.order_by(StocktakeCountAttempt.attempt_number.desc()).limit(1)
    attempt = await db.scalar(query)
    if parent and prior is not None and attempt is not None:
        attempt = await db.scalar(select(StocktakeCountAttempt).where(
            StocktakeCountAttempt.company_id == recon.company_id,
            StocktakeCountAttempt.stocktake_session_id == recon.id,
            StocktakeCountAttempt.id == attempt.recount_of_attempt_id,
        ))
    if attempt is None:
        raise CustodyRejected("COUNT_ATTEMPT_NOT_FOUND")
    return attempt


async def review_token(db, *, recon, vehicle, attempt):
    lines = (await db.scalars(select(StocktakeCountAttemptLine).where(
        StocktakeCountAttemptLine.company_id == recon.company_id,
        StocktakeCountAttemptLine.stocktake_session_id == recon.id,
        StocktakeCountAttemptLine.count_attempt_id == attempt.id,
    ).order_by(StocktakeCountAttemptLine.stocktake_line_id).limit(MAX_LINES + 1))).all()
    if len(lines) > MAX_LINES:
        raise CustodyRejected("SETTLEMENT_CUSTODY_TOO_LARGE")
    return digest({
        "company": recon.company_id, "session": recon.related_work_session_id,
        "location": recon.location_id, "recon": recon.id, "context": vehicle.context_digest,
        "attempt": attempt.id, "number": attempt.attempt_number, "counter": attempt.counted_by,
        "submitted": attempt.submitted_at.isoformat(),
        "lines": [(l.stocktake_line_id, canonical_quantity(l.expected_quantity),
                   canonical_quantity(l.actual_quantity), canonical_quantity(l.variance_quantity)) for l in lines],
    })


def count_token(*, recon, vehicle, attempt):
    return digest(("M04_RECOUNT", recon.company_id, recon.id, recon.related_work_session_id,
                   vehicle.vehicle_id, vehicle.location_id, vehicle.context_digest,
                   attempt.id, attempt.attempt_number))


def recount_line_key(*, recon, vehicle, row):
    return digest((recon.company_id, recon.id, vehicle.vehicle_id, vehicle.location_id,
                   row["product_variant_id"], row["batch_id"], row["stock_status"]))[:24]
