from __future__ import annotations

import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from starlette.requests import Request

from api.authentication import login_routes
from api.authentication.login_orchestration import (
    PrincipalLoginRateLimited,
    PrincipalLoginRejected,
)
from api.authentication.schemas import (
    DashboardPrincipalLoginResponse,
    FieldPrincipalLoginResponse,
)
from schemas import LoginRequest


class PrincipalLoginRouteAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.db = object()
        self.payload = LoginRequest(
            company_code="WNS-01",
            username="operator",
            password="StrongPass1",
        )
        self.request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/login",
                "headers": [],
                "client": ("10.0.0.9", 12345),
                "server": ("testserver", 80),
                "scheme": "http",
                "query_string": b"",
            }
        )

    @staticmethod
    def dashboard_response() -> DashboardPrincipalLoginResponse:
        return DashboardPrincipalLoginResponse(
            token="access-token",
            refresh_token="refresh-token",
            principal_id=101,
            backoffice_user_id=202,
            channel="DASHBOARD",
            is_company_owner=False,
            company_id=7,
            company_code="WNS-01",
            driver_id=303,
            driver_name="Legacy User",
            is_admin=False,
            dashboard_access=True,
        )

    @staticmethod
    def field_response() -> FieldPrincipalLoginResponse:
        return FieldPrincipalLoginResponse(
            token="access-token",
            refresh_token="refresh-token",
            principal_id=111,
            representative_id=222,
            channel="FIELD",
            company_id=7,
            company_code="WNS-01",
            driver_id=333,
            driver_name="Legacy Rep",
            is_admin=False,
        )

    def _fake_main(self, ip: str = "198.51.100.25"):
        module = types.ModuleType("main")
        module.get_real_ip = lambda request: ip
        return patch.dict(sys.modules, {"main": module})

    async def test_dashboard_endpoint_delegates_correctly(self):
        expected = self.dashboard_response()
        delegate = AsyncMock(return_value=expected)
        with self._fake_main(), patch.object(
            login_routes, "login_dashboard_principal", delegate
        ):
            result = await login_routes.dashboard_principal_login(
                self.request, self.payload, self.db
            )
        self.assertIs(result, expected)
        delegate.assert_awaited_once_with(
            self.db,
            company_code="WNS-01",
            username="operator",
            password="StrongPass1",
            ip_address="198.51.100.25",
            secret=login_routes.Config.SECRET_KEY,
        )

    async def test_field_endpoint_delegates_correctly(self):
        expected = self.field_response()
        delegate = AsyncMock(return_value=expected)
        with self._fake_main("203.0.113.44"), patch.object(
            login_routes, "login_field_principal", delegate
        ):
            result = await login_routes.field_principal_login(
                self.request, self.payload, self.db
            )
        self.assertIs(result, expected)
        delegate.assert_awaited_once_with(
            self.db,
            company_code="WNS-01",
            username="operator",
            password="StrongPass1",
            ip_address="203.0.113.44",
            secret=login_routes.Config.SECRET_KEY,
        )

    def test_correct_strict_response_models(self):
        by_path = {route.path: route for route in login_routes.router.routes}
        self.assertIs(
            by_path["/login"].response_model, DashboardPrincipalLoginResponse
        )
        self.assertIs(
            by_path["/driver/login"].response_model, FieldPrincipalLoginResponse
        )
        self.assertEqual(by_path["/login"].methods, {"POST"})
        self.assertEqual(by_path["/driver/login"].methods, {"POST"})

    async def test_401_mapping(self):
        delegate = AsyncMock(side_effect=PrincipalLoginRejected("secret db reason"))
        with self._fake_main(), patch.object(
            login_routes, "login_dashboard_principal", delegate
        ):
            with self.assertRaises(HTTPException) as caught:
                await login_routes.dashboard_principal_login(
                    self.request, self.payload, self.db
                )
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(caught.exception.detail, "Authentication failed.")
        self.assertNotIn("secret", caught.exception.detail)

    async def test_429_mapping(self):
        delegate = AsyncMock(side_effect=PrincipalLoginRateLimited("internal count"))
        with self._fake_main(), patch.object(
            login_routes, "login_field_principal", delegate
        ):
            with self.assertRaises(HTTPException) as caught:
                await login_routes.field_principal_login(
                    self.request, self.payload, self.db
                )
        self.assertEqual(caught.exception.status_code, 429)
        self.assertEqual(
            caught.exception.detail, "Too many login attempts. Try again later."
        )
        self.assertNotIn("internal", caught.exception.detail)

    async def test_ip_forwarded_correctly(self):
        delegate = AsyncMock(return_value=self.dashboard_response())
        with self._fake_main("192.0.2.123"), patch.object(
            login_routes, "login_dashboard_principal", delegate
        ):
            await login_routes.dashboard_principal_login(
                self.request, self.payload, self.db
            )
        self.assertEqual(delegate.await_args.kwargs["ip_address"], "192.0.2.123")

    async def test_secret_forwarded_correctly(self):
        delegate = AsyncMock(return_value=self.field_response())
        with self._fake_main(), patch.object(
            login_routes, "login_field_principal", delegate
        ):
            await login_routes.field_principal_login(
                self.request, self.payload, self.db
            )
        self.assertIs(
            delegate.await_args.kwargs["secret"], login_routes.Config.SECRET_KEY
        )

    def test_no_legacy_identity_or_authority_logic(self):
        source = Path(login_routes.__file__).read_text(encoding="utf-8")
        for forbidden in (
            "Driver",
            "is_admin",
            "role_name",
            "issue_access_token",
            "create_access_token",
            "create_refresh_session",
            ".commit(",
            ".rollback(",
        ):
            self.assertNotIn(forbidden, source)

    def test_existing_runtime_routes_remain_untouched_and_unmounted(self):
        auth_source = (
            Path(__file__).resolve().parents[1] / "api" / "auth.py"
        ).read_text(encoding="utf-8")
        self.assertIn('@router.post("/login", response_model=LoginResponse)', auth_source)
        self.assertIn(
            '@router.post("/driver/login", response_model=LoginResponse)', auth_source
        )
        self.assertNotIn("login_routes", auth_source)


if __name__ == "__main__":
    unittest.main()
