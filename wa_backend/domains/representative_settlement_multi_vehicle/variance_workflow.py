"""Vehicle review/recount delegates preserving Stocktake's single command authority.

Pre-acquire the exact existing Stocktake idempotency lock before WorkSession /
Vehicle / location / Stocktake locks. Public Stocktake calls commit their own
receipt atomically; no outer pending idempotency record can be stranded.
"""
from sqlalchemy import select

from domains.stocktake.contracts import StocktakeApprovalCommand, StocktakeCountCommand, StocktakeRecountCommand
from domains.stocktake.idempotency import stocktake_request_hash
from models import StocktakeCountAttemptLine
from services import OperationIdempotencyError, lock_idempotent_operation_record

from .contracts import CustodyRejected
from .period_pricing import resolve_canonical_shortage_prices
from .review_evidence import attempt_for_command, count_token, previous_command, recount_line_key, review_token
from .snapshots import load_vehicle_snapshot
from .variance_scope import internal_count_rows, variance_scope

CAPABILITIES = {"approve": "stocktake.approve", "recount": "stocktake.recount", "count": "stocktake.count"}
OPERATIONS = {"approve": "STOCKTAKE_APPROVE", "recount": "STOCKTAKE_RECOUNT", "count": "STOCKTAKE_COUNT"}


async def read_vehicle_variance(db, *, access, session_id, vehicle_id, actor, sheet=False):
    from api.warehouse.stocktake import get_stocktake_count_sheet, get_stocktake_review
    _, vehicle, recon = await variance_scope(
        db, access=access, session_id=session_id, vehicle_id=vehicle_id,
        capability="stocktake.count" if sheet else "stocktake.review", lock=True,
    )
    attempt = await attempt_for_command(db, recon=recon)
    if sheet:
        rows = await get_stocktake_count_sheet(recon.id, db=db, access=access, legacy_actor=actor)
        return {"status": "RECOUNT_REQUIRED", "reconciliation_reference": recon.reference_number,
                "count_token": count_token(recon=recon, vehicle=vehicle, attempt=attempt),
                "lines": [{"line_key": recount_line_key(recon=recon, vehicle=vehicle, row=r),
                           **{k: r[k] for k in ("product_name", "stock_status", "batch_number", "expiry_date")},
                           "uom": r["base_uom_code"]} for r in rows]}
    view = await get_stocktake_review(recon.id, db=db, access=access)
    return {"status": recon.status, "reconciliation_reference": recon.reference_number,
            "review_token": await review_token(db, recon=recon, vehicle=vehicle, attempt=attempt),
            "requires_independent_recount": view["latest_attempt"]["requires_independent_recount"],
            "independent_recount_satisfied": view["independent_recount_satisfied"],
            "lines": [{k: r[k] for k in ("product_name", "batch_number", "stock_status",
                                          "expected_quantity", "actual_quantity", "variance_quantity", "expiry_date")}
                      for r in view["lines"]]}


async def _stocktake_command(db, *, recon, vehicle, payload, action, prior):
    key = "previous_attempt_id" if action == "recount" else "attempt_id"
    attempt = await attempt_for_command(db, recon=recon, prior=prior, response_key=key, parent=action == "count")
    if action == "approve":
        command = StocktakeApprovalCommand(request_id=payload.request_id, count_attempt_id=attempt.id,
                                           password=payload.password, notes=payload.notes)
    elif action == "recount":
        command = StocktakeRecountCommand(request_id=payload.request_id, count_attempt_id=attempt.id,
                                          reason=payload.reason, authorizer_username=payload.authorizer_username,
                                          authorizer_password=payload.authorizer_password)
    else:
        rows = await internal_count_rows(db, recon=recon, vehicle=vehicle)
        if not {i.line_key for i in payload.items} <= set(rows):
            raise CustodyRejected("RECOUNT_LINES_INCOMPLETE", status=422)
        command = StocktakeCountCommand(request_id=payload.request_id, notes=payload.notes, items=[{
            "product_variant_id": rows[i.line_key]["product_variant_id"],
            "batch_id": rows[i.line_key]["batch_id"], "stock_status": rows[i.line_key]["stock_status"],
            "uom_id": rows[i.line_key]["base_uom_id"], "actual_quantity": i.actual_quantity,
        } for i in sorted(payload.items, key=lambda i: i.line_key)])
    return attempt, command


async def run_vehicle_variance(db, *, access, actor, session_id, vehicle_id, payload, action):
    from api.warehouse.stocktake import approve_stocktake_session, recount_stocktake_session, submit_stocktake_count
    if action not in CAPABILITIES:
        raise ValueError("Unknown M04 variance action")
    scope = dict(access=access, session_id=session_id, vehicle_id=vehicle_id, capability=CAPABILITIES[action])
    _, vehicle, recon = await variance_scope(db, **scope, lock=False)
    operation = OPERATIONS[action]
    prior_args = dict(company_id=access.company_id, actor_id=actor.id,
                      request_id=payload.request_id, operation=operation)
    prior = await previous_command(db, **prior_args)
    attempt, command = await _stocktake_command(
        db, recon=recon, vehicle=vehicle, payload=payload, action=action, prior=prior)
    lock_args = dict(company_id=access.company_id, actor_id=actor.id,
                     operation=operation, request_id=str(payload.request_id))
    try:
        _, locked_record = await lock_idempotent_operation_record(
            db, **lock_args, request_hash=stocktake_request_hash(command, target=recon.id))
    except OperationIdempotencyError as exc:
        # Another identical command may have committed between the unlocked
        # attempt pre-read and the canonical advisory lock. Recover its original
        # immutable attempt once, then recheck the FULL canonical body hash.
        # A genuine different-body/actor conflict remains rejected.
        if exc.code != "IDEMPOTENCY_PAYLOAD_CONFLICT" or prior is not None:
            raise
        prior = await previous_command(db, **prior_args)
        if prior is None:
            raise
        attempt, command = await _stocktake_command(
            db, recon=recon, vehicle=vehicle, payload=payload, action=action, prior=prior)
        _, locked_record = await lock_idempotent_operation_record(
            db, **lock_args, request_hash=stocktake_request_hash(command, target=recon.id))
    if locked_record is not None and locked_record.state == "COMMITTED":
        prior = locked_record
    key = "previous_attempt_id" if action == "recount" else "attempt_id"
    work, locked_vehicle, locked_recon = await variance_scope(db, **scope, lock=True)
    if locked_recon.id != recon.id or locked_vehicle != vehicle:
        raise CustodyRejected("CUSTODY_CHANGED")
    locked_attempt = await attempt_for_command(db, recon=recon, prior=prior, response_key=key, parent=action == "count")
    expected = (count_token(recon=recon, vehicle=vehicle, attempt=locked_attempt) if action == "count"
                else await review_token(db, recon=recon, vehicle=vehicle, attempt=locked_attempt))
    supplied = payload.count_token if action == "count" else payload.review_token
    if expected != supplied:
        raise CustodyRejected("CUSTODY_REVIEW_STALE")
    if prior is None:
        if work.is_settled:
            raise CustodyRejected("FINANCIAL_SETTLEMENT_ALREADY_CLOSED")
        await load_vehicle_snapshot(db, company_id=access.company_id, session_id=session_id, responsibility=vehicle)
        if action == "approve":
            shortage = (await db.scalars(select(StocktakeCountAttemptLine.stocktake_line_id).where(
                StocktakeCountAttemptLine.company_id == access.company_id,
                StocktakeCountAttemptLine.count_attempt_id == attempt.id,
                StocktakeCountAttemptLine.variance_quantity < 0,
            ))).all()
            if shortage:
                from models import StocktakeLine
                variants = (await db.scalars(select(StocktakeLine.product_variant_id).where(
                    StocktakeLine.company_id == access.company_id, StocktakeLine.id.in_(shortage),
                ))).all()
                await resolve_canonical_shortage_prices(
                    db, company_id=access.company_id, work_session_id=session_id,
                    vehicle_location_id=vehicle.location_id, variant_ids=variants,
                )
    handler = {"approve": approve_stocktake_session, "recount": recount_stocktake_session,
               "count": submit_stocktake_count}[action]
    result = await handler(recon.id, command, db=db, access=access, legacy_actor=actor)
    return {"status": "RECONCILED_AWAITING_SIGNED_COUNT" if action == "approve" else result["status"],
            "reconciliation_reference": recon.reference_number,
            "movement_count": result.get("movement_count", 0), "financial_ready": False}
