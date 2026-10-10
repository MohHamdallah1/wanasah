"""Principal refresh expand gate in a NEW synthetic localhost PostgreSQL 16 cluster.

Never accepts existing database URLs or reads developer credentials. No installs.
Run from wa_backend: python tests/run_principal_refresh_session_expand_gate.py --run
"""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import time

import psycopg
from psycopg import sql

import run_identity_schema_expand_gate as fixtures

BACKEND = Path(__file__).resolve().parents[1]
TABLE = "principal_refresh_tokens"
REVISION, PREVIOUS = "b7e3f6a1c902", "a4d2e7c9b630"
ADMIN, RUNTIME, DATABASE = "principal_refresh_admin", "principal_refresh_runtime", "principal_refresh_test"


def old_rows(conn):
    digest = hashlib.sha256()
    tables = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename").fetchall()
    for (table,) in tables:
        if table in (TABLE, "alembic_version"):
            continue
        rows = conn.execute(sql.SQL("SELECT to_jsonb(t) FROM {} t ORDER BY to_jsonb(t)::text").format(sql.Identifier(table))).fetchall()
        digest.update(json.dumps([table, rows], sort_keys=True, default=str).encode())
    return digest.hexdigest()


def session(conn, company_id, principal_id, token, channel="DASHBOARD"):
    # Synthetic persistence fixtures only: never invoke JWT codecs/login/rotation.
    return conn.execute(f"INSERT INTO {TABLE}(company_id,principal_id,channel,token,expires_at,auth_revision) "
                        "VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP + interval '30 days',1) RETURNING id",
                        (company_id, principal_id, channel, token)).fetchone()[0]


def seed_old(conn):
    a, b = fixtures.company(conn, "REFRESH-A"), fixtures.company(conn, "REFRESH-B")
    pa = fixtures.principal(conn, a, "office-a", "BACKOFFICE")
    other = fixtures.principal(conn, a, "office-other", "BACKOFFICE")
    pb = fixtures.principal(conn, b, "office-b", "BACKOFFICE")
    legacy = conn.execute("INSERT INTO drivers(company_id,username,password_hash,full_name,created_at) "
                          "VALUES (%s,'legacy','synthetic-no-login','Synthetic legacy',CURRENT_TIMESTAMP) RETURNING id", (a,)).fetchone()[0]
    successor = conn.execute("INSERT INTO refresh_tokens(token,driver_id,expires_at,is_revoked,created_at) "
                            "VALUES ('synthetic-legacy-next',%s,CURRENT_TIMESTAMP + interval '30 days',false,CURRENT_TIMESTAMP) RETURNING id", (legacy,)).fetchone()[0]
    conn.execute("INSERT INTO refresh_tokens(token,driver_id,expires_at,is_revoked,replaced_by_id,created_at) "
                 "VALUES ('synthetic-legacy-old',%s,CURRENT_TIMESTAMP + interval '30 days',true,%s,CURRENT_TIMESTAMP)", (legacy, successor))
    return {"a": a, "b": b, "pa": pa, "pb": pb, "other": other}


def verify_schema(conn):
    from domains.auth_sessions.models import PrincipalRefreshToken
    table = PrincipalRefreshToken.__table__
    expected = {str(c.name) for c in table.constraints}
    actual = {row[0] for row in conn.execute("SELECT conname FROM pg_constraint WHERE conrelid=%s::regclass", (TABLE,))}
    assert expected == actual and len(actual) == 8
    actual_indexes = {name: definition for name, definition in conn.execute(
        "SELECT indexname,indexdef FROM pg_indexes WHERE schemaname='public' AND tablename=%s", (TABLE,))}
    assert len(actual_indexes) == 8
    for index in table.indexes:
        assert index.name in actual_indexes
        columns = ", ".join(c.name for c in index.columns)
        assert f"({columns})" in actual_indexes[index.name]
        assert ("CREATE UNIQUE INDEX" in actual_indexes[index.name]) == bool(index.unique)
    assert "(token)" in actual_indexes["uq_principal_refresh_tokens_token"]
    assert conn.execute("SELECT relrowsecurity AND relforcerowsecurity FROM pg_class WHERE oid=%s::regclass", (TABLE,)).fetchone()[0]
    policies = conn.execute("SELECT permissive,qual,with_check FROM pg_policies WHERE schemaname='public' AND tablename=%s", (TABLE,)).fetchall()
    assert len(policies) == 2 and {p[0] for p in policies} == {"PERMISSIVE", "RESTRICTIVE"}
    assert all("app.current_tenant" in row[1] and "app.current_tenant" in row[2] for row in policies)
    assert conn.execute("SELECT has_table_privilege(%s,%s,'SELECT,INSERT,UPDATE,DELETE')", (RUNTIME, TABLE)).fetchone()[0]
    assert not conn.execute("SELECT has_table_privilege(%s,%s,'TRUNCATE')", (RUNTIME, TABLE)).fetchone()[0]
    seq = conn.execute("SELECT pg_get_serial_sequence(%s,'id')", (TABLE,)).fetchone()[0]
    assert seq == "public.principal_refresh_tokens_id_seq"
    assert conn.execute("SELECT has_sequence_privilege(%s,%s,'USAGE,SELECT')", (RUNTIME, seq)).fetchone()[0]
    assert not conn.execute("SELECT has_sequence_privilege(%s,%s,'UPDATE')", (RUNTIME, seq)).fetchone()[0]


def verify_constraints(conn, f):
    a, pa = f["a"], f["pa"]
    old = session(conn, a, pa, "synthetic-new-old")
    successor = session(conn, a, pa, "synthetic-new-next")
    alternative = session(conn, a, f["other"], "synthetic-other-principal")
    different_channel = session(conn, a, pa, "synthetic-other-channel", "FIELD")
    foreign = session(conn, f["b"], f["pb"], "synthetic-foreign")
    another = session(conn, a, pa, "synthetic-another-predecessor")
    conn.execute(f"UPDATE {TABLE} SET is_revoked=true,replaced_by_id=%s WHERE id=%s", (successor, old))
    assert conn.execute(f"SELECT token FROM {TABLE} WHERE id=(SELECT replaced_by_id FROM {TABLE} WHERE token=%s)",
                        ("synthetic-new-old",)).fetchone() == ("synthetic-new-next",)
    insert = f"INSERT INTO {TABLE}(company_id,principal_id,channel,token,expires_at,auth_revision) VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP,%s)"
    cases = [
        (insert, (a, pa, "ADMIN", "invalid-channel", 1), "23514"),
        (insert, (a, pa, "dashboard", "invalid-case", 1), "23514"),
        (insert, (a, pa, "DASHBOARD", "zero-revision", 0), "23514"),
        (insert, (a, pa, "DASHBOARD", "negative-revision", -1), "23514"),
        (insert, (a, pa, "DASHBOARD", "null-revision", None), "23502"),
        (insert, (a, pa, None, "null-channel", 1), "23502"),
        (insert, (a, f["pb"], "DASHBOARD", "foreign-principal", 1), "23503"),
        (insert, (a, 99999999, "DASHBOARD", "orphan-principal", 1), "23503"),
        (insert, (a, pa, "DASHBOARD", "synthetic-new-next", 1), "23505"),
        (insert, (f["b"], f["pb"], "DASHBOARD", "synthetic-new-next", 1), "23505"),
        (f"UPDATE {TABLE} SET replaced_by_id=%s WHERE id=%s", (foreign, another), "23503"),
        (f"UPDATE {TABLE} SET replaced_by_id=%s WHERE id=%s", (alternative, another), "23503"),
        (f"UPDATE {TABLE} SET replaced_by_id=%s WHERE id=%s", (different_channel, another), "23503"),
        (f"UPDATE {TABLE} SET replaced_by_id=%s WHERE id=%s", (99999999, another), "23503"),
        (f"UPDATE {TABLE} SET replaced_by_id=%s WHERE id=%s", (successor, another), "23505"),
        (f"UPDATE {TABLE} SET channel='FIELD' WHERE id=%s", (successor,), "23503"),
    ]
    for query, params, code in cases:
        fixtures.expect_error(conn, query, params, code)
    # Legacy SET NULL behavior survives, without nulling the composite identity.
    conn.execute(f"DELETE FROM {TABLE} WHERE id=%s", (successor,))
    assert conn.execute(f"SELECT company_id,principal_id,channel,replaced_by_id,is_revoked FROM {TABLE} WHERE id=%s", (old,)).fetchone() == (a, pa, "DASHBOARD", None, True)
    # Multiple sessions and null successor pointers remain allowed per legacy semantics.
    assert conn.execute(f"SELECT count(*) FROM {TABLE} WHERE principal_id=%s AND replaced_by_id IS NULL", (pa,)).fetchone()[0] == 3
    parent = fixtures.principal(conn, a, "cascade-only", "BACKOFFICE")
    parent_old = session(conn, a, parent, "synthetic-cascade-old")
    parent_next = session(conn, a, parent, "synthetic-cascade-next")
    conn.execute(f"UPDATE {TABLE} SET replaced_by_id=%s WHERE id=%s", (parent_next, parent_old))
    conn.execute("DELETE FROM company_principals WHERE id=%s", (parent,))
    assert conn.execute(f"SELECT count(*) FROM {TABLE} WHERE principal_id=%s", (parent,)).fetchone()[0] == 0
    f.update(old=old, foreign=foreign)
    return len(cases)


def verify_rls(admin, connect, f):
    admin.execute(f'CREATE POLICY refresh_gate_permissive ON "{TABLE}" USING (true) WITH CHECK (true)')
    try:
        with psycopg.connect(**connect, user=RUNTIME, autocommit=True) as conn:
            assert conn.execute("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()[0] is False
            assert conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0] == 0
            for company_id in (f["a"], f["b"]):
                with conn.transaction():
                    conn.execute("SELECT set_config('app.current_tenant',%s,true)", (str(company_id),))
                    assert conn.execute(f"SELECT DISTINCT company_id FROM {TABLE}").fetchall() == [(company_id,)]
            with conn.transaction():
                conn.execute("SELECT set_config('app.current_tenant',%s,true)", (str(f["a"]),))
                assert conn.execute(f"SELECT id FROM {TABLE} WHERE token='synthetic-foreign'").fetchone() is None
                assert conn.execute(f"UPDATE {TABLE} SET is_revoked=true WHERE company_id=%s", (f["b"],)).rowcount == 0
                assert conn.execute(f"DELETE FROM {TABLE} WHERE company_id=%s", (f["b"],)).rowcount == 0
                fixtures.expect_error(conn, f"INSERT INTO {TABLE}(company_id,principal_id,channel,token,expires_at,auth_revision) "
                                     "VALUES (%s,%s,'DASHBOARD','forbidden-tenant',CURRENT_TIMESTAMP,1)", (f["b"], f["pb"]), "42501")
                own = session(conn, f["a"], f["pa"], "synthetic-runtime-owned")
                assert conn.execute(f"UPDATE {TABLE} SET is_revoked=true WHERE id=%s", (own,)).rowcount == 1
                fixtures.expect_error(conn, f"UPDATE {TABLE} SET company_id=%s,principal_id=%s WHERE id=%s", (f["b"], f["pb"], own), "42501")
                fixtures.expect_error(conn, f"UPDATE {TABLE} SET replaced_by_id=%s WHERE id=%s", (f["foreign"], own), "23503")
                assert conn.execute(f"DELETE FROM {TABLE} WHERE id=%s", (own,)).rowcount == 1
                fixtures.expect_error(conn, f"TRUNCATE {TABLE}", (), "42501")
                fixtures.expect_error(conn, "SELECT setval('principal_refresh_tokens_id_seq',1)", (), "42501")
            with conn.transaction():
                conn.execute("SELECT set_config('app.current_tenant','',true)")
                assert conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0] == 0
    finally:
        admin.execute(f'DROP POLICY refresh_gate_permissive ON "{TABLE}"')


def populated_refusal(conn, alembic):
    before = conn.execute(f"SELECT id FROM {TABLE} ORDER BY id").fetchall()
    try:
        alembic("downgrade", PREVIOUS)
    except RuntimeError as exc:
        assert "Cannot downgrade populated principal refresh sessions" in str(exc)
    else:
        raise AssertionError("Populated downgrade destroyed sessions")
    assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
    assert conn.execute(f"SELECT id FROM {TABLE} ORDER BY id").fetchall() == before


def downgrade_writer_race(admin, connect, f, alembic):
    with psycopg.connect(**connect, user=ADMIN, autocommit=True) as writer:
        writer.execute("BEGIN")
        row_id = session(writer, f["a"], f["pa"], "synthetic-downgrade-race")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(alembic, "downgrade", PREVIOUS)
            try:
                deadline = time.monotonic() + 30
                while not admin.execute("SELECT EXISTS(SELECT 1 FROM pg_locks WHERE relation='principal_refresh_tokens'::regclass AND mode='AccessExclusiveLock' AND NOT granted)").fetchone()[0]:
                    if future.done() or time.monotonic() >= deadline:
                        raise AssertionError("Downgrade did not wait for concurrent session insert")
                    time.sleep(0.1)
                writer.execute("COMMIT")
                try:
                    future.result(timeout=40)
                except RuntimeError as exc:
                    assert "Cannot downgrade populated principal refresh sessions" in str(exc)
                else:
                    raise AssertionError("Concurrent session silently erased")
            finally:
                writer.execute("ROLLBACK")
        assert admin.execute(f"SELECT id FROM {TABLE} WHERE id=%s", (row_id,)).fetchone() == (row_id,)
        admin.execute(f"DELETE FROM {TABLE} WHERE id=%s", (row_id,))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--pg-bin", type=Path, default=Path(r"C:\Program Files\PostgreSQL\16\bin") if os.name == "nt" else Path("/usr/lib/postgresql/16/bin"))
    args = parser.parse_args()
    if not args.run:
        parser.error("--run required; no existing database URL is accepted")
    assert Path.cwd().resolve() == BACKEND
    pg = lambda name: str(args.pg_bin / (name + (".exe" if os.name == "nt" else "")))
    cluster = Path(tempfile.mkdtemp(prefix="wanasah_principal_refresh_")).resolve()
    data = cluster / "data"
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "ENVIRONMENT": "test", "SECRET_KEY": "PrincipalRefreshSynthetic12345678901234567890123456",
                "DATABASE_URL": f"postgresql+asyncpg://{RUNTIME}@127.0.0.1:{port}/{DATABASE}",
                "DATABASE_URL_MIGRATION": f"postgresql+asyncpg://{ADMIN}@127.0.0.1:{port}/{DATABASE}"})
    os.environ.update({key: env[key] for key in ("PYTHONDONTWRITEBYTECODE", "ENVIRONMENT", "SECRET_KEY", "DATABASE_URL", "DATABASE_URL_MIGRATION")})
    sys.path.insert(0, str(BACKEND))
    checks, started, failure = [], False, None
    fixtures.TABLES = (TABLE,)  # Fingerprint every pre-existing table, including identity/bridge.
    def checkpoint(label):
        checks.append(label)
        print(label + "=PASS", flush=True)
    def alembic(*arguments):
        return fixtures.run([sys.executable, "-m", "alembic", *arguments], env=env)
    try:
        fixtures.run([pg("initdb"), "-D", str(data), "-U", ADMIN, "--auth=trust", "--encoding=UTF8", "--no-locale"])
        fixtures.run([pg("pg_ctl"), "-D", str(data), "-l", str(cluster / "postgres.log"), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], pg_ctl=True)
        started = True
        print(f"ISOLATED_CLUSTER_STARTED={cluster}", flush=True)
        connect = {"host": "127.0.0.1", "port": port, "dbname": DATABASE}
        with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user=ADMIN, autocommit=True) as conn:
            assert Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve() == data
            conn.execute(f"CREATE ROLE {RUNTIME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
            conn.execute(f"CREATE DATABASE {DATABASE}")
        alembic("upgrade", PREVIOUS)
        checkpoint("CLEAN_BOOTSTRAP_TO_CURRENT_HEAD")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            f = seed_old(conn)
            schema, rows = fixtures.legacy_contract(conn), old_rows(conn)
        alembic("upgrade", "head")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            assert conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0] == 0
            verify_schema(conn)
            checkpoint("ADDITIVE_EMPTY_UPGRADE_CONSTRAINTS_EIGHT_INDEXES_RLS_GRANTS_SEQUENCE")
            count = verify_constraints(conn, f)
            checkpoint(f"FK_CHECK_UNIQUE_REJECTION_CASES_{count}")
            checkpoint("EXACT_TOKEN_LOOKUP_SUCCESSOR_UNIQUENESS_DELETE_SET_NULL_CASCADE")
            verify_rls(conn, connect, f)
            checkpoint("TENANT_RLS_READ_WRITE_REPLACEMENT_AND_RESTRICTIVE_POLICY")
            populated_refusal(conn, alembic)
            checkpoint("POPULATED_DOWNGRADE_REFUSED_WITH_ROWS_AND_HEAD_RETAINED")
            assert fixtures.legacy_contract(conn) == schema and old_rows(conn) == rows
            assert conn.execute("SELECT count(*) FROM pg_constraint WHERE contype='f' AND confrelid='drivers'::regclass").fetchone()[0] == 56
            checkpoint("ALL_OLD_SCHEMA_ROWS_56_DRIVER_FKS_LEGACY_REFRESH_ROTATION_PRESERVED")
            # Delete only new synthetic sessions in this owned isolated cluster.
            conn.execute(f"DELETE FROM {TABLE}")
            downgrade_writer_race(conn, connect, f, alembic)
            checkpoint("CONCURRENT_INSERT_PREVENTS_DOWNGRADE_DATA_LOSS")
        assert "No new upgrade operations detected" in alembic("check")
        checkpoint("ALEMBIC_METADATA_DRIFT_CHECK")
        alembic("downgrade", PREVIOUS)
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            assert conn.execute("SELECT to_regclass(%s)", (TABLE,)).fetchone()[0] is None
            assert fixtures.legacy_contract(conn) == schema and old_rows(conn) == rows
        alembic("upgrade", "head")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            verify_schema(conn)
            assert fixtures.legacy_contract(conn) == schema and old_rows(conn) == rows
            assert conn.execute(f"SELECT count(*) FROM {TABLE}").fetchone()[0] == 0
        checkpoint("EMPTY_DOWNGRADE_UPGRADE_ROUNDTRIP_AND_OLD_CONTRACT_PRESERVATION")
    except psycopg.Error as exc:
        failure = f"{type(exc).__name__} SQLSTATE={exc.sqlstate} table={exc.diag.table_name} column={exc.diag.column_name}"
        raise RuntimeError(failure) from None
    except Exception as exc:
        failure = type(exc).__name__
        raise
    finally:
        if started or (data / "postmaster.pid").exists():
            fixtures.run([pg("pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], pg_ctl=True)
            checkpoint("ISOLATED_CLUSTER_STOPPED")
        body = ["# Principal refresh persistence expand validation", "",
                "Source main: 93258405bccf3d86d6a3293b28028925b153f843.",
                f"Migration: {REVISION}; down_revision: {PREVIOUS}.",
                "Existing interpreter/packages only; fresh localhost PostgreSQL 16; all fixtures synthetic.",
                f"Retained stopped cluster/logs: {cluster}.", "",
                *[f"- PASS: {label}" for label in checks], *([f"- FAIL: {failure}"] if failure else []), "",
                "5 static/model/offline-DDL checks: python -m unittest tests/test_principal_refresh_session_expand.py -v.",
                "Isolated gate: python tests/run_principal_refresh_session_expand_gate.py --run (from wa_backend).", "",
                "Storage mirrors current RefreshToken: exact VARCHAR(500) token value, global token uniqueness,",
                "one predecessor per successor (unique nullable replaced_by_id), explicit expiry/revocation/created_at.",
                "Tenant principal FK and same-company/principal/channel successor FK are database-enforced.",
                "Successor deletion sets only replaced_by_id NULL; principal deletion cascades sessions, as legacy identity deletion does.",
                "auth_revision is required explicitly and must be positive; no implicit issuing revision is chosen.",
                "Eight constraints, eight indexes, two RLS policies (one restrictive), one independent sequence.",
                "Empty round-trip succeeds; populated downgrade refuses before DROP under ACCESS EXCLUSIVE lock.",
                "A session committed while downgrade waited was retained, and downgrade refused.",
                "All pre-existing table/column/constraint/index/RLS definitions and all old rows are fingerprint-preserved.",
                "56 current Driver FKs (55 original plus temporary bridge) remain unchanged.",
                "No JWTs issued or endpoints called. No legacy refresh conversion/revocation or runtime auth cutover.",
                "Channel/principal-type/profile/activity/revision validation, locking/rotation/grace and logout remain later runtime cutover work."]
        (BACKEND / "tests/PRINCIPAL_REFRESH_SESSION_EXPAND_VALIDATION.md").write_text("\n".join(body) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
