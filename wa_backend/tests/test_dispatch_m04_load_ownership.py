"""Canonical Vehicle Load ownership, before the approved foreign-file hook."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.dialects import postgresql

from domains.representative_settlement_multi_vehicle.contracts import CustodyRejected
from domains.representative_settlement_multi_vehicle.load_ownership import canonical_load_context


def result(rows):
    return NS(all=lambda: rows, scalars=lambda: NS(all=lambda: rows))


@pytest.mark.asyncio
async def test_ended_current_canonical_day_blocks_direct_load_and_query_compiles():
    db = NS(execute=AsyncMock(return_value=result([NS(id=71, end_time=object())])))
    assert await canonical_load_context(db, company_id=1, vehicle_id=20) == {
        "route_id": None, "session_id": 71, "ended": True}
    sql = str(db.execute.await_args.args[0].compile(dialect=postgresql.dialect()))
    assert "FROM dispatch_route_execution_periods JOIN work_sessions" in sql
    assert "work_sessions.id = dispatch_route_execution_periods.work_session_id" in sql


@pytest.mark.asyncio
async def test_active_day_uses_exact_active_period_not_legacy_last_route():
    db = NS(execute=AsyncMock(side_effect=[result([NS(id=71, end_time=None)]), result([123])]))
    assert await canonical_load_context(db, company_id=1, vehicle_id=20) == {
        "route_id": 123, "session_id": 71, "ended": False}


@pytest.mark.asyncio
@pytest.mark.parametrize("active", [[], [123, 456]])
async def test_ambiguous_active_period_fails_closed(active):
    db = NS(execute=AsyncMock(side_effect=[result([NS(id=71, end_time=None)]), result(active)]))
    with pytest.raises(CustodyRejected, match="VEHICLE_CUSTODY_REVIEW_REQUIRED"):
        await canonical_load_context(db, company_id=1, vehicle_id=20)


@pytest.mark.asyncio
async def test_multiple_unclosed_current_sessions_fail_closed():
    db = NS(execute=AsyncMock(return_value=result([NS(id=71, end_time=1), NS(id=72, end_time=1)])))
    with pytest.raises(CustodyRejected, match="VEHICLE_CUSTODY_REVIEW_REQUIRED"):
        await canonical_load_context(db, company_id=1, vehicle_id=20)


@pytest.mark.asyncio
async def test_later_custodian_allowed_only_when_prior_inventory_is_signed():
    db = NS(execute=AsyncMock(return_value=result([])), scalar=AsyncMock(return_value=71))
    with pytest.raises(CustodyRejected, match="VEHICLE_CUSTODY_REVIEW_REQUIRED"):
        await canonical_load_context(db, company_id=1, vehicle_id=20)
    db.scalar.return_value = None
    assert await canonical_load_context(db, company_id=1, vehicle_id=20) is None
