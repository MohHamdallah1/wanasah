from __future__ import annotations

import os
import time

from main import app


@app.middleware("http")
async def live_stock_benchmark_timing(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-wanasah-benchmark-pid"] = str(os.getpid())
    response.headers["x-wanasah-benchmark-server-ms"] = (
        f"{(time.perf_counter() - started) * 1000:.3f}"
    )
    return response


@app.get(
    "/__live_stock_benchmark_readiness__",
    include_in_schema=False,
)
async def live_stock_benchmark_readiness():
    return {
        "ready": True,
        "pid": os.getpid(),
    }
