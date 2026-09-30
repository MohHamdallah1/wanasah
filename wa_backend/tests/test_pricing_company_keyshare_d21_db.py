"""D2.1 pricing company-lock compatibility on real local PostgreSQL.

Opt-in, tenant-scoped, SELECT-only transactions, all rolled back.
This is a lock contract gate, not a full invoice or Route Launch concurrency gate.
"""
from __future__ import annotations

import ipaddress
import os
import unittest

from sqlalchemy import select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import DBAPIError

from context import tenant_context
from database import AsyncSessionLocal, engine
from domains.pricing.core import acquire_pricing_company_lock
from models import Company


@unittest.skipUnless(
    os.environ.get("WANASAH_D21_COMPANY_LOCK_DB_GATE") == "1",
    "Requires explicit local-development PostgreSQL opt-in",
)
class CompanyPricingLockCompatibilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.sessions = []

    async def asyncTearDown(self):
        for session in reversed(self.sessions):
            try:
                await session.rollback()
            finally:
                await session.close()
        await engine.dispose()

    async def _open(self, company_id: int):
        token = tenant_context.set(company_id)
        try:
            session = AsyncSessionLocal()
            self.sessions.append(session)
            await session.execute(
                text("SELECT set_config('app.current_tenant', :id, false)"),
                {"id": str(company_id)},
            )
            db, host = (
                await session.execute(
                    text("SELECT current_database(), inet_server_addr()::text")
                )
            ).one()
            self.assertEqual(db, "velotrack_db")
            self.assertIsNotNone(host)
            self.assertTrue(ipaddress.ip_address(host.split("/", 1)[0]).is_loopback)
            await session.execute(text("SET LOCAL lock_timeout = '150ms'"))
            await session.execute(text("SET LOCAL statement_timeout = '1000ms'"))
            return session
        finally:
            tenant_context.reset(token)

    async def test_readers_pass_but_pricing_writers_still_serialize(self):
        compiled = str(
            select(Company.id)
            .where(Company.id == 38)
            .with_for_update(key_share=True, read=False)
            .compile(
                dialect=postgresql.dialect(),
                compile_kwargs={"literal_binds": True},
            )
        )
        self.assertIn("FOR NO KEY UPDATE", compiled)

        holder = await self._open(38)
        await acquire_pricing_company_lock(holder, 38)

        same_company_reader = await self._open(38)
        self.assertEqual(
            await same_company_reader.scalar(
                text("SELECT id FROM companies WHERE id=38 FOR KEY SHARE")
            ),
            38,
        )
        await same_company_reader.rollback()

        other_company_reader = await self._open(2)
        self.assertEqual(
            await other_company_reader.scalar(
                text("SELECT id FROM companies WHERE id=2 FOR KEY SHARE")
            ),
            2,
        )
        await other_company_reader.rollback()

        competing_pricing_writer = await self._open(38)
        with self.assertRaises(DBAPIError) as blocked:
            await acquire_pricing_company_lock(competing_pricing_writer, 38)
        self.assertEqual(
            getattr(blocked.exception.orig, "sqlstate", None), "55P03",
        )
        await competing_pricing_writer.rollback()

        await holder.rollback()
        restored_pricing_writer = await self._open(38)
        await acquire_pricing_company_lock(restored_pricing_writer, 38)