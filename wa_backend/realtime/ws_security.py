"""Browser WebSocket first-frame bearer auth, origin policy and session lifetime.

Never put access/refresh tokens in a URL or Sec-WebSocket-Protocol header.
No unauthenticated peer enters a company/job broadcaster.
"""
from __future__ import annotations

import asyncio
import json
import os
import time

from fastapi import WebSocket, WebSocketDisconnect

_HANDSHAKE_SLOTS = asyncio.Semaphore(128)
_AUTH_TIMEOUT_SECONDS = 5.0
_MAX_AUTH_FRAME_CHARS = 8192
_MAX_BEARER_CHARS = 4096
_MAX_SESSION_SECONDS = 300.0


def allowed_browser_origins() -> list[str]:
    """One source of truth for CORS and WS Origin allowlists."""
    raw = os.getenv(
        "CORS_ALLOWED_ORIGINS",
        "https://dashboard.wanasah.com,https://www.wanasah.com",
    )
    allowed = [value.strip() for value in raw.split(",") if value.strip()]
    env = os.getenv("ENVIRONMENT", "production")
    dev = os.getenv("ENABLE_CORS_WILDCARD", "false").lower() in (
        "true", "1", "yes"
    )
    if env == "development" or dev:
        for origin in (
            "http://localhost:8080", "http://127.0.0.1:8080",
            "http://localhost:5173", "http://127.0.0.1:5173",
            "http://localhost:3000", "http://127.0.0.1:3000",
        ):
            if origin not in allowed:
                allowed.append(origin)
    return allowed


async def _close_safely(websocket: WebSocket, code: int) -> None:
    try:
        await websocket.close(code=code)
    except (RuntimeError, WebSocketDisconnect, OSError):
        # The peer may already have disconnected; never log credentials.
        pass


async def receive_websocket_bearer(websocket: WebSocket) -> str | None:
    """Accept, then read one bounded auth frame; never register before auth.

    Reject missing/untrusted browser Origin. CORS middleware does not enforce
    WebSocket Origin. Only normal access JWTs are later authenticated by the
    owning endpoint's tenant/role-aware auth service.
    """
    origin = websocket.headers.get("origin")
    if not origin or origin not in allowed_browser_origins():
        await _close_safely(websocket, 1008)
        return None
    if websocket.scope.get("query_string"):
        # Defense in depth; the outer ASGI middleware zeroes query bytes
        # before Uvicorn serializes a rejected handshake to its access log.
        await _close_safely(websocket, 1008)
        return None

    try:
        await asyncio.wait_for(_HANDSHAKE_SLOTS.acquire(), timeout=0.1)
    except TimeoutError:
        await _close_safely(websocket, 1013)
        return None
    try:
        await websocket.accept()
        try:
            raw = await asyncio.wait_for(
                websocket.receive_text(),
                timeout=_AUTH_TIMEOUT_SECONDS,
            )
        except (TimeoutError, WebSocketDisconnect, RuntimeError):
            await _close_safely(websocket, 1008)
            return None
        if len(raw) > _MAX_AUTH_FRAME_CHARS:
            await _close_safely(websocket, 1009)
            return None
        try:
            payload = json.loads(raw)
        except (ValueError, TypeError):
            await _close_safely(websocket, 1008)
            return None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"type", "token"}
            or payload.get("type") != "auth"
            or not isinstance(payload.get("token"), str)
            or not (1 <= len(payload["token"]) <= _MAX_BEARER_CHARS)
        ):
            await _close_safely(websocket, 1008)
            return None
        return payload["token"]
    finally:
        _HANDSHAKE_SLOTS.release()


async def drain_authenticated_websocket(
    websocket: WebSocket,
    *,
    token_expires_at: int,
) -> None:
    """Do not retain bearer-authorized streams beyond JWT exp or five minutes.

    HTTP logout/revocation is checked again on the next short reconnect;
    no client-pushed messages carry business authority on these read-only feeds.
    """
    lifetime = min(
        _MAX_SESSION_SECONDS,
        float(token_expires_at) - time.time(),
    )
    if lifetime <= 0:
        await _close_safely(websocket, 1008)
        return
    end = time.monotonic() + lifetime
    while True:
        remaining = end - time.monotonic()
        if remaining <= 0:
            await _close_safely(websocket, 1008)
            return
        try:
            await asyncio.wait_for(websocket.receive_text(), timeout=remaining)
        except TimeoutError:
            await _close_safely(websocket, 1008)
            return
        except (WebSocketDisconnect, RuntimeError):
            return
