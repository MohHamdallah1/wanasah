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
        # +++ عزل الشركات: القاموس يربط كل شركة بقائمة اتصالاتها الخاصة +++
        self.active_connections: dict[int, list[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, company_id: int) -> bool:
        """Accept a new WebSocket connection and add it to the active pool of the tenant."""
        # +++ حساب الإجمالي لكل الشركات لمنع استنزاف الرام +++
        total_connections = sum(len(conns) for conns in self.active_connections.values())
        
        # +++   نسف هجمات استنزاف الموارد (OOM) +++
        if total_connections >= MAX_WS_CONNECTIONS:
            logger.warning(f"[WS] DDoS Shield Active: Rejected connection. Max limit ({MAX_WS_CONNECTIONS}) reached.")
            await websocket.close(code=1008) # 1008 = Policy Violation
            return False

        await websocket.accept()
        if company_id not in self.active_connections:
            self.active_connections[company_id] = []
        self.active_connections[company_id].append(websocket)
        
        logger.info(f"[WS] Client connected to Company {company_id}. Total active globally: {total_connections + 1}")
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
            *[connection.send_json(message) for connection in connections],
            return_exceptions=True
        )

        # +++ تنظيف القنوات الميتة التي أرجعت استثناء +++
        for connection, result in zip(connections, results):
            if isinstance(result, Exception):
                logger.warning(f"[WS] Removing failed/dead connection: {result}")
                self.disconnect(connection, company_id)

# Global singleton used by the WS endpoint and dispatch APIs
dispatch_manager = ConnectionManager()