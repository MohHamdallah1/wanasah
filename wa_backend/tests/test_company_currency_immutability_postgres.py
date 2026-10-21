"""Real-PostgreSQL V1 company functional-currency immutability acceptance."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from tests.purchase_reference_pg_support import pg  # noqa: F401


@pytest.mark.asyncio
async def test_currency_provisioning_is_immutable_but_other_company_edits_survive(pg):
    company_id = pg.a.company_id
    async with AsyncSession(pg.admin, expire_on_commit=False) as db:
        before = (await db.execute(text(
            "SELECT name, currency_code FROM companies WHERE id = :id"
        ), {"id": company_id})).one()
        assert before.currency_code == "JOD"

        # Ordinary non-currency edits and idempotent currency values remain legal.
        await db.execute(text(
            "UPDATE companies SET name = :name, currency_code = :currency WHERE id = :id"
        ), {"name": "Allowed company rename", "currency": "JOD", "id": company_id})
        await db.commit()

    async with AsyncSession(pg.admin, expire_on_commit=False) as db:
        with pytest.raises(DBAPIError, match="COMPANY_CURRENCY_IMMUTABLE"):
            await db.execute(text(
                "UPDATE companies SET currency_code='USD' WHERE id=:id"
            ), {"id": company_id})
        await db.rollback()

    async with AsyncSession(pg.admin, expire_on_commit=False) as db:
        row = (await db.execute(text(
            "SELECT name, currency_code FROM companies WHERE id=:id"
        ), {"id": company_id})).one()
        assert row.name == "Allowed company rename"
        assert row.currency_code == "JOD"

        # The rejection is database-wide, including privileged migration role.
        trigger_present = await db.scalar(text("""
            SELECT count(*) FROM pg_trigger
            WHERE tgname='trg_companies_currency_immutable_v1'
              AND NOT tgisinternal
        """))
        assert trigger_present == 1


@pytest.mark.asyncio
async def test_both_tenants_reject_direct_currency_rewriting(pg):
    async with AsyncSession(pg.admin, expire_on_commit=False) as db:
        for tenant in (pg.a, pg.b):
            with pytest.raises(DBAPIError, match="COMPANY_CURRENCY_IMMUTABLE"):
                await db.execute(text(
                    "UPDATE companies SET currency_code='QAR' WHERE id=:id"
                ), {"id": tenant.company_id})
            await db.rollback()
        values = (await db.execute(text(
            "SELECT currency_code FROM companies WHERE id IN (:a,:b)"
        ), {"a": pg.a.company_id, "b": pg.b.company_id})).all()
        assert len(values) == 2
        assert {value[0] for value in values} == {"JOD"}
