"""HTTP error adaptation for the existing visit engine's bounded additions."""
import hashlib
import json

from fastapi import HTTPException
from services import InventoryMutationError, begin_idempotent_operation, complete_idempotent_operation

from domains.field_operations.contracts import FieldContractError
from domains.field_operations.context import pending_shop_commercial_state
from domains.field_operations.invoice import invoice_from_calculation
from domains.field_operations.returns import (
    canonicalize_returns, revalidate_batch_metadata, revalidate_provenance,
)
from domains.pricing.core import PricingError
from domains.sales_calculation.core import CalculationError
from domains.vehicles import VehicleError

_ERRORS = (FieldContractError, PricingError, CalculationError, VehicleError)


def _http(error):
    return HTTPException(
        status_code=error.status_code,
        detail={"code": error.code, "message": error.message, "context": error.context},
    )


async def run_field_query(operation, *args, **kwargs):
    try:
        return await operation(*args, **kwargs)
    except _ERRORS as error:
        raise _http(error) from None


def canonicalize_visit_returns(payload, *, context, driver_id, visit_id):
    try:
        return canonicalize_returns(payload, context=context, driver_id=driver_id, visit_id=visit_id)
    except FieldContractError as error:
        raise _http(error) from None


async def revalidate_return_provenance(db, **kwargs):
    return await run_field_query(revalidate_provenance, db, **kwargs)


async def revalidate_return_batch_metadata(db, **kwargs):
    return await run_field_query(revalidate_batch_metadata, db, **kwargs)


async def begin_field_shop_command(db, *, payload, company_id, driver_id):
    if payload.request_id is None:
        return None, None  # Existing clients retain their compatibility contract.
    request_hash = hashlib.sha256(json.dumps(
        payload.model_dump(mode="json", exclude={"request_id"}),
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    try:
        return await begin_idempotent_operation(
            db, company_id=company_id, actor_id=driver_id, operation="FIELD_CREATE_SHOP",
            request_id=str(payload.request_id), request_hash=request_hash,
        )
    except InventoryMutationError as error:
        await db.rollback()
        raise HTTPException(status_code=409, detail={
            "code": "FIELD_SHOP_IDEMPOTENCY_CONFLICT", "message": str(error), "context": {},
        }) from None


def complete_field_shop_command(record, response):
    if record is not None:
        complete_idempotent_operation(record, response)
