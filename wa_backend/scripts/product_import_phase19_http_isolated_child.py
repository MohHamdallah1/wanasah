"""Small real-network FastAPI + live worker + PostgreSQL synthetic import gate.

The parent runner owns the disposable cluster and checks the source is empty.
This child refuses every other DB target. No user tokens/files are read or logged.
"""
from __future__ import annotations

import asyncio
import base64
import csv
import io
import json
import socket
from openpyxl import load_workbook
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
    process.p19_label = label
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
                raise RuntimeError(f"Isolated {proc.p19_label} exited before readiness (exit={proc.returncode}).")
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
    # All three snapshots exclude the intentionally rejected physical row 101.
    # Compare precise Product/Variant/Row versions and ALL original price
    # publication identities and active barcode identities before and after.
    rows = admin.execute(
        "SELECT r.row_identity,r.product_variant_id,r.version,"
        "v.version,p.id,p.version FROM product_import_rows r "
        "JOIN product_variants v ON v.id=r.product_variant_id AND v.company_id=r.company_id "
        "JOIN products p ON p.id=v.product_id AND p.company_id=v.company_id "
        "WHERE r.company_id=2 AND r.job_id=%s AND r.status='IMPORTED' "
        "AND r.row_number < 101 ORDER BY r.row_number",
        (job_id,),
    ).fetchall()
    if len(rows) != 99:
        raise RuntimeError(f"Expected 99 persisted original ProductVariant row links; got {len(rows)}.")
    ids = [int(row[1]) for row in rows]
    prices = admin.execute(
        "SELECT id,product_variant_id,publication_id,version FROM price_book_entries "
        "WHERE company_id=2 AND product_variant_id=ANY(%s) ORDER BY id",
        (ids,),
    ).fetchall()
    barcodes = admin.execute(
        "SELECT id,product_variant_id,barcode,version FROM product_barcodes "
        "WHERE company_id=2 AND is_active=true AND product_variant_id=ANY(%s) ORDER BY id",
        (ids,),
    ).fetchall()
    if len(prices) < 99 or len(barcodes) < 99:
        raise RuntimeError("Missing original price/publication or active barcode identities.")
    return (list(map(tuple, rows)), list(map(tuple, prices)), list(map(tuple, barcodes)))


def assert_unmodified(admin, job_id: str, before) -> None:
    if before != original_imported(admin, job_id):
        raise RuntimeError(
            "Correction mutated an earlier successful row, Product/Variant version, "
            "price publication or active barcode identity."
        )


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
                "values": {"package_uom": "CARTON"},
            }],
        },
    ), 404, "cross-tenant correction POST")
    print("P19_REAL_HTTP_WRONG_TENANT=PASS", flush=True)

    denied_payload = {
        "request_id": str(uuid4()), "expected_job_version": rows["job_version"],
        "rows": [{"row_identity": str(uuid4()), "expected_version": item["version"],
                  "values": {"name": "This row does not exist"}}],
    }
    require(client.post(
        f"/simple-products/imports/{job_id}/correction/rows", json=denied_payload,
    ), 409, "forged unknown row identity")
    denied_payload["request_id"] = str(uuid4())
    denied_payload["rows"][0]["row_identity"] = str(before[0][0][0])
    denied_payload["rows"][0]["expected_version"] = int(before[0][0][2])
    require(client.post(
        f"/simple-products/imports/{job_id}/correction/rows", json=denied_payload,
    ), 409, "previously imported row cannot be edited")
    print("P19_REAL_HTTP_FORGED_IMPORTED_NEGATIVES=PASS", flush=True)

    original = {
        "request_id": str(uuid4()),
        "expected_job_version": rows["job_version"],
        "rows": [{
            "row_identity": item["row_identity"], "expected_version": item["version"],
            "values": {"package_uom": "CARTON"},
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
    return job_id



def test_real_auth_revocation_and_audit(
    client: httpx.Client,
    wrong: httpx.Client,
    admin: psycopg.Connection,
    token: str,
    job_id: str,
) -> None:
    """Actual auth dependency, persisted blacklist, RLS and audit envelope.

    Restricted to disposable tenant-2; never mutates original source DB.
    No bearer text or row cells are printed in diagnostic output.
    """
    from uuid import UUID

    # A real idempotent 100-row correction must retain an accountable actor,
    # request identity, scoped Variant linkage, before/after snapshots and
    # outbox event references, not merely 100 table rows.
    audit_rows = admin.execute(
        """
        SELECT e.company_id,e.event_type,e.entity_type,e.entity_id,
               e.actor_user_id,e.actor_context,e.reason_code,e.request_id,
               e.before_snapshot,e.after_snapshot,e.schema_version,
               o.company_id,o.event_type,o.payload
        FROM product_import_rows r
        JOIN domain_audit_events e
          ON e.company_id=r.company_id
         AND e.entity_type='ProductVariant'
         AND e.entity_id=r.product_variant_id::text
        JOIN transactional_outbox o
          ON o.company_id=e.company_id
         AND o.aggregate_type=e.entity_type
         AND o.aggregate_id=e.entity_id
        WHERE r.company_id=2 AND r.job_id=%s AND r.status='IMPORTED'
        ORDER BY r.row_number
        """,
        (job_id,),
    ).fetchall()
    if len(audit_rows) != 100:
        raise RuntimeError("Expected exactly one persisted audit/outbox per corrected Variant.")
    for row in audit_rows:
        (company, event, entity_type, entity_id, actor, context, reason, request_id,
         before, after, schema_version, outbox_company, outbox_event, payload) = row
        if company != 2 or outbox_company != 2 or entity_type != "ProductVariant":
            raise RuntimeError("Audit/outbox company or aggregate ownership violated.")
        if actor != 1 or not isinstance(context, dict):
            raise RuntimeError("Audit actor identity/context missing or foreign.")
        if not event or not reason or not isinstance(request_id, UUID) or schema_version != 1:
            raise RuntimeError("Audit event code/version/request identity invalid.")
        if after is not None and not isinstance(after, dict):
            raise RuntimeError("Audit after-snapshot malformed.")
        if before is not None and not isinstance(before, dict):
            raise RuntimeError("Audit before-snapshot malformed.")
        if event != outbox_event or not isinstance(payload, dict):
            raise RuntimeError("Audit/outbox event types diverged.")
        if str(payload.get("entity_id")) != entity_id or str(payload.get("company_id")) != "2":
            raise RuntimeError("Outbox payload refers to another tenant/Variant.")
        if str(payload.get("request_id")) != str(request_id):
            raise RuntimeError("Outbox command request differs from audit request.")
    print("P19_REAL_HTTP_AUDIT_CONTENT_AND_FK_SCOPING=PASS", flush=True)

    # Browser token signatures/claims alone must not bypass live is_active
    # or persisted blacklist. This uses the already-authenticated client
    # against the same Uvicorn instance, not in-process auth mocks.
    ready = "/simple-products/import-worker/readiness"
    require(client.get(ready), 200, "authorized original tenant baseline")
    admin.execute("UPDATE drivers SET is_active=false WHERE company_id=2 AND id=1")
    try:
        require(client.get(ready), 403, "revoked account must lose import permission immediately")
        require(wrong.get(ready), 200, "unrelated company's access must survive revocation")
    finally:
        admin.execute("UPDATE drivers SET is_active=true WHERE company_id=2 AND id=1")
    require(client.get(ready), 200, "restored test actor is authorized")
    print("P19_REAL_HTTP_PERSISTED_ACCOUNT_REVOCATION=PASS", flush=True)

    admin.execute("INSERT INTO token_blacklist(token,blacklisted_at) VALUES (%s,now())", (token,))
    require(client.get(ready), 401, "blacklisted signed JWT must be rejected")
    require(wrong.get(ready), 200, "other tenant JWT must remain valid")
    print("P19_REAL_HTTP_BLACKLISTED_ACCESS_TOKEN=PASS", flush=True)

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
    if len(table) != 2 or mapping["package_uom"] not in table[0]:
        raise RuntimeError("Official correction CSV source columns/failed-row count invalid.")
    table[1][table[0].index(mapping["package_uom"])] = "CARTON"
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


def test_xlsx(client: httpx.Client, wrong: httpx.Client, admin) -> None:
    # Real official Excel path, not a CSV test renamed .xlsx. Preserve
    # __wanasah_row_identity and all source columns in the roundtrip.
    job_id, mapping = upload(client, label="P19REALXLSX" + uuid4().hex[:8])
    before = original_imported(admin, job_id)
    artifact = require(
        client.get(f"/simple-products/imports/{job_id}/correction?format=xlsx"),
        200, "official XLSX correction GET",
    )
    require(
        wrong.get(f"/simple-products/imports/{job_id}/correction?format=xlsx"),
        404, "foreign-company XLSX GET",
    )
    if artifact.get("row_count") != 1:
        raise RuntimeError("Official XLSX must contain exactly one rejected physical row.")
    binary = base64.b64decode(artifact["content_base64"], validate=True)
    book = load_workbook(io.BytesIO(binary), read_only=False, data_only=False)
    try:
        if book.sheetnames != ["Corrections"]:
            raise RuntimeError("Unexpected correction XLSX sheets.")
        sheet = book["Corrections"]
        table = list(sheet.values)
        if len(table) != 2 or mapping["package_uom"] not in table[0]:
            raise RuntimeError("Missing package selector in real official XLSX.")
        if "__wanasah_row_identity" not in table[0]:
            raise RuntimeError("Missing immutable identity in official XLSX.")
        identity = str(table[1][table[0].index("__wanasah_row_identity")])
        if not identity:
            raise RuntimeError("No immutable identity in rejected Excel row.")
        sheet.cell(row=2, column=table[0].index(mapping["package_uom"]) + 1).value = "CARTON"
        out = io.BytesIO()
        book.save(out)
    finally:
        book.close()
    target = f"/simple-products/imports/{job_id}/correction"
    request_id = str(uuid4())
    payload = out.getvalue()
    form = {"request_id": request_id}
    file = {"file": ("p19-correction.xlsx", payload,
                     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    first = require(client.post(target, data=form, files=file), 202,
                    "official XLSX correction POST")
    replay = require(client.post(target, data=form, files=file), 202,
                     "official XLSX exact replay")
    if first.get("replayed") or not replay.get("replayed"):
        raise RuntimeError("XLSX correction replay contract invalid.")
    wait_job(client, job_id, valid_states={"COMPLETED"})
    final = verify_job(admin, job_id, 100)
    assert_unmodified(admin, job_id, before)
    print("P19_REAL_HTTP_XLSX_CORRECTION_REPLAY=PASS", flush=True)
    print("P19_REAL_HTTP_XLSX_LINEAGE=" + str(final), flush=True)


def test_next_error(client: httpx.Client, admin) -> None:
    # Construct one literal row with TWO faults. The first validation pass
    # reports the missing name, then the second exposes the bad package UOM.
    original, mapping, _ = build_source(100, "P19TWOERRORS" + uuid4().hex[:8])
    parsed = list(csv.reader(io.StringIO(original.decode("utf-8-sig"), newline="")))
    if len(parsed) != 101:
        raise RuntimeError("Expected generator to produce 100 physical rows.")
    candidate = list(parsed[-1])
    candidate[parsed[0].index(mapping["name"])] = ""
    output = io.StringIO(newline="")
    csv.writer(output).writerows([parsed[0], candidate])
    payload = output.getvalue().encode("utf-8-sig")
    ack = require(client.post(
        "/simple-products/imports",
        data={"request_id": str(uuid4()), "default_lot_control_mode": "NONE",
              "default_expiry_control_mode": "NONE"},
        files={"file": ("p19-two-errors.csv", payload, "text/csv")},
    ), 202, "two-error fresh import")
    job_id = str(ack["job_id"])
    wait_job(client, job_id, valid_states={"VALIDATION_FAILED"})
    target = f"/simple-products/imports/{job_id}/correction/rows"
    first = require(client.get(target), 200, "first rejection")
    row = first["items"][0]
    first_code = row["errors"][0]["code"]
    if first_code != "IMPORT_NAME_REQUIRED":
        raise RuntimeError(f"Unexpected first validation error code={first_code}")

    first_correction = {
        "request_id": str(uuid4()),
        "expected_job_version": first["job_version"],
        "rows": [{
            "row_identity": row["row_identity"], "expected_version": row["version"],
            "values": {"name": "Fixed name, bad package remains"},
        }],
    }
    # Deliberately abandon the real network response after transmitting the
    # complete JSON request. The client must reconcile the ambiguous outcome
    # using the same exact request_id + payload, never a fresh mutation id.
    body = json.dumps(first_correction, separators=(",", ":")).encode("utf-8")
    wire = (
        f"POST {target} HTTP/1.1\r\nHost: 127.0.0.1:{API_PORT}\r\n"
        f"Authorization: {client.headers['Authorization']}\r\n"
        f"Content-Type: application/json\r\nContent-Length: {len(body)}\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii") + body
    with socket.create_connection(("127.0.0.1", API_PORT), timeout=5) as connection:
        connection.sendall(wire)
        connection.shutdown(socket.SHUT_WR)
        # Never read the ACK; abandoning response is the fault under test.
    time.sleep(.1)
    require(client.post(target, json=first_correction), 202,
            "same exact request after abandoned HTTP response")
    replay = require(client.post(target, json=first_correction), 202,
                     "stable id replay after network disconnect")
    if not replay.get("replayed"):
        raise RuntimeError("HTTP disconnect recovery did not stabilize request identity.")
    print("P19_REAL_HTTP_DROPPED_RESPONSE_REPLAY=PASS", flush=True)
    wait_job(client, job_id, valid_states={"VALIDATION_FAILED"})
    second = require(client.get(target), 200, "newly exposed rejection")
    row2 = second["items"][0]
    new_code = row2["errors"][0]["code"]
    if new_code == first_code or row2["row_identity"] != row["row_identity"]:
        raise RuntimeError("Next validation error did not emerge on original row identity.")
    require(client.post(target, json={
        "request_id": str(uuid4()),
        "expected_job_version": second["job_version"],
        "rows": [{
            "row_identity": row2["row_identity"], "expected_version": row2["version"],
            "values": {"package_uom": "CARTON"},
        }],
    }), 202, "second correction")
    wait_job(client, job_id, valid_states={"COMPLETED"})
    proof = verify_job(admin, job_id, 1)
    print(f"P19_REAL_HTTP_SEQUENTIAL_VALIDATION=PASS first={first_code} then={new_code}", flush=True)
    print("P19_REAL_HTTP_SEQUENTIAL_LINEAGE=" + str(proof), flush=True)


async def test_real_staging_io_lock_release(admin) -> None:
    # Real asyncpg PostgreSQL transaction holds a transaction advisory lock
    # during an actual server-side wait. A *short test-only* guard deadline
    # exercises the exact production guard, not a mocked connection.
    from unittest.mock import patch
    from sqlalchemy import text
    from database import engine
    from domains.simple_products.imports.infrastructure import staging_io
    from domains.simple_products.imports.infrastructure.repository import (
        close_tenant_session, open_tenant_session,
    )
    from domains.simple_products.imports.domain.errors import (
        ProductImportStagingTimeoutError, classify_import_error,
    )
    guard = staging_io.StagingIOGuard(company_id=2, job_id=uuid4())
    locked_key = 209301033
    token, db = await open_tenant_session(2, io_guard=guard)
    backend_pid = -1
    try:
        backend_pid = int(await guard.run(
            db.scalar(text("SELECT pg_backend_pid()")), operation="identify_staging_pid",
        ))
        await guard.run(
            db.execute(text("SELECT pg_advisory_xact_lock(:k)").bindparams(k=locked_key)),
            operation="create_test_transaction_lock",
        )
        with patch.object(staging_io, "STAGING_IO_TIMEOUT_SECONDS", 0.2):
            try:
                await guard.run(
                    db.execute(text("SELECT pg_sleep(5)")),
                    operation="staging_batch",
                )
            except ProductImportStagingTimeoutError as cause:
                classified = classify_import_error(cause)
                if not classified.retryable or classified.code != "PRODUCT_IMPORT_STAGING_TIMEOUT":
                    raise RuntimeError("Timed-out staging was not retryable job-level error.") from cause
            else:
                raise RuntimeError("Real SQL sleep bypassed guarded staging timeout.")
        try:
            await guard.run(db.rollback(), operation="rollback_staging", cleanup=True)
        except Exception:
            # Severed asyncpg transport already owns transaction cleanup.
            pass
    finally:
        await close_tenant_session(token, db, io_guard=guard)
        await engine.dispose()

    deadline = time.monotonic() + 6.0
    while time.monotonic() < deadline:
        active_pid = admin.execute(
            "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() AND pid=%s",
            (backend_pid,),
        ).fetchone()[0]
        free_lock = admin.execute(
            "SELECT pg_try_advisory_xact_lock(%s)", (locked_key,),
        ).fetchone()[0]
        if int(active_pid) == 0 and bool(free_lock):
            print("P19_REAL_PG_STAGING_TIMEOUT_LOCK_RELEASE=PASS", flush=True)
            return
        time.sleep(0.05)
    raise RuntimeError("Real timed-out staging transport did not release PostgreSQL backend and transaction lock.")


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
        # This actor exists ONLY in the throwaway DB and has no Role grants.
        # A forged is_admin claim cannot override the persisted permission gate.
        admin.execute(
            "INSERT INTO drivers("
            "id,company_id,username,password_hash,full_name,phone_number,"
            "is_active,is_admin,can_allow_debt,max_debt_limit,created_at"
            ") SELECT 3,2,username||'-p19-unprivileged',password_hash,"
            "full_name||' unprivileged',NULL,true,false,false,"
            "max_debt_limit,created_at FROM drivers WHERE company_id=2 AND id=1"
        )
        restricted_token = create_access_token(
            {"sub": "3", "is_admin": True}, 2, "Admin",
        )

        asyncio.run(test_real_staging_io_lock_release(admin), loop_factory=asyncio.SelectorEventLoop)

        processes.append(start("p19-http-server", "-m",
                               "scripts.product_import_phase19_http_selector_server"))
        for role in ("control", "maintenance", "execution"):
            processes.append(start(f"p19-{role}", "-m",
                                   "domains.simple_products.imports.infrastructure.worker_cli",
                                   "--role", role))
        with (
            httpx.Client(base_url=BASE, timeout=40.0,
                         headers={"Authorization": f"Bearer {primary_token}"}) as client,
            httpx.Client(base_url=BASE, timeout=40.0,
                         headers={"Authorization": f"Bearer {foreign_token}"}) as wrong,
            httpx.Client(base_url=BASE, timeout=40.0,
                         headers={"Authorization": f"Bearer {restricted_token}"}) as restricted,
        ):
            wait_health(client, processes)
            require(restricted.get("/simple-products/import-worker/readiness"),
                    403, "unprivileged synthetic actor must be denied")
            print("P19_REAL_HTTP_ROLE_PERMISSION_DENIAL=PASS", flush=True)
            require(wrong.get("/simple-products/import-worker/readiness"), 200,
                    "synthetic second tenant authenticated access")
            wait_worker(client)
            inline_job_id = test_inline(client, wrong, admin)
            test_csv(client, wrong, admin)
            test_xlsx(client, wrong, admin)
            test_next_error(client, admin)
            test_real_auth_revocation_and_audit(
                client, wrong, admin, primary_token, inline_job_id,
            )
        print("PRODUCT_IMPORT_PHASE19_REAL_HTTP_ISOLATED=PASS", flush=True)
    except BaseException:
        # Sanitized component-level evidence only: never echo traceback, JWT,
        # DSN, startup SQL or error-message parameters from a role log.
        for proc, _ in processes:
            if proc.poll() is not None:
                lines = (LOG_DIR / f"{proc.p19_label}.log").read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
                kinds = [line.split(":", 1)[0].strip() for line in lines
                         if line.startswith(("RuntimeError:", "ValueError:",
                                             "TypeError:", "ModuleNotFoundError:",
                                             "ImportError:", "OSError:",
                                             "SystemExit:", "PermissionError:"))]
                print(f"P19_COMPONENT_EXIT={proc.p19_label}:{proc.returncode} exception_kind={kinds[-1] if kinds else 'UNCLASSIFIED'}", flush=True)
                # Only the known application startup error category, never raw
                # SQL/request exception text or an authentication bearer.
                import re
                error_categories = []
                for line in lines[-100:]:
                    stripped = line.strip()
                    if stripped.startswith("ERROR:"):
                        error_categories.append(re.sub(r"(postgresql(?:\\+asyncpg)?://)[^\\s]+", r"\\1[REDACTED]", stripped)[:180])
                    elif re.match(r"^(?:[A-Za-z_]+\\.)*[A-Za-z_]+(?:Error|Exception):", stripped):
                        error_categories.append(stripped.split(":", 1)[0][:90])
                print(f"P19_COMPONENT_ERROR_CLASSES={proc.p19_label}:{error_categories[-8:]}", flush=True)
                if proc.p19_label == "p19-http-server":
                    # Synthetic-only diagnostics. Remove all URL/DSN/token-like
                    # spans and print just the traceback exception structure.
                    for entry in lines[-55:]:
                        stripped = entry.strip()
                        if ("Error" not in stripped and "Exception" not in stripped
                                and "Failed" not in stripped and "Permission" not in stripped
                                and "connection" not in stripped.lower()):
                            continue
                        safe = re.sub(r"(?:postgresql(?:\\+asyncpg)?|redis)://[^\\s)]+",
                                      "[REDACTED_DSN]", stripped)
                        safe = re.sub(r"Bearer\\s+[A-Za-z0-9._-]+", "Bearer [REDACTED]", safe)
                        print("P19_UVICORN_ERROR_CLASS_LINE=" + safe[:210], flush=True)
        raise
    finally:
        for proc, handle in reversed(processes):
            stop(proc, handle)
        admin.close()


if __name__ == "__main__":
    main()
