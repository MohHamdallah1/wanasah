"""Purchase reference application commands; caller owns commit/rollback.

Manual reference writes never invoke inventory mutation, financial costing or
Pricing. Receipt mutation/selection is intentionally not implemented here.
"""
from copy import deepcopy
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import json

from domains.uom_authority import UomAuthorityError, load_variant_uom_authorities

from .authorization import require_access
from .contracts import MANAGE, OPERATION, READ, ManualReferenceWrite
from .errors import PurchaseReferenceError
from .models import PurchaseCostReference, PurchaseReferenceChange, PurchaseReferenceCommand
from . import repository as repo
from .values import convert_exact, currency_value, ratio_parts


def _snapshot(row):
    return {
        "product_variant_id": row.product_variant_id,
        "amount": format(row.amount, ".6f"),
        "purchase_uom_id": row.purchase_uom_id,
        "base_uom_id": row.base_uom_id,
        "factor_numerator": format(row.factor_numerator, "f"),
        "factor_denominator": format(row.factor_denominator, "f"),
        "currency_code": row.currency_code,
        "revision": row.revision,
        "source": row.source,
        "source_cost_event_id": row.source_cost_event_id,
        "provenance": deepcopy(row.provenance),
        "changed_at": row.changed_at.isoformat(),
    }


def _request_hash(variant_id, payload):
    body = payload.model_dump(mode="json", exclude={"request_id"})
    # Canonical money: "2", "2.0" and "2.000000" are the same command input.
    body["amount"] = format(payload.amount, ".6f")
    body["product_variant_id"] = variant_id
    body["operation"] = OPERATION
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _same_currency(stored, current):
    try:
        current = currency_value(current)
    except ValueError as exc:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_CURRENCY_INVALID", "Company currency is unavailable.") from exc
    if stored != current:
        raise PurchaseReferenceError(
            "PURCHASE_REFERENCE_CURRENCY_MISMATCH",
            "Purchase reference and company currency differ; no conversion was applied.",
            context={"reference_currency": stored, "company_currency": current},
        )
    return current


async def _authority(db, company_id, variant_id):
    try:
        return (await load_variant_uom_authorities(
            db, company_id=company_id, variant_ids=[variant_id],
        ))[variant_id]
    except UomAuthorityError as exc:
        raise PurchaseReferenceError(exc.code, exc.message, context=exc.context) from exc


async def read_reference(db, *, access, product_variant_id, quote_uom_id=None):
    company_id = await require_access(db, access, (READ, MANAGE))
    variant, currency = await repo.variant_and_currency(db, company_id, product_variant_id, lock=True)
    row = await repo.current_reference(db, company_id, product_variant_id)
    if row is None:
        return {"reference": None}
    _same_currency(row.currency_code, currency)
    response = _snapshot(row)
    codes = await repo.uom_codes(db, [row.purchase_uom_id, row.base_uom_id])
    response["purchase_uom_code"] = codes[row.purchase_uom_id]
    response["base_uom_code"] = codes[row.base_uom_id]
    if quote_uom_id is not None:
        if variant.base_uom_id != row.base_uom_id:
            raise PurchaseReferenceError("PURCHASE_REFERENCE_UOM_CHANGED", "Product base UOM changed; save an explicit new reference.")
        authority = await _authority(db, company_id, product_variant_id)
        try:
            target = authority.factor_to_base(quote_uom_id)
        except UomAuthorityError as exc:
            raise PurchaseReferenceError(exc.code, exc.message, context=exc.context) from exc
        quoted = convert_exact(
            row.amount,
            source_factor=Fraction(row.factor_numerator) / Fraction(row.factor_denominator),
            target_factor=target,
        )
        response["quote"] = {"amount": format(quoted, ".6f"), "purchase_uom_id": quote_uom_id,
                             "currency_code": row.currency_code}
    return {"reference": response}


async def write_manual_reference(db, *, access, product_variant_id, payload):
    """One reference-only command, safe to compose in the caller transaction.

    Call before other business locks. Reference revision is independent of the
    Catalog version. Replay returns frozen response without reacquiring writer
    gate or reapplying the previous reference.
    """
    if not isinstance(payload, ManualReferenceWrite):
        raise TypeError("ManualReferenceWrite is required")
    if type(product_variant_id) is not int or product_variant_id <= 0:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_PRODUCT_INVALID", "Product identifier is invalid.", status_code=422)
    payload = ManualReferenceWrite.model_validate(payload.model_dump(mode="python"))
    company_id = await require_access(db, access, MANAGE)
    digest = _request_hash(product_variant_id, payload)
    await repo.acquire_operation_guard(db, company_id, payload.request_id)
    prior = await repo.command_record(db, company_id, payload.request_id)
    if prior is not None:
        if (prior.request_hash != digest or prior.actor_principal_id != access.subject.principal_id
                or prior.actor_backoffice_user_id != access.subject.backoffice_user_id):
            raise PurchaseReferenceError("PURCHASE_REFERENCE_REPLAY_CONFLICT", "Request identity was reused with different input or actor.")
        return deepcopy(prior.response_json)

    await repo.acquire_writer_guard(db, company_id=company_id)
    variant, currency = await repo.variant_and_currency(db, company_id, product_variant_id, lock=True)
    if variant.lifecycle_status == "ARCHIVED":
        raise PurchaseReferenceError("PURCHASE_REFERENCE_PRODUCT_ARCHIVED", "Archived products cannot receive a new reference.")
    _same_currency(payload.currency_code, currency)
    row = await repo.current_reference(db, company_id, product_variant_id, lock=True)
    revision = row.revision if row is not None else 0
    if revision != payload.expected_revision:
        raise PurchaseReferenceError("PURCHASE_REFERENCE_REVISION_CONFLICT", "Purchase reference changed.",
                                     context={"current_revision": revision})
    if row is not None:
        _same_currency(row.currency_code, currency)
    authority = await _authority(db, company_id, product_variant_id)
    try:
        numerator, denominator = ratio_parts(authority.factor_to_base(payload.purchase_uom_id))
    except UomAuthorityError as exc:
        raise PurchaseReferenceError(exc.code, exc.message, context=exc.context) from exc
    before = _snapshot(row) if row is not None else None
    now = datetime.now(timezone.utc)
    values = dict(
        amount=payload.amount, purchase_uom_id=payload.purchase_uom_id,
        base_uom_id=authority.base_uom_id, factor_numerator=numerator,
        factor_denominator=denominator, currency_code=payload.currency_code,
        source="MANUAL_PRODUCT", source_cost_event_id=None,
        provenance={"operation": OPERATION, "request_id": str(payload.request_id), "reason": payload.reason},
        changed_at=now,
    )
    if row is None:
        row = PurchaseCostReference(company_id=company_id, product_variant_id=product_variant_id,
                                    revision=1, **values)
        db.add(row)
    else:
        row.revision += 1
        for key, value in values.items():
            setattr(row, key, value)
    response = {"reference": _snapshot(row)}
    db.add(PurchaseReferenceCommand(
        company_id=company_id, request_id=payload.request_id, operation=OPERATION,
        actor_principal_id=access.subject.principal_id,
        actor_backoffice_user_id=access.subject.backoffice_user_id,
        request_hash=digest, response_json=deepcopy(response), created_at=now,
    ))
    # Flush parent command before immutable change. Current->history FK is
    # deferred so neither first insertion nor revision update can commit unaudited.
    await db.flush()
    db.add(PurchaseReferenceChange(
        company_id=company_id, product_variant_id=product_variant_id,
        revision=row.revision, request_id=payload.request_id,
        before_snapshot=before, **values,
    ))
    await db.flush()
    return response
