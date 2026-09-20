from __future__ import annotations

import os

from main import app


@app.get(
    "/__live_stock_benchmark_readiness__",
    include_in_schema=False,
)
async def live_stock_benchmark_readiness():
    return {
        "ready": True,
        "pid": os.getpid(),
    }
