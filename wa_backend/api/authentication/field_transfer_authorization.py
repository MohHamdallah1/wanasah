"""Authorize all submitted FIELD transfer decisions before the handler can mutate."""
from fastapi import Depends

from domains.authorization.field_access import FieldCapabilityAccess
from schemas import BatchTransferResponseRequest, TransferResponseRequest
from .field_authorization import (
    get_current_field_capability_access,
    require_field_capabilities,
)

_DECISION_CAPABILITIES = {
    "accepted": "transfer.receive",
    "rejected": "transfer.reject",
}


async def require_transfer_decision_capability(
    payload: TransferResponseRequest,
    access: FieldCapabilityAccess = Depends(get_current_field_capability_access),
):
    return await require_field_capabilities(
        (_DECISION_CAPABILITIES[payload.response],)
    )(access=access)


async def require_transfer_batch_capabilities(
    payload: BatchTransferResponseRequest,
    access: FieldCapabilityAccess = Depends(get_current_field_capability_access),
):
    # Validate the entire decision set before entering atomic batch processing.
    codes = tuple(sorted({_DECISION_CAPABILITIES[item.status] for item in payload.transfers}))
    return await require_field_capabilities(codes)(access=access)
