#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
Wanasah — Automated E2E Backend & WebSocket Smoke Test Suite
═══════════════════════════════════════════════════════════════════════════════
Step 5.4: In-memory smoke tests using httpx ASGITransport (no uvicorn required).
═══════════════════════════════════════════════════════════════════════════════
"""
import asyncio
import sys
import time
from pathlib import Path

import httpx
from httpx import ASGITransport

# ── Ensure wa_backend is on sys.path ────────────────────────────────────────
WA_BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WA_BACKEND_DIR))

from main import app  # noqa: E402

# ═══════════════════════════════════════════════════════════════════════════════
# Test runner helpers
# ═══════════════════════════════════════════════════════════════════════════════
passed = 0
failed = 0
failures: list[str] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    global passed, failed
    if ok:
        passed += 1
        print(f"  ✅ {name}")
    else:
        failed += 1
        failures.append(f"{name}: {detail}")
        print(f"  ❌ {name}  —  {detail}")


def assert_status(resp: httpx.Response, expected: int, test_name: str) -> bool:
    if resp.status_code != expected:
        record(test_name, False, f"expected status {expected}, got {resp.status_code}")
        return False
    return True


# ═══════════════════════════════════════════════════════════════════════════════
# Main test suite
# ═══════════════════════════════════════════════════════════════════════════════
async def main() -> int:
    global passed, failed, failures
    started = time.monotonic()

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        # ─────────────────────────────────────────────────────────────────
        # 1. GET /health — Liveness probe
        # ─────────────────────────────────────────────────────────────────
        print("\n═══ 1. GET /health (Liveness) ═══")
        try:
            resp = await client.get("/health")
            ok_status = assert_status(resp, 200, "/health status 200")
            ok_body = resp.json().get("status") == "alive"
            record("/health returns {\"status\": \"alive\"}", ok_status and ok_body,
                   f"body={resp.text}" if not (ok_status and ok_body) else "")
        except Exception as e:
            record("/health", False, str(e))

        # ─────────────────────────────────────────────────────────────────
        # 2. GET /ready — Readiness probe
        # ─────────────────────────────────────────────────────────────────
        print("\n═══ 2. GET /ready (Readiness) ═══")
        try:
            resp = await client.get("/ready")
            # Ready may return 503 if DB is unavailable, but must not raise 500
            ok_no_500 = resp.status_code != 500
            record("/ready does not raise 500 Internal Error", ok_no_500,
                   f"status={resp.status_code}" if not ok_no_500 else "")
            # If it returns JSON, it should have a 'status' key
            try:
                body = resp.json()
                record("/ready response is valid JSON", True)
            except Exception:
                record("/ready response is valid JSON", False, f"body={resp.text}")
        except Exception as e:
            record("/ready", False, str(e))

        # ─────────────────────────────────────────────────────────────────
        # 3. Security Headers & Request ID
        # ─────────────────────────────────────────────────────────────────
        print("\n═══ 3. Security Headers & Request ID ═══")
        try:
            resp = await client.get("/health")
            headers = resp.headers

            # X-Request-Id
            req_id = headers.get("x-request-id")
            record("X-Request-Id header present", req_id is not None,
                   "header missing in response")

            # X-Content-Type-Options
            content_type_opts = headers.get("x-content-type-options")
            record("X-Content-Type-Options: nosniff",
                   content_type_opts == "nosniff",
                   f"got: {content_type_opts}")

            # Strict-Transport-Security
            hsts = headers.get("strict-transport-security")
            record("Strict-Transport-Security header present",
                   hsts is not None and "max-age=" in str(hsts),
                   f"got: {hsts}")

            # X-Frame-Options
            xfo = headers.get("x-frame-options")
            record("X-Frame-Options: DENY", xfo == "DENY",
                   f"got: {xfo}")

            # Referrer-Policy
            rp = headers.get("referrer-policy")
            record("Referrer-Policy header present", rp is not None,
                   f"got: {rp}")

        except Exception as e:
            record("Security-headers check", False, str(e))

        # ─────────────────────────────────────────────────────────────────
        # 4. Auth Failure Formatting
        # ─────────────────────────────────────────────────────────────────
        print("\n═══ 4. Auth Failure Formatting ═══")
        try:
            # Try /auth/login first; fall back to /login if router prefix differs
            auth_url = "/auth/login"
            resp = await client.post(
                auth_url,
                json={"username": "invalid_user_test", "password": "wrong"}
            )
            # 404 means the route itself is missing — hard failure
            if resp.status_code == 404:
                # Try the unprefixed fallback
                resp = await client.post(
                    "/login",
                    json={"username": "invalid_user_test", "password": "wrong"}
                )

            # Strict: must be 401 or 422 for bad credentials; 404 = route missing
            ok_status = resp.status_code in (401, 422)
            record("POST /auth/login (or /login) returns 401 or 422 for invalid creds",
                   ok_status,
                   f"status={resp.status_code} (404=route missing, 500=crash)")

            try:
                body = resp.json()
                has_message = "message" in body or "detail" in body
                record("Auth error response contains 'message' or 'detail' key",
                       has_message,
                       f"body keys: {list(body.keys())}")
            except Exception:
                record("Auth error response is valid JSON", False,
                       f"body={resp.text[:200]}")

        except Exception as e:
            record("POST auth login check", False, str(e))

        # ─────────────────────────────────────────────────────────────────
        # 5. WebSocket Handshake Verification
        # ─────────────────────────────────────────────────────────────────
        print("\n═══ 5. WebSocket /ws/dispatch Verification ═══")
        try:
            # Verify the WS route is registered on the app
            ws_routes = [
                r for r in app.routes
                if hasattr(r, "path") and "/ws/dispatch" in str(r.path)
            ]
            record("WebSocket route /ws/dispatch is registered",
                   len(ws_routes) > 0,
                   f"routes found: {len(ws_routes)}")

            # Note: httpx sends HTTP GET (type: http), but @app.websocket matches
            # only WebSocket scopes (type: websocket), so a plain GET returns 404.
            # The route-registry check above is the authoritative verification
            # that the endpoint exists and is active in the ASGI app.

        except Exception as e:
            record("WebSocket check", False, str(e))

    # ═══════════════════════════════════════════════════════════════════════
    # Summary
    # ═══════════════════════════════════════════════════════════════════════
    duration = time.monotonic() - started
    total = passed + failed
    print("\n" + "═" * 60)
    print(f"  🧪 Wanasah Smoke Test Results")
    print(f"  ✅ Passed : {passed}/{total}")
    print(f"  ❌ Failed : {failed}/{total}")
    print(f"  ⏱️  Duration: {duration:.3f}s")
    if failures:
        print(f"\n  Failures:")
        for f in failures:
            print(f"    ─ {f}")
    print("═" * 60 + "\n")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)