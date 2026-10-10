"""Focused canonical logout orchestration; no routes, schemas or database access."""
import ast
from dataclasses import replace
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

# Dependency imports must never bind a development database or credentials.
os.environ.update({"ENVIRONMENT": "test", "SECRET_KEY": "LogoutUnitSynthetic123456789012345678901234567890123456",
                   "DATABASE_URL": "postgresql+asyncpg://logout_unit@127.0.0.1:1/logout_unit",
                   "DATABASE_URL_MIGRATION": "postgresql+asyncpg://logout_unit_admin@127.0.0.1:1/logout_unit"})
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.authentication import logout
from domains.auth_sessions.codec import decode_company_token, issue_access_token, issue_refresh_token

SECRET = os.environ["SECRET_KEY"]


def access():
    token = issue_access_token(principal_id=10, company_id=1, channel="DASHBOARD", principal_type="BACKOFFICE", auth_revision=1, secret=SECRET)
    return token, decode_company_token(token, secret=SECRET, expected_type="access")


def refresh(**changes):
    values = dict(principal_id=10, company_id=1, channel="DASHBOARD", principal_type="BACKOFFICE", auth_revision=1, secret=SECRET)
    return issue_refresh_token(**{**values, **changes})


class LogoutTests(unittest.IsolatedAsyncioTestCase):
    def db(self):
        db = MagicMock(spec=AsyncSession)
        db.in_transaction.return_value = True
        return db

    async def test_access_only(self):
        token, claims = access()
        db = self.db()
        with patch.object(logout, "blacklist_authenticated_access_token", AsyncMock(return_value=True)) as blacklist, \
             patch.object(logout, "revoke_refresh_session", AsyncMock()) as revoke:
            self.assertIsNone(await logout.logout_authenticated_principal(db, access_token=token, claims=claims, secret=SECRET))
            self.assertEqual(blacklist.await_count, 1)
            self.assertTrue(blacklist.call_args.args == (db,) and blacklist.call_args.kwargs == {"token": token, "claims": claims})
            self.assertEqual(revoke.await_count, 0)
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    async def test_access_plus_refresh_order_and_repeated_logout(self):
        token, claims = access()
        refresh_token = refresh()
        calls = []
        async def revoke(*args, **kwargs):
            calls.append("revoke")
        async def blacklist(*args, **kwargs):
            calls.append("blacklist")
            return calls.count("blacklist") == 1
        with patch.object(logout, "blacklist_authenticated_access_token", AsyncMock(side_effect=blacklist)), \
             patch.object(logout, "revoke_refresh_session", AsyncMock(side_effect=revoke)) as revoke_mock:
            db = self.db()
            for _ in range(2):
                await logout.logout_authenticated_principal(db, access_token=token, claims=claims, refresh_token=refresh_token, secret=SECRET)
            self.assertEqual(calls, ["revoke", "blacklist", "revoke", "blacklist"])
            self.assertTrue(revoke_mock.call_args.args == (db, refresh_token))
            self.assertTrue(revoke_mock.call_args.kwargs == {"secret": SECRET})
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    async def test_wrong_refresh_identity_channel_revision_and_invalid_token(self):
        token, claims = access()
        invalid = [refresh(company_id=2), refresh(principal_id=11), refresh(channel="FIELD", principal_type="FIELD_REPRESENTATIVE"),
                   refresh(auth_revision=2), "", "invalid-canonical-token"]
        for supplied in invalid:
            with patch.object(logout, "blacklist_authenticated_access_token", AsyncMock()) as blacklist, \
                 patch.object(logout, "revoke_refresh_session", AsyncMock()) as revoke:
                with self.assertRaises(HTTPException) as rejected:
                    await logout.logout_authenticated_principal(self.db(), access_token=token, claims=claims, refresh_token=supplied, secret=SECRET)
                self.assertEqual(rejected.exception.status_code, 401)
                self.assertEqual(blacklist.await_count, 0)
                self.assertEqual(revoke.await_count, 0)

    async def test_wrong_access_token_claims_cannot_blacklist(self):
        token, claims = access()
        with patch.object(logout, "blacklist_authenticated_access_token", AsyncMock()) as blacklist:
            for wrong in (replace(claims, principal_id=11), replace(claims, token_type="refresh"), replace(claims, jti="different")):
                with self.assertRaises(HTTPException):
                    await logout.logout_authenticated_principal(self.db(), access_token=token, claims=wrong, secret=SECRET)
            self.assertEqual(blacklist.await_count, 0)

    async def test_persistence_failure_is_opaque_and_caller_retains_transaction(self):
        token, claims = access()
        db = self.db()
        with patch.object(logout, "blacklist_authenticated_access_token", AsyncMock(side_effect=RuntimeError(token))):
            with self.assertRaises(HTTPException) as rejected:
                await logout.logout_authenticated_principal(db, access_token=token, claims=claims, secret=SECRET)
        self.assertEqual(rejected.exception.status_code, 401)
        self.assertEqual(rejected.exception.headers, {"WWW-Authenticate": "Bearer"})
        self.assertNotIn(token, rejected.exception.detail)
        self.assertTrue(rejected.exception.__suppress_context__)
        self.assertTrue(db.in_transaction())
        db.commit.assert_not_called()
        db.rollback.assert_not_called()

    async def test_explicit_caller_transaction_and_no_cutover_or_logging(self):
        token, claims = access()
        db = self.db()
        db.in_transaction.return_value = False
        with self.assertRaises(HTTPException):
            await logout.logout_authenticated_principal(db, access_token=token, claims=claims, secret=SECRET)
        db.execute.assert_not_called()
        tree = ast.parse(Path(logout.__file__).read_text(encoding="utf-8"))
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertTrue(calls.isdisjoint({"commit", "rollback", "begin", "begin_nested", "post", "info", "debug", "error", "exception"}))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertTrue(names.isdisjoint({"Driver", "RefreshToken", "is_admin", "print", "logger"}))


if __name__ == "__main__":
    unittest.main()
