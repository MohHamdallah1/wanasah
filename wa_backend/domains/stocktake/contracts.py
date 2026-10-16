"""Stocktake mutation contracts with durable command identity.

The legacy request payloads remain the business contract.  CP9 adds only a
request_id so ambiguous retries can be replayed safely without expanding the
shared schemas module owned by other checkpoints.
"""
from uuid import UUID, uuid4

from pydantic import Field

from schemas import (
    StocktakeApprovalRequest,
    StocktakeCancelRequest,
    StocktakeRecountRequest,
    UnifiedStocktakeCountRequest,
    UnifiedStocktakeStartRequest,
)


class StocktakeStartCommand(UnifiedStocktakeStartRequest):
    request_id: UUID = Field(default_factory=uuid4)


class StocktakeCountCommand(UnifiedStocktakeCountRequest):
    request_id: UUID = Field(default_factory=uuid4)


class StocktakeApprovalCommand(StocktakeApprovalRequest):
    request_id: UUID = Field(default_factory=uuid4)


class StocktakeRecountCommand(StocktakeRecountRequest):
    request_id: UUID = Field(default_factory=uuid4)


class StocktakeCancelCommand(StocktakeCancelRequest):
    request_id: UUID = Field(default_factory=uuid4)
