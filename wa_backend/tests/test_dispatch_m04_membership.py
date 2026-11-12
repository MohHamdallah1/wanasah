"""M04 all-vehicle S1 read: exactly bounded, signed and all-or-nothing scope.

These unit cases exercise the real SQL-producing read model with controlled
query results. Real FORCE RLS and Bearer are owned by the M04 PG16 gates.
"""
from datetime import datetime, timezone
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import true

from models import InventoryLocation, StocktakeSession, Vehicle
from domains.representative_settlement_multi_vehicle import read_model
from domains.representative_settlement_multi_vehicle.contracts import CustodyRejected
from domains.representative_settlement_multi_vehicle.models import (
    VehicleCustodyCheckpoint, VehicleCustodyCheckpointEpoch,
)
from tests.test_dispatch_m04_domain import vehicles


class Result:
    def __init__(self, rows):
        self.rows = rows

    def all(self):
        return self.rows


class BoundedReadDB:
    def __init__(self, allowed=(110, 120), checkpoints=(), links=(), recons=()):
        self.allowed = allowed
        self.checkpoints = checkpoints
        self.links = links
        self.recons = recons
        self.queries = []

    async def scalars(self, query):
        self.queries.append(query)
        ent = query.column_descriptions[0]["entity"]
        if ent is InventoryLocation:
            return Result(list(self.allowed))
        if ent is VehicleCustodyCheckpoint:
            return Result(list(self.checkpoints))
        raise AssertionError(f"Unexpected scalar source {ent}")

    async def execute(self, query):
        self.queries.append(query)
        ent = query.column_descriptions[0]["entity"]
        if ent is Vehicle:
            return Result([(10, "A"), (20, "B")])
        if ent is VehicleCustodyCheckpointEpoch:
            return Result(list(self.links))
        if ent is StocktakeSession:
            return Result(list(self.recons))
        raise AssertionError(f"Unexpected execute source {ent}")


@pytest.fixture
def ready(monkeypatch):
    work = NS(id=71, is_settled=False, end_time=datetime.now(timezone.utc))
    monkeypatch.setattr(read_model, "session_responsibilities",
                        AsyncMock(return_value=(work, vehicles())))
    monkeypatch.setattr(read_model, "require_m04_schema", AsyncMock())
    monkeypatch.setattr(
        "domains.representative_settlement_multi_vehicle.application.require_capability",
        AsyncMock(),
    )
    access = NS(company_id=1, location_filter=lambda *_args, **_kw: true())
    return work, access


@pytest.mark.asyncio
async def test_m04_read_returns_both_exact_s1_cars_without_stock_or_historic_last_route(ready):
    _, access = ready
    db = BoundedReadDB()
    result = await read_model.read_session_vehicle_membership(
        db, access=access, session_id=71,
    )
    assert result["work_session_id"] == 71
    assert result["all_vehicle_counts_signed"] is False
    assert result["financially_settled"] is False
    assert [(row["vehicle_id"], row["period_ids"], row["checkpoint_status"])
            for row in result["vehicles"]] == [
        (10, [1, 3], "NOT_COUNTED"),
        (20, [2], "NOT_COUNTED"),
    ]
    assert not any("quantity" in str(row) or "balance" in str(row)
                   for row in result["vehicles"])
    assert len(db.queries) == 5  # scoped locations, plates, checkpoints, links, recon


@pytest.mark.asyncio
async def test_m04_read_denies_partial_vehicle_location_scope_before_names_or_counts(ready):
    _, access = ready
    db = BoundedReadDB(allowed=(110,))
    with pytest.raises(CustodyRejected, match="AUTHORIZATION_DENIED") as denied:
        await read_model.read_session_vehicle_membership(
            db, access=access, session_id=71,
        )
    assert denied.value.status == 403
    assert len(db.queries) == 1  # no plate or checkpoint partial disclosure


@pytest.mark.asyncio
async def test_m04_read_rejects_signed_but_wrong_context_checkpoint(ready):
    _, access = ready
    db = BoundedReadDB(checkpoints=[NS(
        id=912, vehicle_location_id=110, vehicle_id=10,
        context_digest="0" * 64, signed_at=datetime.now(timezone.utc),
        signed_by_principal_id=901, context_manifest={
            "period_ids": [1, 3], "epoch_ids": [1, 3],
        }, mode="COUNT_IN_PLACE", stocktake_session_id=None,
    )], links=[(912, 1), (912, 3)])
    with pytest.raises(CustodyRejected, match="STALE_OR_UNSIGNED"):
        await read_model.read_session_vehicle_membership(
            db, access=access, session_id=71,
        )
