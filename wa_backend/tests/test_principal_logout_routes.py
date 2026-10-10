"""Focused tests for the unmounted canonical logout HTTP transaction adapter."""
import ast
from pathlib import Path
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SECRET = "LogoutRouteSynthetic123456789012345678901234567890123456789"
with patch.dict(os.environ, {"ENVIRONMENT": "test", "SECRET_KEY": SECRET,
                            "DATABASE_URL": "postgresql+asyncpg://logout_route_unit@127.0.0.1:1/logout_route_unit",
                            "DATABASE_URL_MIGRATION": "postgresql+asyncpg://logout_route_admin@127.0.0.1:1/logout_route_unit"}):
    from api.authentication import logout_routes as adapter
from domains.auth_sessions.claims import CompanyTokenClaims
from domains.auth_sessions.context import DashboardRequestContext


def carrier():
    claims = CompanyTokenClaims(token_type="access", principal_id=10, company_id=1, channel="DASHBOARD",
                                principal_type="BACKOFFICE", auth_revision=2, jti="synthetic", exp=2000000000)
    context = DashboardRequestContext(principal_id=10, company_id=1, backoffice_user_id=70, auth_revision=2, is_company_owner=False)
    return adapter.AuthenticatedAccessSession(token="  exact.synthetic.access.token  ", claims=claims, context=context)


class LogoutRouteTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        setting = patch.object(adapter.Config, "SECRET_KEY", SECRET)
        setting.start()
        self.addCleanup(setting.stop)

    def db(self, *, active=False):
        db = MagicMock(spec=AsyncSession)
        state = {"active": active, "events": []}
        db.in_transaction.side_effect = lambda: state["active"]
        async def begin():
            state["events"].append("begin")
            state["active"] = True
        async def commit():
            state["events"].append("commit")
            state["active"] = False
        async def rollback():
            state["events"].append("rollback")
            state["active"] = False
        db.begin = AsyncMock(side_effect=begin)
        db.commit.side_effect = commit
        db.rollback.side_effect = rollback
        return db, state

    async def request(self, db, session, headers=None):
        # Only this disposable test app includes the router; runtime is untouched.
        app = FastAPI()
        app.include_router(adapter.router)
        async def test_db():
            return db
        async def test_session():
            return session
        app.dependency_overrides[adapter.get_db] = test_db
        app.dependency_overrides[adapter.get_authenticated_access_session] = test_session
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://logout-route.test") as client:
            return await client.post("/logout", headers=headers)

    async def test_access_only_exact_carrier_and_success_commit(self):
        db, state = self.db()
        session = carrier()
        async def orchestration(received_db, **kwargs):
            state["events"].append("orchestration")
            self.assertIs(received_db, db)
            self.assertTrue(kwargs["access_token"] == session.token)
            self.assertIs(kwargs["claims"], session.claims)
            self.assertIsNone(kwargs["refresh_token"])
            self.assertTrue(kwargs["secret"] == SECRET)
            self.assertTrue(db.in_transaction())
        with patch.object(adapter, "logout_authenticated_principal", AsyncMock(side_effect=orchestration)) as logout:
            response = await self.request(db, session)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"message": "Logged out successfully."})
        self.assertEqual(logout.await_count, 1)
        self.assertEqual(state["events"], ["begin", "orchestration", "commit"])
        self.assertEqual(db.rollback.await_count, 0)

    async def test_access_refresh_exact_header_adopts_authentication_transaction(self):
        db, state = self.db(active=True)
        supplied = "  exact.synthetic.refresh.token  "
        with patch.object(adapter, "logout_authenticated_principal", AsyncMock()) as logout:
            response = await self.request(db, carrier(), {"X-Refresh-Token": supplied})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(logout.call_args.kwargs["refresh_token"] == supplied)
        self.assertEqual(db.begin.await_count, 0)
        self.assertEqual(state["events"], ["commit"])
        self.assertEqual(db.rollback.await_count, 0)

    async def test_empty_supplied_refresh_is_not_silently_omitted(self):
        db, _ = self.db()
        with patch.object(adapter, "logout_authenticated_principal", AsyncMock()) as logout:
            await self.request(db, carrier(), {"X-Refresh-Token": ""})
        self.assertTrue(logout.call_args.kwargs["refresh_token"] == "")

    async def test_opaque_401_propagates_and_rolls_back(self):
        db, state = self.db(active=True)
        rejection = HTTPException(status_code=401, detail="Authentication credentials are invalid or expired.", headers={"WWW-Authenticate": "Bearer"})
        with patch.object(adapter, "logout_authenticated_principal", AsyncMock(side_effect=rejection)):
            response = await self.request(db, carrier(), {"X-Refresh-Token": "synthetic-mismatched"})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")
        self.assertEqual(response.json(), {"detail": rejection.detail})
        self.assertEqual(state["events"], ["rollback"])
        self.assertEqual(db.commit.await_count, 0)

    async def test_orchestration_or_commit_failure_rolls_back_without_disclosure(self):
        for failure_at in ("orchestration", "commit"):
            db, state = self.db()
            session = carrier()
            fault = RuntimeError(session.token)
            if failure_at == "commit":
                db.commit.side_effect = fault
            with patch.object(adapter, "logout_authenticated_principal", AsyncMock(side_effect=fault if failure_at == "orchestration" else None)):
                response = await self.request(db, session)
            self.assertEqual(response.status_code, 500)
            self.assertNotIn(session.token, response.text)
            self.assertEqual(db.rollback.await_count, 1)
            self.assertFalse(state["active"])

    async def test_rollback_failure_still_returns_safe_error(self):
        db, _ = self.db(active=True)
        session = carrier()
        db.rollback.side_effect = RuntimeError(session.token)
        with patch.object(adapter, "logout_authenticated_principal", AsyncMock(side_effect=RuntimeError(session.token))):
            response = await self.request(db, session)
        self.assertEqual(response.status_code, 500)
        self.assertNotIn(session.token, response.text)
        self.assertEqual(db.rollback.await_count, 1)

    async def test_response_model_repeat_and_no_extra_decode_or_authority(self):
        db, _ = self.db()
        with patch.object(adapter, "logout_authenticated_principal", AsyncMock()) as logout, \
             patch("domains.auth_sessions.codec.decode_company_token", side_effect=AssertionError("Adapter must not decode")) as decode:
            for _ in range(2):
                response = await adapter.logout_principal(session=carrier(), db=db, refresh_token=None)
                self.assertIsInstance(response, adapter.PrincipalLogoutResponse)
                self.assertEqual(response.model_dump(), {"message": "Logged out successfully."})
        self.assertEqual(logout.await_count, 2)
        self.assertEqual(decode.call_count, 0)
        self.assertEqual(db.commit.await_count, 2)
        route = adapter.router.routes[0]
        self.assertEqual((route.path, route.methods), ("/logout", {"POST"}))
        self.assertIs(route.response_model, adapter.PrincipalLogoutResponse)
        tree = ast.parse(Path(adapter.__file__).read_text(encoding="utf-8"))
        names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
        self.assertTrue(names.isdisjoint({"Driver", "RefreshToken", "is_admin", "jwt", "logger", "print", "decode_company_token"}))
        attrs = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
        self.assertTrue(attrs.isdisjoint({"role", "capabilities", "decode", "begin_nested", "include_router", "info", "error", "exception"}))


if __name__ == "__main__":
    unittest.main()
