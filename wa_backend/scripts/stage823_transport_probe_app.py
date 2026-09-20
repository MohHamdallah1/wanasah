from __future__ import annotations

import asyncio
import os
import time

from fastapi import FastAPI, Request

app = FastAPI(
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


@app.middleware("http")
async def _timing(request: Request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-wanasah-probe-server-ms"] = (
        f"{(time.perf_counter() - started) * 1000:.3f}"
    )
    response.headers["x-wanasah-probe-pid"] = str(os.getpid())
    return response


@app.get("/raw")
async def raw():
    return {"ok": True}


@app.get("/hold")
async def hold():
    # Forces the client to establish concurrent loopback connections during
    # transport prewarm without involving the production app or any DB/queue.
    await asyncio.sleep(0.05)
    return {"ok": True}
