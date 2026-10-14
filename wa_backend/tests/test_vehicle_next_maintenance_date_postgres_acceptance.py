"""Real PostgreSQL acceptance for PR #320 Vehicle maintenance business date.

The suite starts a fresh localhost PostgreSQL 16 cluster, migrates only synthetic
rows, exercises the actual Vehicle API/domain persistence path, and destroys the
entire disposable database/cluster afterwards. It never reads the developer DB.
"""
from __future__ import annotations

import asyncio
from datetime import date
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from uuid import uuid4

import psycopg


BACKEND = Path(__file__).resolve().parents[1]
PARENT_REVISION = "c9e7a41d2b60"
TARGET_REVISION = "d1a8f6c3b742"
ADMIN = "vehicle_maintenance_acceptance_admin"
RUNTIME = "vehicle_maintenance_acceptance_runtime"
DATABASE = "vehicle_maintenance_acceptance"
SECRET = "VehicleMaintenanceAcceptanceAbc12345678901234567890"


class VehicleMaintenanceDatePostgresAcceptance(unittest.TestCase):
    @classmethod
    def _run(cls, args, *, env=None, timeout=180, quiet=False):
        result = subprocess.run(
            [str(arg) for arg in args],
            cwd=BACKEND,
            env=env,
            text=True,
            timeout=timeout,
            stdout=subprocess.DEVNULL if quiet else subprocess.PIPE,
            stderr=subprocess.DEVNULL if quiet else subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(
                f"{Path(str(args[0])).name} failed ({result.returncode}): "
                f"{(result.stdout or '')[-3000:]} {(result.stderr or '')[-3000:]}"
            )
        return result.stdout or ""

    @classmethod
    def _find_pg_bin(cls) -> Path:
        candidates = []
        configured = os.environ.get("WANASAH_TEST_PG_BIN")
        if configured:
            candidates.append(Path(configured))
        pg_ctl = shutil.which("pg_ctl") or shutil.which("pg_ctl.exe")
        if pg_ctl:
            candidates.append(Path(pg_ctl).resolve().parent)
        if os.name == "nt":
            candidates.extend(
                [
                    Path(r"C:\Tools\PostgreSQL\16\pgsql\bin"),
                    Path(r"C:\Program Files\PostgreSQL\16\bin"),
                ]
            )
        else:
            candidates.append(Path("/usr/lib/postgresql/16/bin"))
        exe = ".exe" if os.name == "nt" else ""
        for candidate in candidates:
            if (candidate / f"pg_ctl{exe}").is_file() and (candidate / f"initdb{exe}").is_file():
                return candidate
        raise AssertionError("PostgreSQL 16 initdb/pg_ctl not found for isolated acceptance")

    @classmethod
    def _pg(cls, name: str) -> str:
        suffix = ".exe" if os.name == "nt" else ""
        return str(cls.pg_bin / f"{name}{suffix}")

    @classmethod
    def _alembic(cls, *args: str) -> str:
        return cls._run([sys.executable, "-m", "alembic", *args], env=cls.env)

    @classmethod
    def _connect(cls, *, database=DATABASE, autocommit=True):
        return psycopg.connect(
            host="127.0.0.1",
            port=cls.port,
            dbname=database,
            user=ADMIN,
            autocommit=autocommit,
        )

    @classmethod
    def _vehicle_schema(cls, conn):
        columns = conn.execute(
            """SELECT column_name, data_type, udt_name, is_nullable, column_default, ordinal_position
               FROM information_schema.columns
               WHERE table_schema='public' AND table_name='vehicles'
               ORDER BY ordinal_position"""
        ).fetchall()
        constraints = conn.execute(
            """SELECT conname, pg_get_constraintdef(c.oid)
               FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid
               JOIN pg_namespace n ON n.oid=r.relnamespace
               WHERE n.nspname='public' AND r.relname='vehicles'
               ORDER BY conname"""
        ).fetchall()
        indexes = conn.execute(
            """SELECT indexname,indexdef FROM pg_indexes
               WHERE schemaname='public' AND tablename='vehicles'
               ORDER BY indexname"""
        ).fetchall()
        return columns, constraints, indexes

    @classmethod
    def _legacy_vehicle_row(cls, conn):
        return conn.execute(
            """SELECT id,company_id,plate_number,vehicle_type,current_mileage,next_oil_change,
                      license_expiry_date,maintenance_status,is_active,version
               FROM vehicles WHERE id=%s""",
            (cls.legacy_vehicle_id,),
        ).fetchone()

    @classmethod
    def _cleanup_cluster(cls):
        errors = []
        if getattr(cls, "started", False):
            try:
                with cls._connect(database="postgres") as conn:
                    conn.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname=%s AND pid<>pg_backend_pid()",
                        (DATABASE,),
                    )
                    conn.execute(f'DROP DATABASE IF EXISTS "{DATABASE}"')
                    exists = conn.execute(
                        "SELECT 1 FROM pg_database WHERE datname=%s", (DATABASE,)
                    ).fetchone()
                    if exists is not None:
                        raise AssertionError("Disposable database still exists after DROP DATABASE")
                print("DISPOSABLE_DATABASE_DROPPED=PASS", flush=True)
            except Exception as exc:  # cleanup must continue to stop/delete the cluster
                errors.append(f"drop database: {exc}")
            try:
                cls._run(
                    [cls._pg("pg_ctl"), "-D", str(cls.data), "-m", "fast", "-w", "stop"],
                    quiet=True,
                )
                print("ISOLATED_CLUSTER_STOPPED=PASS", flush=True)
            except Exception as exc:
                errors.append(f"stop cluster: {exc}")
        cluster = getattr(cls, "cluster", None)
        if cluster and Path(cluster).exists():
            try:
                shutil.rmtree(cluster)
            except Exception as exc:
                errors.append(f"delete cluster directory: {exc}")
        if cluster and Path(cluster).exists():
            errors.append("cluster directory still exists")
        elif cluster:
            print("ISOLATED_CLUSTER_DIRECTORY_REMOVED=PASS", flush=True)
        if errors:
            raise AssertionError("; ".join(errors))

    @classmethod
    def setUpClass(cls):
        cls.started = False
        cls.cluster = None
        cls.original_env = {
            key: os.environ.get(key)
            for key in (
                "PYTHONDONTWRITEBYTECODE",
                "ENVIRONMENT",
                "SECRET_KEY",
                "DATABASE_URL",
                "DATABASE_URL_MIGRATION",
            )
        }
        try:
            cls.pg_bin = cls._find_pg_bin()
            version = cls._run([cls._pg("pg_ctl"), "--version"])
            if not re.search(r"PostgreSQL\) 16\.", version):
                raise AssertionError(f"Expected PostgreSQL 16, got: {version.strip()}")

            cls.cluster = Path(tempfile.mkdtemp(prefix="wanasah_vehicle_maintenance_")).resolve()
            cls.data = cls.cluster / "data"
            with socket.socket() as reserved:
                reserved.bind(("127.0.0.1", 0))
                cls.port = reserved.getsockname()[1]

            cls.env = os.environ.copy()
            cls.runtime_url = f"postgresql+asyncpg://{RUNTIME}@127.0.0.1:{cls.port}/{DATABASE}"
            cls.migration_url = f"postgresql+asyncpg://{ADMIN}@127.0.0.1:{cls.port}/{DATABASE}"
            cls.async_url = cls.migration_url
            cls.env.update(
                {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "ENVIRONMENT": "test",
                    "SECRET_KEY": SECRET,
                    "DATABASE_URL": cls.runtime_url,
                    "DATABASE_URL_MIGRATION": cls.migration_url,
                }
            )
            os.environ.update(
                {
                    key: cls.env[key]
                    for key in (
                        "PYTHONDONTWRITEBYTECODE",
                        "ENVIRONMENT",
                        "SECRET_KEY",
                        "DATABASE_URL",
                        "DATABASE_URL_MIGRATION",
                    )
                }
            )

            cls._run(
                [
                    cls._pg("initdb"),
                    "-D",
                    str(cls.data),
                    "-U",
                    ADMIN,
                    "--auth=trust",
                    "--encoding=UTF8",
                    "--no-locale",
                ]
            )
            cls._run(
                [
                    cls._pg("pg_ctl"),
                    "-D",
                    str(cls.data),
                    "-l",
                    str(cls.cluster / "postgres.log"),
                    "-o",
                    f"-h 127.0.0.1 -p {cls.port}",
                    "-w",
                    "start",
                ],
                quiet=True,
            )
            cls.started = True
            with cls._connect(database="postgres") as conn:
                if Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve() != cls.data:
                    raise AssertionError("Connected PostgreSQL is not the isolated acceptance cluster")
                conn.execute(
                    f"CREATE ROLE {RUNTIME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS"
                )
                conn.execute(f'CREATE DATABASE "{DATABASE}"')
            print(f"ISOLATED_POSTGRES_16_STARTED={cls.cluster}", flush=True)

            cls._alembic("upgrade", PARENT_REVISION)
            with cls._connect() as conn:
                cls.parent_revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                cls.parent_schema = cls._vehicle_schema(conn)
                parent_columns = {row[0] for row in cls.parent_schema[0]}
                if "next_maintenance_date" in parent_columns:
                    raise AssertionError("Parent revision already contains next_maintenance_date")
                cls.company_id = conn.execute(
                    """INSERT INTO companies(name,company_code,is_active,subscription_status,currency_code,timezone,created_at)
                       VALUES ('Vehicle PG Acceptance','VEH-PG-ACC',true,'active','JOD','UTC',CURRENT_TIMESTAMP)
                       RETURNING id"""
                ).fetchone()[0]
                cls.actor_id = conn.execute(
                    """INSERT INTO drivers(company_id,username,password_hash,full_name,is_active,created_at)
                       VALUES (%s,'vehicle-pg-actor','synthetic-not-for-login','Vehicle PG Actor',true,CURRENT_TIMESTAMP)
                       RETURNING id""",
                    (cls.company_id,),
                ).fetchone()[0]
                cls.legacy_vehicle_id = conn.execute(
                    """INSERT INTO vehicles(
                           company_id,plate_number,vehicle_type,current_mileage,next_oil_change,
                           license_expiry_date,maintenance_status,is_active,version
                       ) VALUES (%s,'LEGACY-PG-01','Legacy Van',12345,15000,DATE '2031-07-08','Active',true,7)
                       RETURNING id""",
                    (cls.company_id,),
                ).fetchone()[0]
                cls.legacy_before = cls._legacy_vehicle_row(conn)

            cls._alembic("upgrade", TARGET_REVISION)
            with cls._connect() as conn:
                cls.upgrade_revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                cls.upgraded_schema = cls._vehicle_schema(conn)
                column = conn.execute(
                    """SELECT data_type,is_nullable FROM information_schema.columns
                       WHERE table_schema='public' AND table_name='vehicles'
                         AND column_name='next_maintenance_date'"""
                ).fetchone()
                cls.upgrade_column_contract = column
                row = conn.execute(
                    """SELECT id,company_id,plate_number,vehicle_type,current_mileage,next_oil_change,
                              license_expiry_date,maintenance_status,is_active,version,next_maintenance_date
                       FROM vehicles WHERE id=%s""",
                    (cls.legacy_vehicle_id,),
                ).fetchone()
                cls.legacy_after_upgrade = row
                upgraded_columns_without_new = [
                    item for item in cls.upgraded_schema[0] if item[0] != "next_maintenance_date"
                ]
                cls.upgrade_only_added_column = (
                    upgraded_columns_without_new == list(cls.parent_schema[0])
                    and cls.upgraded_schema[1] == cls.parent_schema[1]
                    and cls.upgraded_schema[2] == cls.parent_schema[2]
                    and len(cls.upgraded_schema[0]) == len(cls.parent_schema[0]) + 1
                )

            cls._alembic("downgrade", PARENT_REVISION)
            with cls._connect() as conn:
                cls.downgrade_revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                cls.downgraded_schema = cls._vehicle_schema(conn)
                cls.downgrade_schema_exact = cls.downgraded_schema == cls.parent_schema
                cls.legacy_after_downgrade = cls._legacy_vehicle_row(conn)

            cls._alembic("upgrade", TARGET_REVISION)
            with cls._connect() as conn:
                cls.final_revision = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
                cls.legacy_after_roundtrip = conn.execute(
                    """SELECT id,company_id,plate_number,vehicle_type,current_mileage,next_oil_change,
                              license_expiry_date,maintenance_status,is_active,version,next_maintenance_date
                       FROM vehicles WHERE id=%s""",
                    (cls.legacy_vehicle_id,),
                ).fetchone()

            sys.path.insert(0, str(BACKEND))
            from api.vehicles.management import create_vehicle_endpoint, update_vehicle_endpoint
            from api.vehicles.read import read_vehicle_detail, read_vehicles
            from api.vehicles.schemas import VehicleCreateRequest, VehicleUpdateRequest

            cls.create_vehicle_endpoint = staticmethod(create_vehicle_endpoint)
            cls.update_vehicle_endpoint = staticmethod(update_vehicle_endpoint)
            cls.read_vehicle_detail = staticmethod(read_vehicle_detail)
            cls.read_vehicles = staticmethod(read_vehicles)
            cls.VehicleCreateRequest = VehicleCreateRequest
            cls.VehicleUpdateRequest = VehicleUpdateRequest
            cls.access = SimpleNamespace(company_id=int(cls.company_id))
            cls.legacy_actor = SimpleNamespace(id=int(cls.actor_id))
        except Exception:
            try:
                cls._cleanup_cluster()
            finally:
                cls._restore_environment()
            raise

    @classmethod
    def _restore_environment(cls):
        for key, value in getattr(cls, "original_env", {}).items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    @classmethod
    def tearDownClass(cls):
        try:
            cls._cleanup_cluster()
        finally:
            cls._restore_environment()

    @classmethod
    def _row(cls, vehicle_id: int):
        with cls._connect() as conn:
            row = conn.execute(
                """SELECT id,company_id,plate_number,vehicle_type,current_mileage,next_oil_change,
                          license_expiry_date,next_maintenance_date,maintenance_status,is_active,version
                   FROM vehicles WHERE id=%s""",
                (vehicle_id,),
            ).fetchone()
            return row

    @classmethod
    def _custody_rows(cls, vehicle_id: int):
        with cls._connect() as conn:
            return conn.execute(
                """SELECT id,company_id,name,code,location_type,vehicle_id,is_active,version
                   FROM inventory_locations
                   WHERE company_id=%s AND vehicle_id=%s AND location_type='VEHICLE'
                   ORDER BY id""",
                (cls.company_id, vehicle_id),
            ).fetchall()

    @classmethod
    def _inventory_balance_count(cls, location_id: int):
        with cls._connect() as conn:
            return conn.execute(
                "SELECT count(*) FROM inventory_balances WHERE company_id=%s AND location_id=%s",
                (cls.company_id, location_id),
            ).fetchone()[0]

    @classmethod
    def _call_with_db(cls, callback):
        async def run():
            from sqlalchemy import event
            from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

            engine = create_async_engine(cls.async_url, pool_pre_ping=True)
            statements = []

            def capture(_conn, _cursor, statement, _params, _context, _executemany):
                statements.append(statement)

            event.listen(engine.sync_engine, "before_cursor_execute", capture)
            try:
                session_factory = async_sessionmaker(engine, expire_on_commit=False)
                async with session_factory() as db:
                    result = await callback(db)
                return result, statements
            finally:
                await engine.dispose()

        return asyncio.run(run())

    def _create(self, *, next_date="OMITTED", maintenance_status="Active", full=False):
        kwargs = {
            "request_id": uuid4(),
            "plate_number": f"PG-{uuid4().hex[:10].upper()}",
            "maintenance_status": maintenance_status,
        }
        if full:
            kwargs.update(
                vehicle_type="Refrigerated Van",
                current_mileage=54321,
                next_oil_change=60000,
                license_expiry_date=date(2033, 9, 10),
            )
        if next_date != "OMITTED":
            kwargs["next_maintenance_date"] = next_date
        payload = self.VehicleCreateRequest(**kwargs)

        async def call(db):
            return await self.create_vehicle_endpoint(
                payload=payload,
                db=db,
                access=self.access,
                legacy_actor=self.legacy_actor,
            )

        return self._call_with_db(call)

    def _update(self, vehicle_id: int, expected_version: int, **fields):
        payload = self.VehicleUpdateRequest(
            request_id=uuid4(),
            expected_version=expected_version,
            **fields,
        )

        async def call(db):
            return await self.update_vehicle_endpoint(
                vehicle_id=vehicle_id,
                payload=payload,
                db=db,
                access=self.access,
                legacy_actor=self.legacy_actor,
            )

        return self._call_with_db(call)

    def _get(self, vehicle_id: int):
        async def call(db):
            return await self.read_vehicle_detail(
                vehicle_id=vehicle_id,
                db=db,
                access=self.access,
            )

        return self._call_with_db(call)

    def _list(self):
        async def call(db):
            return await self.read_vehicles(
                search=None,
                active=None,
                maintenance_status=None,
                cursor=None,
                limit=100,
                db=db,
                access=self.access,
            )

        return self._call_with_db(call)

    def test_01_real_migration_upgrade_is_nullable_postgresql_date_and_target_revision(self):
        self.assertEqual(self.parent_revision, PARENT_REVISION)
        self.assertEqual(self.upgrade_revision, TARGET_REVISION)
        self.assertEqual(self.final_revision, TARGET_REVISION)
        self.assertEqual(self.upgrade_column_contract, ("date", "YES"))
        self.assertTrue(self.upgrade_only_added_column)

    def test_02_existing_vehicle_survives_upgrade_with_null_and_no_other_field_change(self):
        self.assertEqual(self.legacy_after_upgrade[:-1], self.legacy_before)
        self.assertIsNone(self.legacy_after_upgrade[-1])
        self.assertEqual(self.legacy_after_roundtrip[:-1], self.legacy_before)
        self.assertIsNone(self.legacy_after_roundtrip[-1])

    def test_03_real_downgrade_removes_only_new_column_and_preserves_existing_row(self):
        self.assertEqual(self.downgrade_revision, PARENT_REVISION)
        self.assertTrue(self.downgrade_schema_exact)
        self.assertEqual(self.legacy_after_downgrade, self.legacy_before)

    def test_04_create_omitted_persists_null(self):
        payload, _sql = self._create()
        row = self._row(payload["id"])
        self.assertIsNone(payload["next_maintenance_date"])
        self.assertIsNone(row[7])
        self.assertEqual((payload["maintenance_status"], row[8]), ("Active", "Active"))

    def test_05_create_future_date_persists_exact_date_and_requested_status(self):
        wanted = date(2035, 11, 12)
        payload, _sql = self._create(next_date=wanted, maintenance_status="In_Maintenance")
        row = self._row(payload["id"])
        self.assertEqual((payload["next_maintenance_date"], row[7]), (wanted.isoformat(), wanted))
        self.assertEqual((payload["maintenance_status"], row[8]), ("In_Maintenance", "In_Maintenance"))

    def test_06_create_past_date_is_accepted_without_automatic_maintenance_transition(self):
        wanted = date(2020, 1, 2)
        payload, _sql = self._create(next_date=wanted)
        row = self._row(payload["id"])
        self.assertEqual((payload["next_maintenance_date"], row[7]), (wanted.isoformat(), wanted))
        self.assertEqual((payload["maintenance_status"], row[8]), ("Active", "Active"))

    def test_07_update_omitted_keeps_existing_date(self):
        wanted = date(2030, 2, 3)
        created, _ = self._create(next_date=wanted, full=True)
        updated, _ = self._update(created["id"], created["version"], vehicle_type="Updated Van")
        row = self._row(created["id"])
        self.assertEqual(updated["next_maintenance_date"], wanted.isoformat())
        self.assertEqual(row[7], wanted)
        self.assertEqual(updated["version"], created["version"] + 1)

    def test_08_update_replaces_with_exact_date(self):
        original = date(2030, 2, 3)
        replacement = date(2031, 4, 5)
        created, _ = self._create(next_date=original)
        updated, _ = self._update(
            created["id"], created["version"], next_maintenance_date=replacement
        )
        row = self._row(created["id"])
        self.assertEqual((updated["next_maintenance_date"], row[7]), (replacement.isoformat(), replacement))
        self.assertEqual(updated["maintenance_status"], "Active")
        self.assertEqual(updated["version"], created["version"] + 1)

    def test_09_update_explicit_null_clears_database_column(self):
        created, _ = self._create(next_date=date(2030, 2, 3))
        updated, _ = self._update(
            created["id"], created["version"], next_maintenance_date=None
        )
        row = self._row(created["id"])
        self.assertIsNone(updated["next_maintenance_date"])
        self.assertIsNone(row[7])
        self.assertEqual(updated["version"], created["version"] + 1)

    def test_10_get_and_list_return_iso_business_dates_or_null_without_timestamp_shift(self):
        wanted = date(2032, 4, 5)
        dated, _ = self._create(next_date=wanted)
        blank, _ = self._create()
        detail, _ = self._get(dated["id"])
        blank_detail, _ = self._get(blank["id"])
        page, _ = self._list()
        by_id = {item["id"]: item for item in page["items"]}
        self.assertEqual(detail["next_maintenance_date"], "2032-04-05")
        self.assertNotIn("T", detail["next_maintenance_date"])
        self.assertIsNone(blank_detail["next_maintenance_date"])
        self.assertEqual(by_id[dated["id"]]["next_maintenance_date"], "2032-04-05")
        self.assertIsNone(by_id[blank["id"]]["next_maintenance_date"])

    def test_11_other_vehicle_fields_and_canonical_custody_are_unchanged(self):
        wanted = date(2034, 6, 7)
        created, _ = self._create(next_date=wanted, maintenance_status="Active", full=True)
        before = self._row(created["id"])
        custody_before = self._custody_rows(created["id"])
        self.assertEqual(len(custody_before), 1)
        self.assertEqual(custody_before[0][1], self.company_id)
        self.assertEqual(custody_before[0][4:], ("VEHICLE", created["id"], True, 1))
        self.assertEqual(
            before[2:10],
            (
                created["plate_number"],
                "Refrigerated Van",
                54321,
                60000,
                date(2033, 9, 10),
                wanted,
                "Active",
                True,
            ),
        )
        replacement = date(2036, 8, 9)
        updated, _ = self._update(
            created["id"], created["version"], next_maintenance_date=replacement
        )
        after = self._row(created["id"])
        custody_after = self._custody_rows(created["id"])
        self.assertEqual(before[2:7], after[2:7])
        self.assertEqual(before[8:10], after[8:10])
        self.assertEqual(after[7], replacement)
        self.assertEqual(after[10], before[10] + 1)
        self.assertEqual([row[0] for row in custody_after], [row[0] for row in custody_before])
        detail, _ = self._get(created["id"])
        self.assertTrue(detail["custody_ready"])
        self.assertEqual(updated["maintenance_status"], "Active")

    def test_12_optimistic_version_conflict_remains_fail_closed(self):
        created, _ = self._create(next_date=date(2030, 5, 6), full=True)
        updated, _ = self._update(
            created["id"], created["version"], current_mileage=54322
        )
        self.assertEqual(updated["version"], created["version"] + 1)
        before_stale = self._row(created["id"])
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as caught:
            self._update(
                created["id"], created["version"], next_maintenance_date=date(2040, 1, 1)
            )
        self.assertEqual(caught.exception.status_code, 409)
        self.assertEqual(caught.exception.detail["code"], "VEHICLE_VERSION_CONFLICT")
        self.assertEqual(self._row(created["id"]), before_stale)

    def test_13_vehicle_crud_never_writes_inventory_balance(self):
        created, create_sql = self._create(next_date=date(2030, 7, 8), full=True)
        custody = self._custody_rows(created["id"])
        self.assertEqual(len(custody), 1)
        updated, update_sql = self._update(
            created["id"], created["version"], next_maintenance_date=date(2031, 7, 8)
        )
        self.assertEqual(updated["version"], created["version"] + 1)
        dml = re.compile(r"^\s*(insert\s+into|update|delete\s+from)\s+inventory_balances\b", re.I)
        touched = [statement for statement in (*create_sql, *update_sql) if dml.search(statement)]
        self.assertEqual(touched, [])
        self.assertEqual(self._inventory_balance_count(custody[0][0]), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
