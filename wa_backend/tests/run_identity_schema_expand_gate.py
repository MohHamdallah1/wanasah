"""Identity expand acceptance in a fresh localhost PostgreSQL 16 cluster only.

No development .env, credentials, database or rows are read/copied. No packages
are installed. Cluster/data/logs are retained after stopping for inspection.
Run from wa_backend: python tests/run_identity_schema_expand_gate.py --run
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time

import psycopg

BACKEND = Path(__file__).resolve().parents[1]
REVISION = "e9c4b1a7d620"
PREVIOUS = "c6f1a4d8e203"
TABLES = ("company_principals", "backoffice_users", "field_representatives", "company_owners")
ADMIN = "identity_expand_admin"
RUNTIME = "identity_expand_runtime"
DATABASE = "identity_expand_test"


def run(args, *, env=None, pg_ctl=False, timeout=110):
    result = subprocess.run(
        args, cwd=BACKEND, env=env, text=True, timeout=timeout,
        stdout=subprocess.DEVNULL if pg_ctl else subprocess.PIPE,
        stderr=subprocess.DEVNULL if pg_ctl else subprocess.PIPE,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if result.returncode:
        # Only synthetic loopback configuration is ever passed to these commands.
        raise RuntimeError(f"{Path(args[0]).name} failed ({result.returncode}): "
                           f"{(result.stdout or '')[-2000:]} {(result.stderr or '')[-2000:]}")
    return result.stdout or ""


def legacy_contract(conn):
    """Fingerprint all pre-existing table definitions/FKs/indexes/RLS, not data."""
    exclusion = list(TABLES)
    queries = (
        """SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity,
                  a.attname, format_type(a.atttypid,a.atttypmod), a.attnotnull,
                  pg_get_expr(d.adbin,d.adrelid)
           FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           JOIN pg_attribute a ON a.attrelid=c.oid AND a.attnum>0 AND NOT a.attisdropped
           LEFT JOIN pg_attrdef d ON d.adrelid=c.oid AND d.adnum=a.attnum
           WHERE n.nspname='public' AND c.relkind IN ('r','p')
             AND NOT (c.relname=ANY(%s)) ORDER BY c.relname,a.attnum""",
        """SELECT c.relname, k.conname, pg_get_constraintdef(k.oid)
           FROM pg_constraint k JOIN pg_class c ON c.oid=k.conrelid
           JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND NOT (c.relname=ANY(%s)) ORDER BY c.relname,k.conname""",
        """SELECT tablename,indexname,indexdef FROM pg_indexes
           WHERE schemaname='public' AND NOT (tablename=ANY(%s))
           ORDER BY tablename,indexname""",
        """SELECT tablename,policyname,permissive,roles,cmd,qual,with_check FROM pg_policies
           WHERE schemaname='public' AND NOT (tablename=ANY(%s)) ORDER BY tablename,policyname""",
    )
    rows = [conn.execute(query, (exclusion,)).fetchall() for query in queries]
    return hashlib.sha256(json.dumps(rows, default=str).encode()).hexdigest()


def expect_error(conn, query, params, code):
    try:
        with conn.transaction():
            conn.execute(query, params)
    except psycopg.Error as exc:
        assert exc.sqlstate == code, (code, exc.sqlstate)
        return
    raise AssertionError(f"Expected SQLSTATE {code}")


def company(conn, code):
    return conn.execute(
        """INSERT INTO companies(name,company_code,is_active,subscription_status,
             currency_code,timezone,created_at)
           VALUES (%s,%s,true,'active','JOD','UTC',CURRENT_TIMESTAMP) RETURNING id""",
        (code, code),
    ).fetchone()[0]


def principal(conn, company_id, username, kind):
    return conn.execute(
        """INSERT INTO company_principals(company_id,username,password_hash,full_name,principal_type)
           VALUES (%s,%s,'synthetic-not-for-login','Synthetic identity',%s) RETURNING id""",
        (company_id, username, kind),
    ).fetchone()[0]


def backoffice(conn, company_id, principal_id):
    return conn.execute(
        "INSERT INTO backoffice_users(company_id,principal_id) VALUES (%s,%s) RETURNING id",
        (company_id, principal_id),
    ).fetchone()[0]


def verify_schema(conn):
    from domains.identity.models import (CompanyPrincipal, BackofficeUser, FieldRepresentative, CompanyOwner)
    models = (CompanyPrincipal, BackofficeUser, FieldRepresentative, CompanyOwner)
    expected = {(m.__tablename__, str(c.name)) for m in models for c in m.__table__.constraints}
    actual = set(conn.execute(
        """SELECT r.relname,c.conname FROM pg_constraint c JOIN pg_class r ON r.oid=c.conrelid
           JOIN pg_namespace n ON n.oid=r.relnamespace
           WHERE n.nspname='public' AND r.relname=ANY(%s)""", (list(TABLES),)
    ).fetchall())
    assert actual == expected, (expected-actual, actual-expected)
    sequences = [conn.execute("SELECT pg_get_serial_sequence(%s,'id')", (name,)).fetchone()[0]
                 for name in TABLES[:3]]
    assert len(set(sequences)) == 3 and all(sequences)
    assert conn.execute("SELECT pg_get_serial_sequence('company_owners','company_id')").fetchone()[0] is None
    assert conn.execute(
        "SELECT count(*) FROM pg_indexes WHERE schemaname='public' AND tablename=ANY(%s)",
        (list(TABLES),),
    ).fetchone()[0] == 12
    assert conn.execute(
        """SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
           WHERE n.nspname='public' AND c.relname=ANY(%s)
             AND c.relrowsecurity AND c.relforcerowsecurity""", (list(TABLES),)
    ).fetchone()[0] == 4
    policies = conn.execute(
        """SELECT tablename,permissive,qual,with_check FROM pg_policies
           WHERE schemaname='public' AND tablename=ANY(%s)""", (list(TABLES),)
    ).fetchall()
    assert len(policies) == 8 and sum(row[1] == "RESTRICTIVE" for row in policies) == 4
    assert all("app.current_tenant" in row[2] and "app.current_tenant" in row[3] for row in policies)
    for name in TABLES:
        assert conn.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')",
                            (RUNTIME, name)).fetchone()[0]
        assert not conn.execute("SELECT has_table_privilege(%s,%s,'TRUNCATE')",
                                (RUNTIME, name)).fetchone()[0]
    for seq in sequences:
        assert conn.execute("SELECT has_sequence_privilege(%s,%s,'USAGE,SELECT')",
                            (RUNTIME, seq)).fetchone()[0]
        assert not conn.execute("SELECT has_sequence_privilege(%s,%s,'UPDATE')",
                                (RUNTIME, seq)).fetchone()[0]


def verify_constraints(conn, legacy_company):
    a, b = company(conn, "IDENTITY-TEST-A"), company(conn, "IDENTITY-TEST-B")
    principal(conn, a, "unused", "BACKOFFICE")  # Make profile/principal id independence visible.
    pa = principal(conn, a, "same-name", "BACKOFFICE")
    fa = principal(conn, a, "field-a", "FIELD_REPRESENTATIVE")
    pb = principal(conn, b, "same-name", "BACKOFFICE")  # Username may repeat across companies.
    fb = principal(conn, b, "field-b", "FIELD_REPRESENTATIVE")
    second = principal(conn, a, "second-office", "BACKOFFICE")
    ba, bb, other = backoffice(conn, a, pa), backoffice(conn, b, pb), backoffice(conn, a, second)
    field_a = conn.execute(
        "INSERT INTO field_representatives(company_id,principal_id) VALUES (%s,%s) RETURNING id",
        (a, fa),
    ).fetchone()[0]
    conn.execute("INSERT INTO field_representatives(id,company_id,principal_id) VALUES (900007,%s,%s)", (b, fb))
    assert ba != pa and field_a != fa
    conn.execute("INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,%s)", (a, ba))
    cases = [
        ("INSERT INTO company_principals(company_id,username,password_hash,full_name,principal_type) "
         "VALUES (%s,'same-name','x','x','BACKOFFICE')", (a,), "23505"),
        ("INSERT INTO company_principals(company_id,username,password_hash,full_name,principal_type) "
         "VALUES (%s,'bad-type','x','x','DRIVER')", (a,), "23514"),
        ("INSERT INTO company_principals(company_id,username,password_hash,full_name,principal_type,auth_revision) "
         "VALUES (%s,'bad-revision','x','x','BACKOFFICE',0)", (a,), "23514"),
        ("INSERT INTO company_principals(company_id,username,password_hash,full_name,principal_type) "
         "VALUES (999999999,'orphan','x','x','BACKOFFICE')", (), "23503"),
        ("INSERT INTO backoffice_users(company_id,principal_id) VALUES (%s,%s)", (b, pa), "23503"),
        ("INSERT INTO backoffice_users(company_id,principal_id) VALUES (%s,%s)", (a, fa), "23503"),
        ("INSERT INTO field_representatives(company_id,principal_id) VALUES (%s,%s)", (a, pa), "23503"),
        ("INSERT INTO backoffice_users(company_id,principal_id,principal_type) VALUES (%s,%s,'FIELD_REPRESENTATIVE')",
         (a, fa), "23514"),
        ("INSERT INTO field_representatives(company_id,principal_id,principal_type) VALUES (%s,%s,'BACKOFFICE')",
         (a, pa), "23514"),
        ("INSERT INTO backoffice_users(company_id,principal_id) VALUES (%s,%s)", (a, pa), "23505"),
        ("INSERT INTO field_representatives(company_id,principal_id) VALUES (%s,%s)", (a, fa), "23505"),
        ("UPDATE company_principals SET principal_type='FIELD_REPRESENTATIVE' WHERE id=%s", (pa,), "23503"),
        ("UPDATE field_representatives SET max_debt_limit=-0.001 WHERE id=%s", (field_a,), "23514"),
        ("INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,%s)", (a, other), "23505"),
        ("INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,%s)", (b, ba), "23503"),
        ("INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,900007)", (b,), "23503"),
        ("DELETE FROM backoffice_users WHERE id=%s", (ba,), "23503"),
        ("DELETE FROM company_principals WHERE id=%s", (pa,), "23503"),
    ]
    for query, params, code in cases:
        expect_error(conn, query, params, code)
    conn.execute("INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,%s)", (b, bb))
    # Expand did not select an owner for the unrelated synthetic legacy company.
    assert conn.execute("SELECT count(*) FROM company_owners WHERE company_id=%s",
                        (legacy_company,)).fetchone()[0] == 0
    return {"a": a, "b": b, "pb": pb, "fb": fb, "bb": bb, "negative_constraints": len(cases)}


def verify_rls(admin, connection_args, fixture):
    # A permissive future policy must not defeat the restrictive tenant fence.
    for table in TABLES:
        admin.execute(f'CREATE POLICY identity_gate_permissive ON "{table}" USING (true) WITH CHECK (true)')
    try:
        with psycopg.connect(**connection_args, user=RUNTIME, autocommit=True) as conn:
            assert conn.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()[0] is False
            for table in TABLES:
                assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            for tenant in (fixture["a"], fixture["b"]):
                with conn.transaction():
                    conn.execute("SELECT set_config('app.current_tenant',%s,true)", (str(tenant),))
                    for table in TABLES:
                        rows = conn.execute(f"SELECT DISTINCT company_id FROM {table}").fetchall()
                        assert rows == [(tenant,)], (table, rows)
            with conn.transaction():
                conn.execute("SELECT set_config('app.current_tenant',%s,true)", (str(fixture["a"]),))
                for table in TABLES:
                    assert conn.execute(f"UPDATE {table} SET company_id=company_id WHERE company_id=%s",
                                        (fixture["b"],)).rowcount == 0
                    assert conn.execute(f"DELETE FROM {table} WHERE company_id=%s",
                                        (fixture["b"],)).rowcount == 0
                cases = [
                    ("INSERT INTO company_principals(company_id,username,password_hash,full_name,principal_type) "
                     "VALUES (%s,'forbidden','x','x','BACKOFFICE')", (fixture["b"],)),
                    ("INSERT INTO backoffice_users(company_id,principal_id) VALUES (%s,%s)",
                     (fixture["b"], fixture["pb"])),
                    ("INSERT INTO field_representatives(company_id,principal_id) VALUES (%s,%s)",
                     (fixture["b"], fixture["fb"])),
                    ("INSERT INTO company_owners(company_id,backoffice_user_id) VALUES (%s,%s)",
                     (fixture["b"], fixture["bb"])),
                ]
                for query, params in cases:
                    expect_error(conn, query, params, "42501")
            with conn.transaction():
                conn.execute("SELECT set_config('app.current_tenant','',true)")
                for table in TABLES:
                    assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
    finally:
        for table in TABLES:
            admin.execute(f'DROP POLICY identity_gate_permissive ON "{table}"')


def verify_downgrade_insert_race(admin, connection_args, company_id, alembic):
    """A row committed while downgrade waits must be retained, never dropped."""
    with psycopg.connect(**connection_args, user=ADMIN, autocommit=True) as writer:
        writer.execute("BEGIN")
        actor_id = principal(writer, company_id, "downgrade-race", "BACKOFFICE")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(alembic, "downgrade", PREVIOUS)
            try:
                deadline = time.monotonic() + 30
                while not admin.execute(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE relation="
                    "'company_principals'::regclass AND mode='AccessExclusiveLock' AND NOT granted)"
                ).fetchone()[0]:
                    if future.done() or time.monotonic() >= deadline:
                        raise AssertionError("Downgrade did not wait for the in-flight identity writer")
                    time.sleep(0.1)
                writer.execute("COMMIT")
                try:
                    future.result(timeout=40)
                except RuntimeError as exc:
                    assert "Cannot downgrade populated identity tables" in str(exc)
                else:
                    raise AssertionError("Downgrade erased an identity committed while it waited")
            finally:
                writer.execute("ROLLBACK")
        assert admin.execute("SELECT id FROM company_principals WHERE id=%s", (actor_id,)).fetchone() == (actor_id,)
        assert admin.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
        admin.execute("DELETE FROM company_principals WHERE id=%s", (actor_id,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true", help="Explicitly allow a new isolated local test cluster.")
    parser.add_argument("--pg-bin", type=Path, default=Path(r"C:\Program Files\PostgreSQL\16\bin")
                        if os.name == "nt" else Path("/usr/lib/postgresql/16/bin"))
    args = parser.parse_args()
    if not args.run:
        parser.error("--run required; no existing database URL is accepted")
    assert Path.cwd().resolve() == BACKEND
    for binary in ("initdb", "pg_ctl"):
        assert (args.pg_bin / (binary + (".exe" if os.name == "nt" else ""))).is_file()
    pg = lambda name: str(args.pg_bin / (name + (".exe" if os.name == "nt" else "")))
    assert re.search(r"PostgreSQL\) 16\.", run([pg("pg_ctl"), "--version"]))
    cluster = Path(tempfile.mkdtemp(prefix="wanasah_identity_expand_")).resolve()
    data = cluster / "data"
    evidence = BACKEND / "tests/IDENTITY_SCHEMA_EXPAND_VALIDATION.md"
    checks = []
    started = False
    failure = None
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    env = os.environ.copy()
    env.update({
        "PYTHONDONTWRITEBYTECODE": "1", "ENVIRONMENT": "test",
        "SECRET_KEY": "IdentityExpandTestOnlyAbc123456789012345678901234567",
        "DATABASE_URL": f"postgresql+asyncpg://{RUNTIME}@127.0.0.1:{port}/{DATABASE}",
        "DATABASE_URL_MIGRATION": f"postgresql+asyncpg://{ADMIN}@127.0.0.1:{port}/{DATABASE}",
    })
    # Also cover imports in this test process without reading the developer env.
    os.environ.update({k: env[k] for k in ("PYTHONDONTWRITEBYTECODE", "ENVIRONMENT", "SECRET_KEY", "DATABASE_URL", "DATABASE_URL_MIGRATION")})
    sys.path.insert(0, str(BACKEND))

    def checkpoint(label):
        checks.append(label)
        print(label + "=PASS", flush=True)

    def alembic(*arguments):
        return run([sys.executable, "-m", "alembic", *arguments], env=env)

    try:
        run([pg("initdb"), "-D", str(data), "-U", ADMIN, "--auth=trust", "--encoding=UTF8", "--no-locale"])
        run([pg("pg_ctl"), "-D", str(data), "-l", str(cluster / "postgres.log"),
             "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], pg_ctl=True)
        started = True
        print(f"ISOLATED_CLUSTER_STARTED={cluster}", flush=True)
        connect = {"host": "127.0.0.1", "port": port, "dbname": DATABASE}
        with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user=ADMIN, autocommit=True) as conn:
            assert Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve() == data
            conn.execute(f"CREATE ROLE {RUNTIME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
            conn.execute(f"CREATE DATABASE {DATABASE}")
        alembic("upgrade", PREVIOUS)
        checkpoint("CLEAN_BASELINE_BOOTSTRAP")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            legacy_company = company(conn, "IDENTITY-LEGACY-SENTINEL")
            legacy_driver = conn.execute(
                """INSERT INTO drivers(company_id,username,password_hash,full_name,is_active,is_admin,created_at)
                   VALUES (%s,'legacy-sentinel','synthetic','Legacy sentinel',true,true,CURRENT_TIMESTAMP) RETURNING id""",
                (legacy_company,),
            ).fetchone()[0]
            legacy = legacy_contract(conn)
            assert conn.execute(
                "SELECT count(*) FROM pg_constraint WHERE contype='f' AND confrelid='drivers'::regclass"
            ).fetchone()[0] == 55
        alembic("upgrade", "head")
        checkpoint("ADDITIVE_EXPAND_UPGRADE")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            assert legacy_contract(conn) == legacy
            for table in TABLES:
                assert conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0
            verify_schema(conn)
            checkpoint("CONSTRAINTS_INDEXES_RLS_GRANTS_SEQUENCES")
            fixture = verify_constraints(conn, legacy_company)
            checkpoint(f"NEGATIVE_CONSTRAINTS_{fixture['negative_constraints']}")
            verify_rls(conn, connect, fixture)
            checkpoint("RUNTIME_RLS_ALL_FOUR_TABLES_MISSING_AND_FOREIGN_TENANT")
            try:
                alembic("downgrade", PREVIOUS)
            except RuntimeError as exc:
                assert "Cannot downgrade populated identity tables" in str(exc)
            else:
                raise AssertionError("Populated downgrade unexpectedly succeeded")
            assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
            checkpoint("POPULATED_DOWNGRADE_REFUSED_AT_HEAD")
            # Only our four new tables in this independently-created test cluster.
            for table in reversed(TABLES):
                conn.execute(f"DELETE FROM {table}")
            assert legacy_contract(conn) == legacy
            verify_downgrade_insert_race(conn, connect, legacy_company, alembic)
            checkpoint("CONCURRENT_INSERT_PREVENTS_DOWNGRADE_DATA_LOSS")
        check_output = alembic("check")
        assert "No new upgrade operations detected" in check_output
        checkpoint("ALEMBIC_MODEL_DRIFT_CHECK")
        alembic("downgrade", PREVIOUS)
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            for table in TABLES:
                assert conn.execute("SELECT to_regclass(%s)", (table,)).fetchone()[0] is None
            assert legacy_contract(conn) == legacy
            assert conn.execute("SELECT is_admin FROM drivers WHERE id=%s", (legacy_driver,)).fetchone() == (True,)
        alembic("upgrade", "head")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            verify_schema(conn)
            assert legacy_contract(conn) == legacy
            assert conn.execute("SELECT is_admin FROM drivers WHERE id=%s", (legacy_driver,)).fetchone() == (True,)
        checkpoint("EMPTY_DOWNGRADE_UPGRADE_AND_LEGACY_PRESERVATION")
    except Exception as exc:
        failure = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if started or (data / "postmaster.pid").exists():
            run([pg("pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], pg_ctl=True)
            checkpoint("ISOLATED_CLUSTER_STOPPED")
        body = [
            "# Identity additive schema validation", "",
            "Source main: 5cf830518580f9287fb141d29355e7b62b88ba70.",
            f"Migration: {REVISION}; down_revision: {PREVIOUS}.", "",
            "Existing backend interpreter/packages only; no installations or developer database access.",
            "Fresh PostgreSQL 16 cluster bound only to 127.0.0.1; all data synthetic.",
            f"Retained stopped cluster/log path: {cluster}.", "",
            "## Results", "",
            *[f"- PASS: {label}" for label in checks],
            *(["", f"- BLOCKED/FAIL: {failure}"] if failure else []), "",
            "Owner slot uniqueness/Backoffice/type linkage are DB-enforced. Expand leaves all four",
            "tables empty; exactly-one owner presence for each operating company belongs to the later",
            "approved provisioning/live-data preflight and cutover. No legacy owner was selected.",
            "Runtime role grants follow existing backend DML conventions; protected ownership mutation",
            "authorization remains part of the later dedicated workflow, with no owner-management API here.",
            "Downgrade accepts only empty new tables and refuses populated identity tables before any DROP.",
            "The emptiness check holds ACCESS EXCLUSIVE locks; a concurrent committed insert was retained.",
            "No legacy FK or ambiguous actor field was changed or classified.",
        ]
        evidence.write_text("\n".join(body) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
