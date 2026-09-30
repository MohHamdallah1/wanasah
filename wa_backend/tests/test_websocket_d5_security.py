"""D5: real ASGI WebSocket handshake, tenant scope and secret-safe logging policy."""
from __future__ import annotations

import asyncio
import importlib
import json
import time
import unittest
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main
from realtime import ws_security

IMPORT_ROUTER = importlib.import_module(
    "domains.simple_products.imports.api.router"
)


class WebSocketD5SecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)
        self.allowed_origin = main.ALLOWED_ORIGINS[0]
        self.headers = {"origin": self.allowed_origin}

    def _identity(self, company=38):
        return SimpleNamespace(
            company_id=company,
            driver_id=1,
            token_expires_at=int(time.time()) + 180,
        )

    def test_dispatch_valid_first_frame_connects_only_after_auth(self):
        with patch.object(
            main,
            "authenticate_websocket_admin",
            new_callable=AsyncMock,
            return_value=self._identity(),
        ) as auth:
            with self.client.websocket_connect(
                "/ws/dispatch", headers=self.headers
            ) as socket:
                socket.send_json({"type": "auth", "token": "CANARY_VALID"})
                self.assertEqual(
                    socket.receive_json()["event"], "WS_AUTHENTICATED"
                )
                auth.assert_awaited_once_with("CANARY_VALID")

    def test_dispatch_invalid_access_token_closes_1008(self):
        with self.client.websocket_connect(
            "/ws/dispatch", headers=self.headers
        ) as socket:
            socket.send_json({"type": "auth", "token": "INVALID_CANARY"})
            with self.assertRaises(WebSocketDisconnect) as failure:
                socket.receive_json()
            self.assertEqual(failure.exception.code, 1008)

    def test_dispatch_missing_first_frame_times_out_without_auth(self):
        with patch.object(ws_security, "_AUTH_TIMEOUT_SECONDS", 0.05):
            with self.client.websocket_connect(
                "/ws/dispatch", headers=self.headers
            ) as socket:
                with self.assertRaises(WebSocketDisconnect) as failure:
                    socket.receive_json()
                self.assertEqual(failure.exception.code, 1008)

    def test_dispatch_oversized_auth_frame_rejected(self):
        with self.client.websocket_connect(
            "/ws/dispatch", headers=self.headers
        ) as socket:
            socket.send_text("x" * 9000)
            with self.assertRaises(WebSocketDisconnect) as failure:
                socket.receive_json()
            self.assertEqual(failure.exception.code, 1009)

    def test_dispatch_unknown_origin_rejected_at_handshake(self):
        with self.assertRaises(WebSocketDisconnect) as denial:
            with self.client.websocket_connect(
                "/ws/dispatch",
                headers={"origin": "https://attacker.invalid"},
            ):
                pass
        self.assertEqual(denial.exception.code, 1008)

    def test_dispatch_missing_origin_rejected_at_handshake(self):
        with self.assertRaises(WebSocketDisconnect) as denial:
            with self.client.websocket_connect("/ws/dispatch"):
                pass
        self.assertEqual(denial.exception.code, 1008)

    def test_query_token_is_rejected_and_zeroed_before_uvicorn_logging(self):
        query = b"token=VERY_PRIVATE_D5_CANARY&job=33"
        scope = {
            "type": "websocket",
            "path": "/ws/dispatch",
            "query_string": query,
            "headers": [],
            "state": {},
        }
        sent = []
        invoked = []

        async def inner(_scope, _receive, _send):
            invoked.append(True)

        async def send(msg):
            sent.append(msg)

        async def receive():
            return {"type": "websocket.connect"}

        asyncio.run(
            main.WanasahRawASGIMiddleware(inner)(scope, receive, send)
        )
        self.assertEqual(scope["query_string"], b"")
        self.assertFalse(invoked)
        self.assertEqual(sent[0]["type"], "websocket.close")
        self.assertEqual(sent[0]["code"], 1008)
        self.assertNotIn(b"VERY_PRIVATE_D5_CANARY", scope["query_string"])

    def test_valid_dispatch_session_expires_at_jwt_exp(self):
        soon = self._identity()
        soon.token_expires_at = int(time.time()) + 2
        with patch.object(
            main,
            "authenticate_websocket_admin",
            new_callable=AsyncMock,
            return_value=soon,
        ):
            with self.client.websocket_connect(
                "/ws/dispatch", headers=self.headers
            ) as socket:
                socket.send_json({"type": "auth", "token": "CANARY_SHORT"})
                self.assertEqual(
                    socket.receive_json()["event"], "WS_AUTHENTICATED"
                )
                with self.assertRaises(WebSocketDisconnect) as failure:
                    socket.receive_json()
                self.assertEqual(failure.exception.code, 1008)

    def test_product_import_exact_job_and_tenant_scope(self):
        job_id = uuid4()
        fake_db = SimpleNamespace(
            scalar=AsyncMock(
                side_effect=[
                    SimpleNamespace(id=1, is_active=True),
                    job_id,
                ]
            )
        )

        @asynccontextmanager
        async def fake_session(_company):
            yield fake_db

        access = SimpleNamespace(require=AsyncMock())
        with (
            patch.object(
                IMPORT_ROUTER, "authenticate_websocket_user",
                new_callable=AsyncMock,
                return_value=self._identity(38),
            ) as auth,
            patch.object(
                IMPORT_ROUTER, "tenant_session",
                new=fake_session,
            ),
            patch.object(
                IMPORT_ROUTER, "InventoryAccess",
                return_value=access,
            ),
        ):
            with self.client.websocket_connect(
                f"/simple-products/imports/{job_id}/ws",
                headers=self.headers,
            ) as socket:
                socket.send_json({"type": "auth", "token": "CANARY_IMPORT"})
                self.assertEqual(
                    socket.receive_json()["event"], "WS_AUTHENTICATED"
                )
                auth.assert_awaited_once_with("CANARY_IMPORT")
                access.require.assert_awaited_once_with(
                    "catalog.read", any_location=True
                )
                self.assertEqual(fake_db.scalar.await_count, 2)

    def test_product_import_other_tenant_job_is_not_registered(self):
        job_id = uuid4()
        fake_db = SimpleNamespace(
            scalar=AsyncMock(
                side_effect=[
                    SimpleNamespace(id=1, is_active=True),
                    None,
                ]
            )
        )

        @asynccontextmanager
        async def fake_session(_company):
            yield fake_db

        with (
            patch.object(
                IMPORT_ROUTER, "authenticate_websocket_user",
                new_callable=AsyncMock,
                return_value=self._identity(38),
            ),
            patch.object(IMPORT_ROUTER, "tenant_session", new=fake_session),
            patch.object(
                IMPORT_ROUTER, "InventoryAccess",
                return_value=SimpleNamespace(require=AsyncMock()),
            ),
        ):
            with self.client.websocket_connect(
                f"/simple-products/imports/{job_id}/ws",
                headers=self.headers,
            ) as socket:
                socket.send_json({"type": "auth", "token": "CANARY_IMPORT"})
                with self.assertRaises(WebSocketDisconnect) as failure:
                    socket.receive_json()
                self.assertEqual(failure.exception.code, 1008)


if __name__ == "__main__":
    unittest.main()
