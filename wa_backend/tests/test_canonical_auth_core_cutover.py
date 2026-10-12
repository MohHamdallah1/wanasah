"""Focused HTTP/session activation gate; requires existing backend dependencies."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
SECRET = "AuthCoreSynthetic123456789012345678901234567890123456789"
with patch.dict(os.environ, {
    "ENVIRONMENT": "test", "SECRET_KEY": SECRET,
    "DATABASE_URL": "postgresql+asyncpg://auth_core_unit@127.0.0.1:1/auth_core_unit",
    "DATABASE_URL_MIGRATION": "postgresql+asyncpg://auth_core_admin@127.0.0.1:1/auth_core_unit",
}):
    from fastapi import FastAPI, HTTPException
    from httpx import ASGITransport, AsyncClient
    import jwt
    from api import auth, dependencies
    from api.authentication import login_orchestration as orchestration, login_transport as transport
    from api.authentication import login_transport_routes as routes
    from api.authentication.login import LoginCompanyContext
    from domains.authorization.dashboard_admission import DashboardAdmissionRejected
    from domains.auth_sessions.codec import decode_company_token
    from domains.auth_sessions.context import DashboardRequestContext, FieldRequestContext
    from domains.identity.contracts import AuthenticationRejected, DashboardAuthenticationResult, FieldAuthenticationResult


class OperationalDriver:
    id = 303

    @property
    def is_admin(self):
        raise AssertionError("No Driver flag authority")

    @property
    def company_id(self):
        raise AssertionError("No Driver tenant authority")

    @property
    def full_name(self):
        raise AssertionError("Display name belongs to canonical principal")


class CanonicalAuthCoreCutoverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.db = SimpleNamespace(commit=AsyncMock(), rollback=AsyncMock(), add=Mock())
        self.app = FastAPI()
        self.app.include_router(auth.router)
        async def database():
            return self.db
        self.app.dependency_overrides[routes.get_db] = database

    def identity(self, *, field=False, owner=False):
        if field:
            return FieldAuthenticationResult(101, 7, 404, "field", "Field display", 3)
        return DashboardAuthenticationResult(101, 7, 202, "office", "Canonical display", 3, owner)

    async def login(self, *, field=False, owner=False, denied=False, missing_mapping=False, wrong_channel=False):
        identity = self.identity(field=field, owner=owner)
        prepared = AsyncMock(return_value=LoginCompanyContext(7, "WN"))
        authenticated = AsyncMock(side_effect=AuthenticationRejected if wrong_channel else None,
                                  return_value=identity)
        admission = AsyncMock(side_effect=DashboardAdmissionRejected if denied else None,
                              return_value=identity)
        legacy = AsyncMock(side_effect=HTTPException(401, "synthetic mapping failure") if missing_mapping else None,
                           return_value=OperationalDriver())
        refresh = AsyncMock(return_value=SimpleNamespace(refresh_token="synthetic-refresh"))
        helper = "get_current_field_legacy_driver" if field else "get_current_backoffice_legacy_driver"
        with (
            patch.object(routes.Config, "SECRET_KEY", SECRET),
            patch.object(routes, "_request_ip", return_value="127.0.0.1"),
            patch.object(orchestration, "enforce_company_login_attempt_limit", AsyncMock()),
            patch.object(orchestration, "prepare_login_company", prepared),
            patch.object(orchestration, "authenticate_identity", authenticated),
            patch.object(orchestration, "require_dashboard_admission", admission),
            patch.object(transport, helper, legacy),
            patch.object(orchestration, "create_refresh_session", refresh),
        ):
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://auth-core.test") as client:
                response = await client.post("/driver/login" if field else "/login",
                                             json={"company_code": "WN", "username": "user", "password": "StrongPass1"})
        return response, legacy, refresh, admission, authenticated

    def test_public_auth_routes_are_mounted_once_with_bounded_response_models(self):
        expected = {"/login", "/driver/login", "/refresh", "/logout"}
        selected = [route for route in auth.router.routes if getattr(route, "path", None) in expected]
        self.assertEqual(len(selected), 4)
        self.assertEqual({route.path for route in selected}, expected)
        self.assertTrue(all(route.methods == {"POST"} for route in selected))
        models = {route.path: route.response_model for route in selected}
        self.assertIs(models["/login"], transport.DashboardLoginTransportResponse)
        self.assertIs(models["/driver/login"], transport.FieldLoginTransportResponse)

    async def test_owner_and_ordinary_dashboard_keep_clients_with_canonical_subject(self):
        for owner in (False, True):
            response, legacy, refresh, admission, authenticated = await self.login(owner=owner)
            self.assertEqual(response.status_code, 200, response.text)
            data = response.json()
            self.assertEqual((data["principal_id"], data["backoffice_user_id"], data["driver_id"]), (101, 202, 303))
            self.assertEqual((data["legacy_driver_id"], data["company_id"], data["principal_type"]), (303, 7, "BACKOFFICE"))
            self.assertIs(data["is_admin"], owner)
            self.assertIs(data["is_company_owner"], owner)
            self.assertTrue(data["dashboard_access"])
            self.assertEqual(data["driver_name"], data["display_name"])
            claims = decode_company_token(data["token"], secret=SECRET, expected_type="access")
            self.assertEqual((claims.principal_id, claims.company_id, claims.channel, claims.auth_revision),
                             (101, 7, "DASHBOARD", 3))
            self.assertFalse(hasattr(claims, "is_admin"))
            self.assertFalse(hasattr(claims, "role"))
            self.assertEqual(authenticated.call_args.kwargs["channel"].value, "DASHBOARD")
            admission.assert_awaited_once()
            legacy.assert_awaited_once()
            refresh.assert_awaited_once()

    async def test_field_returns_separate_profile_and_mapped_offline_driver_id(self):
        response, legacy, refresh, admission, authenticated = await self.login(field=True)
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()
        self.assertEqual((data["principal_id"], data["representative_id"], data["driver_id"]), (101, 404, 303))
        self.assertEqual(data["principal_type"], "FIELD_REPRESENTATIVE")
        self.assertFalse(data["is_admin"])
        self.assertFalse(data["dashboard_access"])
        self.assertNotIn("backoffice_user_id", data)
        self.assertEqual(decode_company_token(data["token"], secret=SECRET).channel, "FIELD")
        self.assertEqual(authenticated.call_args.kwargs["channel"].value, "FIELD")
        admission.assert_not_awaited()
        legacy.assert_awaited_once()
        refresh.assert_awaited_once()

    async def test_missing_capability_denies_before_operational_mapping_or_session(self):
        response, legacy, refresh, _, _ = await self.login(denied=True)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Authentication failed."})
        legacy.assert_not_awaited()
        refresh.assert_not_awaited()

    async def test_mapping_failure_never_creates_a_valid_refresh_session(self):
        for field in (False, True):
            self.db.commit.reset_mock()
            response, legacy, refresh, _, _ = await self.login(field=field, missing_mapping=True)
            self.assertEqual(response.status_code, 401)
            self.assertNotIn("synthetic mapping failure", response.text)
            legacy.assert_awaited_once()
            refresh.assert_not_awaited()
            self.db.commit.assert_awaited_once()  # only the failed login-attempt record
            self.assertTrue(all(not getattr(call.args[0], "is_successful", True)
                                for call in self.db.add.call_args_list))

    async def test_wrong_channel_rejects_before_mapping_admission_or_issuance(self):
        for field in (False, True):
            response, legacy, refresh, admission, _ = await self.login(field=field, wrong_channel=True)
            self.assertEqual(response.status_code, 401)
            legacy.assert_not_awaited()
            refresh.assert_not_awaited()
            admission.assert_not_awaited()

    async def test_generic_locator_uses_only_trusted_context_and_retired_gates_deny(self):
        db = object()
        dashboard = DashboardRequestContext(101, 7, 202, 3, False)
        field = FieldRequestContext(101, 7, 404, 3)
        for context, helper in ((dashboard, "get_current_backoffice_legacy_driver"),
                                (field, "get_current_field_legacy_driver")):
            with patch.object(dependencies, helper, AsyncMock(return_value=OperationalDriver())) as locate:
                result = await dependencies.get_current_driver(current=context, db=db)
            self.assertEqual(result.id, 303)
            locate.assert_awaited_once_with(current=context, db=db)
        for helper, args in ((dependencies.get_current_admin, {}),
                             (dependencies.get_current_driver_owned, {"driver_id": 303})):
            with self.assertRaises(HTTPException) as denied:
                await helper(**args)
            self.assertEqual(denied.exception.status_code, 403)

    async def test_legacy_refresh_cannot_rotate_at_new_public_route(self):
        from datetime import datetime, timedelta, timezone
        legacy = jwt.encode({"type": "refresh", "sub": "303", "company_id": 7, "role": "Admin",
                             "exp": datetime.now(timezone.utc) + timedelta(days=1)}, SECRET, algorithm="HS256")
        events = []
        class Transaction:
            async def __aenter__(self):
                events.append("begin")
            async def __aexit__(self, kind, *args):
                events.append("rollback" if kind else "commit")
        db = SimpleNamespace(begin=lambda: Transaction(), in_transaction=lambda: True,
                             scalar=AsyncMock(side_effect=AssertionError("legacy token must fail before DB")))
        async def database():
            return db
        from api.authentication.refresh_routes import get_db, Config
        self.app.dependency_overrides[get_db] = database
        with patch.object(Config, "SECRET_KEY", SECRET):
            async with AsyncClient(transport=ASGITransport(app=self.app), base_url="http://auth-core.test") as client:
                response = await client.post("/refresh", json={"refresh_token": legacy})
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json(), {"detail": "Authentication failed."})
        db.scalar.assert_not_awaited()
        self.assertEqual(events, ["begin", "rollback"])


if __name__ == "__main__":
    unittest.main()
