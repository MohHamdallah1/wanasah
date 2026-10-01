"""Isolated real HTTP+Worker+PG zero-row/near-total-invalid import edge gate.

Never touches a source company, user files or original developer job.
"""
from __future__ import annotations

import csv
import io
import os
import time
from uuid import uuid4

import httpx
import psycopg
from sqlalchemy.engine import make_url

if os.environ.get("WANASAH_P19_HTTP_DISPOSABLE_CHILD") != "1":
    raise RuntimeError("Edge gate refuses execution outside owned disposable runner.")
if os.environ.get("WANASAH_P19_HTTP_CASE") != "edges":
    raise RuntimeError("Edge gate requires explicit edges mode.")
for name in ("DATABASE_URL", "DATABASE_URL_MIGRATION"):
    target = make_url(os.environ.get(name, ""))
    if (target.database != "p19_http_synthetic" or target.host != "127.0.0.1"
        or int(target.port or 0) != 55446):
        raise RuntimeError("Edge gate refuses any database except disposable 127.0.0.1:55446.")

from api.auth import create_access_token
from domains.simple_products.imports.domain.localization import EN_IMPORT_LOCALE
from scripts import product_import_phase19_http_isolated_child as shared
from scripts.product_import_business_integrity_gate import _assert_business_evidence
from scripts.run_product_import_phase19_live_load import build_source

ROWS = 1000
FINAL = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "VALIDATION_FAILED", "CANCELLED"}


def _new_import(client: httpx.Client, payload: bytes, label: str) -> httpx.Response:
    return client.post(
        "/simple-products/imports",
        data={
            "request_id": str(uuid4()),
            "default_lot_control_mode": "NONE",
            "default_expiry_control_mode": "NONE",
        },
        files={"file": (label + ".csv", payload, "text/csv")},
    )


def _wait(client: httpx.Client, job_id: str, *, seconds: float = 120) -> dict:
    cutoff = time.monotonic() + seconds
    while time.monotonic() < cutoff:
        r = shared.require(
            client.get(f"/simple-products/imports/{job_id}"),
            200, "edge import status",
        )
        if str(r.get("status")) in FINAL:
            return r
        time.sleep(.25)
    raise TimeoutError("Bounded edge import Worker did not reach terminal state.")


def run(client: httpx.Client, admin: psycopg.Connection) -> None:
    # 0 data rows: the official header remains recognizable, but the
    # file must never create an empty Product/Price/Variant.
    source, _mapping, _prefix = build_source(1, "P19-EDGE-ZERO-" + uuid4().hex[:8])
    first_line = source.splitlines(keepends=True)[0]
    if not first_line.startswith(b"\xef\xbb\xbf"):
        raise RuntimeError("Expected BOM in test source.")
    zero = _new_import(client, first_line, "P19-EMPTY-SYNTHETIC")
    if zero.status_code == 202:
        admitted = shared.require(zero, 202, "empty-row admission")
        job_id = str(admitted["job_id"])
        state = _wait(client, job_id)
        if str(state["status"]) not in {"FAILED", "VALIDATION_FAILED"}:
            raise RuntimeError("Empty source unexpectedly created a successful business job.")
        persisted = admin.execute(
            "SELECT count(*) FROM product_import_rows WHERE company_id=2 AND job_id=%s",
            (job_id,),
        ).fetchone()[0]
        if int(persisted):
            raise RuntimeError("Empty file generated staged rows.")
    elif zero.status_code == 422:
        job_id = None
    else:
        raise RuntimeError(f"Empty source was not rejected: HTTP {zero.status_code}")
    print("P19_REAL_HTTP_ZERO_PRODUCT_ROWS_REJECTED=PASS", flush=True)

    source, _mapping, _prefix = build_source(ROWS, "P19-EDGE-999INVALID-" + uuid4().hex[:8])
    reader = csv.DictReader(io.StringIO(source.decode("utf-8-sig")))
    if reader.fieldnames is None:
        raise RuntimeError("Synthetic source headers missing.")
    cells = list(reader)
    if len(cells) != ROWS:
        raise RuntimeError("Synthetic source size mismatch.")
    name_field = EN_IMPORT_LOCALE.template.headers["name"]
    for item in cells[1:]:
        item[name_field] = ""  # 999 known-invalid rows; row 1 remains valid.
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=reader.fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(cells)
    payload = buffer.getvalue().encode("utf-8-sig")

    admitted = shared.require(
        _new_import(client, payload, "P19-NEARLY-ALL-INVALID"),
        202, "near-100 percent invalid source admission",
    )
    job_id = str(admitted["job_id"])
    result = _wait(client, job_id, seconds=180)
    if str(result["status"]) != "COMPLETED_WITH_ERRORS":
        raise RuntimeError("Near-100% invalid source ended in unexpected state.")

    outcome = _assert_business_evidence(admin, job_id, 1)
    if (outcome["imported"], outcome["invalid"], outcome["import_failed"]) != (1, 999, 0):
        raise RuntimeError("Near-all-invalid row and Product/Price/Audit result mismatch.")
    physical = admin.execute(
        "SELECT count(*),count(DISTINCT row_number),min(row_number),max(row_number) "
        "FROM product_import_rows WHERE company_id=2 AND job_id=%s",
        (job_id,),
    ).fetchone()
    if tuple(map(int, physical)) != (1000, 1000, 2, 1001):
        raise RuntimeError("Near-all-invalid physical source identity mismatch.")
    remaining = admin.execute(
        "SELECT count(*) FROM procrastinate_jobs WHERE task_name='wanasah.process_product_import' "
        "AND args->>'job_id'=%s AND status IN ('todo','doing')",
        (job_id,),
    ).fetchone()[0]
    cleared = admin.execute(
        "SELECT source_payload_cleared_at FROM product_import_jobs "
        "WHERE company_id=2 AND id=%s",
        (job_id,),
    ).fetchone()[0]
    if remaining or cleared is None:
        raise RuntimeError("High-invalid Worker did not clear its source/queue.")
    print("P19_REAL_HTTP_1000_ROWS_999_INVALID=PASS", flush=True)
    print("P19_EDGE_1000_PERSISTED_VARIANT_PRICE_AUDIT_OUTBOX=PASS", flush=True)
    print("P19_HIGH_INVALID_SOURCESTORE_AND_QUEUE=PASS", flush=True)


def main() -> None:
    target = make_url(os.environ["DATABASE_URL_MIGRATION"])
    admin = psycopg.connect(
        target.set(drivername="postgresql").render_as_string(hide_password=False),
        autocommit=True,
    )
    processes = []
    try:
        for company in (2, 3):
            count = admin.execute(
                "SELECT count(*) FROM companies WHERE id=%s", (company,),
            ).fetchone()[0]
            if int(count) != 1:
                raise RuntimeError("Expected one source-approved synthetic company.")
        token = create_access_token({"sub": "1", "is_admin": True}, 2, "Admin")
        processes.append(shared.start("edge-api", "-m", "scripts.product_import_phase19_http_selector_server"))
        for role in ("control", "maintenance", "execution"):
            processes.append(shared.start(
                f"edge-{role}", "-m",
                "domains.simple_products.imports.infrastructure.worker_cli", "--role", role,
            ))
        with httpx.Client(
            base_url=shared.BASE, timeout=40.0,
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            shared.wait_health(client, processes)
            shared.wait_worker(client)
            run(client, admin)
        print("PRODUCT_IMPORT_P19_REAL_HTTP_EDGES=PASS", flush=True)
    finally:
        for process, handle in reversed(processes):
            shared.stop(process, handle)
        admin.close()


if __name__ == "__main__":
    main()
