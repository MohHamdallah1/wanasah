from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api.auth import create_access_token  # noqa: E402
from context import tenant_context  # noqa: E402
from database import AsyncSessionLocal, engine  # noqa: E402
from models import Driver  # noqa: E402

WORKERS = 4
POOL_SIZE = 5
MAX_OVERFLOW = 0
DB_CAP = WORKERS * (POOL_SIZE + MAX_OVERFLOW)


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * p
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[low]
    weight = pos - low
    return ordered[low] * (1.0 - weight) + ordered[high] * weight


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def benchmark_token(company_id: int, driver_id: int) -> str:
    token = tenant_context.set(company_id)
    try:
        async with AsyncSessionLocal() as db:
            driver = await db.scalar(
                select(Driver).where(
                    Driver.id == driver_id,
                    Driver.company_id == company_id,
                    Driver.is_active.is_(True),
                )
            )
            if driver is None:
                raise RuntimeError(
                    f"Active driver {driver_id} not found in company {company_id}."
                )
            return create_access_token(
                {
                    "sub": str(driver.id),
                    "is_admin": bool(driver.is_admin),
                    "username": driver.username,
                },
                company_id=company_id,
                role_name="Admin" if driver.is_admin else "Inventory",
            )
    finally:
        tenant_context.reset(token)


def start_server() -> tuple[subprocess.Popen, int, str]:
    if DB_CAP != 20:
        raise RuntimeError("Probe topology must remain 4 x 5 = 20 DB connections.")

    port = free_port()
    env = os.environ.copy()
    env.update(
        {
            "WEB_CONCURRENCY": str(WORKERS),
            "DB_APP_CONNECTION_BUDGET": str(DB_CAP),
            "DB_POOL_SIZE": str(POOL_SIZE),
            "DB_MAX_OVERFLOW": str(MAX_OVERFLOW),
            "DB_POOL_TIMEOUT": "3",
            "DB_POOL_RECYCLE": "1800",
        }
    )

    log_file = tempfile.NamedTemporaryFile(
        prefix="wanasah-stage823-probe-",
        suffix=".log",
        delete=False,
    )
    log_path = log_file.name
    log_file.close()
    log_stream = open(log_path, "w", encoding="utf-8")

    kwargs: dict[str, Any] = {
        "cwd": str(ROOT),
        "env": env,
        "stdout": log_stream,
        "stderr": subprocess.STDOUT,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "scripts.stage823_uvicorn_probe_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            str(WORKERS),
            "--log-level",
            "warning",
        ],
        **kwargs,
    )
    log_stream.close()
    return process, port, log_path


def read_log(path: str, limit: int = 12000) -> str:
    try:
        value = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return value[-limit:]


def stop_server(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        process.wait(timeout=10)
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


async def wait_ready(process: subprocess.Popen, base_url: str, log_path: str) -> None:
    deadline = time.monotonic() + 60.0
    async with httpx.AsyncClient(base_url=base_url, timeout=2.0) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError(
                    "Probe Uvicorn exited before readiness.\n" + read_log(log_path)
                )
            try:
                response = await client.get("/__stage823_probe/raw")
                if response.status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            await asyncio.sleep(0.2)
    raise RuntimeError(
        "Probe Uvicorn did not become ready.\n" + read_log(log_path)
    )


async def run_case(
    *,
    client: httpx.AsyncClient,
    name: str,
    path: str,
    concurrency: int,
    requests: int,
) -> dict[str, Any]:
    warmup = max(2, min(concurrency, 5))
    for _ in range(warmup):
        response = await client.get(path)
        response.raise_for_status()

    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    server_ms: list[float] = []
    statuses: list[int] = []
    pids: dict[str, int] = {}
    timeouts = 0
    transport_errors = 0

    async def one() -> None:
        nonlocal timeouts, transport_errors
        async with sem:
            started = time.perf_counter()
            try:
                response = await client.get(path)
                statuses.append(response.status_code)
                raw_server = response.headers.get("x-wanasah-probe-server-ms")
                if raw_server is not None:
                    server_ms.append(float(raw_server))
                pid = response.headers.get("x-wanasah-probe-pid", "?")
                pids[pid] = pids.get(pid, 0) + 1
            except httpx.TimeoutException:
                timeouts += 1
            except httpx.HTTPError:
                transport_errors += 1
            finally:
                latencies.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(one() for _ in range(requests)))
    errors = (
        sum(1 for status in statuses if status != 200)
        + timeouts
        + transport_errors
    )
    return {
        "route": name,
        "concurrency": concurrency,
        "requests": requests,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": max(latencies),
        "server_p95_ms": percentile(server_ms, 0.95),
        "client_minus_server_p95_ms": percentile(
            [
                max(0.0, client_ms - server_value)
                for client_ms, server_value in zip(latencies, server_ms)
            ],
            0.95,
        ) if len(server_ms) == len(latencies) else None,
        "errors": errors,
        "timeouts": timeouts,
        "transport_errors": transport_errors,
        "worker_hits": pids,
    }


async def async_main(args: argparse.Namespace) -> None:
    token = await benchmark_token(args.company_id, args.driver_id)
    await engine.dispose()

    process, port, log_path = start_server()
    base_url = f"http://127.0.0.1:{port}"
    try:
        await wait_ready(process, base_url, log_path)
        headers = {"Authorization": f"Bearer {token}"}
        routes = [
            ("raw", "/__stage823_probe/raw", False),
            ("db", "/__stage823_probe/db", False),
            ("auth", "/__stage823_probe/auth", True),
            (
                "alerts",
                f"/warehouse/inventory/alerts/summary?location_id={args.location_id}",
                True,
            ),
            (
                "cursor",
                f"/warehouse/inventory/cursor?location_id={args.location_id}&limit=50",
                True,
            ),
        ]

        async with httpx.AsyncClient(
            base_url=base_url,
            headers=headers,
            timeout=30.0,
        ) as client:
            print(
                "PROBE_TOPOLOGY="
                + json.dumps(
                    {
                        "workers": WORKERS,
                        "pool_size": POOL_SIZE,
                        "max_overflow": MAX_OVERFLOW,
                        "db_cap": DB_CAP,
                    },
                    sort_keys=True,
                )
            )
            for concurrency in args.concurrency:
                for name, path, _needs_auth in routes:
                    result = await run_case(
                        client=client,
                        name=name,
                        path=path,
                        concurrency=concurrency,
                        requests=args.requests,
                    )
                    print(
                        "PROBE="
                        + json.dumps(result, sort_keys=True)
                    )
    finally:
        stop_server(process)
        log_tail = read_log(log_path)
        if log_tail.strip():
            print("PROBE_UVICORN_LOG_BEGIN")
            print(log_tail)
            print("PROBE_UVICORN_LOG_END")
        try:
            Path(log_path).unlink(missing_ok=True)
        except OSError:
            pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Stage 8.2.3 four-worker Uvicorn diagnostic matrix. "
            "Separates raw ASGI, DB checkout, auth, alerts and cursor latency."
        )
    )
    parser.add_argument("--company-id", type=int, required=True)
    parser.add_argument("--driver-id", type=int, required=True)
    parser.add_argument("--location-id", type=int, required=True)
    parser.add_argument(
        "--concurrency",
        type=int,
        nargs="+",
        default=[1, 5, 10, 20],
    )
    parser.add_argument("--requests", type=int, default=40)
    args = parser.parse_args()
    if any(value < 1 or value > 100 for value in args.concurrency):
        parser.error("concurrency values must be between 1 and 100")
    if args.requests < max(args.concurrency):
        parser.error("--requests must be >= max concurrency")
    return args


def main() -> None:
    asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    main()
