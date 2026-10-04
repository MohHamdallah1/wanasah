import os
from types import SimpleNamespace

os.environ.setdefault("SECRET_KEY", "TransitProvisionGuardTestSecretKeyAa1234567890")
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://test:test@localhost/test")

import pytest
from sqlalchemy.dialects import postgresql

from services import ensure_system_transit_location


def _location():
    return SimpleNamespace(
        is_system_managed=True,
        location_type="IN_TRANSIT",
        is_active=True,
        branch_id=None,
        vehicle_id=None,
    )


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _Session:
    def __init__(self, results):
        self.results = list(results)
        self.sql = []
        self.added = []
        self.flushes = 0

    async def execute(self, statement, params=None):
        self.sql.append(
            str(statement.compile(dialect=postgresql.dialect()))
        )
        if self.results:
            return _ScalarResult(self.results.pop(0))
        return _ScalarResult(None)

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        self.flushes += 1


@pytest.mark.asyncio
async def test_existing_transit_location_does_not_take_company_provision_guard():
    location = _location()
    db = _Session([location])
    result = await ensure_system_transit_location(db, 7)

    assert result is location
    assert len(db.sql) == 1
    assert "pg_advisory_xact_lock" not in db.sql[0]
    assert db.added == []
    assert db.flushes == 0


@pytest.mark.asyncio
async def test_missing_location_keeps_guard_and_rechecks_before_create():
    location = _location()
    db = _Session([None, None, location])
    result = await ensure_system_transit_location(db, 7)

    assert result is location
    assert len(db.sql) == 3
    assert "pg_advisory_xact_lock" in db.sql[1]
    assert db.added == []
    assert db.flushes == 0
