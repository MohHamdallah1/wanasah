# STALE_HANDSHAKE_MONITOR_V1
from __future__ import annotations

import asyncio
import json
import logging

import asyncpg

from config import Config
from ws_manager import dispatch_manager

logger = logging.getLogger("wanasah_logger")

WORKER_EVENT_CHANNEL = "wanasah_worker_events"
_ALLOWED_EVENTS = {
    "STALE_HANDSHAKE_WARNING",
    "STALE_HANDSHAKE_CRITICAL",
    "STALE_SESSION_WARNING",
    "STALE_SESSION_CRITICAL",
    "INTEGRITY_ALERT",
}


def _to_asyncpg_dsn(raw_url: str) -> str:
    url = str(raw_url or "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is required for worker event relay.")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql+asyncpg://"):
        url = "postgresql://" + url[len("postgresql+asyncpg://"):]
    elif url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://"):]
    return url


class WorkerEventRelay:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=1000)

    async def start(self) -> None:
        if self._task is not None and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name="wanasah-worker-event-relay",
        )

    async def stop(self) -> None:
        self._stop.set()
        task = self._task
        self._task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def _on_notification(
        self,
        connection,
        pid: int,
        channel: str,
        payload: str,
    ) -> None:
        if channel != WORKER_EVENT_CHANNEL:
            return
        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            logger.error(
                "Worker event relay queue full; dropping realtime event. "
                "SystemAuditLog remains authoritative."
            )

    async def _dispatch_payload(self, raw_payload: str) -> None:
        try:
            data = json.loads(raw_payload)
            if not isinstance(data, dict):
                raise ValueError("payload must be an object")
            event = str(data.get("event") or "")
            company_id = int(data.get("company_id"))
            message = str(data.get("message") or "").strip()
            if event not in _ALLOWED_EVENTS:
                raise ValueError("event is not allowlisted")
            if company_id <= 0 or not message:
                raise ValueError("invalid company_id/message")
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            logger.error("Rejected malformed worker event: %s", exc)
            return

        outbound = {"event": event, "message": message}
        extra = data.get("data")
        if isinstance(extra, dict):
            outbound["data"] = extra

        await dispatch_manager.broadcast(outbound, company_id=company_id)

    async def _run(self) -> None:
        dsn = _to_asyncpg_dsn(Config.SQLALCHEMY_DATABASE_URI)
        while not self._stop.is_set():
            conn = None
            try:
                conn = await asyncpg.connect(dsn)
                await conn.add_listener(
                    WORKER_EVENT_CHANNEL,
                    self._on_notification,
                )
                logger.info("Worker event relay LISTEN active.")

                while not self._stop.is_set():
                    if conn.is_closed():
                        raise ConnectionError(
                            "Worker event relay PostgreSQL connection closed."
                        )
                    try:
                        payload = await asyncio.wait_for(
                            self._queue.get(),
                            timeout=15.0,
                        )
                    except asyncio.TimeoutError:
                        continue
                    await self._dispatch_payload(payload)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Worker event relay disconnected: %s",
                    exc,
                    exc_info=True,
                )
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    pass
            finally:
                if conn is not None and not conn.is_closed():
                    try:
                        await conn.remove_listener(
                            WORKER_EVENT_CHANNEL,
                            self._on_notification,
                        )
                    except Exception:
                        pass
                    await conn.close()


worker_event_relay = WorkerEventRelay()
