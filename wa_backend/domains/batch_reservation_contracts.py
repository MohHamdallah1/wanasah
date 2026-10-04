"""Read-only reservation explanation; IDs and action hints confer no authority."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.functional_validators import BeforeValidator
from quantity import canonical_quantity, parse_quantity

OWNER_PREVIEW_LIMIT = 20


def _canonical_quantity(value):
    return canonical_quantity(parse_quantity(value, allow_zero=True))


CanonicalQuantity = Annotated[str, BeforeValidator(_canonical_quantity)]


class ReservationOwner(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    owner_type: Literal["DISPATCH_HANDSHAKE"] = "DISPATCH_HANDSHAKE"
    module: Literal["DISPATCH"] = "DISPATCH"
    transfer_id: int = Field(gt=0)
    reference_number: str = Field(min_length=1, max_length=100)
    transfer_purpose: Literal["ROUTE_LOAD", "ROUTE_RETURN"]
    work_session_id: int = Field(gt=0)
    route_id: int = Field(gt=0)
    expected_receiver_id: int = Field(gt=0)
    created_by: int = Field(gt=0)
    quantity: CanonicalQuantity
    operation_status: Literal["PENDING"] = "PENDING"
    navigation_target: Literal["DISPATCH_ROUTE_TRANSFERS"] = "DISPATCH_ROUTE_TRANSFERS"
    # Hint at this read snapshot. Dispatch rechecks permission/status, requires a
    # reason and stable request_id, and remains the only cancellation authority.
    action: Literal["FORCE_CANCEL_HANDSHAKE"] | None


class ReservationEvidence(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    coverage: Literal["NONE", "COMPLETE", "PARTIAL", "UNRESOLVED"]
    reason: Literal[
        "OWNER_EVIDENCE_UNAVAILABLE", "OWNER_EVIDENCE_MISMATCH", "OWNER_PREVIEW_LIMIT",
    ] | None = None
    owners: list[ReservationOwner] = Field(default_factory=list, max_length=OWNER_PREVIEW_LIMIT)
    # Reserved quantity not represented in this preview: hidden/unsupported
    # evidence or omitted owners. Never silently label that remainder resolved.
    unattributed_quantity: CanonicalQuantity
    owners_truncated: bool = False
