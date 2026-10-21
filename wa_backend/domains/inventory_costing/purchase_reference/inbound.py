"""Receipt-only reference side effect, composed in the existing posting transaction.

The receipt adapter acquires the guards after durable replay, before Supplier,
invoice, lifecycle, batch, policy, inventory or costing locks. This module never
commits, rolls back, posts inventory, or edits historical evidence.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from fractions import Fraction
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import object_session

from domains.authorization.backoffice_access import BackofficeCapabilityAccessRejected
from domains.inventory_supplier_evidence import InventorySupplierEvidence
from models import Company, InventoryCostEvent, InventoryMovement, OperationIdempotency, ProductVariant

from . import repository as repo
from .authorization import require_identity, require_receipt_access
from .contracts import MANAGE, READ
from .errors import PurchaseReferenceError
from .models import PurchaseCostReference, PurchaseReferenceChange, PurchaseReferenceCommand
from .service import _same_currency, _snapshot
from .values import amount_value, currency_value, ratio_parts

OPERATION = "SUPPLIER_INBOUND_SET"


def receipt_hash_arguments(payload):
    """Leave every historical item/hash byte unchanged when selection is absent."""
    excluded = {"purchase_reference_selections"}
    if payload.supplier_id is None:
        excluded.add("supplier_id")
    selected = canonical_selections(payload.purchase_reference_selections)
    context = None
    if selected:
        context = {"purchase_reference_selections": [
            {"product_variant_id": variant_id, "uom_id": pair[0], "unit_cost": format(pair[1], ".6f")}
            for variant_id, pair in sorted(selected.items())
        ]}
    return {"exclude_fields": excluded, "context": context}


def canonical_selections(selections):
    selected = {}
    for item in selections or ():
        variant_id = int(item.product_variant_id)
        if variant_id in selected:
            raise PurchaseReferenceError("INBOUND_REFERENCE_SELECTION_DUPLICATE",
                                         "Select at most one reference cost per product.", status_code=422)
        selected[variant_id] = (int(item.uom_id), amount_value(item.unit_cost))
    return selected


def select_reference_pairs(actual_pairs, selections):
    """Resolve business ambiguity without using array, movement or event order."""
    selected = canonical_selections(selections)
    if not set(selected) <= set(actual_pairs):
        raise PurchaseReferenceError("INBOUND_REFERENCE_SELECTION_INVALID",
                                     "A selected product is absent from this receipt.", status_code=422)
    result = {}
    for variant_id, pairs in sorted(actual_pairs.items()):
        choice = selected.get(variant_id)
        if choice is None:
            if len(pairs) != 1:
                raise PurchaseReferenceError(
                    "INBOUND_REFERENCE_SELECTION_REQUIRED",
                    "Select the future reference cost from this product's actual receipt costs.",
                    status_code=422, context={
                        "product_variant_id": variant_id,
                        "options": [{"uom_id": uom, "unit_cost": format(cost, ".6f")}
                                    for uom, cost in sorted(pairs)],
                    },
                )
            choice = next(iter(pairs))  # exactly one distinct native pair
        if choice not in pairs:
            raise PurchaseReferenceError("INBOUND_REFERENCE_SELECTION_INVALID",
                                         "The selected cost/UOM is not an actual receipt cost.", status_code=422,
                                         context={"product_variant_id": variant_id})
        result[variant_id] = choice
    return result


@dataclass(frozen=True)
class _ReceiptWriter:
    db: object
    transaction: object
    operation: OperationIdempotency
    company_id: int
    location_id: int
    principal_id: int
    backoffice_user_id: int


def _require_pending(db, operation, company_id):
    if (not isinstance(operation, OperationIdempotency)
            or object_session(operation) is not db.sync_session
            or operation.company_id != company_id or operation.operation != "WAREHOUSE_INBOUND"
            or operation.completed_at is not None or operation.response_json is not None):
        raise PurchaseReferenceError("INBOUND_REFERENCE_NOT_PENDING",
                                     "Only a new pending receipt can update purchase references.")


async def begin_receipt_reference(db, *, access, operation, location_id):
    company_id = await require_receipt_access(db, access, location_id)
    _require_pending(db, operation, company_id)
    request_id = UUID(operation.request_id)
    # Same order as manual writes, including a request UUID reused across sources.
    await repo.acquire_operation_guard(db, company_id, request_id)
    await repo.acquire_writer_guard(db, company_id=company_id)
    if await repo.command_record(db, company_id, request_id) is not None:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_REPLAY_CONFLICT",
                                     "Request identity was already used by another reference command.")
    return _ReceiptWriter(db, db.get_transaction(), operation, company_id, location_id,
                          access.subject.principal_id, access.subject.backoffice_user_id)


async def write_receipt_references(db, *, access, writer, reference_id, movement_ids, selections):
    """Validate posted evidence, then append one audit revision per affected SKU."""
    company_id = await require_receipt_access(db, access, writer.location_id)
    if (writer.db is not db or writer.transaction is not db.get_transaction()
            or writer.company_id != company_id
            or writer.principal_id != access.subject.principal_id
            or writer.backoffice_user_id != access.subject.backoffice_user_id):
        raise PurchaseReferenceError("INBOUND_REFERENCE_TRANSACTION_INVALID",
                                     "Reference writer must remain in the receipt transaction.")
    _require_pending(db, writer.operation, company_id)
    request_id = UUID(writer.operation.request_id)
    ids = sorted(set(movement_ids))
    if not ids or len(ids) != len(movement_ids):
        raise PurchaseReferenceError("INBOUND_REFERENCE_PROVENANCE_INVALID", "Receipt movement evidence is incomplete.")
    await db.flush()  # supplier snapshots and cost events belong to this same transaction
    rows = list((await db.execute(
        select(InventoryCostEvent, InventoryMovement)
        .join(InventoryMovement, (
            (InventoryMovement.company_id == InventoryCostEvent.company_id)
            & (InventoryMovement.id == InventoryCostEvent.inventory_movement_id)
            & (InventoryMovement.product_variant_id == InventoryCostEvent.product_variant_id)
            & (InventoryMovement.batch_id == InventoryCostEvent.batch_id)
        ))
        .join(InventorySupplierEvidence, (
            (InventorySupplierEvidence.company_id == InventoryMovement.company_id)
            & (InventorySupplierEvidence.movement_id == InventoryMovement.id)
        ))
        .where(
            InventoryCostEvent.company_id == company_id,
            InventoryMovement.company_id == company_id,
            InventorySupplierEvidence.company_id == company_id,
            InventorySupplierEvidence.request_id == request_id,
            InventoryMovement.id.in_(ids),
            InventoryMovement.reference_type == "INBOUND_SUPPLIER",
            InventoryMovement.reference_id == reference_id,
            InventoryMovement.destination_location_id == writer.location_id,
            InventoryMovement.source_location_id.is_(None),
            InventoryMovement.movement_kind == "PHYSICAL",
            InventoryCostEvent.event_type == "PURCHASE_IN",
            InventoryCostEvent.cost_basis == "PURCHASE_ACTUAL",
        )
    )).all())
    if len(rows) != len(ids):
        raise PurchaseReferenceError("INBOUND_REFERENCE_PROVENANCE_INVALID",
                                     "Cost evidence does not belong to this exact posted receipt.")
    by_variant = {}
    for event, movement in rows:
        if event.input_quantity is None or event.input_quantity <= 0 or event.quantity != movement.quantity:
            raise PurchaseReferenceError("INBOUND_REFERENCE_PROVENANCE_INVALID", "Receipt cost quantity is invalid.")
        by_variant.setdefault(event.product_variant_id, []).append(event)
    pairs = {variant: {(event.input_uom_id, amount_value(event.input_unit_cost)) for event in events}
             for variant, events in by_variant.items()}
    choices = select_reference_pairs(pairs, selections)
    # Lock all Product parents before Company, never Company -> next Product.
    variants = {row.id: row for row in (await db.scalars(
        select(ProductVariant).where(ProductVariant.company_id == company_id,
                                     ProductVariant.id.in_(sorted(by_variant)))
        .order_by(ProductVariant.id).with_for_update(read=True)
        .execution_options(populate_existing=True)
    )).all()}
    if set(variants) != set(by_variant):
        raise PurchaseReferenceError("INBOUND_REFERENCE_PROVENANCE_INVALID", "Receipt products are unavailable.")
    currency = await db.scalar(select(Company.currency_code).where(
        Company.id == company_id).with_for_update(read=True))
    try:
        currency = currency_value(currency)
    except ValueError as exc:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_CURRENCY_INVALID", "Company currency is unavailable.") from exc
    now = datetime.now(timezone.utc)
    changes, response = [], {"references": []}
    for variant_id, pair in sorted(choices.items()):
        matching = [event for event in by_variant[variant_id]
                    if (event.input_uom_id, event.input_unit_cost) == pair]
        factors = {Fraction(event.quantity) / Fraction(event.input_quantity) for event in matching}
        if len(factors) != 1:
            raise PurchaseReferenceError("INBOUND_REFERENCE_PROVENANCE_INVALID", "Receipt UOM evidence is inconsistent.")
        numerator, denominator = ratio_parts(next(iter(factors)))
        # Every matching event supports the same explicitly chosen value. The
        # smallest immutable ID is only an audit anchor, never a cost winner.
        event_ids = sorted(event.id for event in matching)
        row = await repo.current_reference(db, company_id, variant_id, lock=True)
        before = _snapshot(row) if row is not None else None
        if row is not None:
            _same_currency(row.currency_code, currency)
        values = dict(
            amount=pair[1], purchase_uom_id=pair[0], base_uom_id=variants[variant_id].base_uom_id,
            factor_numerator=numerator, factor_denominator=denominator, currency_code=currency,
            source="SUPPLIER_INBOUND", source_cost_event_id=event_ids[0],
            provenance={"operation": OPERATION, "request_id": str(request_id),
                        "receipt_reference_id": reference_id, "location_id": writer.location_id,
                        "cost_event_ids": event_ids,
                        "selection": "EXPLICIT" if len(pairs[variant_id]) > 1 else "SINGLE_DISTINCT_PAIR"},
            changed_at=now,
        )
        if row is None:
            row = PurchaseCostReference(company_id=company_id, product_variant_id=variant_id, revision=1, **values)
            db.add(row)
        else:
            row.revision += 1
            for key, value in values.items():
                setattr(row, key, value)
        response["references"].append(_snapshot(row))
        changes.append(PurchaseReferenceChange(
            company_id=company_id, product_variant_id=variant_id, revision=row.revision,
            request_id=request_id, before_snapshot=before, **values,
        ))
    db.add(PurchaseReferenceCommand(
        company_id=company_id, request_id=request_id, operation=OPERATION,
        actor_principal_id=writer.principal_id, actor_backoffice_user_id=writer.backoffice_user_id,
        request_hash=writer.operation.request_hash, response_json=deepcopy(response), created_at=now,
    ))
    await db.flush()
    db.add_all(changes)
    await db.flush()
    return response


async def inbound_reference_prefill(db, *, access, variant_ids):
    """Optional native reference suggestions; actual receipt input stays required.

    Inbound authority alone does not reveal the company-wide reference. Existing
    company READ/MANAGE is required; clients without it receive no suggestions.
    No locks or writes are needed for these advisory, potentially stale defaults.
    """
    company_id = await require_identity(db, access)
    try:
        await access.require("inbound.create", any_location=True)
        await access.require((READ, MANAGE))
    except BackofficeCapabilityAccessRejected:
        return {}
    rows = (await db.execute(
        select(PurchaseCostReference, Company.currency_code)
        .join(Company, Company.id == PurchaseCostReference.company_id)
        .where(PurchaseCostReference.company_id == company_id,
               PurchaseCostReference.product_variant_id.in_(sorted(set(variant_ids))))
    )).all()
    result = {}
    for row, currency in rows:
        _same_currency(row.currency_code, currency)
        result[row.product_variant_id] = _snapshot(row)
    return result
