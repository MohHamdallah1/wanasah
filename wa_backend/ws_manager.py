# ═══════════════════════════════════════════════════════════════════════════════
# Wanasah — WebSocket Connection Manager (Dispatch Dashboard)
# ═══════════════════════════════════════════════════════════════════════════════
# Step 5.7a: Real-time push for dispatch data (replaces polling)
# ═══════════════════════════════════════════════════════════════════════════════
import asyncio
import logging
from fastapi import WebSocket

logger = logging.getLogger("wanasah_logger")

# +++ الدرع الأمني (DDoS Shield): وضع سقف صارم للاتصالات المفتوحة لمنع اختناق الرام +++
MAX_WS_CONNECTIONS = 50

class ConnectionManager:
    """Manages WebSocket connections for the dispatch dashboard live feed."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> bool:
        """Accept a new WebSocket connection and add it to the active pool."""
        # +++   نسف هجمات استنزاف الموارد (OOM) +++
        if len(self.active_connections) >= MAX_WS_CONNECTIONS:
            logger.warning(f"[WS] DDoS Shield Active: Rejected connection. Max limit ({MAX_WS_CONNECTIONS}) reached.")
            await websocket.close(code=1008) # 1008 = Policy Violation
            return False

        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[WS] Client connected. Total active: {len(self.active_connections)}")
        return True

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket from the active pool."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"[WS] Client disconnected. Total active: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send a JSON-serialisable dictionary to all connected clients in parallel.

        Uses asyncio.gather to prevent slow connections from blocking others.
        Disconnected or failing clients are cleaned up safely.
        """
        if not self.active_connections:
            return

        # +++ لقطة آمنة بالذاكرة لمنع RuntimeError: list changed size during iteration +++
        connections = list(self.active_connections)
        
        # +++ بث بالتوازي لكل الشاشات فوراً دون انتظار العميل البطيء +++
        results = await asyncio.gather(
            *[connection.send_json(message) for connection in connections],
            return_exceptions=True
        )

        # +++ تنظيف القنوات الميتة التي أرجعت استثناء +++
        for connection, result in zip(connections, results):
            if isinstance(result, Exception):
                logger.warning(f"[WS] Removing failed/dead connection: {result}")
                self.disconnect(connection)

# Global singleton used by the WS endpoint and dispatch APIs
dispatch_manager = ConnectionManager()