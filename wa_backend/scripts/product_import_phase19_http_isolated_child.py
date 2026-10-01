"""Small real-network FastAPI + live worker + PostgreSQL synthetic import gate.

The parent runner owns the disposable cluster and checks the source is empty.
This child refuses every other DB target. No user tokens/files are read or logged.
"""
from __future__ import annotations

import base64
import csv
import io
import os
from pathlib import Path
import subprocess
import sys
import time
from uuid import uuid4

import httpx
import psycopg
from sqlalchemy.engine import make_url

if os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("Refusing Product Import HTTP test outside guarded disposable runner.")
url = make_url(os.environ.get("DATABASE_URL", ""))
if (
    url.database != "p19_http_synthetic"
    or url.host != "127.0.0.1"
    or int(url.port or 0) != 55446
):
    raise RuntimeError("Refusing Product Import HTTP test outside port-55446 synthetic database.")

from api.auth import create_access_token
from scripts.product_import_business_integrity_gate import _assert_business_evidence
from scripts.run_product_import_phase19_live_load import build_source

ROOT = Path(__file__).resolve().parents[1]
API_PORT = int(os.environ["WANASAH_P19_HTTP_API_PORT"])
BASE = f"http://127.0.0.1:{API_PORT}"
LOG_DIR = Path(os.environ["WANASAH_P19_HTTP_LOG_DIR"])
TERMINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "VALIDATION_FAILED", "CANCELLED", "NEEDS_MAPPING"}


def start(label: str, *args: str):
    # Separate logs avoid accidental disclosure of synthetic JWTs/HTTP payload.
    handle = (LOG_DIR / f"{label}.log").open("w", encoding="utf-8")
    try:
        process = subprocess.Popen(
            [sys.executable, *args], cwd=ROOT, env=os.environ.copy(),
            stdout=handle, stderr=subprocess.STDOUT,
        )
    except BaseException:
        handle.close()
        raise
    return process, handle


def stop(process, handle) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=12)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    handle.close()


def require(response: httpx.Response, status: int, label: str) -> dict:
    if response.status_code != status:
        code = "UNKNOWN"
        try:
            body = response.json()
            if isinstance(body, dict):
                error = body.get("error") or body.get("detail") or {}
                if isinstance(error, dict):
                    code = str(error.get("code", "UNKNOWN"))[:90]
        except (ValueError, TypeError):
            pass
        raise RuntimeError(f"{label}: HTTP {response.status_code} expected {status}, code={code}")
    return response.json()


def wait_health(client: httpx.Client, processes, seconds=70) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        for proc, _ in processes:
            if proc.poll() is not None:
                raise RuntimeError(f"An isolated API/worker exited before readiness (exit={proc.returncode}).")
        try:
            if client.get("/health").status_code == 200:
                return
        except httpx.RequestError:
            pass
        time.sleep(.5)
    raise RuntimeError("Isolated API did not start on loopback.")


def wait_worker(client: httpx.Client, seconds=100) -> None:
    end = time.monotonic() + seconds
    latest = ""
    while time.monotonic() < end:
        r = client.get("/simple-products/import-worker/readiness")
        if r.status_code == 200:
            latest = str(r.json().get("status", ""))
            if r.json().get("ready") is True:
                print("P19_REAL_HTTP_EXECUTION_READINESS=PASS", flush=True)
                return
        else:
            latest = "HTTP_" + str(r.status_code)
        time.sleep(1)
    raise RuntimeError(f"Isolated execution worker not READY ({latest}).")


def wait_job(client: httpx.Client, job_id: str, *, valid_states: set[str], seconds=145) -> dict:
    deadline = time.monotonic() + seconds
    last = "UNKNOWN"
    while time.monotonic() < deadline:
        row = require(client.get(f"/simple-products/imports/{job_id}"), 200, "job status")
        last = str(row.get("status", "UNKNOWN"))
        if last in valid_states:
            return row
        if last in TERMINAL:
            raise RuntimeError(f"Import unexpectedly terminal in {last}, wanted {sorted(valid_states)}.")
        time.sleep(.5)
    raise RuntimeError(f"Isolated import did not reach {sorted(valid_states)}; last={last}.")


def upload(client: httpx.Client, *, label: str):
    payload, mapping, _ = build_source(100, label)
    request_id = str(uuid4())
    response = require(client.post(
        "/simple-products/imports",
        data={
            "request_id": request_id,
            "default_lot_control_mode": "NONE",
            "default_expiry_control_mode": "NONE",
        },
        files={"file": (f"{label}.csv", payload, "text/csv")},
    ), 202, "create new synthetic import")
    job_id = response.get("job_id")
    if not isinstance(job_id, str):
        raise RuntimeError("Missing new import job identity.")
    first = wait_job(client, job_id, valid_states={"COMPLETED_WITH_ERRORS"})
    if int(first.get("imported_rows", -1)) != 99:
        raise RuntimeError(f"Expected 99 imported rows, got {first.get('imported_rows')}.")
    if int(first.get("invalid_rows", -1)) != 1:
        raise RuntimeError(f"Expected one rejected row, got {first.get('invalid_rows')}.")
    return job_id, mapping


def original_imported(admin, job_id: str):
    rows = admin.execute(
        "SELECT row_identity, product_variant_id, version FROM product_import_rows "
        "WHERE company_id=2 AND job_id=%s AND status='IMPORTED' ORDER BY row_number",
        (job_id,),
    ).fetchall()
    if len(rows) != 99:
        raise RuntimeError(f"Expected 99 persisted ProductVariant row links; got {len(rows)}.")
    return [tuple(item) for item in rows]


def assert_unmodified(admin, job_id: str, before) -> None:
    after = original_imported(admin, job_id) if len(before) == 99 else []
    if before != after:
        raise RuntimeError("Correction changed previously imported row identities/versions.")


def verify_job(admin, job_id: str, expected: int):
    evidence = _assert_business_evidence(admin, job_id, expected)
    if evidence["invalid"] or evidence["import_failed"]:
        raise RuntimeError("Correction did not resolve the rejected source row.")
    return evidence


def test_inline(client: httpx.Client, wrong: httpx.Client, admin) -> None:
    job_id, _ = upload(client, label="P19REALINLINE" + uuid4().hex[:8])
    before = original_imported(admin, job_id)
    rows = require(client.get(
        f"/simple-products/imports/{job_id}/correction/rows?after_row=0&limit=25",
    ), 200, "inline rejected-row read")
    if len(rows.get("items", [])) != 1:
        raise RuntimeError("Expected one real rejected-row projection.")
    item = rows["items"][0]
    if int(item.get("row_number", 0)) != 101 or not item.get("editable"):
        raise RuntimeError("Invalid physical row number/edit permission.")

    require(wrong.get(f"/simple-products/imports/{job_id}"), 404, "cross-tenant GET")
    require(wrong.get(f"/simple-products/imports/{job_id}/correction/rows"), 404, "cross-tenant rejected-row GET")
    require(wrong.post(
        f"/simple-products/imports/{job_id}/correction/rows",
        json={
            "request_id": str(uuid4()), "expected_job_version": rows["job_version"],
            "rows": [{
                "row_identity": item["row_identity"], "expected_version": item["version"],
                "values": {"name": "FOREIGN TENANT CANNOT EDIT"},
            }],
        },
    ), 404, "cross-tenant correction POST")
    print("P19_REAL_HTTP_WRONG_TENANT=PASS", flush=True)

    original = {
        "request_id": str(uuid4()),
        "expected_job_version": rows["job_version"],
        "rows": [{
            "row_identity": item["row_identity"], "expected_version": item["version"],
            "values": {"name": "Synthetic corrected item"},
        }],
    }
    target = f"/simple-products/imports/{job_id}/correction/rows"
    first = require(client.post(target, json=original), 202, "inline correction POST")
    if first.get("replayed") or int(first.get("corrected_rows", -1)) != 1:
        raise RuntimeError("First inline correction ACK invalid.")
    replay = require(client.post(target, json=original), 202, "exact correction replay")
    if not replay.get("replayed") or replay.get("job_id") != job_id:
        raise RuntimeError("Exact HTTP correction replay was not idempotent.")
    wait_job(client, job_id, valid_states={"COMPLETED"})
    final = verify_job(admin, job_id, 100)
    assert_unmodified(admin, job_id, before)
    print("P19_REAL_HTTP_INLINE_CORRECTION_REPLAY=PASS", flush=True)
    print("P19_REAL_HTTP_INLINE_LINEAGE=" + str(final), flush=True)

    # A fresh save cannot mutate successful historical rows.
    stale = dict(original, request_id=str(uuid4()))
    require(client.post(target, json=stale), 409, "stale/completed correction")
    print("P19_REAL_HTTP_STALE_SUCCESS_GUARD=PASS", flush=True)


def test_csv(client: httpx.Client, wrong: httpx.Client, admin) -> None:
    job_id, mapping = upload(client, label="P19REALFILE" + uuid4().hex[:8])
    before = original_imported(admin, job_id)
    artifact = require(
        client.get(f"/simple-products/imports/{job_id}/correction?format=csv"),
        200, "official file correction GET",
    )
    if int(artifact.get("row_count", -1)) != 1:
        raise RuntimeError("Official correction export must contain only one failed row.")
    encoded = artifact.get("content_base64")
    if not isinstance(encoded, str):
        raise RuntimeError("Missing correction file response.")
    original_bytes = base64.b64decode(encoded, validate=True)
    original_bom = original_bytes.startswith(b"\xef\xbb\xbf")
    original_text = original_bytes.decode("utf-8-sig" if original_bom else "utf-8")
    reader = csv.reader(io.StringIO(original_text, newline=""))
    table = list(reader)
    if len(table) != 2 or mapping["name"] not in table[0]:
        raise RuntimeError("Official correction CSV source columns/failed-row count invalid.")
    table[1][table[0].index(mapping["name"])] = "Synthetic CSV correction"
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerows(table)
    updated_bytes = buffer.getvalue().encode("utf-8-sig" if original_bom else "utf-8")

    require(wrong.get(f"/simple-products/imports/{job_id}/correction?format=csv"),
            404, "cross-tenant correction file GET")
    target = f"/simple-products/imports/{job_id}/correction"
    request_id = str(uuid4())
    form = {"request_id": request_id}
    file = {"file": ("p19-correction.csv", updated_bytes, "text/csv")}
    first = require(client.post(target, data=form, files=file), 202, "official CSV POST")
    if first.get("replayed") or int(first.get("corrected_rows", -1)) != 1:
        raise RuntimeError("First correction file ACK invalid.")
    replay = require(client.post(target, data=form, files=file), 202, "official CSV exact replay")
    if not replay.get("replayed"):
        raise RuntimeError("Correction file exact replay was not idempotent.")
    wait_job(client, job_id, valid_states={"COMPLETED"})
    final = verify_job(admin, job_id, 100)
    assert_unmodified(admin, job_id, before)
    print("P19_REAL_HTTP_FILE_CORRECTION_REPLAY=PASS", flush=True)
    print("P19_REAL_HTTP_FILE_LINEAGE=" + str(final), flush=True)


def main() -> None:
    admin_url = make_url(os.environ["DATABASE_URL_MIGRATION"])
    admin = psycopg.connect(
        admin_url.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    processes = []
    try:
        tenant_counts = [
            admin.execute("SELECT count(*) FROM companies WHERE id=%s", (identity,)).fetchone()[0]
            for identity in (2, 3)
        ]
        if tenant_counts != [1, 1]:
            raise RuntimeError("Synthetic cross-company seed not established.")
        # No token is emitted; FastAPI's real authentication/permissions/RLS
        # evaluate signed expiring bearer tokens against persisted test drivers.
        primary_token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")
        foreign_token = create_access_token({"sub": "2", "is_admin": True}, 3, "Admin")

        processes.append(start("p19-http-server", "-m", "uvicorn", "main:app", "--host",
                               "127.0.0.1", "--port", str(API_PORT), "--no-access-log"))
        for role in ("control", "maintenance", "execution"):
            processes.append(start(f"p19-{role}", "-m",
                                   "domains.simple_products.imports.infrastructure.worker_cli",
                                   "--role", role))
        with (
            httpx.Client(base_url=BASE, timeout=40.0,
                         headers={"Authorization": f"Bearer {primary_token}"}) as client,
            httpx.Client(base_url=BASE, timeout=40.0,
                         headers={"Authorization": f"Bearer {foreign_token}"}) as wrong,
        ):
            wait_health(client, processes)
            require(wrong.get("/simple-products/import-worker/readiness"), 200,
                    "synthetic second tenant authenticated access")
            wait_worker(client)
            test_inline(client, wrong, admin)
            test_csv(client, wrong, admin)
        print("PRODUCT_IMPORT_PHASE19_REAL_HTTP_ISOLATED=PASS", flush=True)
    finally:
        for proc, handle in reversed(processes):
            stop(proc, handle)
        admin.close()


if __name__ == "__main__":
    main()
