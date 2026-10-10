from __future__ import annotations

import inspect
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from api.authentication import refresh_routes
from api.authentication.refresh_routes import PrincipalRefreshRequest, refresh_principal_access
from api.authentication.schemas import PrincipalTokenPairResponse


class PrincipalRefreshRouteAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_exact_token_db_and_secret(self):
        db = SimpleNamespace()
        expected = PrincipalTokenPairResponse(token="access", refresh_token="refresh-next")

        with (
            patch.object(refresh_routes.Config, "SECRET_KEY", "secret"),
            patch.object(
                refresh_routes,
                "refresh_principal_session",
                new=AsyncMock(return_value=expected),
            ) as rotate,
        ):
            result = await refresh_principal_access(
                PrincipalRefreshRequest(refresh_token="refresh-old"),
                db,
            )

        self.assertIs(result, expected)
        rotate.assert_awaited_once_with(
            db,
            refresh_token="refresh-old",
            secret="secret",
        )

    async def test_boundary_http_rejection_propagates_without_rewriting_details(self):
        rejection = HTTPException(status_code=401, detail="Authentication failed.")
        with patch.object(
            refresh_routes,
            "refresh_principal_session",
            new=AsyncMock(side_effect=rejection),
        ):
            with self.assertRaises(HTTPException) as raised:
                await refresh_principal_access(
                    PrincipalRefreshRequest(refresh_token="bad"),
                    SimpleNamespace(),
                )
        self.assertIs(raised.exception, rejection)

    def test_router_exposes_only_canonical_refresh_path_here(self):
        routes = [route for route in refresh_routes.router.routes if getattr(route, "path", None) == "/refresh"]
        self.assertEqual(len(routes), 1)
        route = routes[0]
        self.assertEqual(route.methods, {"POST"})
        self.assertIs(route.response_model, PrincipalTokenPairResponse)

    def test_request_contract_preserves_existing_refresh_token_shape(self):
        payload = PrincipalRefreshRequest(refresh_token="token")
        self.assertEqual(payload.refresh_token, "token")
        self.assertEqual(set(payload.model_dump()), {"refresh_token"})

    def test_adapter_contains_no_legacy_authority_or_token_logic(self):
        source = inspect.getsource(refresh_routes)
        for forbidden in ("Driver", "is_admin", "RefreshToken", "jwt.decode", "issue_access_token"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)

    async def test_adapter_does_not_own_commit_or_rollback(self):
        class _DB:
            commit_count = 0
            rollback_count = 0

            async def commit(self):
                self.commit_count += 1

            async def rollback(self):
                self.rollback_count += 1

        db = _DB()
        expected = PrincipalTokenPairResponse(token="access", refresh_token="refresh")
        with patch.object(
            refresh_routes,
            "refresh_principal_session",
            new=AsyncMock(return_value=expected),
        ):
            await refresh_principal_access(
                PrincipalRefreshRequest(refresh_token="old"),
                db,
            )

        self.assertEqual(db.commit_count, 0)
        self.assertEqual(db.rollback_count, 0)


if __name__ == "__main__":
    unittest.main()
