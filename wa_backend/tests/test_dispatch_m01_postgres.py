"""M01: isolated PG16 migration/backfill/RLS/rollback gates.

To run the real database gate, explicitly set RUN_M01_PG16=1 and provide both
DATABASE_URL (restricted runtime) and DATABASE_URL_MIGRATION (admin). The test
creates and drops only its own random database; never touches the named source.
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path
import unittest
from uuid import uuid4

import asyncpg
from alembic import command
from alembic.config import Config
from sqlalchemy.engine import make_url

BACKEND = Path(__file__).resolve().parents[1]


async def _connect(url, database):
    u = make_url(url)
    return await asyncpg.connect(
        user=u.username, password=u.password, host=u.host, port=u.port,
        database=database, command_timeout=120,
    )


async def _create_db(migration_url, database):
    conn = await _connect(migration_url, "postgres")
    try:
        version = int(await conn.fetchval("SHOW server_version_num"))
        if not 160000 <= version < 170000:
            raise AssertionError(f"Requires PG16; found server_version_num={version}")
        await conn.execute(f'CREATE DATABASE "{database}" TEMPLATE template0')
        return version
    finally:
        await conn.close()


async def _drop_db(migration_url, database):
    conn = await _connect(migration_url, "postgres")
    try:
        await conn.execute(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    finally:
        await conn.close()


async def _fixtures(migration_url, database):
    conn = await _connect(migration_url, database)
    try:
        a, b = [], []
        for i, dest in ((1, a), (2, b)):
            cid = await conn.fetchval(
                """INSERT INTO companies
                   (name, company_code, is_active, subscription_status,
                    currency_code, timezone, created_at)
                   VALUES ($1,$2,true,'active','QAR','Asia/Qatar',NOW())
                   RETURNING id""", f"M01 Tenant {i}", f"m01_{i}_{uuid4().hex[:8]}")
            driver = await conn.fetchval(
                """INSERT INTO drivers
                   (company_id,username,password_hash,full_name,is_active,created_at)
                   VALUES ($1,$2,'unused','M01 rep',true,NOW()) RETURNING id""",
                cid, f"m01_driver_{i}")
            vehicle = await conn.fetchval(
                """INSERT INTO vehicles
                   (company_id,plate_number,current_mileage,maintenance_status,is_active)
                   VALUES ($1,$2,0,'Active',true) RETURNING id""",
                cid, f"M01-{i}-{uuid4().hex[:4]}")
            zone = await conn.fetchval(
                """INSERT INTO zones(company_id,name,is_active)
                   VALUES ($1,$2,true) RETURNING id""", cid, f"M01 zone {i}")
            location = await conn.fetchval(
                """INSERT INTO inventory_locations
                   (company_id,name,code,location_type,vehicle_id,created_at,updated_at)
                   VALUES ($1,$2,$3,'VEHICLE',$4,NOW(),NOW()) RETURNING id""",
                cid, "M01 vehicle", f"M01V{i}", vehicle)
            ws = await conn.fetchval(
                """INSERT INTO work_sessions
                   (company_id,driver_id,start_time,session_date)
                   VALUES ($1,$2,NOW()-interval '1 day',CURRENT_DATE-1) RETURNING id""",
                cid, driver)
            route = await conn.fetchval(
                """INSERT INTO dispatch_routes
                   (company_id,zone_id,driver_id,vehicle_id,work_session_id,
                    source_location_id,dispatch_date,status,created_at)
                   VALUES ($1,$2,$3,$4,$5,$6,CURRENT_DATE-1,'postponed',NOW())
                   RETURNING id""", cid, zone, driver, vehicle, ws, location)
            dest.extend((cid, driver, vehicle, zone, location, ws, route))
        # A second closed route permits DB-level live-period collision testing
        # without relaxing the existing legacy driver/vehicle guards.
        second = await conn.fetchval(
            """INSERT INTO dispatch_routes
               (company_id,zone_id,driver_id,vehicle_id,
                source_location_id,dispatch_date,status,created_at)
               VALUES ($1,$2,$3,$4,$5,CURRENT_DATE,'closed',NOW()) RETURNING id""",
            a[0], a[3], a[1], a[2], a[4])
        # A loaded vehicle with *no route* must remain physically loaded and
        # receive an UNCONFIRMED review sentinel, never a guessed custodian.
        unassigned_vehicle = await conn.fetchval(
            """INSERT INTO vehicles
               (company_id,plate_number,current_mileage,maintenance_status,is_active)
               VALUES ($1,$2,0,'Active',true) RETURNING id""",
            a[0], f"M01-UNASSIGNED-{uuid4().hex[:5]}")
        unassigned_location = await conn.fetchval(
            """INSERT INTO inventory_locations
               (company_id,name,code,location_type,vehicle_id,created_at,updated_at)
               VALUES ($1,'Unassigned loaded vehicle',$2,'VEHICLE',$3,NOW(),NOW())
               RETURNING id""",
            a[0], f"M01U{uuid4().hex[:5]}", unassigned_vehicle)
        product = await conn.fetchval(
            """INSERT INTO products(company_id,code,name,created_at,updated_at)
               VALUES ($1,$2,'M01 goods',NOW(),NOW()) RETURNING id""",
            a[0], f"M01P{uuid4().hex[:5]}")
        uom = await conn.fetchval("SELECT id FROM uom ORDER BY id LIMIT 1")
        variant = await conn.fetchval(
            """INSERT INTO product_variants
               (company_id,product_id,base_uom_id,name,sku,created_at,updated_at)
               VALUES ($1,$2,$3,'M01 SKU',$4,NOW(),NOW()) RETURNING id""",
            a[0], product, uom, f"M01SKU{uuid4().hex[:5]}")
        batch = await conn.fetchval(
            """INSERT INTO product_batches
               (company_id,product_variant_id,batch_number,created_at,updated_at)
               VALUES ($1,$2,'M01-LOT',NOW(),NOW()) RETURNING id""", a[0], variant)
        await conn.execute(
            """INSERT INTO inventory_balances
               (company_id,location_id,product_variant_id,batch_id,stock_status,
                on_hand_quantity,reserved_quantity,last_updated)
               VALUES ($1,$2,$3,$4,'AVAILABLE',17,0,NOW())""",
            a[0],unassigned_location,variant,batch)
        a.extend((unassigned_vehicle, unassigned_location))
        return a, b, second
    finally:
        await conn.close()


class M01MetadataTest(unittest.TestCase):
    def test_mapping_registers_bounded_tables(self):
        from models import Base, DispatchRoute, Visit
        names = Base.metadata.tables
        self.assertIn("dispatch_route_execution_periods", names)
        self.assertIn("vehicle_custody_epochs", names)
        self.assertIn("assignment_context_revision", DispatchRoute.__table__.c)
        self.assertIn("execution_period_id", Visit.__table__.c)
        self.assertIn("fk_visit_execution_period_context",
                      {fk.name for fk in Visit.__table__.foreign_key_constraints})


@unittest.skipUnless(os.getenv("RUN_M01_PG16") == "1", "Explicit disposable PG16 gate not selected")
class M01PostgresTest(unittest.TestCase):
    def test_real_pg16_migration_rls_backfill_uniqueness_and_rollback(self):
        rt = os.getenv("DATABASE_URL")
        mg = os.getenv("DATABASE_URL_MIGRATION")
        if not rt or not mg:
            self.fail("Both restricted runtime and migration URLs are required for PG16 gate")
        name = "m01_937_" + uuid4().hex[:10]
        asyncio.run(_create_db(mg, name))
        old_rt, old_mg = rt, mg
        orig_cwd = Path.cwd()
        os.environ["DATABASE_URL"] = make_url(rt).set(database=name).render_as_string(hide_password=False)
        os.environ["DATABASE_URL_MIGRATION"] = make_url(mg).set(database=name).render_as_string(hide_password=False)
        cfg = Config(str(BACKEND / "alembic.ini"))
        try:
            os.chdir(BACKEND)
            command.upgrade(cfg, "f6c2a7d4e890")
            a, b, second = asyncio.run(_fixtures(os.environ["DATABASE_URL_MIGRATION"], name))
            route_before = asyncio.run(self._routes(os.environ["DATABASE_URL_MIGRATION"], name))
            command.upgrade(cfg, "b7e2c4a9d631")
            asyncio.run(self._assertions(os.environ["DATABASE_URL"], os.environ["DATABASE_URL_MIGRATION"], name, a, b, second))
            route_after = asyncio.run(self._routes(os.environ["DATABASE_URL_MIGRATION"], name))
            self.assertEqual(route_before, route_after, "M01 changed legacy route/read state")
            with self.assertRaisesRegex(RuntimeError, "canonical writes"):
                command.downgrade(cfg, "f6c2a7d4e890")
            asyncio.run(self._remove_test_writes(os.environ["DATABASE_URL_MIGRATION"], name))
            command.downgrade(cfg, "f6c2a7d4e890")
            asyncio.run(self._check_downgrade(os.environ["DATABASE_URL_MIGRATION"], name))
        finally:
            os.chdir(orig_cwd)
            os.environ["DATABASE_URL"] = old_rt
            os.environ["DATABASE_URL_MIGRATION"] = old_mg
            asyncio.run(_drop_db(mg, name))

    async def _routes(self, mg, db):
        c = await _connect(mg, db)
        try:
            return [tuple(r) for r in await c.fetch(
                "SELECT company_id,id,driver_id,vehicle_id,work_session_id,status,dispatch_date "
                "FROM dispatch_routes ORDER BY company_id,id")]
        finally:
            await c.close()

    async def _assertions(self, rt, mg, db, a, b, second):
        admin = await _connect(mg, db)
        restricted = await _connect(rt, db)
        try:
            for table in ("dispatch_route_execution_periods","vehicle_custody_epochs"):
                row = await admin.fetchrow(
                    """SELECT relrowsecurity,relforcerowsecurity FROM pg_class
                       WHERE oid=($1::regclass)""", table)
                assert row["relrowsecurity"] and row["relforcerowsecurity"], table
            current_role = await restricted.fetchrow(
                """SELECT rolsuper,rolbypassrls FROM pg_roles
                   WHERE rolname=current_user""")
            assert not current_role["rolsuper"] and not current_role["rolbypassrls"]
            periods = await admin.fetch("SELECT company_id,route_id,work_session_id,state,"
                "vehicle_location_id,review_reason FROM dispatch_route_execution_periods ORDER BY company_id")
            assert len(periods) == 2, periods
            assert periods[0]["state"] == "HISTORICAL"
            assert periods[0]["vehicle_location_id"] == a[4]
            assert periods[0]["review_reason"] == "LEGACY_CUSTODIAN_UNVERIFIED"
            assert periods[1]["state"] == "HISTORICAL"
            assert await admin.fetchval("SELECT count(*) FROM vehicle_custody_epochs") == 1
            custody = await admin.fetchrow("SELECT vehicle_id,vehicle_location_id,state,custodian_principal_id,started_at FROM vehicle_custody_epochs")
            assert (custody["vehicle_id"],custody["vehicle_location_id"],custody["state"]) == (a[7],a[8],"NEEDS_REVIEW")
            assert custody["custodian_principal_id"] is None and custody["started_at"] is None
            assert await admin.fetchval("SELECT on_hand_quantity FROM inventory_balances WHERE location_id=$1",a[8]) == 17
            assert await admin.fetchval("SELECT count(*) FROM inventory_movements") == 0
            assert await restricted.fetchval("SELECT count(*) FROM dispatch_route_execution_periods") == 0
            async with restricted.transaction():
                await restricted.execute("SELECT set_config('app.current_tenant',$1,true)",str(a[0]))
                assert await restricted.fetchval(
                    "SELECT count(*) FROM dispatch_route_execution_periods") == 1
                try:
                    async with restricted.transaction():
                        await restricted.execute(
                            """INSERT INTO dispatch_route_execution_periods
                               (company_id,route_id,driver_id,vehicle_id,state,context_revision,
                                evidence_origin) VALUES ($1,$2,$3,$4,'NEEDS_REVIEW',2,'CANONICAL')""",
                            b[0],b[6],b[1],b[2])
                    raise AssertionError("RLS cross-tenant insert succeeded")
                except asyncpg.InsufficientPrivilegeError:
                    pass
            # Wrong-company FK violation, even when the operation is privileged.
            try:
                async with admin.transaction():
                    await admin.execute(
                        """INSERT INTO dispatch_route_execution_periods
                           (company_id,route_id,driver_id,vehicle_id,state,context_revision)
                           VALUES ($1,$2,$3,$4,'NEEDS_REVIEW',2)""",
                        a[0],b[6],a[1],a[2])
                raise AssertionError("Tenant-crossed route FK was accepted")
            except asyncpg.ForeignKeyViolationError:
                pass
            # Unambiguous live-period index collision: two different closed
            # legacy routes deliberately share the same driver and vehicle.
            async with admin.transaction():
                # Check applies to CANONICAL only, so use HISTORICAL to avoid
                # claiming a current assignment when full handshake is absent.
                await admin.execute(
                    """INSERT INTO dispatch_route_execution_periods
                       (company_id,route_id,driver_id,vehicle_id,vehicle_location_id,
                        state,context_revision,evidence_origin)
                       VALUES ($1,$2,$3,$4,$5,'HISTORICAL',2,'M01_BACKFILL')""",
                    a[0],second,a[1],a[2],a[4])
            # Historical periods do not block live assignment.
            assert await admin.fetchval(
                """SELECT count(*) FROM dispatch_route_execution_periods
                   WHERE company_id=$1 AND state='HISTORICAL'""",a[0]) == 2
            # Attempted operational insertion without canonical evidence fails closed.
            try:
                async with admin.transaction():
                    await admin.execute(
                        """INSERT INTO dispatch_route_execution_periods
                           (company_id,route_id,driver_id,vehicle_id,state,context_revision)
                           VALUES ($1,$2,$3,$4,'ACTIVE',3)""",
                        a[0],second,a[1],a[2])
                raise AssertionError("Canonical evidence check was bypassed")
            except asyncpg.CheckViolationError:
                pass
            # A live custody epoch needs exact accepted identities and signed evidence.
            try:
                async with admin.transaction():
                    await admin.execute(
                        """INSERT INTO vehicle_custody_epochs
                           (company_id,vehicle_id,vehicle_location_id,custodian_kind,
                            state,context_revision)
                           VALUES ($1,$2,$3,'BACKOFFICE','ACCEPTED',1)""",
                        a[0],a[2],a[4])
                raise AssertionError("Custody acceptance without principal succeeded")
            except asyncpg.CheckViolationError:
                pass
            # Two open unresolved custody records on one vehicle conflict.
            await admin.execute(
                """INSERT INTO vehicle_custody_epochs
                   (company_id,vehicle_id,vehicle_location_id,custodian_kind,state,
                    context_revision,reason,evidence_origin)
                   VALUES ($1,$2,$3,'UNCONFIRMED','NEEDS_REVIEW',1,'test','M01_BACKFILL')""",
                a[0],a[2],a[4])
            try:
                async with admin.transaction():
                    await admin.execute(
                        """INSERT INTO vehicle_custody_epochs
                           (company_id,vehicle_id,vehicle_location_id,custodian_kind,
                            state,context_revision,evidence_origin)
                           VALUES ($1,$2,$3,'UNCONFIRMED','NEEDS_REVIEW',2,'M01_BACKFILL')""",
                        a[0],a[2],a[4])
                raise AssertionError("Duplicate current custodian epoch inserted")
            except asyncpg.UniqueViolationError:
                pass

            # Two canonical period inserts compete for the same driver/vehicle.
            # A second transaction must wait on the partial unique index, then
            # fail as a real concurrency conflict (not a UI-only availability filter).
            backoffice = await admin.fetchval(
                """INSERT INTO company_principals
                   (company_id,username,password_hash,full_name,principal_type)
                   VALUES ($1,$2,'unused','M01 acceptance','BACKOFFICE') RETURNING id""",
                a[0],f"m01_bo_{uuid4().hex[:6]}")
            field_principal = await admin.fetchval(
                """INSERT INTO company_principals
                   (company_id,username,password_hash,full_name,principal_type)
                   VALUES ($1,$2,'unused','M01 field','FIELD_REPRESENTATIVE') RETURNING id""",
                a[0],f"m01_field_{uuid4().hex[:6]}")
            rep = await admin.fetchval(
                """INSERT INTO field_representatives(company_id,principal_id)
                   VALUES($1,$2) RETURNING id""",a[0],field_principal)
            # An ACTIVE period must have a real work session; PLANNED may
            # precede session start, but activation may not.
            try:
                async with admin.transaction():
                    await admin.execute(
                        """INSERT INTO dispatch_route_execution_periods
                           (company_id,route_id,driver_id,field_representative_id,
                            vehicle_id,vehicle_location_id,state,context_revision,
                            started_at,started_by_principal_id,request_id,payload_hash)
                           VALUES ($1,$2,$3,$4,$5,$6,'ACTIVE',55,NOW(),$7,$8,$9)""",
                        a[0],second,a[1],rep,a[2],a[4],
                        backoffice,uuid4().hex,"f"*64)
                raise AssertionError("ACTIVE period without WorkSession succeeded")
            except asyncpg.CheckViolationError as exc:
                assert exc.constraint_name == "ck_route_period_active_session"
            first_req, second_req = uuid4().hex, uuid4().hex
            active_insert = """
                INSERT INTO dispatch_route_execution_periods
                  (company_id,route_id,driver_id,field_representative_id,
                   vehicle_id,vehicle_location_id,state,context_revision,
                   started_at,started_by_principal_id,request_id,payload_hash)
                VALUES ($1,$2,$3,$4,$5,$6,'PLANNED',$7,NOW(),$8,$9,$10)
            """
            competing = await _connect(mg,db)
            try:
                tx1 = admin.transaction()
                await tx1.start()
                await admin.execute(active_insert, a[0],second,a[1],rep,
                                    a[2],a[4],3,backoffice,first_req,"a"*64)
                tx2 = competing.transaction()
                await tx2.start()
                await competing.execute("SET LOCAL lock_timeout = '350ms'")
                try:
                    await competing.execute(active_insert, a[0],a[6],a[1],rep,
                                            a[2],a[4],2,backoffice,second_req,"b"*64)
                    raise AssertionError("Concurrent live period was not blocked")
                except asyncpg.LockNotAvailableError:
                    pass
                finally:
                    await tx2.rollback()
                await tx1.commit()
                try:
                    async with competing.transaction():
                        await competing.execute(active_insert, a[0],a[6],a[1],rep,
                                                a[2],a[4],2,backoffice,second_req,"b"*64)
                    raise AssertionError("Second current driver/vehicle period was inserted")
                except asyncpg.UniqueViolationError:
                    pass
                # Closing a period frees live resource occupancy, not its
                # immutable context revision (ABA reuse of revision must fail).
                await admin.execute(
                    """UPDATE dispatch_route_execution_periods
                       SET ended_at=NOW(),state='CLOSED'
                       WHERE company_id=$1 AND request_id=$2""",a[0],first_req)
                try:
                    async with competing.transaction():
                        await competing.execute(active_insert, a[0],second,a[1],rep,
                                                a[2],a[4],3,backoffice,uuid4().hex,"c"*64)
                    raise AssertionError("Closed period's context revision was reused")
                except asyncpg.UniqueViolationError:
                    pass
            finally:
                await competing.close()

            # Resolve the synthetic unconfirmed current epoch explicitly
            # before recording a new accepted responsibility epoch.
            await admin.execute(
                """UPDATE vehicle_custody_epochs SET started_at=NOW()-interval '1 second',
                   ended_at=NOW() WHERE company_id=$1 AND vehicle_id=$2
                   AND state='NEEDS_REVIEW'""",a[0],a[2])
            # An accepted custody requires explicit typed principal and witness.
            await admin.execute(
                """INSERT INTO vehicle_custody_epochs
                   (company_id,vehicle_id,vehicle_location_id,custodian_kind,
                    custodian_principal_id,accepted_by_principal_id,state,
                    context_revision,started_at,request_id,payload_hash)
                   VALUES ($1,$2,$3,'BACKOFFICE',$4,$4,'ACCEPTED',2,NOW(),$5,$6)""",
                a[0],a[2],a[4],backoffice,uuid4().hex,"d"*64)
            try:
                async with admin.transaction():
                    await admin.execute(
                        """INSERT INTO vehicle_custody_epochs
                           (company_id,vehicle_id,vehicle_location_id,custodian_kind,
                            custodian_principal_id,accepted_by_principal_id,state,
                            context_revision,started_at,request_id,payload_hash)
                           VALUES ($1,$2,$3,'BACKOFFICE',$4,$4,'ACCEPTED',3,NOW(),$5,$6)""",
                        a[0],a[2],a[4],backoffice,uuid4().hex,"e"*64)
                raise AssertionError("A second open accepted custody was allowed")
            except asyncpg.UniqueViolationError:
                pass
            await admin.execute(
                """UPDATE vehicle_custody_epochs SET ended_at=NOW()
                   WHERE company_id=$1 AND vehicle_id=$2 AND state='ACCEPTED'""",
                a[0],a[2])
            try:
                async with admin.transaction():
                    await admin.execute(
                        """INSERT INTO vehicle_custody_epochs
                           (company_id,vehicle_id,vehicle_location_id,custodian_kind,
                            state,context_revision)
                           VALUES ($1,$2,$3,'UNCONFIRMED','NEEDS_REVIEW',4)""",
                        a[0],a[2],b[4])
                raise AssertionError("Vehicle custody used another company's location")
            except asyncpg.ForeignKeyViolationError:
                pass
        finally:
            await restricted.close()
            await admin.close()

    async def _remove_test_writes(self, mg, db):
        c = await _connect(mg, db)
        try:
            await c.execute("DELETE FROM dispatch_route_execution_periods WHERE evidence_origin='CANONICAL'")
            await c.execute("DELETE FROM vehicle_custody_epochs WHERE evidence_origin='CANONICAL'")
        finally:
            await c.close()

    async def _check_downgrade(self, mg, db):
        c = await _connect(mg, db)
        try:
            assert await c.fetchval(
                "SELECT to_regclass('public.dispatch_route_execution_periods')") is None
            assert await c.fetchval(
                "SELECT to_regclass('public.vehicle_custody_epochs')") is None
            assert await c.fetchval(
                "SELECT count(*) FROM information_schema.columns "
                "WHERE table_name='dispatch_routes' AND column_name='assignment_context_revision'") == 0
        finally:
            await c.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
