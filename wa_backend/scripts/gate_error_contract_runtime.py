from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

from httpx import ASGITransport, AsyncClient

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("ENVIRONMENT", "development")

from main import app

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


async def verify(client: AsyncClient, method: str, path: str, expected_status: int) -> None:
    response = await client.request(method, path)
    try:
        payload = response.json()
    except Exception:
        payload = None

    error = payload.get("error") if isinstance(payload, dict) else None
    top_request_id = payload.get("request_id") if isinstance(payload, dict) else None
    header_request_id = response.headers.get("x-request-id")
    canonical_request_id = error.get("request_id") if isinstance(error, dict) else None

    record(f"{expected_status} status: {method} {path}", response.status_code == expected_status, f"actual={response.status_code}")
    record(f"{expected_status} canonical envelope", isinstance(error, dict))
    record(
        f"{expected_status} canonical code",
        isinstance(error, dict) and error.get("code") == f"HTTP_{expected_status}",
        f"code={error.get('code') if isinstance(error, dict) else None}",
    )
    record(
        f"{expected_status} request id coherence",
        bool(header_request_id)
        and header_request_id == top_request_id == canonical_request_id,
        f"header={header_request_id} top={top_request_id} canonical={canonical_request_id}",
    )
    record(
        f"{expected_status} context object",
        isinstance(error, dict) and isinstance(error.get("context"), dict),
    )


async def main() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        await verify(client, "GET", "/__stage75_definitely_missing__", 404)
        await verify(client, "POST", "/health", 405)

    failures = [name for name, ok, _ in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")
    if failures:
        print("ERROR_CONTRACT_RUNTIME_GATE=FAIL")
        raise SystemExit(1)
    print("ERROR_CONTRACT_RUNTIME_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(main())
