# ═══════════════════════════════════════════════════════════════════════════════
# Wanasah — WebSocket Connection Manager (Dispatch Dashboard)
# ═══════════════════════════════════════════════════════════════════════════════
# Step 5.7a: Real-time push for dispatch data (replaces polling)
# ═══════════════════════════════════════════════════════════════════════════════
import logging
from fastapi import WebSocket

logger = logging.getLogger("wanasah_logger")


class ConnectionManager:
    """Manages WebSocket connections for the dispatch dashboard live feed."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection and add it to the active pool."""
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"[WS] Client connected. Total active: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a disconnected WebSocket from the active pool."""
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            logger.info(f"[WS] Client disconnected. Total active: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Send a JSON-serialisable dictionary to all connected clients.

        Disconnected or failing clients are silently removed from the pool
        so one bad connection never crashes the broadcast loop.
        """
        dead_connections: list[WebSocket] = []

        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                # Client likely disconnected or had a transport error
                dead_connections.append(connection)

        # Clean up dead connections outside the iteration loop
        for dead in dead_connections:
            self.disconnect(dead)


# Global singleton used by the WS endpoint and dispatch APIs
dispatch_manager = ConnectionManager()