# ═══════════════════════════════════════════════════════════════════════════════
# Wanasah — WebSocket Connection Manager (Dispatch Dashboard)
# ═══════════════════════════════════════════════════════════════════════════════
# Step 5.7a: Real-time push for dispatch data (replaces polling)
# ═══════════════════════════════════════════════════════════════════════════════
import asyncio
import os
import logging
from fastapi import WebSocket

logger = logging.getLogger("wanasah_logger")

# +++ الدرع الأمني (DDoS Shield): وضع سقف صارم للاتصالات المفتوحة لمنع اختناق الرام +++
def _positive_env_int(name: str, default: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError as exc:
        raise RuntimeError(f"{name} must be a positive integer.") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


MAX_WS_CONNECTIONS = _positive_env_int("WS_MAX_GLOBAL_CONNECTIONS", 50)
MAX_WS_CONNECTIONS_PER_TENANT = _positive_env_int(
    "WS_MAX_CONNECTIONS_PER_TENANT",
    10,
)
if MAX_WS_CONNECTIONS < (2 * MAX_WS_CONNECTIONS_PER_TENANT):
    raise RuntimeError(
        "WS_MAX_GLOBAL_CONNECTIONS must be at least twice "
        "WS_MAX_CONNECTIONS_PER_TENANT."
    )
WS_SEND_TIMEOUT_SECONDS = 3.0

class ConnectionManager:
    """Manages WebSocket connections for the dispatch dashboard live feed."""

    def __init__(self):
        self.active_connections: dict[int, list[WebSocket]] = {}
        self._connections_lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, company_id: int) -> bool:
        company_id = int(company_id)
        if company_id <= 0:
            await websocket.close(code=1008)
            return False

        async with self._connections_lock:
            tenant_connections = len(
                self.active_connections.get(company_id, [])
            )
            total_connections = sum(
                len(conns) for conns in self.active_connections.values()
            )

            if tenant_connections >= MAX_WS_CONNECTIONS_PER_TENANT:
                logger.warning(
                    "[WS] Tenant connection limit reached for company %s (%s).",
                    company_id,
                    MAX_WS_CONNECTIONS_PER_TENANT,
                )
                await websocket.close(code=1008)
                return False

            if total_connections >= MAX_WS_CONNECTIONS:
                logger.warning(
                    "[WS] Global connection limit reached (%s).",
                    MAX_WS_CONNECTIONS,
                )
                await websocket.close(code=1008)
                return False

            await websocket.accept()
            self.active_connections.setdefault(company_id, []).append(websocket)

        logger.info(
            "[WS] Client connected to Company %s. Tenant=%s Global=%s",
            company_id,
            tenant_connections + 1,
            total_connections + 1,
        )
        return True

    def disconnect(self, websocket: WebSocket, company_id: int):
        """Remove a disconnected WebSocket from the active pool."""
        if company_id in self.active_connections and websocket in self.active_connections[company_id]:
            self.active_connections[company_id].remove(websocket)
            # +++ تنظيف القاموس إذا فرغت الشركة من الاتصالات +++
            if not self.active_connections[company_id]:
                del self.active_connections[company_id]
            logger.info(f"[WS] Client disconnected from Company {company_id}.")

    async def broadcast(self, message: dict, company_id: int):
        """Send a JSON-serialisable dictionary to all connected clients of a specific company in parallel.

        Uses asyncio.gather to prevent slow connections from blocking others.
        Disconnected or failing clients are cleaned up safely.
        """
        if company_id not in self.active_connections or not self.active_connections[company_id]:
            return

        # +++ لقطة آمنة بالذاكرة لعملاء الشركة المعنية فقط +++
        connections = list(self.active_connections[company_id])
        
        # +++ بث بالتوازي لكل الشاشات فوراً دون انتظار العميل البطيء +++
        results = await asyncio.gather(
            *[
                asyncio.wait_for(
                    connection.send_json(message),
                    timeout=WS_SEND_TIMEOUT_SECONDS,
                )
                for connection in connections
            ],
            return_exceptions=True,
        )

        # +++ تنظيف القنوات الميتة التي أرجعت استثناء +++
        for connection, result in zip(connections, results):
            if isinstance(result, Exception):
                logger.warning(f"[WS] Removing failed/dead connection: {result}")
                self.disconnect(connection, company_id)

# Global singleton used by the WS endpoint and dispatch APIs
dispatch_manager = ConnectionManager()