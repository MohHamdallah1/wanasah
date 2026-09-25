from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient


BACKEND = Path(__file__).resolve().parent.parent
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("ENVIRONMENT", "development")

LOG_PATH = BACKEND / ".gate_http_5xx_observability.log"
os.environ["WANASAH_ERROR_LOG_PATH"] = str(LOG_PATH)

from main import app  # noqa: E402
from observability.http_errors import (  # noqa: E402
    shutdown_http_error_logging,
)


RESULTS: list[tuple[str, bool, str]] = []
CONTROLLED_PATH = "/__gate_http_5xx_controlled__"
UNHANDLED_PATH = "/__gate_http_5xx_unhandled__"
MISSING_PATH = "/__gate_http_5xx_missing__"


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(
        f"[{'PASS' if ok else 'FAIL'}] {name}"
        + (f" — {detail}" if detail else "")
    )


async def controlled_503() -> None:
    try:
        raise RuntimeError(
            "CONTROLLED_ROOT_CAUSE "
            "postgresql+asyncpg://gate_user:gatepass@db.internal/wanasah"
        )
    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "GATE_CONTROLLED_503",
                "message": "Safe controlled service outage.",
                "context": {"component": "gate"},
            },
        ) from exc


async def unhandled_500() -> None:
    logging.getLogger("wanasah_logger").error(
        "LEGACY_ROUTE_LOG_MUST_NOT_ENTER_ERROR_FILE"
    )
    raise RuntimeError(
        "UNHANDLED_ROOT_CAUSE SECRET_KEY=gate-super-secret"
    )


app.add_api_route(
    CONTROLLED_PATH,
    controlled_503,
    methods=["GET"],
    include_in_schema=False,
)
app.add_api_route(
    UNHANDLED_PATH,
    unhandled_500,
    methods=["GET"],
    include_in_schema=False,
)


def request_id_from(response) -> str | None:
    payload = response.json()
    error = payload.get("error") if isinstance(payload, dict) else None
    top = payload.get("request_id") if isinstance(payload, dict) else None
    canonical = error.get("request_id") if isinstance(error, dict) else None
    header = response.headers.get("x-request-id")
    if header and header == top == canonical:
        return header
    return None


async def run() -> None:
    if LOG_PATH.exists():
        LOG_PATH.unlink()
    for rotated in LOG_PATH.parent.glob(LOG_PATH.name + ".*"):
        rotated.unlink()

    transport = ASGITransport(
        app=app,
        raise_app_exceptions=False,
    )

    async with AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        missing = await client.get(MISSING_PATH)
        controlled = await client.get(CONTROLLED_PATH)
        unhandled = await client.get(UNHANDLED_PATH)

    missing_id = request_id_from(missing)
    controlled_id = request_id_from(controlled)
    unhandled_id = request_id_from(unhandled)

    controlled_payload = controlled.json()
    controlled_error = controlled_payload.get("error", {})
    unhandled_payload = unhandled.json()
    unhandled_error = unhandled_payload.get("error", {})

    record(
        "404 remains a normal non-server error",
        missing.status_code == 404 and bool(missing_id),
        f"status={missing.status_code} request_id={missing_id}",
    )
    record(
        "controlled 503 preserves canonical safe client contract",
        (
            controlled.status_code == 503
            and controlled_error.get("code") == "GATE_CONTROLLED_503"
            and bool(controlled_id)
        ),
        f"status={controlled.status_code} code={controlled_error.get('code')}",
    )
    record(
        "unhandled 500 preserves canonical redacted client contract",
        (
            unhandled.status_code == 500
            and unhandled_error.get("code") == "INTERNAL_SERVER_ERROR"
            and bool(unhandled_id)
        ),
        f"status={unhandled.status_code} code={unhandled_error.get('code')}",
    )

    controlled_body = controlled.text
    unhandled_body = unhandled.text
    record(
        "controlled root cause is not leaked to client",
        "CONTROLLED_ROOT_CAUSE" not in controlled_body
        and "gatepass" not in controlled_body,
    )
    record(
        "unexpected root cause is not leaked to client",
        "UNHANDLED_ROOT_CAUSE" not in unhandled_body
        and "gate-super-secret" not in unhandled_body,
    )

    shutdown_http_error_logging()
    log_text = LOG_PATH.read_text(encoding="utf-8")

    record(
        "4xx request id is absent from error.log",
        bool(missing_id) and missing_id not in log_text,
        f"request_id={missing_id}",
    )
    record(
        "controlled 503 request id is logged exactly once",
        bool(controlled_id) and log_text.count(controlled_id) == 1,
        (
            f"request_id={controlled_id} "
            f"count={log_text.count(controlled_id or '') if controlled_id else 0}"
        ),
    )
    record(
        "unhandled 500 request id is logged exactly once",
        bool(unhandled_id) and log_text.count(unhandled_id) == 1,
        (
            f"request_id={unhandled_id} "
            f"count={log_text.count(unhandled_id or '') if unhandled_id else 0}"
        ),
    )
    record(
        "controlled 503 log keeps code status path and root cause",
        (
            '"error_code":"GATE_CONTROLLED_503"' in log_text
            and '"status_code":503' in log_text
            and CONTROLLED_PATH in log_text
            and '"root_cause_type":"RuntimeError"' in log_text
            and "CONTROLLED_ROOT_CAUSE" in log_text
        ),
    )
    record(
        "unhandled 500 log keeps code status path and root cause",
        (
            '"error_code":"INTERNAL_SERVER_ERROR"' in log_text
            and '"status_code":500' in log_text
            and UNHANDLED_PATH in log_text
            and "UNHANDLED_ROOT_CAUSE" in log_text
        ),
    )
    record(
        "server logs redact database credentials and named secrets",
        (
            "gatepass" not in log_text
            and "gate-super-secret" not in log_text
            and "***REDACTED***" in log_text
        ),
    )
    record(
        "legacy route-local logger cannot create duplicate error.log incidents",
        (
            "LEGACY_ROUTE_LOG_MUST_NOT_ENTER_ERROR_FILE" not in log_text
            and log_text.count('"event":"http_server_error"') == 2
        ),
        f"incident_count={log_text.count(chr(34) + 'event' + chr(34) + ':' + chr(34) + 'http_server_error' + chr(34))}",
    )

    failures = [name for name, ok, _ in RESULTS if not ok]
    print(f"CHECKS={len(RESULTS)}")
    print(f"FAILURES={len(failures)}")
    for failure in failures:
        print(f"FAILED_CHECK={failure}")

    try:
        if LOG_PATH.exists():
            LOG_PATH.unlink()
        for rotated in LOG_PATH.parent.glob(LOG_PATH.name + ".*"):
            rotated.unlink()
    finally:
        os.environ.pop("WANASAH_ERROR_LOG_PATH", None)

    if failures:
        print("HTTP_5XX_OBSERVABILITY_RUNTIME_GATE=FAIL")
        raise SystemExit(1)

    print("HTTP_5XX_OBSERVABILITY_RUNTIME_GATE=PASS")


if __name__ == "__main__":
    asyncio.run(run())
