from __future__ import annotations

import asyncio
import os
import time

from fastapi import Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from api.dependencies import get_current_driver
from database import get_db
from main import app


@app.middleware("http")
async def _stage823_probe_timing(request, call_next):
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["x-wanasah-probe-server-ms"] = (
        f"{(time.perf_counter() - started) * 1000:.3f}"
    )
    response.headers["x-wanasah-probe-pid"] = str(os.getpid())
    return response


@app.get("/__stage823_probe/raw", include_in_schema=False)
async def _stage823_probe_raw():
    return {"ok": True}


@app.get("/__stage823_probe/hold", include_in_schema=False)
async def _stage823_probe_hold():
    # Diagnostic-only endpoint: holding the request open forces HTTPX to
    # establish the requested number of concurrent loopback connections.
    await asyncio.sleep(0.05)
    return {"ok": True}


@app.get("/__stage823_probe/db", include_in_schema=False)
async def _stage823_probe_db(db: AsyncSession = Depends(get_db)):
    value = await db.scalar(text("SELECT 1"))
    return {"ok": value == 1}


@app.get("/__stage823_probe/auth", include_in_schema=False)
async def _stage823_probe_auth(current_driver=Depends(get_current_driver)):
    return {"ok": True, "driver_id": int(current_driver.id)}
