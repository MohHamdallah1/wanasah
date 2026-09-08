# STALE_HANDSHAKE_MONITOR_V1
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WORKER_EVENT_CHANNEL = "wanasah_worker_events"
_MAX_NOTIFY_BYTES = 7000


async def emit_worker_event(
    db: AsyncSession,
    *,
    company_id: int,
    event: str,
    message: str,
    data: dict | None = None,
) -> None:
    payload = {
        "company_id": int(company_id),
        "event": str(event),
        "message": str(message),
        "data": data or {},
    }
    raw = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(raw.encode("utf-8")) > _MAX_NOTIFY_BYTES:
        raise ValueError("Worker realtime event payload is too large.")

    await db.execute(
        text("SELECT pg_notify(:channel, :payload)"),
        {"channel": WORKER_EVENT_CHANNEL, "payload": raw},
    )
