"""PostgreSQL NOTIFY relay for durable Product Import progress."""
from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

import asyncpg

from domains.simple_products.imports.infrastructure.queue_dsn import (
    product_import_psycopg_dsn,
)
from domains.simple_products.imports.infrastructure.realtime_manager import (
    product_import_connection_manager,
)


logger = logging.getLogger(
    "wanasah_logger"
)
PRODUCT_IMPORT_EVENT_CHANNEL = (
    "wanasah_product_import_progress"
)
COALESCE_SECONDS = 0.25
MAX_EVENT_BUFFER = 1000
LISTEN_HEARTBEAT_SECONDS = 15.0
LISTEN_HEARTBEAT_TIMEOUT_SECONDS = 5.0


def _parse_event(
    raw_payload: str,
) -> tuple[
    tuple[int, UUID],
    dict[str, object],
] | None:
    try:
        raw = json.loads(
            raw_payload
        )
        if (
            not isinstance(
                raw,
                dict,
            )
            or raw.get(
                "event"
            )
            != "PRODUCT_IMPORT_PROGRESS"
        ):
            return None
        company_id = int(
            raw[
                "company_id"
            ]
        )
        job_id = UUID(
            str(
                raw[
                    "job_id"
                ]
            )
        )
        if company_id <= 0:
            return None
        outbound = {
            "event":
                "PRODUCT_IMPORT_PROGRESS",
            "job_id":
                str(
                    job_id
                ),
            "status":
                str(
                    raw.get(
                        "status",
                        "",
                    )
                ),
            "version":
                int(
                    raw.get(
                        "version",
                        0,
                    )
                ),
            "total_rows":
                int(
                    raw.get(
                        "total_rows",
                        0,
                    )
                ),
            "processed_rows":
                int(
                    raw.get(
                        "processed_rows",
                        0,
                    )
                ),
            "valid_rows":
                int(
                    raw.get(
                        "valid_rows",
                        0,
                    )
                ),
            "failed_rows":
                int(
                    raw.get(
                        "failed_rows",
                        0,
                    )
                ),
        }
        return (
            (
                company_id,
                job_id,
            ),
            outbound,
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None


class ProductImportEventRelay:
    """Bounded, coalescing relay. Durable job state remains authoritative."""

    def __init__(
        self,
    ) -> None:
        self._task: (
            asyncio.Task
            | None
        ) = None
        self._stop = asyncio.Event()
        self._queue: asyncio.Queue[
            str
        ] = asyncio.Queue(
            maxsize=
                MAX_EVENT_BUFFER
        )

    async def start(
        self,
    ) -> None:
        if (
            self._task is not None
            and not self._task.done()
        ):
            return
        self._stop.clear()
        self._task = asyncio.create_task(
            self._run(),
            name=
                "product-import-event-relay",
        )

    async def stop(
        self,
    ) -> None:
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
        if (
            channel
            != PRODUCT_IMPORT_EVENT_CHANNEL
        ):
            return
        try:
            self._queue.put_nowait(
                payload
            )
        except asyncio.QueueFull:
            logger.error(
                "Product Import realtime buffer full; dropping push event. "
                "Durable HTTP state remains authoritative."
            )

    async def _flush_batch(
        self,
        first_payload: str,
    ) -> None:
        payloads = [
            first_payload
        ]
        await asyncio.sleep(
            COALESCE_SECONDS
        )
        while (
            len(
                payloads
            )
            < MAX_EVENT_BUFFER
        ):
            try:
                payloads.append(
                    self._queue.get_nowait()
                )
            except asyncio.QueueEmpty:
                break

        latest: dict[
            tuple[int, UUID],
            dict[str, object],
        ] = {}
        for raw in payloads:
            parsed = _parse_event(
                raw
            )
            if parsed is None:
                continue
            key, payload = parsed
            previous = latest.get(
                key
            )
            if (
                previous is None
                or int(
                    payload[
                        "version"
                    ]
                )
                >= int(
                    previous[
                        "version"
                    ]
                )
            ):
                latest[
                    key
                ] = payload

        for (
            company_id,
            job_id,
        ), payload in latest.items():
            await (
                product_import_connection_manager.broadcast(
                    payload,
                    company_id=
                        company_id,
                    job_id=
                        job_id,
                )
            )

    async def _run(
        self,
    ) -> None:
        while not self._stop.is_set():
            connection = None
            try:
                connection = (
                    await asyncpg.connect(
                        product_import_psycopg_dsn(),
                        timeout=10.0,
                        command_timeout=10.0,
                    )
                )
                await connection.add_listener(
                    PRODUCT_IMPORT_EVENT_CHANNEL,
                    self._on_notification,
                )
                logger.info(
                    "Product Import realtime LISTEN active."
                )
                while not self._stop.is_set():
                    try:
                        payload = (
                            await asyncio.wait_for(
                                self._queue.get(),
                                timeout=
                                    LISTEN_HEARTBEAT_SECONDS,
                            )
                        )
                    except asyncio.TimeoutError:
                        await asyncio.wait_for(
                            connection.execute(
                                "SELECT 1"
                            ),
                            timeout=
                                LISTEN_HEARTBEAT_TIMEOUT_SECONDS,
                        )
                        continue
                    await self._flush_batch(
                        payload
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "Product Import realtime relay disconnected."
                )
                try:
                    await asyncio.wait_for(
                        self._stop.wait(),
                        timeout=5.0,
                    )
                except asyncio.TimeoutError:
                    pass
            finally:
                if (
                    connection
                    is not None
                    and not connection.is_closed()
                ):
                    try:
                        await connection.remove_listener(
                            PRODUCT_IMPORT_EVENT_CHANNEL,
                            self._on_notification,
                        )
                    except Exception:
                        pass
                    await connection.close()


product_import_event_relay = (
    ProductImportEventRelay()
)
