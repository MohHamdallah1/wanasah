"""Focused real-transaction adapter gate; NEW synthetic localhost database only.

Reuses the existing isolated logout fixture harness without changing it. No runtime
router mounting, developer credentials, package installs, or schema edits.
Run from wa_backend: python tests/run_principal_logout_routes_gate.py --run
"""
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import run_principal_logout_gate as isolated


async def check_adapter(admin, runtime_url, f, checkpoint):
    from api.authentication import logout_routes as adapter
    from domains.auth_sessions.codec import issue_access_token, decode_company_token
    from domains.auth_sessions.context import DashboardRequestContext
    from domains.auth_sessions.refresh_sessions import create_refresh_session

    engine = create_async_engine(runtime_url, echo=False, hide_parameters=True)
    sessions = async_sessionmaker(engine, expire_on_commit=False, autobegin=False)
    context = DashboardRequestContext(principal_id=f["pa"], company_id=f["a"], backoffice_user_id=f["bo"], auth_revision=1, is_company_owner=False)

    def carrier():
        raw = issue_access_token(principal_id=f["pa"], company_id=f["a"], channel="DASHBOARD", principal_type="BACKOFFICE", auth_revision=1, secret=isolated.SECRET)
        claims = decode_company_token(raw, secret=isolated.SECRET, expected_type="access")
        return adapter.AuthenticatedAccessSession(token=raw, claims=claims, context=context)

    def blacklisted(current):
        return admin.execute("SELECT count(*) FROM token_blacklist WHERE token=%s", (current.token,)).fetchone()[0]

    def revoked(token):
        return admin.execute("SELECT is_revoked FROM principal_refresh_tokens WHERE token=%s", (token,)).fetchone()[0]

    async def refresh(current=context):
        async with sessions() as db, db.begin():
            return (await create_refresh_session(db, current, secret=isolated.SECRET)).refresh_token

    try:
        current = carrier()
        async with sessions() as db:
            assert not db.in_transaction()
            response = await adapter.logout_principal(session=current, db=db, refresh_token=None)
            assert not db.in_transaction()
        assert response.model_dump() == {"message": "Logged out successfully."}
        assert blacklisted(current) == 1
        checkpoint("ADAPTER_BEGINS_IDLE_SESSION_AND_COMMITS_ACCESS_ONLY")

        current = carrier()
        supplied, sibling = await refresh(), await refresh()
        async with sessions() as db:
            # Represent the same request transaction already begun by authentication.
            await db.begin()
            await db.scalar(text("SELECT 1"))
            assert db.in_transaction()
            response = await adapter.logout_principal(session=current, db=db, refresh_token=supplied)
            assert not db.in_transaction()
        assert blacklisted(current) == 1 and revoked(supplied) is True and revoked(sibling) is False
        checkpoint("ADAPTER_ADOPTS_AUTH_TRANSACTION_COMMITS_BLACKLIST_AND_EXACT_REFRESH")
        async with sessions() as db:
            await adapter.logout_principal(session=current, db=db, refresh_token=supplied)
        assert blacklisted(current) == 1 and revoked(sibling) is False
        checkpoint("REPEATED_AUTHENTICATED_ORCHESTRATION_REMAINS_STATE_IDEMPOTENT")

        current = carrier()
        supplied = await refresh()
        original = adapter.logout_authenticated_principal
        async def database_fault(db, **kwargs):
            assert kwargs["access_token"] is current.token and kwargs["claims"] is current.claims
            await original(db, **kwargs)
            # Both mutations exist only in this transaction, invisible outside it.
            assert blacklisted(current) == 0 and revoked(supplied) is False
            await db.execute(text("SELECT 1 / 0"))
        async with sessions() as db:
            with patch.object(adapter, "logout_authenticated_principal", side_effect=database_fault):
                try:
                    await adapter.logout_principal(session=current, db=db, refresh_token=supplied)
                except HTTPException as exc:
                    assert exc.status_code == 500
                    assert current.token not in exc.detail and supplied not in exc.detail
                    assert not db.in_transaction()
                else:
                    raise AssertionError("Database failure unexpectedly committed")
        assert blacklisted(current) == 0 and revoked(supplied) is False
        checkpoint("REAL_POSTGRES_FAILURE_ROLLS_BACK_BOTH_MUTATIONS")

        other_bo = admin.execute("SELECT id FROM backoffice_users WHERE company_id=%s AND principal_id=%s", (f["a"], f["other"])).fetchone()[0]
        other = DashboardRequestContext(principal_id=f["other"], company_id=f["a"], backoffice_user_id=other_bo, auth_revision=1, is_company_owner=False)
        mismatched = await refresh(other)
        current = carrier()
        async with sessions() as db:
            try:
                await adapter.logout_principal(session=current, db=db, refresh_token=mismatched)
            except HTTPException as exc:
                assert exc.status_code == 401 and exc.headers == {"WWW-Authenticate": "Bearer"}
                assert not db.in_transaction()
            else:
                raise AssertionError("Mismatched refresh identity accepted")
        assert blacklisted(current) == 0 and revoked(mismatched) is False
        checkpoint("ORCHESTRATION_AUTHORITY_OPAQUE_401_PROPAGATED_AND_ROLLED_BACK")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    isolated.check_logout = check_adapter
    isolated.main()
