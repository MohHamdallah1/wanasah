"""Resolve customer-return book identity from net delivered shop evidence.

A printed lot is evidence, never an operator-selected database Batch. Multiple
anonymous receipts remain distinct. All final stock/cost effects still belong to
the existing visit engine. Resolution does not assert physical carton identity.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from itertools import combinations

from pydantic import ValidationError
from sqlalchemy import Date, String, and_, case, cast, func, literal, or_, select

from domains.product_tracking import is_reserved_internal_batch_number, public_batch_number
from domains.sales_calculation.driver_sale import (
    mobile_quantity_to_base, resolve_driver_mobile_uom_contracts,
)
from models import InventoryMovement, ProductBatch, ProductVariant, Visit
from schemas import ResolvedVisitReturnInput, VisitReturnInput, VisitUpdateRequest
from .contracts import FieldContractError, ReturnResolutionRequest
from .context import assigned_visit
from .tokens import open_reference, owner_binding, require_binding, seal_reference

_PURPOSE = "FIELD_RETURN_RESOLUTION"
_MAX_CANDIDATES = 100
_DELIVERY_TYPES = ("VISIT_ITEM_OUT", "VISIT_SAMPLE_OUT", "VISIT_EXCHANGE_OUT", "VISIT_REWARD_OUT")


def _date(value):
    return value.isoformat() if value is not None else None


def _batch_evidence(batch, variant):
    return {
        "lot_number": public_batch_number(batch.batch_number),
        "production_date": _date(batch.production_date),
        "expiry_date": _date(batch.expiry_date),
        "lot_control_mode": variant.lot_control_mode,
        "expiry_control_mode": variant.expiry_control_mode,
    }


@dataclass(frozen=True)
class ReturnCandidate:
    batch: ProductBatch
    delivered_quantity: Decimal
    delivery_dates: frozenset


async def _candidate_batches(db, *, company_id, shop_id, requests):
    # Net shop deliveries include exact physical reversals, exchanges and samples.
    # A quantity does not disambiguate lots: two smaller deliveries might form
    # one mixed return, so keep EVERY positive candidate and fail closed.
    delivery = and_(
        InventoryMovement.reference_type.in_(_DELIVERY_TYPES),
        InventoryMovement.source_location_id.is_not(None),
        InventoryMovement.destination_location_id.is_(None),
        InventoryMovement.source_stock_status == "AVAILABLE",
    )
    reversed_delivery = and_(
        InventoryMovement.reference_type == "VISIT_REVERSAL",
        InventoryMovement.source_location_id.is_(None),
        InventoryMovement.destination_stock_status == "AVAILABLE",
    )
    returned = and_(
        InventoryMovement.reference_type == "VISIT_RETURN_IN",
        InventoryMovement.source_location_id.is_(None),
        InventoryMovement.destination_stock_status == "DAMAGED",
    )
    reversed_return = and_(
        InventoryMovement.reference_type == "VISIT_REVERSAL",
        InventoryMovement.destination_location_id.is_(None),
        InventoryMovement.source_stock_status == "DAMAGED",
    )
    net = func.sum(case(
        (or_(delivery, reversed_return), InventoryMovement.quantity),
        (or_(reversed_delivery, returned), -InventoryMovement.quantity),
        else_=Decimal("0"),
    ))
    dates = sorted({request.delivery_date for request in requests if request.delivery_date})
    matching_date = case(
        (and_(delivery, Visit.operational_date.in_(dates)), Visit.operational_date),
        else_=literal(None, Date),
    )
    query = select(ProductBatch, net, func.array_agg(func.distinct(matching_date))).join(
        InventoryMovement, and_(
            InventoryMovement.company_id == ProductBatch.company_id,
            InventoryMovement.product_variant_id == ProductBatch.product_variant_id,
            InventoryMovement.batch_id == ProductBatch.id,
        ),
    ).join(Visit, and_(
        Visit.company_id == InventoryMovement.company_id,
        cast(Visit.id, String) == InventoryMovement.reference_id,
    )).where(
        ProductBatch.company_id == company_id,
        ProductBatch.product_variant_id.in_(sorted({r.product_variant_id for r in requests})),
        InventoryMovement.company_id == company_id,
        InventoryMovement.movement_kind == "PHYSICAL",
        Visit.company_id == company_id, Visit.shop_id == shop_id,
    ).group_by(ProductBatch.id).having(net > 0).order_by(ProductBatch.id).limit(1001)
    rows = (await db.execute(query)).all()
    if len(rows) > 1000:
        raise FieldContractError(
            "FIELD_RETURN_PROVENANCE_REVIEW_REQUIRED",
            "Delivery evidence exceeds the bounded field resolution.",
            context={"required_action": "BACKOFFICE_REVIEW_RETURN_PROVENANCE"},
        )
    result = {}
    for batch, quantity, delivered_dates in rows:
        result.setdefault(batch.product_variant_id, []).append(ReturnCandidate(
            batch, Decimal(quantity), frozenset(value for value in delivered_dates if value),
        ))
    return result

def choose_batch(candidates, *, variant, request):
    if not candidates:
        raise FieldContractError(
            "FIELD_RETURN_SOURCE_NOT_FOUND",
            "No matching delivered stock can substantiate this return.",
            context={"required_action": "VERIFY_RETURN_DELIVERY_EVIDENCE"},
        )
    if len(candidates) == 1:
        return candidates[0]
    evidence = [_batch_evidence(candidate.batch, variant) for candidate in candidates]
    fields = ("lot_number", "expiry_date", "production_date")
    # Ask only for evidence sufficient to distinguish these actual candidates.
    for size in range(1, len(fields) + 1):
        for keys in combinations(fields, size):
            values = [tuple(row[key] for key in keys) for row in evidence]
            if all(all(value is not None for value in group) for group in values) and len(set(values)) == len(values):
                raise FieldContractError(
                    "FIELD_RETURN_EVIDENCE_REQUIRED",
                    "Confirm the printed evidence on the returned goods.",
                    context={
                        "required_evidence": list(keys),
                        "choices": [{key: row[key] for key in keys} for row in evidence],
                    },
                )
    if request.delivery_date is None:
        raise FieldContractError(
            "FIELD_RETURN_EVIDENCE_REQUIRED",
            "Confirm the original delivery date.",
            context={"required_evidence": ["delivery_date"]},
        )
    raise FieldContractError(
        "FIELD_RETURN_PROVENANCE_REVIEW_REQUIRED",
        "The supplied business evidence still identifies multiple receipts.",
        context={"required_action": "BACKOFFICE_REVIEW_RETURN_PROVENANCE"},
    )


async def _resolve_many(db, *, company_id, shop_id, requests):
    ids = sorted({request.product_variant_id for request in requests})
    rows = (await db.execute(select(ProductVariant).where(
        ProductVariant.company_id == company_id, ProductVariant.id.in_(ids),
    ))).scalars().all()
    variants = {variant.id: variant for variant in rows}
    if set(variants) != set(ids):
        raise FieldContractError("FIELD_RETURN_PRODUCT_NOT_FOUND", "Product is unavailable.", status_code=404)
    contracts = await resolve_driver_mobile_uom_contracts(db, company_id=company_id, variant_ids=ids)
    by_variant = await _candidate_batches(
        db, company_id=company_id, shop_id=shop_id, requests=requests,
    )
    resolved, used, available = [], {}, {}
    for request in requests:
        if request.lot_number and is_reserved_internal_batch_number(request.lot_number):
            raise FieldContractError("FIELD_RETURN_EVIDENCE_INVALID", "Use printed business evidence.", status_code=422)
        variant = variants[request.product_variant_id]
        all_candidates = by_variant.get(request.product_variant_id, [])
        if len(all_candidates) > _MAX_CANDIDATES:
            raise FieldContractError(
                "FIELD_RETURN_PROVENANCE_REVIEW_REQUIRED", "Delivery history needs review.",
                context={"required_action": "BACKOFFICE_REVIEW_RETURN_PROVENANCE"},
            )
        candidates = [candidate for candidate in all_candidates
            if (request.lot_number is None or public_batch_number(candidate.batch.batch_number) == request.lot_number)
            and (request.production_date is None or candidate.batch.production_date == request.production_date)
            and (request.expiry_date is None or candidate.batch.expiry_date == request.expiry_date)
            and (request.delivery_date is None or request.delivery_date in candidate.delivery_dates)]
        chosen = choose_batch(candidates, variant=variant, request=request)
        base_quantity = mobile_quantity_to_base(
            contracts[request.product_variant_id], carton_quantity=request.quantity,
            pack_quantity=request.packs_quantity, field_name="return_quantity", allow_zero=False,
        )
        if chosen.delivered_quantity < base_quantity:
            raise FieldContractError(
                "FIELD_RETURN_DELIVERY_QUANTITY_UNSUBSTANTIATED",
                "The supplied return exceeds the matching net delivery evidence.",
                context={"required_action": "VERIFY_RETURN_DELIVERY_EVIDENCE"},
            )
        batch_key = chosen.batch.id
        used[batch_key] = used.get(batch_key, Decimal("0")) + base_quantity
        available[batch_key] = chosen.delivered_quantity
        if used[batch_key] > available[batch_key]:
            raise FieldContractError(
                "FIELD_RETURN_DELIVERY_QUANTITY_UNSUBSTANTIATED",
                "Combined return lines exceed matching delivery evidence.",
                context={"required_action": "VERIFY_RETURN_DELIVERY_EVIDENCE"},
            )
        resolved.append((chosen.batch, variant))
    return resolved

async def resolve_return(db, *, context, driver_id, visit_id, request):
    visit, shop, work = await assigned_visit(
        db, context=context, driver_id=driver_id, visit_id=visit_id,
    )
    batch, variant = (await _resolve_many(
        db, company_id=context.company_id, shop_id=shop.id, requests=[request],
    ))[0]
    proof = {
        **owner_binding(context, driver_id), "visit": visit.id, "shop": shop.id,
        "session": work.session.id, "batch": batch.id,
        "request": request.model_dump(mode="json"),
        "evidence": _batch_evidence(batch, variant),
    }
    return {
        "status": "RESOLVED", "resolution_token": seal_reference(_PURPOSE, proof),
        "evidence": {key: value for key, value in proof["evidence"].items()
                     if key in ("lot_number", "production_date", "expiry_date")},
    }


def canonicalize_returns(payload, *, context, driver_id, visit_id):
    proofs, returns = [], []
    for item in payload.returns:
        if not isinstance(item, ResolvedVisitReturnInput):
            returns.append(item)
            continue
        proof = open_reference(_PURPOSE, item.resolution_token)
        require_binding(proof, {**owner_binding(context, driver_id), "visit": visit_id})
        try:
            request = ReturnResolutionRequest.model_validate(proof["request"])
            if type(proof["batch"]) is not int or proof["batch"] <= 0:
                raise ValueError
            for field in ("product_variant_id", "quantity", "packs_quantity", "return_type"):
                if getattr(item, field) != getattr(request, field):
                    raise ValueError
            returns.append(VisitReturnInput(
                **item.model_dump(exclude={"resolution_token"}), batch_id=proof["batch"],
            ))
        except (KeyError, ValueError, TypeError, ValidationError):
            raise FieldContractError(
                "FIELD_RETURN_RESOLUTION_MISMATCH",
                "Resolve the changed return quantity or evidence again.", status_code=422,
            ) from None
        proofs.append(proof)
    if not proofs:
        return payload, ()
    try:
        canonical = VisitUpdateRequest(
            **payload.model_dump(exclude={"returns"}), returns=returns,
        )
    except ValidationError:
        raise FieldContractError(
            "FIELD_RETURN_LINES_INVALID", "Return lines conflict.", status_code=422,
        ) from None
    return canonical, tuple(proofs)


async def revalidate_provenance(db, *, context, driver_id, visit, session, proofs):
    # Caller owns session -> shop -> visit locks. Revalidate BEFORE correcting
    # this very visit changes its delivery evidence. Query all lines in bulk.
    if not proofs:
        return
    requests = []
    for proof in proofs:
        require_binding(proof, {
            **owner_binding(context, driver_id), "visit": visit.id,
            "shop": visit.shop_id, "session": session.id,
        })
        requests.append(ReturnResolutionRequest.model_validate(proof["request"]))
    resolved = await _resolve_many(
        db, company_id=context.company_id, shop_id=visit.shop_id, requests=requests,
    )
    for proof, (batch, variant) in zip(proofs, resolved):
        if batch.id != proof["batch"] or _batch_evidence(batch, variant) != proof["evidence"]:
            raise FieldContractError(
                "FIELD_RETURN_RESOLUTION_CHANGED", "Return provenance changed; resolve it again.",
            )

async def revalidate_batch_metadata(db, *, company_id, proofs):
    if not proofs:
        return
    # Lock only after the visit engine owns lifecycle/location guards. No lock
    # is added ahead of its established product -> location -> Batch ordering.
    batch_ids = sorted({proof["batch"] for proof in proofs})
    rows = (await db.execute(
        select(ProductBatch, ProductVariant).join(ProductVariant, and_(
            ProductVariant.company_id == ProductBatch.company_id,
            ProductVariant.id == ProductBatch.product_variant_id,
        )).where(
            ProductBatch.company_id == company_id, ProductBatch.id.in_(batch_ids),
            ProductVariant.company_id == company_id,
        ).order_by(ProductBatch.id).with_for_update(read=True, of=ProductBatch)
    )).all()
    found = {batch.id: (batch, variant) for batch, variant in rows}
    for proof in proofs:
        pair = found.get(proof["batch"])
        if (pair is None or pair[0].product_variant_id != proof["request"]["product_variant_id"]
                or _batch_evidence(*pair) != proof["evidence"]):
            raise FieldContractError(
                "FIELD_RETURN_RESOLUTION_CHANGED", "Return identity changed; resolve it again.",
            )
