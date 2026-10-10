"""Focused lifecycle gate using only a NEW synthetic localhost PostgreSQL cluster.

No developer database/credentials, package installations or HTTP endpoints.
Run from wa_backend: python tests/run_principal_refresh_sessions_gate.py --run
"""
import argparse
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

import jwt
import psycopg
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import run_identity_schema_expand_gate as fixtures

BACKEND = Path(__file__).resolve().parents[1]
ADMIN, RUNTIME, DATABASE = "refresh_service_admin", "refresh_service_runtime", "refresh_service_test"
SECRET = "RefreshServiceSyntheticSecret123456789012345678901234567890"


def seed(conn):
    a, b = fixtures.company(conn, "SERVICE-A"), fixtures.company(conn, "SERVICE-B")
    pa = fixtures.principal(conn, a, "office", "BACKOFFICE")
    other = fixtures.principal(conn, a, "other", "BACKOFFICE")
    pb = fixtures.principal(conn, b, "office", "BACKOFFICE")
    pf = fixtures.principal(conn, a, "field", "FIELD_REPRESENTATIVE")
    no_bo = fixtures.principal(conn, a, "missing-office-profile", "BACKOFFICE")
    no_field = fixtures.principal(conn, a, "missing-field-profile", "FIELD_REPRESENTATIVE")
    bo = fixtures.backoffice(conn, a, pa)
    fixtures.backoffice(conn, a, other)
    fixtures.backoffice(conn, b, pb)
    field = conn.execute("INSERT INTO field_representatives(company_id,principal_id) VALUES (%s,%s) RETURNING id", (a, pf)).fetchone()[0]
    return dict(a=a, b=b, pa=pa, pb=pb, other=other, pf=pf, no_bo=no_bo, no_field=no_field, bo=bo, field=field)


async def lifecycle(admin, connect, url, f, checkpoint):
    from domains.auth_sessions import refresh_sessions as service
    from domains.auth_sessions.codec import issue_refresh_token, decode_company_token
    from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
    from domains.auth_sessions.models import PrincipalRefreshToken
    from domains.identity.models import CompanyPrincipal

    engine = create_async_engine(url, echo=False, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autobegin=False)
    office = DashboardRequestContext(principal_id=f["pa"], company_id=f["a"], backoffice_user_id=f["bo"], auth_revision=1, is_company_owner=False)
    field = FieldRequestContext(principal_id=f["pf"], company_id=f["a"], representative_id=f["field"], auth_revision=1)

    async def create(context=office):
        async with sessions() as db, db.begin():
            result = await service.create_refresh_session(db, context, secret=SECRET)
            assert db.in_transaction()
            return result

    async def rotate(token, clock=None):
        async with sessions() as db, db.begin():
            with patch.object(service, "_utc_now", return_value=clock) if clock else _no_patch():
                result = await service.rotate_refresh_session(db, token, secret=SECRET)
            assert db.in_transaction()
            return result

    async def reject(token, clock=None, tenant=None):
        count = admin.execute("SELECT count(*) FROM principal_refresh_tokens").fetchone()[0]
        async with sessions() as db, db.begin():
            if tenant is not None:
                await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"), {"c": str(tenant)})
            try:
                with patch.object(service, "_utc_now", return_value=clock) if clock else _no_patch():
                    await service.rotate_refresh_session(db, token, secret=SECRET)
            except service.RefreshSessionRejected:
                assert db.in_transaction()
                assert await db.scalar(text("SELECT 1")) == 1
            else:
                raise AssertionError("Expected closed refresh rejection")
        assert admin.execute("SELECT count(*) FROM principal_refresh_tokens").fetchone()[0] == count

    try:
        # Only caller boundary commits; another connection cannot see issuance until then.
        async with sessions() as db, db.begin():
            initial = await service.create_refresh_session(db, office, secret=SECRET)
            assert admin.execute("SELECT count(*) FROM principal_refresh_tokens WHERE token=%s", (initial.refresh_token,)).fetchone()[0] == 0
            claims = decode_company_token(initial.refresh_token, secret=SECRET, expected_type="refresh")
            row = await db.scalar(select(PrincipalRefreshToken).where(PrincipalRefreshToken.token == initial.refresh_token))
            assert row.company_id == claims.company_id and row.principal_id == claims.principal_id
            assert row.channel == claims.channel and row.auth_revision == claims.auth_revision
            assert row.expires_at == datetime.fromtimestamp(claims.exp, timezone.utc).replace(tzinfo=None)
            assert db.in_transaction()
        await create(field)
        checkpoint("NEW_DASHBOARD_FIELD_SESSIONS_EXACT_CANONICAL_BINDING_CALLER_COMMIT")

        class CallerAbort(Exception):
            pass
        try:
            async with sessions() as db, db.begin():
                tentative = await service.rotate_refresh_session(db, initial.refresh_token, secret=SECRET)
                predecessor = await db.scalar(select(PrincipalRefreshToken).where(PrincipalRefreshToken.token == initial.refresh_token))
                assert predecessor.is_revoked and predecessor.replaced_by_id is not None
                assert admin.execute("SELECT is_revoked,replaced_by_id FROM principal_refresh_tokens WHERE token=%s", (initial.refresh_token,)).fetchone() == (False, None)
                assert admin.execute("SELECT count(*) FROM principal_refresh_tokens WHERE token=%s", (tentative.refresh_token,)).fetchone()[0] == 0
                raise CallerAbort
        except CallerAbort:
            pass
        assert admin.execute("SELECT is_revoked,replaced_by_id FROM principal_refresh_tokens WHERE token=%s", (initial.refresh_token,)).fetchone() == (False, None)
        assert admin.execute("SELECT count(*) FROM principal_refresh_tokens WHERE token=%s", (tentative.refresh_token,)).fetchone()[0] == 0
        checkpoint("ROTATION_ATOMIC_AND_CALLER_ROLLBACK_RETAINS_PREDECESSOR")

        successor = await rotate(initial.refresh_token)
        saved = admin.execute("SELECT id,created_at FROM principal_refresh_tokens WHERE token=%s", (successor.refresh_token,)).fetchone()
        successor_id, created_at = saved
        assert admin.execute("SELECT is_revoked,replaced_by_id FROM principal_refresh_tokens WHERE token=%s", (initial.refresh_token,)).fetchone() == (True, successor_id)
        assert replace(successor, refresh_token=initial.refresh_token) == initial
        assert (await rotate(initial.refresh_token)).refresh_token == successor.refresh_token
        clock = created_at.replace(tzinfo=timezone.utc)
        assert (await rotate(initial.refresh_token, clock + timedelta(seconds=15))).refresh_token == successor.refresh_token
        await reject(initial.refresh_token, clock + timedelta(seconds=15, microseconds=1))
        await reject(initial.refresh_token, clock - timedelta(seconds=1))
        checkpoint("VALID_ROTATION_LINK_AND_GRACE_REPLAY_INCLUSIVE_15_SECONDS_NO_DUPLICATE")

        for column, wrong, correct in (("auth_revision", 2, 1), ("is_revoked", True, False),
                                       ("expires_at", datetime(2000, 1, 1), datetime.fromtimestamp(decode_company_token(successor.refresh_token, secret=SECRET).exp, timezone.utc).replace(tzinfo=None))):
            query = psycopg.sql.SQL("UPDATE principal_refresh_tokens SET {}=%s WHERE id=%s").format(psycopg.sql.Identifier(column))
            admin.execute(query, (wrong, successor_id))
            await reject(initial.refresh_token)
            admin.execute(query, (correct, successor_id))
        switched = issue_refresh_token(principal_id=f["other"], company_id=f["a"], channel="DASHBOARD", principal_type="BACKOFFICE", auth_revision=1, secret=SECRET)
        admin.execute("UPDATE principal_refresh_tokens SET token=%s WHERE id=%s", (switched, successor_id))
        await reject(initial.refresh_token)
        admin.execute("UPDATE principal_refresh_tokens SET token=%s WHERE id=%s", (successor.refresh_token, successor_id))
        checkpoint("REVOKED_EXPIRED_REVISION_OR_SIGNED_IDENTITY_MISMATCH_SUCCESSOR_REFUSED")

        candidate = await create()
        for column, wrong, correct in (("principal_id", f["other"], f["pa"]), ("channel", "FIELD", "DASHBOARD"),
                                       ("auth_revision", 2, 1), ("expires_at", datetime(2000, 1, 1), datetime.fromtimestamp(decode_company_token(candidate.refresh_token, secret=SECRET).exp, timezone.utc).replace(tzinfo=None))):
            query = psycopg.sql.SQL("UPDATE principal_refresh_tokens SET {}=%s WHERE token=%s").format(psycopg.sql.Identifier(column))
            admin.execute(query, (wrong, candidate.refresh_token))
            await reject(candidate.refresh_token)
            admin.execute(query, (correct, candidate.refresh_token))
        admin.execute("UPDATE principal_refresh_tokens SET company_id=%s,principal_id=%s WHERE token=%s", (f["b"], f["pb"], candidate.refresh_token))
        await reject(candidate.refresh_token)
        admin.execute("UPDATE principal_refresh_tokens SET company_id=%s,principal_id=%s WHERE token=%s", (f["a"], f["pa"], candidate.refresh_token))
        await reject(candidate.refresh_token, tenant=f["b"])
        for table, key, column, wrong, correct in (("companies", f["a"], "is_active", False, True),
                                                   ("company_principals", f["pa"], "is_active", False, True),
                                                   ("company_principals", f["pa"], "auth_revision", 2, 1)):
            query = psycopg.sql.SQL("UPDATE {} SET {}=%s WHERE id=%s").format(psycopg.sql.Identifier(table), psycopg.sql.Identifier(column))
            admin.execute(query, (wrong, key))
            await reject(candidate.refresh_token)
            admin.execute(query, (correct, key))
        checkpoint("WRONG_COMPANY_PRINCIPAL_CHANNEL_REVISION_DISABLED_COMPANY_PRINCIPAL_REFUSED")

        for principal_id, channel, kind in ((f["no_bo"], "DASHBOARD", "BACKOFFICE"), (f["no_field"], "FIELD", "FIELD_REPRESENTATIVE"),
                                            (f["pa"], "FIELD", "FIELD_REPRESENTATIVE")):
            token = issue_refresh_token(principal_id=principal_id, company_id=f["a"], channel=channel, principal_type=kind, auth_revision=1, secret=SECRET)
            admin.execute("INSERT INTO principal_refresh_tokens(company_id,principal_id,channel,token,expires_at,auth_revision) "
                          "VALUES (%s,%s,%s,%s,CURRENT_TIMESTAMP + interval '30 days',1)", (f["a"], principal_id, channel, token))
            await reject(token)
        async with sessions() as db, db.begin():
            try:
                await service.create_refresh_session(db, replace(office, backoffice_user_id=999999), secret=SECRET)
            except service.RefreshSessionRejected:
                assert db.in_transaction()
            else:
                raise AssertionError("Wrong authenticated profile accepted")
        checkpoint("MISSING_BACKOFFICE_FIELD_PROFILE_AND_PERSISTED_TYPE_PROFILE_MISMATCH_REFUSED")

        missing = issue_refresh_token(principal_id=f["pa"], company_id=f["a"], channel="DASHBOARD", principal_type="BACKOFFICE", auth_revision=1, secret=SECRET)
        await reject(missing)
        payload = decode_company_token(missing, secret=SECRET).to_payload()
        for change in ({"exp": int(datetime.now(timezone.utc).timestamp()) - 1}, {"type": "access"},
                       {"channel": "FIELD", "principal_type": "BACKOFFICE"}):
            await reject(jwt.encode({**payload, **change}, SECRET, algorithm="HS256"))
        await reject("invalid-signed-token")
        checkpoint("MISSING_STORED_EXPIRED_SIGNATURE_TYPE_CHANNEL_PAIR_REFUSED")

        # A warm ORM identity map must not conceal a committed revision change.
        async with sessions() as db, db.begin():
            await db.execute(text("SELECT set_config('app.current_tenant', :c, true)"), {"c": str(f["a"])})
            cached = await db.scalar(select(CompanyPrincipal).where(CompanyPrincipal.id == f["pa"]))
            assert cached.auth_revision == 1
            admin.execute("UPDATE company_principals SET auth_revision=2 WHERE id=%s", (f["pa"],))
            try:
                await service.rotate_refresh_session(db, candidate.refresh_token, secret=SECRET)
            except service.RefreshSessionRejected:
                assert cached.auth_revision == 2 and db.in_transaction()
            else:
                raise AssertionError("Cached stale principal revision accepted")
            finally:
                admin.execute("UPDATE company_principals SET auth_revision=1 WHERE id=%s", (f["pa"],))
        checkpoint("CACHED_IDENTITY_REVALIDATED_FROM_PERSISTENCE")

        logout = await create()
        unaffected = await create()
        for _ in range(2):
            async with sessions() as db, db.begin():
                await service.revoke_refresh_session(db, logout.refresh_token, secret=SECRET)
                assert db.in_transaction()
        await reject(logout.refresh_token)
        assert admin.execute("SELECT is_revoked FROM principal_refresh_tokens WHERE token=%s", (unaffected.refresh_token,)).fetchone() == (False,)
        async with sessions() as db, db.begin():
            await service.revoke_refresh_session(db, initial.refresh_token, secret=SECRET)
        assert admin.execute("SELECT replaced_by_id FROM principal_refresh_tokens WHERE token=%s", (initial.refresh_token,)).fetchone() == (None,)
        await reject(initial.refresh_token)
        assert admin.execute("SELECT is_revoked FROM principal_refresh_tokens WHERE token=%s", (successor.refresh_token,)).fetchone() == (False,)
        checkpoint("EXACT_REVOKE_IDEMPOTENT_BLOCKS_GRACE_WITH_OTHER_SESSIONS_UNCHANGED")

        concurrent = await create()
        locked, release = asyncio.Event(), asyncio.Event()
        async def first():
            async with sessions() as db, db.begin():
                result = await service.rotate_refresh_session(db, concurrent.refresh_token, secret=SECRET)
                locked.set()
                await release.wait()
                return result
        first_task = asyncio.create_task(first())
        await asyncio.wait_for(locked.wait(), timeout=10)
        second_task = asyncio.create_task(rotate(concurrent.refresh_token))
        try:
            deadline = asyncio.get_running_loop().time() + 10
            while not admin.execute("SELECT EXISTS(SELECT 1 FROM pg_stat_activity WHERE datname=%s AND wait_event_type='Lock' "
                                     "AND query LIKE '%%principal_refresh_tokens%%')", (DATABASE,)).fetchone()[0]:
                if second_task.done() or asyncio.get_running_loop().time() > deadline:
                    raise AssertionError("Second refresh did not wait for predecessor lock")
                await asyncio.sleep(0.05)
        finally:
            release.set()
        first_result, second_result = await asyncio.gather(first_task, second_task)
        assert first_result == second_result
        assert admin.execute("SELECT count(*) FROM principal_refresh_tokens WHERE token=%s", (first_result.refresh_token,)).fetchone()[0] == 1
        predecessor = admin.execute("SELECT is_revoked,replaced_by_id FROM principal_refresh_tokens WHERE token=%s", (concurrent.refresh_token,)).fetchone()
        assert predecessor[0] and predecessor[1] is not None
        checkpoint("CONCURRENT_REFRESH_SERIALIZED_TO_ONE_SUCCESSOR_AND_GRACE_REPLAY")
    finally:
        await engine.dispose()


class _no_patch:
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--pg-bin", type=Path, default=Path(r"C:\Program Files\PostgreSQL\16\bin") if os.name == "nt" else Path("/usr/lib/postgresql/16/bin"))
    args = parser.parse_args()
    if not args.run:
        parser.error("--run required; existing DB URLs are never accepted")
    assert Path.cwd().resolve() == BACKEND
    pg = lambda name: str(args.pg_bin / (name + (".exe" if os.name == "nt" else "")))
    cluster = Path(tempfile.mkdtemp(prefix="wanasah_refresh_service_")).resolve()
    data = cluster / "data"
    with socket.socket() as reserved:
        reserved.bind(("127.0.0.1", 0))
        port = reserved.getsockname()[1]
    runtime = f"postgresql+asyncpg://{RUNTIME}@127.0.0.1:{port}/{DATABASE}"
    env = os.environ.copy()
    env.update({"PYTHONDONTWRITEBYTECODE": "1", "ENVIRONMENT": "test", "SECRET_KEY": SECRET,
                "DATABASE_URL": runtime, "DATABASE_URL_MIGRATION": f"postgresql+asyncpg://{ADMIN}@127.0.0.1:{port}/{DATABASE}"})
    os.environ.update({k: env[k] for k in ("ENVIRONMENT", "SECRET_KEY", "DATABASE_URL", "DATABASE_URL_MIGRATION")})
    sys.path.insert(0, str(BACKEND))
    checks, started = [], False
    def checkpoint(label):
        checks.append(label)
        print(label + "=PASS", flush=True)
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
        fixtures.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        checkpoint("ISOLATED_CURRENT_SCHEMA_BOOTSTRAP")
        with psycopg.connect(**connect, user=ADMIN, autocommit=True) as conn:
            f = seed(conn)
            fixtures.TABLES = ()
            before = fixtures.legacy_contract(conn)
            asyncio.run(lifecycle(conn, connect, runtime, f, checkpoint))
            assert fixtures.legacy_contract(conn) == before
            checkpoint("SCHEMA_UNCHANGED_NO_ENDPOINT_OR_LEGACY_SESSION_CUTOVER")
        print(json.dumps({"status": "PASS", "check_groups": len(checks), "source_main": "c3e504d03c4bd54ddf7300766e09eef04e06a5cd"}), flush=True)
    except Exception as exc:
        # SQL and JWT errors can include token/credential parameters; never echo them.
        raise RuntimeError("Focused lifecycle gate failed: " + type(exc).__name__) from None
    finally:
        if started or (data / "postmaster.pid").exists():
            fixtures.run([pg("pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], pg_ctl=True)
            print("ISOLATED_CLUSTER_STOPPED=PASS", flush=True)


if __name__ == "__main__":
    main()
