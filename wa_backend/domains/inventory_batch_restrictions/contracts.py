"""Presentation evidence only; never a second sellability/lifecycle authority."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

RestrictedDisposition = Literal["QUARANTINED", "BLOCKED", "RECALLED"]


class ReadContract(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")


class DispositionCounts(ReadContract):
    QUARANTINED: int = Field(default=0, ge=0)
    BLOCKED: int = Field(default=0, ge=0)
    RECALLED: int = Field(default=0, ge=0)


class CurrentDispositionReason(ReadContract):
    selection: Literal["LOWEST_BATCH_ID_WITH_CURRENT_REASON"] = "LOWEST_BATCH_ID_WITH_CURRENT_REASON"
    batch_id: int = Field(gt=0)
    disposition: RestrictedDisposition
    disposition_revision: int = Field(gt=0)
    disposition_reason: str = Field(min_length=1, max_length=2000)


class BatchRestrictionSummary(ReadContract):
    schema_version: Literal[1] = 1
    scope: Literal["COMPANY"] = "COMPANY"
    affected_batch_count: int = Field(ge=0)
    # SUM can exceed a single NUMERIC(20,6) balance. Keep exact decimal strings.
    affected_on_hand_quantity: str = Field(pattern=r"^[0-9]+\.[0-9]{6}$")
    quantity_unit: Literal["BASE_STOCK_UNIT"] = "BASE_STOCK_UNIT"
    counts_by_disposition: DispositionCounts
    representative_reason: CurrentDispositionReason | None = None

    @model_validator(mode="after")
    def coherent_counts(self):
        if self.affected_batch_count != sum(self.counts_by_disposition.model_dump().values()):
            raise ValueError("Disposition counts must sum to affected_batch_count.")
        if self.representative_reason is not None:
            count = getattr(self.counts_by_disposition, self.representative_reason.disposition)
            if count == 0:
                raise ValueError("A representative reason must belong to an affected batch.")
        return self
