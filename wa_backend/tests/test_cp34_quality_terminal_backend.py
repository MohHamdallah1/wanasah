"""Quality confirmation must use the canonical credential root."""
from types import SimpleNamespace as NS

import bcrypt
import pytest
from sqlalchemy.dialects import postgresql

from domains.inventory_quality_confirmation import verify_quality_confirmation


class DB:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def scalar(self, statement):
        self.statements.append(statement)
        return self.row


@pytest.mark.asyncio
async def test_confirmation_queries_exact_canonical_company_principal_profile_and_current_credential():
    hashed = bcrypt.hashpw(b"CurrentCanonical123", bcrypt.gensalt(rounds=4)).decode()
    db = DB(NS(password_hash=hashed))
    access = NS(company_id=77, subject=NS(principal_id=101, backoffice_user_id=202))
    assert await verify_quality_confirmation(db, access, "CurrentCanonical123")
    assert not await verify_quality_confirmation(db, access, "OldDriverPassword123")
    sql = str(db.statements[0].compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    for expected in ("company_principals.company_id = 77", "company_principals.id = 101",
                     "backoffice_users.id = 202", "company_principals.is_active IS true",
                     "company_principals.principal_type = 'BACKOFFICE'"):
        assert expected in sql
    assert "drivers" not in sql


@pytest.mark.asyncio
async def test_missing_canonical_identity_cannot_confirm_using_legacy_credentials():
    access = NS(company_id=77, subject=NS(principal_id=101, backoffice_user_id=202))
    assert not await verify_quality_confirmation(DB(None), access, "DriverPassword123")
