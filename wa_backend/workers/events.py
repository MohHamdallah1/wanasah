# WORKER_EVENTS_V2
from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

WORKER_EVENT_CHANNEL = "wanasah_worker_events"
_MAX_NOTIFY_BYTES = 7000
_EVENT_BATCH_SIZE = 200


def _serialize_worker_event(
    *,
    company_id: int,
    event: str,
    message: str,
    data: dict | None = None,
) -> str:
    cid = int(company_id)
    event_name = str(event or "").strip()
    message_text = str(message or "").strip()

    if cid <= 0:
        raise ValueError("worker event company_id must be positive.")
    if not event_name or not message_text:
        raise ValueError("worker event requires event/message.")

    raw = json.dumps(
        {
            "company_id": cid,
            "event": event_name,
            "message": message_text,
            "data": data or {},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    if len(raw.encode("utf-8")) > _MAX_NOTIFY_BYTES:
        raise ValueError("Worker realtime event payload is too large.")
    return raw


async def emit_worker_events(
    db: AsyncSession,
    *,
    events: list[dict],
) -> None:
    if not events:
        return

    raw_payloads = [
        _serialize_worker_event(
            company_id=int(item["company_id"]),
            event=str(item["event"]),
            message=str(item["message"]),
            data=item.get("data"),
        )
        for item in events
    ]

    statement = text(
        "SELECT pg_notify(:channel, t.payload) "
        "FROM jsonb_array_elements_text("
        "CAST(:payloads AS jsonb)"
        ") AS t(payload)"
    )

    for offset in range(0, len(raw_payloads), _EVENT_BATCH_SIZE):
        chunk = raw_payloads[offset : offset + _EVENT_BATCH_SIZE]
        await db.execute(
            statement,
            {
                "channel": WORKER_EVENT_CHANNEL,
                "payloads": json.dumps(
                    chunk,
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        )


async def emit_worker_event(
    db: AsyncSession,
    *,
    company_id: int,
    event: str,
    message: str,
    data: dict | None = None,
) -> None:
    # Compatibility wrapper for low-volume callers such as Integrity Jobs.
    await emit_worker_events(
        db,
        events=[
            {
                "company_id": int(company_id),
                "event": str(event),
                "message": str(message),
                "data": data or {},
            }
        ],
    )
