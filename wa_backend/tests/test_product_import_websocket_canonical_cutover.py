from __future__ import annotations

import importlib
import inspect
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from realtime.auth import WebSocketAuthError


import_router = importlib.import_module(
    "domains.simple_products.imports.api.router"
)

ROOT = Path(__file__).resolve().parents[1]
ROUTER_PATH = ROOT / "domains" / "simple_products" / "imports" / "api" / "router.py"


class _WebSocket:
    def __init__(self):
        self.close = AsyncMock()
        self.send_json = AsyncMock()


class _DB:
    def __init__(self, scalar_result):
        self.scalar_result = scalar_result
        self.scalar_calls = []

    async def scalar(self, statement):
        self.scalar_calls.append(statement)
        return self.scalar_result


class ProductImportWebSocketCanonicalCutoverTests(unittest.IsolatedAsyncioTestCase):
    async def test_catalog_read_auth_then_exact_company_job_fence_and_token_expiry(self):
        job_id = uuid4()
        websocket = _WebSocket()
        identity = SimpleNamespace(
            company_id=77,
            token_expires_at=2_000_000_123,
        )
        db = _DB(job_id)
        tenant_ids = []

        @asynccontextmanager
        async def tenant_session(company_id):
            tenant_ids.append(company_id)
            yield db

        with (
            patch.object(
                import_router,
                "receive_websocket_bearer",
                new_callable=AsyncMock,
                return_value="ws-token",
            ),
            patch.object(
                import_router,
                "authenticate_websocket_user",
                new_callable=AsyncMock,
                return_value=identity,
            ) as authenticate,
            patch.object(import_router, "tenant_session", new=tenant_session),
            patch.object(
                import_router.product_import_connection_manager,
                "connect",
                new_callable=AsyncMock,
                return_value=True,
            ) as connect,
            patch.object(
                import_router.product_import_connection_manager,
                "disconnect",
                new_callable=AsyncMock,
            ) as disconnect,
            patch.object(
                import_router,
                "drain_authenticated_websocket",
                new_callable=AsyncMock,
            ) as drain,
        ):
            await import_router.product_import_progress_websocket(
                websocket,
                job_id,
            )

        authenticate.assert_awaited_once_with(
            "ws-token",
            capability="catalog.read",
            any_location=True,
        )
        self.assertEqual(tenant_ids, [77])
        self.assertEqual(len(db.scalar_calls), 1)
        statement = str(db.scalar_calls[0])
        self.assertIn("product_import_jobs.company_id", statement)
        self.assertIn("product_import_jobs.id", statement)
        connect.assert_awaited_once_with(
            websocket,
            company_id=77,
            job_id=job_id,
            already_accepted=True,
        )
        websocket.send_json.assert_awaited_once_with(
            {"event": "WS_AUTHENTICATED"}
        )
        drain.assert_awaited_once_with(
            websocket,
            token_expires_at=2_000_000_123,
        )
        disconnect.assert_awaited_once_with(
            websocket,
            company_id=77,
            job_id=job_id,
        )
        websocket.close.assert_not_awaited()

    async def test_missing_catalog_read_closes_1008_before_job_lookup(self):
        job_id = uuid4()
        websocket = _WebSocket()
        tenant_entered = False

        @asynccontextmanager
        async def tenant_session(_company_id):
            nonlocal tenant_entered
            tenant_entered = True
            raise AssertionError("job session must not open after auth denial")
            yield

        with (
            patch.object(
                import_router,
                "receive_websocket_bearer",
                new_callable=AsyncMock,
                return_value="ws-token",
            ),
            patch.object(
                import_router,
                "authenticate_websocket_user",
                new_callable=AsyncMock,
                side_effect=WebSocketAuthError("websocket authorization failed"),
            ) as authenticate,
            patch.object(import_router, "tenant_session", new=tenant_session),
            patch.object(
                import_router.product_import_connection_manager,
                "connect",
                new_callable=AsyncMock,
            ) as connect,
        ):
            await import_router.product_import_progress_websocket(
                websocket,
                job_id,
            )

        authenticate.assert_awaited_once_with(
            "ws-token",
            capability="catalog.read",
            any_location=True,
        )
        self.assertFalse(tenant_entered)
        websocket.close.assert_awaited_once_with(code=1008)
        connect.assert_not_awaited()

    async def test_cross_company_or_missing_job_closes_1008(self):
        job_id = uuid4()
        websocket = _WebSocket()
        identity = SimpleNamespace(
            company_id=77,
            token_expires_at=2_000_000_123,
        )
        db = _DB(None)

        @asynccontextmanager
        async def tenant_session(company_id):
            self.assertEqual(company_id, 77)
            yield db

        with (
            patch.object(
                import_router,
                "receive_websocket_bearer",
                new_callable=AsyncMock,
                return_value="ws-token",
            ),
            patch.object(
                import_router,
                "authenticate_websocket_user",
                new_callable=AsyncMock,
                return_value=identity,
            ),
            patch.object(import_router, "tenant_session", new=tenant_session),
            patch.object(
                import_router.product_import_connection_manager,
                "connect",
                new_callable=AsyncMock,
            ) as connect,
        ):
            await import_router.product_import_progress_websocket(
                websocket,
                job_id,
            )

        self.assertEqual(len(db.scalar_calls), 1)
        websocket.close.assert_awaited_once_with(code=1008)
        connect.assert_not_awaited()

    async def test_missing_first_message_token_preserves_existing_return_behavior(self):
        websocket = _WebSocket()
        with (
            patch.object(
                import_router,
                "receive_websocket_bearer",
                new_callable=AsyncMock,
                return_value=None,
            ),
            patch.object(
                import_router,
                "authenticate_websocket_user",
                new_callable=AsyncMock,
            ) as authenticate,
        ):
            await import_router.product_import_progress_websocket(
                websocket,
                uuid4(),
            )
        authenticate.assert_not_awaited()
        websocket.close.assert_not_awaited()


class ProductImportWebSocketSourceAuditTests(unittest.TestCase):
    def test_router_has_no_inventory_access_remaining(self):
        source = ROUTER_PATH.read_text(encoding="utf-8")
        self.assertNotIn("InventoryAccess", source)

    def test_websocket_block_has_no_driver_authorization_or_admin_shortcut(self):
        source = inspect.getsource(
            import_router.product_import_progress_websocket
        )
        for forbidden in (
            "Driver",
            "driver_id",
            "is_active",
            ".is_admin",
            "get_current_backoffice_legacy_driver",
            "InventoryAccess",
        ):
            self.assertNotIn(forbidden, source, forbidden)
        for required in (
            'capability="catalog.read"',
            "any_location=True",
            "identity.company_id",
            "ProductImportJob.company_id",
            "ProductImportJob.id",
            "identity.token_expires_at",
        ):
            self.assertIn(required, source, required)

    def test_websocket_url_and_callable_are_preserved(self):
        source = ROUTER_PATH.read_text(encoding="utf-8")
        self.assertIn(
            '@router.websocket("/imports/{job_id}/ws")',
            source,
        )
        self.assertTrue(
            inspect.iscoroutinefunction(
                import_router.product_import_progress_websocket
            )
        )


if __name__ == "__main__":
    unittest.main()
