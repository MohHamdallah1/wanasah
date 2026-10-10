"""Canonical logout gate in a NEW synthetic localhost PostgreSQL cluster only.

No existing database, package installations, schemas edits or HTTP route cutover.
Run from wa_backend: python tests/run_principal_logout_gate.py --run
"""
import argparse
import asyncio
import os
from pathlib import Path
import socket
import sys
import tempfile
from unittest.mock import patch

from fastapi import HTTPException
import psycopg
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import run_identity_schema_expand_gate as fixtures
from run_principal_refresh_sessions_gate import seed

BACKEND = Path(__file__).resolve().parents[1]
ADMIN, RUNTIME, DATABASE = "logout_gate_admin", "logout_gate_runtime", "logout_gate_test"
SECRET = "LogoutGateSynthetic1234567890123456789012345678901234567890"


async def check_logout(admin, runtime_url, f, checkpoint):
    from api.authentication import logout
    from domains.auth_sessions.codec import issue_access_token, decode_company_token
    from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
    from domains.auth_sessions.refresh_sessions import create_refresh_session

    engine = create_async_engine(runtime_url, echo=False, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autobegin=False)
    context = DashboardRequestContext(principal_id=f["pa"], company_id=f["a"], backoffice_user_id=f["bo"], auth_revision=1, is_company_owner=False)

    def access():
        token = issue_access_token(principal_id=f["pa"], company_id=f["a"], channel="DASHBOARD", principal_type="BACKOFFICE", auth_revision=1, secret=SECRET)
        return token, decode_company_token(token, secret=SECRET, expected_type="access")

    def blacklisted(token):
        return admin.execute("SELECT count(*) FROM token_blacklist WHERE token=%s", (token,)).fetchone()[0]

    def revoked(token):
        return admin.execute("SELECT is_revoked FROM principal_refresh_tokens WHERE token=%s", (token,)).fetchone()[0]

    async def refresh(current=context):
        async with sessions() as db, db.begin():
            return (await create_refresh_session(db, current, secret=SECRET)).refresh_token

    try:
        token, claims = access()
        async with sessions() as db, db.begin():
            await logout.logout_authenticated_principal(db, access_token=token, claims=claims, secret=SECRET)
            assert db.in_transaction() and blacklisted(token) == 0
            assert await db.scalar(text("SELECT count(*) FROM token_blacklist WHERE token=:token"), {"token": token}) == 1
        assert blacklisted(token) == 1
        async with sessions() as db, db.begin():
            await logout.logout_authenticated_principal(db, access_token=token, claims=claims, secret=SECRET)
        assert blacklisted(token) == 1
        checkpoint("ACCESS_ONLY_EXACT_BLACKLIST_IDEMPOTENT_AND_CALLER_COMMIT")

        token, claims = access()
        supplied, sibling = await refresh(), await refresh()
        async with sessions() as db, db.begin():
            await logout.logout_authenticated_principal(db, access_token=token, claims=claims, refresh_token=supplied, secret=SECRET)
            assert db.in_transaction() and blacklisted(token) == 0 and revoked(supplied) is False
            assert await db.scalar(text("SELECT is_revoked FROM principal_refresh_tokens WHERE token=:token"), {"token": supplied}) is True
            assert await db.scalar(text("SELECT count(*) FROM token_blacklist WHERE token=:token"), {"token": token}) == 1
        assert blacklisted(token) == 1 and revoked(supplied) is True and revoked(sibling) is False
        for _ in range(2):
            async with sessions() as db, db.begin():
                await logout.logout_authenticated_principal(db, access_token=token, claims=claims, refresh_token=supplied, secret=SECRET)
        assert blacklisted(token) == 1 and revoked(sibling) is False
        checkpoint("ACCESS_REFRESH_SINGLE_TRANSACTION_EXACT_REVOKE_REPEAT_NO_SIBLING_CHANGE")

        # Simulate a failure after both writes: only caller rollback completes the unit.
        token, claims = access()
        supplied = await refresh()
        real_blacklist = logout.blacklist_authenticated_access_token
        async def fail_after_blacklist(*args, **kwargs):
            await real_blacklist(*args, **kwargs)
            raise RuntimeError("synthetic orchestration failure")
        try:
            async with sessions() as db, db.begin():
                with patch.object(logout, "blacklist_authenticated_access_token", side_effect=fail_after_blacklist):
                    await logout.logout_authenticated_principal(db, access_token=token, claims=claims, refresh_token=supplied, secret=SECRET)
        except HTTPException as exc:
            assert exc.status_code == 401 and token not in exc.detail and supplied not in exc.detail
        else:
            raise AssertionError("Synthetic failure unexpectedly succeeded")
        assert blacklisted(token) == 0 and revoked(supplied) is False
        checkpoint("CALLER_ROLLBACK_UNDOES_BLACKLIST_AND_REFRESH_REVOKE_TOGETHER")

        other_bo = admin.execute("SELECT id FROM backoffice_users WHERE company_id=%s AND principal_id=%s", (f["a"], f["other"])).fetchone()[0]
        foreign_bo = admin.execute("SELECT id FROM backoffice_users WHERE company_id=%s AND principal_id=%s", (f["b"], f["pb"])).fetchone()[0]
        wrong_contexts = [
            DashboardRequestContext(principal_id=f["other"], company_id=f["a"], backoffice_user_id=other_bo, auth_revision=1, is_company_owner=False),
            DashboardRequestContext(principal_id=f["pb"], company_id=f["b"], backoffice_user_id=foreign_bo, auth_revision=1, is_company_owner=False),
            FieldRequestContext(principal_id=f["pf"], company_id=f["a"], representative_id=f["field"], auth_revision=1),
        ]
        for wrong in wrong_contexts:
            wrong_refresh = await refresh(wrong)
            token, claims = access()
            async with sessions() as db, db.begin():
                try:
                    await logout.logout_authenticated_principal(db, access_token=token, claims=claims, refresh_token=wrong_refresh, secret=SECRET)
                except HTTPException as exc:
                    assert exc.status_code == 401 and exc.headers == {"WWW-Authenticate": "Bearer"}
                    assert db.in_transaction() and await db.scalar(text("SELECT 1")) == 1
                else:
                    raise AssertionError("Wrong refresh identity/channel accepted")
            assert blacklisted(token) == 0 and revoked(wrong_refresh) is False
        checkpoint("WRONG_REFRESH_COMPANY_PRINCIPAL_CHANNEL_OPAQUE_NO_MUTATION")

        # Matching signed identity with absent persistence must fail before blacklisting.
        from domains.auth_sessions.codec import issue_refresh_token
        missing = issue_refresh_token(principal_id=f["pa"], company_id=f["a"], channel="DASHBOARD", principal_type="BACKOFFICE", auth_revision=1, secret=SECRET)
        token, claims = access()
        async with sessions() as db, db.begin():
            try:
                await logout.logout_authenticated_principal(db, access_token=token, claims=claims, refresh_token=missing, secret=SECRET)
            except HTTPException as exc:
                assert exc.status_code == 401 and db.in_transaction()
            else:
                raise AssertionError("Missing refresh persistence accepted")
        assert blacklisted(token) == 0
        checkpoint("MISSING_REFRESH_PERSISTENCE_LEAVES_ACCESS_BLACKLIST_UNCHANGED")
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--pg-bin", type=Path, default=Path(r"C:\Program Files\PostgreSQL\16\bin") if os.name == "nt" else Path("/usr/lib/postgresql/16/bin"))
    args = parser.parse_args()
    if not args.run:
        parser.error("--run required; no existing database URL accepted")
    assert Path.cwd().resolve() == BACKEND
    pg = lambda name: str(args.pg_bin / (name + (".exe" if os.name == "nt" else "")))
    cluster = Path(tempfile.mkdtemp(prefix="wanasah_logout_")).resolve()
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
    started = False
    def checkpoint(label):
        print(label + "=PASS", flush=True)
    try:
        fixtures.run([pg("initdb"), "-D", str(data), "-U", ADMIN, "--auth=trust", "--encoding=UTF8", "--no-locale"])
        fixtures.run([pg("pg_ctl"), "-D", str(data), "-l", str(cluster / "postgres.log"), "-o", f"-h 127.0.0.1 -p {port}", "-w", "start"], pg_ctl=True)
        started = True
        print(f"ISOLATED_CLUSTER_STARTED={cluster}", flush=True)
        with psycopg.connect(host="127.0.0.1", port=port, dbname="postgres", user=ADMIN, autocommit=True) as conn:
            assert Path(conn.execute("SHOW data_directory").fetchone()[0]).resolve() == data
            conn.execute(f"CREATE ROLE {RUNTIME} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS")
            conn.execute(f"CREATE DATABASE {DATABASE}")
        fixtures.run([sys.executable, "-m", "alembic", "upgrade", "head"], env=env)
        checkpoint("CURRENT_SCHEMA_BOOTSTRAP_SYNTHETIC_RUNTIME_ROLE")
        with psycopg.connect(host="127.0.0.1", port=port, dbname=DATABASE, user=ADMIN, autocommit=True) as conn:
            f = seed(conn)
            fixtures.TABLES = ()
            before = fixtures.legacy_contract(conn)
            asyncio.run(check_logout(conn, runtime, f, checkpoint))
            assert fixtures.legacy_contract(conn) == before
            checkpoint("SCHEMA_UNCHANGED_NO_HTTP_ROUTE_OR_LEGACY_CUTOVER")
    except Exception as exc:
        raise RuntimeError("Focused logout gate failed: " + type(exc).__name__) from None
    finally:
        if started or (data / "postmaster.pid").exists():
            fixtures.run([pg("pg_ctl"), "-D", str(data), "-m", "fast", "-w", "stop"], pg_ctl=True)
            print("ISOLATED_CLUSTER_STOPPED=PASS", flush=True)


if __name__ == "__main__":
    main()
