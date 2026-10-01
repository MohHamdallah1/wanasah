"""Disposable localhost API launcher with the canonical Windows SelectorEventLoop.

The CLI's default ProactorEventLoop is incompatible with Psycopg's async queue
connector. This matches the worker_cli Windows loop contract without changing
the existing API process or weakening its actual FastAPI lifespan.
"""
from __future__ import annotations

import asyncio
import os
from sqlalchemy.engine import make_url

if os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("Refusing synthetic HTTP server outside guarded disposable runner.")
url = make_url(os.environ.get("DATABASE_URL", ""))
if (
    url.host != "127.0.0.1"
    or url.database != "p19_http_synthetic"
    or int(url.port or 0) != 55446
):
    raise RuntimeError("Refusing synthetic HTTP server outside isolated local PostgreSQL.")

import uvicorn


def main() -> None:
    config = uvicorn.Config(
        "main:app", host="127.0.0.1",
        port=int(os.environ["WANASAH_P19_HTTP_API_PORT"]),
        access_log=False, log_level="info",
    )
    server = uvicorn.Server(config)
    if os.name == "nt":
        asyncio.run(server.serve(), loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(server.serve())


if __name__ == "__main__":
    main()
