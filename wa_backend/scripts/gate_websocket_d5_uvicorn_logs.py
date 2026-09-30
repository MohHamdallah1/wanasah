"""D5 real-Uvicorn access-log canary test (read-only; no credentials emitted)."""
from __future__ import annotations

import os
import pathlib
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

from websockets.sync.client import connect
from websockets.exceptions import InvalidStatus, ConnectionClosed

ROOT = pathlib.Path(__file__).resolve().parents[1]
CANARIES = (
    "D5_NEVER_LOG_LEGACY_DISPATCH_SECRET",
    "D5_NEVER_LOG_LEGACY_IMPORT_SECRET",
    "D5_NEVER_LOG_FIRSTFRAME_SECRET",
)


def _unused_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    port = _unused_port()
    with tempfile.TemporaryDirectory(prefix="wanasah_d5_logs_") as directory:
        log = pathlib.Path(directory) / "uvicorn.log"
        with log.open("w", encoding="utf-8") as handle:
            proc = subprocess.Popen(
                [
                    sys.executable, "-m", "uvicorn", "main:app",
                    "--host", "127.0.0.1", "--port", str(port),
                    "--access-log", "--log-level", "info",
                    # This gate exercises protocol logging, not DB/worker
                    # startup (Psycopg async needs Selector loop on Windows).
                    "--lifespan", "off",
                    "--ws", "websockets",
                    "--ws-max-size", "8192",
                ],
                cwd=ROOT,
                env=os.environ.copy(),
                stdout=handle,
                stderr=subprocess.STDOUT,
            )
            try:
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    if proc.poll() is not None:
                        raise RuntimeError("D5 Uvicorn exited during startup")
                    try:
                        with urlopen(
                            f"http://127.0.0.1:{port}/health", timeout=1
                        ) as result:
                            if result.status == 200:
                                break
                    except Exception:
                        time.sleep(0.2)
                else:
                    raise RuntimeError("D5 Uvicorn health readiness timed out")

                origin = "https://dashboard.wanasah.com"
                paths = (
                    "/ws/dispatch?" + "token=" + CANARIES[0],
                    "/simple-products/imports/"
                    + "00000000-0000-4000-8000-000000000001/ws?token="
                    + CANARIES[1],
                )
                for path in paths:
                    try:
                        with connect(
                            f"ws://127.0.0.1:{port}{path}",
                            origin=origin,
                            proxy=None,
                            open_timeout=4,
                        ):
                            raise AssertionError(
                                "Legacy credential-bearing WebSocket URL accepted"
                            )
                    except InvalidStatus as exc:
                        if exc.response.status_code != 403:
                            raise AssertionError(
                                f"Unexpected rejected WS status: {exc.response.status_code}"
                            ) from exc

                with connect(
                    f"ws://127.0.0.1:{port}/ws/dispatch",
                    origin=origin,
                    proxy=None,
                    open_timeout=4,
                ) as ws:
                    ws.send(
                        '{"type":"auth","token":"'
                        + CANARIES[2]
                        + '"}'
                    )
                    try:
                        ws.recv(timeout=4)
                        raise AssertionError("Invalid first frame was authorized")
                    except ConnectionClosed as exc:
                        if exc.rcvd is None or exc.rcvd.code != 1008:
                            raise AssertionError("Invalid frame must close 1008") from exc

                time.sleep(0.3)
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)

        logs = log.read_text(encoding="utf-8", errors="replace")
        leaked = [secret for secret in CANARIES if secret in logs]
        if leaked:
            raise AssertionError("A D5 access-token canary appeared in Uvicorn logs")
        if 'WebSocket /ws/dispatch" 403' not in logs:
            raise AssertionError("Redacted dispatch rejection not observed in Uvicorn access log")
        if '/simple-products/imports/' not in logs:
            raise AssertionError("Redacted Product Import rejection not observed")
        print("LEGACY_DISPATCH_QUERY_REJECTED_NO_LEAK=PASS")
        print("LEGACY_IMPORT_QUERY_REJECTED_NO_LEAK=PASS")
        print("FIRST_FRAME_INVALID_BEARER_NO_LEAK=PASS")
        print("UVICORN_D5_ACCESS_LOG_GATE=PASS")


if __name__ == "__main__":
    main()
