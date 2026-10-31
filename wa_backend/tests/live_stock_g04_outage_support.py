from __future__ import annotations

import hashlib
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import psycopg
from sqlalchemy.engine import make_url


STATE = Path(os.environ.get("WANASAH_OPERATIONAL_BROWSER_STATE", "/tmp/live-stock-g04-state.json"))
REVOKED = Path(os.environ.get("WANASAH_G04_REVOKED_STATE", "/tmp/live-stock-g04-revoked.json"))
API_PID = Path(os.environ.get("WANASAH_G04_API_PID", "/tmp/live-stock-g04-api.pid"))
API_LOG = Path(os.environ.get("WANASAH_G04_API_LOG", "/tmp/live-stock-g04-api.log"))
API_URL = os.environ.get("WANASAH_G04_API", "http://127.0.0.1:4174")
BACKEND_ROOT = Path(os.environ.get("R3_BACKEND_ROOT", Path(__file__).resolve().parents[1]))

FINGERPRINT_TABLES = (
    "inventory_locations",
    "inventory_balances",
    "inventory_movements",
    "inventory_cost_events",
    "inventory_cost_layers",
    "inventory_cost_states",
    "inventory_stock_policies",
    "operation_idempotency",
)


def _admin_dsn() -> str:
    return make_url(os.environ["DATABASE_URL_MIGRATION"]).set(
        drivername="postgresql"
    ).render_as_string(hide_password=False)


def _state() -> dict:
    return json.loads(STATE.read_text(encoding="utf-8"))


def _digest_rows(rows: list[str]) -> dict:
    payload = "\n".join(rows).encode("utf-8")
    return {
        "count": len(rows),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def fingerprint() -> dict:
    state = _state()
    company_id = int(state["companyId"])
    tables: dict[str, dict] = {}
    with psycopg.connect(_admin_dsn()) as db:
        for table in FINGERPRINT_TABLES:
            rows = [
                row[0]
                for row in db.execute(
                    f"SELECT to_jsonb(t)::text FROM {table} AS t "
                    "WHERE company_id=%s ORDER BY id",
                    (company_id,),
                ).fetchall()
            ]
            tables[table] = _digest_rows(rows)

        physical = [
            {
                "type": row[0],
                "on_hand": str(row[1]),
                "reserved": str(row[2]),
            }
            for row in db.execute(
                """
                SELECT l.location_type,
                       COALESCE(SUM(b.on_hand_quantity), 0),
                       COALESCE(SUM(b.reserved_quantity), 0)
                  FROM inventory_balances AS b
                  JOIN inventory_locations AS l
                    ON l.company_id=b.company_id AND l.id=b.location_id
                 WHERE b.company_id=%s
                 GROUP BY l.location_type
                 ORDER BY l.location_type
                """,
                (company_id,),
            ).fetchall()
        ]
    return {"company_id": company_id, "tables": tables, "physical": physical}


def revoke_reader_warehouse() -> dict:
    state = _state()
    company_id = int(state["companyId"])
    driver_id = int(state["readerDriver"])
    location_id = int(state["warehouse"])
    with psycopg.connect(_admin_dsn()) as db:
        roles = [
            int(row[0])
            for row in db.execute(
                """
                DELETE FROM user_location_access
                 WHERE company_id=%s AND driver_id=%s AND location_id=%s
             RETURNING role_id
                """,
                (company_id, driver_id, location_id),
            ).fetchall()
        ]
        if not roles:
            raise AssertionError("G04 expected an exact reader warehouse grant to revoke")
        db.commit()
    payload = {
        "company_id": company_id,
        "driver_id": driver_id,
        "location_id": location_id,
        "role_ids": sorted(roles),
    }
    REVOKED.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    return payload


def restore_reader_warehouse() -> dict:
    if not REVOKED.exists():
        return {"restored": 0}
    payload = json.loads(REVOKED.read_text(encoding="utf-8"))
    restored = 0
    with psycopg.connect(_admin_dsn()) as db:
        for role_id in payload["role_ids"]:
            result = db.execute(
                """
                INSERT INTO user_location_access(company_id, driver_id, location_id, role_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (company_id, driver_id, location_id, role_id) DO NOTHING
                """,
                (
                    payload["company_id"],
                    payload["driver_id"],
                    payload["location_id"],
                    int(role_id),
                ),
            )
            restored += int(result.rowcount or 0)
        db.commit()
    REVOKED.unlink(missing_ok=True)
    return {"restored": restored}


def _api_reachable() -> bool:
    try:
        with urllib.request.urlopen(API_URL + "/health", timeout=0.4) as response:
            return int(response.status) == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def stop_api() -> None:
    if not API_PID.exists():
        raise AssertionError(f"Missing FastAPI pid file: {API_PID}")
    pid = int(API_PID.read_text(encoding="utf-8").strip())
    os.kill(pid, signal.SIGTERM)
    for _ in range(60):
        if not _api_reachable():
            print(f"G04_API_STOP PASS pid={pid}")
            return
        time.sleep(0.1)
    raise AssertionError("FastAPI remained reachable after SIGTERM")


def start_api() -> None:
    if _api_reachable():
        print("G04_API_START PASS already_reachable=1")
        return
    API_LOG.parent.mkdir(parents=True, exist_ok=True)
    with API_LOG.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "main:app",
                "--host",
                "127.0.0.1",
                "--port",
                "4174",
            ],
            cwd=str(BACKEND_ROOT),
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            env=os.environ.copy(),
        )
    API_PID.write_text(str(process.pid), encoding="utf-8")
    for _ in range(100):
        if process.poll() is not None:
            raise AssertionError(
                f"FastAPI restart exited early with code {process.returncode}"
            )
        if _api_reachable():
            print(f"G04_API_START PASS pid={process.pid}")
            return
        time.sleep(0.1)
    raise AssertionError("FastAPI did not recover after restart")


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else ""
    if action == "fingerprint":
        print(json.dumps(fingerprint(), sort_keys=True))
        return
    if action == "revoke":
        print("G04_REVOKE PASS " + json.dumps(revoke_reader_warehouse(), sort_keys=True))
        return
    if action == "restore":
        print("G04_RESTORE PASS " + json.dumps(restore_reader_warehouse(), sort_keys=True))
        return
    if action == "api-stop":
        stop_api()
        return
    if action == "api-start":
        start_api()
        return
    raise SystemExit(
        "usage: live_stock_g04_outage_support.py "
        "fingerprint|revoke|restore|api-stop|api-start"
    )


if __name__ == "__main__":
    main()
