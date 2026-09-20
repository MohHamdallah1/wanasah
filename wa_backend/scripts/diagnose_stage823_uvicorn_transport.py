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

ROOT = Path(__file__).resolve().parent.parent


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
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


def start_server(workers: int) -> tuple[subprocess.Popen, int, str]:
    pool_size = 5
    db_cap = workers * pool_size
    port = free_port()
    env = os.environ.copy()
    env.update(
        {
            "WEB_CONCURRENCY": str(workers),
            "DB_APP_CONNECTION_BUDGET": str(db_cap),
            "DB_POOL_SIZE": str(pool_size),
            "DB_MAX_OVERFLOW": "0",
            "DB_POOL_TIMEOUT": "3",
            "DB_POOL_RECYCLE": "1800",
        }
    )

    log_file = tempfile.NamedTemporaryFile(
        prefix=f"wanasah-stage823-transport-w{workers}-",
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
            "scripts.stage823_transport_probe_app:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--workers",
            str(workers),
            "--log-level",
            "warning",
        ],
        **kwargs,
    )
    log_stream.close()
    return process, port, log_path


def read_log(path: str, limit: int = 12000) -> str:
    try:
        return Path(path).read_text(
            encoding="utf-8",
            errors="replace",
        )[-limit:]
    except OSError:
        return ""


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


async def wait_all_workers(
    process: subprocess.Popen,
    base_url: str,
    log_path: str,
    workers: int,
) -> list[str]:
    deadline = time.monotonic() + 60.0
    seen: set[str] = set()

    async def one() -> str | None:
        limits = httpx.Limits(max_connections=1, max_keepalive_connections=0)
        try:
            async with httpx.AsyncClient(
                base_url=base_url,
                timeout=3.0,
                limits=limits,
                headers={"Connection": "close"},
                trust_env=False,
            ) as client:
                response = await client.get("/raw")
                if response.status_code == 200:
                    return response.headers.get("x-wanasah-probe-pid")
        except httpx.HTTPError:
            return None
        return None

    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                "Uvicorn transport probe exited before readiness.\n"
                + read_log(log_path)
            )
        batch = await asyncio.gather(*(one() for _ in range(max(4, workers * 4))))
        seen.update(pid for pid in batch if pid)
        if len(seen) >= workers:
            return sorted(seen)
        await asyncio.sleep(0.2)

    raise RuntimeError(
        f"Only workers {sorted(seen)} became visible; expected {workers}.\n"
        + read_log(log_path)
    )


async def prime_connections(client: httpx.AsyncClient, concurrency: int) -> None:
    responses = await asyncio.gather(
        *(
            client.get("/hold")
            for _ in range(concurrency)
        )
    )
    for response in responses:
        response.raise_for_status()


async def measure(
    client: httpx.AsyncClient,
    *,
    label: str,
    concurrency: int,
    requests: int,
) -> dict[str, Any]:
    sem = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    server_ms: list[float] = []
    pids: dict[str, int] = {}
    errors = 0

    async def one() -> None:
        nonlocal errors
        async with sem:
            started = time.perf_counter()
            try:
                response = await client.get("/raw")
                if response.status_code != 200:
                    errors += 1
                    return
                raw_server = response.headers.get("x-wanasah-probe-server-ms")
                if raw_server:
                    server_ms.append(float(raw_server))
                pid = response.headers.get("x-wanasah-probe-pid", "?")
                pids[pid] = pids.get(pid, 0) + 1
            except httpx.HTTPError:
                errors += 1
            finally:
                latencies.append((time.perf_counter() - started) * 1000)

    await asyncio.gather(*(one() for _ in range(requests)))
    return {
        "label": label,
        "concurrency": concurrency,
        "requests": requests,
        "p50_ms": percentile(latencies, 0.50),
        "p95_ms": percentile(latencies, 0.95),
        "p99_ms": percentile(latencies, 0.99),
        "max_ms": max(latencies),
        "server_p95_ms": percentile(server_ms, 0.95),
        "errors": errors,
        "worker_hits": pids,
    }


async def run_topology(workers: int, concurrency: int, requests: int) -> None:
    process, port, log_path = start_server(workers)
    base_url = f"http://127.0.0.1:{port}"
    try:
        pids = await wait_all_workers(process, base_url, log_path, workers)
        print(
            "TRANSPORT_READY="
            + json.dumps(
                {"workers": workers, "pids": pids},
                sort_keys=True,
            )
        )

        limits = httpx.Limits(
            max_connections=concurrency,
            max_keepalive_connections=concurrency,
            keepalive_expiry=30.0,
        )
        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
            limits=limits,
            trust_env=False,
        ) as client:
            cold = await measure(
                client,
                label=f"workers_{workers}_cold",
                concurrency=concurrency,
                requests=requests,
            )
            print("TRANSPORT_PROBE=" + json.dumps(cold, sort_keys=True))

        async with httpx.AsyncClient(
            base_url=base_url,
            timeout=30.0,
            limits=limits,
            trust_env=False,
        ) as client:
            await prime_connections(client, concurrency)
            warm = await measure(
                client,
                label=f"workers_{workers}_prewarmed",
                concurrency=concurrency,
                requests=requests,
            )
            print("TRANSPORT_PROBE=" + json.dumps(warm, sort_keys=True))
    finally:
        stop_server(process)
        log_tail = read_log(log_path)
        if log_tail.strip():
            print("TRANSPORT_UVICORN_LOG_BEGIN")
            print(log_tail)
            print("TRANSPORT_UVICORN_LOG_END")
        try:
            Path(log_path).unlink(missing_ok=True)
        except OSError:
            pass


async def async_main(args: argparse.Namespace) -> None:
    for workers in args.workers:
        await run_topology(
            workers=workers,
            concurrency=args.concurrency,
            requests=args.requests,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Isolate Stage 8.2.3 loopback HTTP transport effects by comparing "
            "one vs four Uvicorn workers and cold vs prewarmed HTTP connections."
        )
    )
    parser.add_argument("--workers", type=int, nargs="+", default=[1, 4])
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--requests", type=int, default=100)
    args = parser.parse_args()
    if any(value not in {1, 2, 4} for value in args.workers):
        parser.error("--workers supports only 1, 2 or 4")
    if args.concurrency < 1 or args.concurrency > 100:
        parser.error("--concurrency must be between 1 and 100")
    if args.requests < args.concurrency:
        parser.error("--requests must be >= concurrency")
    return args


def main() -> None:
    asyncio.run(async_main(parse_args()))


if __name__ == "__main__":
    main()
