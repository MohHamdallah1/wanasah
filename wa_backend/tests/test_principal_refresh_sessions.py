"""Focused defensive refresh-service checks; real transaction/locking gate separate."""
import ast
from dataclasses import fields
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domains.auth_sessions import refresh_sessions as service
from domains.auth_sessions.claims import CompanyTokenClaims
from domains.auth_sessions.context import DashboardRequestContext
from domains.identity.repository import IdentityRecordNotFound


def claims():
    return CompanyTokenClaims(token_type="refresh", principal_id=10, company_id=1, channel="DASHBOARD",
                              principal_type="BACKOFFICE", auth_revision=1, jti="synthetic", exp=2000000000)


def row():
    return SimpleNamespace(company_id=1, principal_id=10, channel="DASHBOARD", auth_revision=1,
                           expires_at=datetime.fromtimestamp(2000000000, timezone.utc).replace(tzinfo=None),
                           created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                           is_revoked=False, replaced_by_id=20, token="synthetic")


class RefreshServiceTests(unittest.IsolatedAsyncioTestCase):
    def db(self):
        db = MagicMock(spec=AsyncSession)
        db.in_transaction.return_value = True
        return db

    async def test_exact_lookup_locks_and_refreshes_cached_row(self):
        db = self.db()
        db.scalar.return_value = row()
        await service._exact(db, "synthetic", claims())
        query = db.scalar.call_args.args[0]
        compiled = str(query.compile(dialect=postgresql.dialect()))
        self.assertIn("FOR UPDATE", compiled)
        self.assertIn("principal_refresh_tokens.token =", compiled)
        self.assertIn("principal_refresh_tokens.company_id =", compiled)
        self.assertTrue(query.get_execution_options()["populate_existing"])

    async def test_missing_or_mismatched_exact_row(self):
        for key, value in (("company_id", 2), ("principal_id", 11), ("channel", "FIELD"),
                           ("auth_revision", 2), ("expires_at", datetime(2000, 1, 1))):
            db, invalid = self.db(), row()
            setattr(invalid, key, value)
            db.scalar.return_value = invalid
            with self.assertRaises(service.RefreshSessionRejected):
                await service._exact(db, "synthetic", claims())
        db = self.db()
        db.scalar.return_value = None
        with self.assertRaises(service.RefreshSessionRejected):
            await service._exact(db, "synthetic", claims())

    async def test_wrong_or_missing_persisted_profile(self):
        company = SimpleNamespace(id=1, is_active=True)
        principal = SimpleNamespace(id=10, company_id=1, is_active=True, auth_revision=1, principal_type="BACKOFFICE")
        for key, value in (("company_id", 2), ("principal_id", 11), ("principal_type", "FIELD_REPRESENTATIVE")):
            profile = SimpleNamespace(company_id=1, principal_id=10, principal_type="BACKOFFICE")
            setattr(profile, key, value)
            with patch.object(service, "require_active_company", AsyncMock(return_value=company)), \
                 patch.object(service, "load_principal_by_id", AsyncMock(return_value=principal)), \
                 patch.object(service, "require_backoffice_profile", AsyncMock(return_value=profile)):
                with self.assertRaises(service.RefreshSessionRejected):
                    await service._persisted_identity(self.db(), claims())
        with patch.object(service, "require_active_company", AsyncMock(return_value=company)), \
             patch.object(service, "load_principal_by_id", AsyncMock(return_value=principal)), \
             patch.object(service, "require_backoffice_profile", AsyncMock(side_effect=IdentityRecordNotFound)):
            with self.assertRaises(service.RefreshSessionRejected):
                await service._persisted_identity(self.db(), claims())

    async def test_grace_mismatched_successor_row_or_signed_claims(self):
        for key, value in (("company_id", 2), ("principal_id", 11), ("channel", "FIELD"), ("auth_revision", 2)):
            db, invalid = self.db(), row()
            setattr(invalid, key, value)
            db.scalar.return_value = invalid
            with self.assertRaises(service.RefreshSessionRejected):
                await service._grace_successor(db, row(), claims(), secret="synthetic")
        for key, value in (("company_id", 2), ("principal_id", 11), ("channel", "FIELD"),
                           ("principal_type", "FIELD_REPRESENTATIVE"), ("auth_revision", 2)):
            db = self.db()
            db.scalar.return_value = row()
            other = SimpleNamespace(**claims().__dict__)
            setattr(other, key, value)
            with patch.object(service, "_decode", return_value=other):
                with self.assertRaises(service.RefreshSessionRejected):
                    await service._grace_successor(db, row(), claims(), secret="synthetic")

    async def test_transaction_must_be_started_by_caller(self):
        db = self.db()
        db.in_transaction.return_value = False
        context = DashboardRequestContext(principal_id=10, company_id=1, backoffice_user_id=7, auth_revision=1, is_company_owner=False)
        for function, argument in ((service.create_refresh_session, context),
                                   (service.rotate_refresh_session, "synthetic"),
                                   (service.revoke_refresh_session, "synthetic")):
            with self.assertRaises(service.RefreshSessionTransactionRequired):
                await function(db, argument, secret="synthetic")
        db.scalar.assert_not_called()
        db.execute.assert_not_called()

    async def test_foreign_tenant_never_overwritten(self):
        db = self.db()
        db.scalar.return_value = "2"
        with self.assertRaises(service.RefreshSessionRejected):
            await service._tenant(db, 1)
        db.execute.assert_not_called()

    def test_narrow_result_and_no_domain_transaction_completion(self):
        self.assertEqual([f.name for f in fields(service.RefreshSessionResult)],
                         ["principal_id", "company_id", "channel", "principal_type", "auth_revision", "refresh_token"])
        result = service._result(claims(), "synthetic-secret-token")
        self.assertNotIn("synthetic-secret-token", repr(result))
        tree = ast.parse(Path(service.__file__).read_text(encoding="utf-8"))
        calls = {node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)}
        self.assertTrue(calls.isdisjoint({"commit", "rollback", "begin", "begin_nested"}))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertTrue(names.isdisjoint({"Driver", "RefreshToken", "is_admin"}))


if __name__ == "__main__":
    unittest.main()
