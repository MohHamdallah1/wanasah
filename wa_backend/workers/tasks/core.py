# WORKER_CORE_V1
from __future__ import annotations

from workers.app import MAINTENANCE_QUEUE, app


@app.task(
    name="wanasah.worker_healthcheck",
    queue=MAINTENANCE_QUEUE,
)
async def worker_healthcheck() -> dict[str, str]:
    """Minimal non-tenant task used only to verify worker execution."""
    return {"status": "ok"}
