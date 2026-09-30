"""Dedicated job-scoped Product Import WebSocket connections."""
from __future__ import annotations

import asyncio
import logging
import os
from uuid import UUID

from fastapi import WebSocket


logger = logging.getLogger(
    "wanasah_logger"
)


def _positive_env_int(
    name: str,
    default: int,
) -> int:
    try:
        value = int(
            os.getenv(
                name,
                str(
                    default
                ),
            )
        )
    except ValueError as exc:
        raise RuntimeError(
            f"{name} must be a positive integer."
        ) from exc
    if value <= 0:
        raise RuntimeError(
            f"{name} must be a positive integer."
        )
    return value


MAX_GLOBAL_CONNECTIONS = _positive_env_int(
    "PRODUCT_IMPORT_WS_MAX_GLOBAL_CONNECTIONS",
    100,
)
MAX_TENANT_CONNECTIONS = _positive_env_int(
    "PRODUCT_IMPORT_WS_MAX_TENANT_CONNECTIONS",
    20,
)
MAX_JOB_CONNECTIONS = _positive_env_int(
    "PRODUCT_IMPORT_WS_MAX_JOB_CONNECTIONS",
    5,
)
SEND_TIMEOUT_SECONDS = 3.0


class ProductImportConnectionManager:
    """Connection registry scoped by authenticated company + exact import job."""

    def __init__(
        self,
    ) -> None:
        self._connections: dict[
            tuple[int, UUID],
            list[WebSocket],
        ] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self,
        websocket: WebSocket,
        *,
        company_id: int,
        job_id: UUID,
        already_accepted: bool = False,
    ) -> bool:
        key = (
            int(
                company_id
            ),
            UUID(
                str(
                    job_id
                )
            ),
        )
        async with self._lock:
            tenant_count = sum(
                len(
                    connections
                )
                for (
                    tenant_id,
                    _job_id,
                ), connections
                in self._connections.items()
                if tenant_id
                == key[
                    0
                ]
            )
            total_count = sum(
                len(
                    connections
                )
                for connections
                in self._connections.values()
            )
            job_count = len(
                self._connections.get(
                    key,
                    [],
                )
            )

            if (
                total_count
                >= MAX_GLOBAL_CONNECTIONS
                or tenant_count
                >= MAX_TENANT_CONNECTIONS
                or job_count
                >= MAX_JOB_CONNECTIONS
            ):
                await websocket.close(
                    code=1013
                )
                return False

            if not already_accepted:
                await websocket.accept()
            self._connections.setdefault(
                key,
                [],
            ).append(
                websocket
            )
        return True

    async def disconnect(
        self,
        websocket: WebSocket,
        *,
        company_id: int,
        job_id: UUID,
    ) -> None:
        key = (
            int(
                company_id
            ),
            UUID(
                str(
                    job_id
                )
            ),
        )
        async with self._lock:
            connections = (
                self._connections.get(
                    key
                )
            )
            if not connections:
                return
            if websocket in connections:
                connections.remove(
                    websocket
                )
            if not connections:
                self._connections.pop(
                    key,
                    None,
                )

    async def broadcast(
        self,
        payload: dict[str, object],
        *,
        company_id: int,
        job_id: UUID,
    ) -> None:
        key = (
            int(
                company_id
            ),
            UUID(
                str(
                    job_id
                )
            ),
        )
        async with self._lock:
            connections = list(
                self._connections.get(
                    key,
                    [],
                )
            )
        if not connections:
            return

        results = await asyncio.gather(
            *[
                asyncio.wait_for(
                    connection.send_json(
                        payload
                    ),
                    timeout=
                        SEND_TIMEOUT_SECONDS,
                )
                for connection
                in connections
            ],
            return_exceptions=True,
        )
        failed = [
            connection
            for connection, result
            in zip(
                connections,
                results,
                strict=True,
            )
            if isinstance(
                result,
                Exception,
            )
        ]
        for connection in failed:
            logger.warning(
                "Removing failed Product Import realtime connection."
            )
            await self.disconnect(
                connection,
                company_id=
                    company_id,
                job_id=
                    job_id,
            )


product_import_connection_manager = (
    ProductImportConnectionManager()
)
