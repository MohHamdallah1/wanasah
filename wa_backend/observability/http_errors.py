from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


LOGGER_NAME = "wanasah_logger"
ERROR_LOG_PATH_ENV = "WANASAH_ERROR_LOG_PATH"
DEFAULT_ERROR_LOG_PATH = "error.log"
ERROR_LOG_MAX_BYTES = 1024 * 1024
ERROR_LOG_BACKUP_COUNT = 5
_HTTP_EVENT_MARKER = "wanasah_http_server_error"


class _HttpServerErrorFilter(logging.Filter):
    """Keep error.log dedicated to one correlated record per HTTP 5xx."""

    def filter(self, record: logging.LogRecord) -> bool:
        return bool(getattr(record, _HTTP_EVENT_MARKER, False))


def _redact_secrets(value: str) -> str:
    text = str(value or "")
    text = re.sub(
        r"(postgresql(?:\+[A-Za-z0-9_]+)?://)[^:@/\s]+:[^@\s]+(@)",
        r"\1***REDACTED***:***REDACTED***\2",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(
        r"(?i)\b(SECRET_KEY|PASSWORD|API_KEY|ACCESS_TOKEN|REFRESH_TOKEN)"
        r"\b\s*[:=]\s*([^\s,;]+)",
        r"\1=***REDACTED***",
        text,
    )
    return text


def _single_line(value: str) -> str:
    return _redact_secrets(value).replace("\r", "\\r").replace("\n", "\\n")


def _root_cause(exc: BaseException) -> BaseException:
    current = exc
    seen: set[int] = set()

    while id(current) not in seen:
        seen.add(id(current))
        if current.__cause__ is not None:
            current = current.__cause__
            continue
        if (
            current.__context__ is not None
            and not current.__suppress_context__
        ):
            current = current.__context__
            continue
        break

    return current


def _exception_trace(exc: BaseException) -> str:
    rendered = "".join(
        traceback.format_exception(type(exc), exc, exc.__traceback__)
    )
    return _single_line(rendered)


def build_http_server_error_event(
    *,
    request_id: str,
    status_code: int,
    error_code: str,
    method: str,
    path: str,
    client_ip: str,
    exc: BaseException,
    handled_http_exception: bool,
) -> dict[str, Any]:
    status = int(status_code)
    if status < 500:
        raise ValueError("HTTP server-error events require status_code >= 500.")

    root = _root_cause(exc)
    return {
        "event": "http_server_error",
        "request_id": _single_line(request_id or "N/A"),
        "status_code": status,
        "error_code": _single_line(error_code or f"HTTP_{status}"),
        "method": _single_line(method),
        "path": _single_line(path),
        "client_ip": _single_line(client_ip),
        "handled_http_exception": bool(handled_http_exception),
        "exception_type": type(exc).__name__,
        "root_cause_type": type(root).__name__,
        "root_cause_message": _single_line(str(root)),
        "traceback": _exception_trace(exc),
    }


_logger = logging.getLogger(LOGGER_NAME)
_logger.setLevel(logging.ERROR)


def _configured_log_path() -> Path:
    configured = os.getenv(ERROR_LOG_PATH_ENV, DEFAULT_ERROR_LOG_PATH).strip()
    if not configured:
        configured = DEFAULT_ERROR_LOG_PATH
    return Path(configured).expanduser().resolve()


def _ensure_http_error_handler() -> RotatingFileHandler:
    target = _configured_log_path()

    for existing in list(_logger.handlers):
        if not getattr(existing, "_wanasah_http_error_handler", False):
            continue
        if Path(existing.baseFilename).resolve() == target:
            return existing
        _logger.removeHandler(existing)
        existing.close()

    target.parent.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        target,
        maxBytes=ERROR_LOG_MAX_BYTES,
        backupCount=ERROR_LOG_BACKUP_COUNT,
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
    )
    handler.addFilter(_HttpServerErrorFilter())
    handler._wanasah_http_error_handler = True
    _logger.addHandler(handler)
    return handler


def _write_http_server_error_event(event: dict[str, Any]) -> None:
    _ensure_http_error_handler()
    payload = json.dumps(
        event,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    _logger.error(
        payload,
        extra={_HTTP_EVENT_MARKER: True},
    )


async def log_http_server_error(
    *,
    request_id: str,
    status_code: int,
    error_code: str,
    method: str,
    path: str,
    client_ip: str,
    exc: BaseException,
    handled_http_exception: bool,
) -> None:
    """Persist one correlated, sanitized HTTP 5xx event without blocking ASGI."""

    if int(status_code) < 500:
        return

    event = build_http_server_error_event(
        request_id=request_id,
        status_code=status_code,
        error_code=error_code,
        method=method,
        path=path,
        client_ip=client_ip,
        exc=exc,
        handled_http_exception=handled_http_exception,
    )

    try:
        await asyncio.to_thread(_write_http_server_error_event, event)
    except Exception:
        # Observability failure must never replace the original API response.
        logging.getLogger("uvicorn.error").exception(
            "Failed to persist HTTP server-error event "
            "[request_id=%s status=%s code=%s]",
            event["request_id"],
            event["status_code"],
            event["error_code"],
        )


def shutdown_http_error_logging() -> None:
    """Close only Wanasah's rotating HTTP-error handler (used by process shutdown/tests)."""

    for existing in list(_logger.handlers):
        if not getattr(existing, "_wanasah_http_error_handler", False):
            continue
        _logger.removeHandler(existing)
        existing.close()
