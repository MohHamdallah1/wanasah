r"""Opt-in real-DB Product Import E2E smoke/load harness (DEVELOPMENT ONLY).

This is NOT a unit benchmark. It submits a real CSV to the existing
application SourceStore/queue and observes the worker's persisted results.
It never truncates/deletes business data and does not change the schema.

Usage from wa_backend:
    .\venv\Scripts\python.exe -m scripts.run_product_import_phase19_live_load --rows 100 --run-id PH19-SMOKE-20260928 --dry-run
    .\venv\Scripts\python.exe -m scripts.run_product_import_phase19_live_load --rows 100 --run-id PH19-SMOKE-20260928 --execute
    .\venv\Scripts\python.exe -m scripts.run_product_import_phase19_live_load --rows 50000 --run-id PH19-LOAD-20260928 --execute

Run IDs must be distinct across independent runs. All rows are synthetic.
The test environment is the user's explicitly authorized LOCAL development DB,
tenant 38. The existing Product Import HTTP authorization is not exercised
by this application-service harness; test that transport separately.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import ipaddress
import io
import json
import selectors
import sys
import time
from collections import Counter
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from domains.simple_products.imports.application.api_service import create_import
from domains.simple_products.imports.domain.localization import (
    CANONICAL_IMPORT_FIELDS,
    EN_IMPORT_LOCALE,
)
from domains.simple_products.imports.domain.mapping import suggest_mapping
from domains.simple_products.imports.domain.normalization import normalize_raw_row
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    open_tenant_session,
)

COMPANY_ID = 38
ACTOR_ID = 26
TERMINAL = {
    "COMPLETED",
    "COMPLETED_WITH_ERRORS",
    "FAILED",
    "VALIDATION_FAILED",
    "CANCELLED",
    "NEEDS_MAPPING",
}
PACKAGES = ("CARTON", "PACK", "CASE")


def build_source(row_count: int, run_id: str) -> tuple[bytes, dict[str, str], str]:
    headers = dict(EN_IMPORT_LOCALE.template.headers)
    mapping = suggest_mapping([headers[f] for f in CANONICAL_IMPORT_FIELDS])
    missing = [f for f in CANONICAL_IMPORT_FIELDS if mapping.get(f) != headers[f]]
    if missing:
        raise RuntimeError(f"Header alias round-trip rejected: {missing!r}")

    series = int(hashlib.sha256(run_id.encode()).hexdigest()[:8], 16) % 1_000_000
    prefix = f"89{series:06d}"
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([headers[field] for field in CANONICAL_IMPORT_FIELDS])

    def source_values(i: int) -> list[str]:
        package = i % 6 != 0
        pkg = PACKAGES[i % len(PACKAGES)] if package else "No outer package"
        units = str(2 + i % 24) if package else ""
        price = f"{1 + (i % 35) / 10:.3f}"
        val = {
            "name": f"PH19 {run_id} item {i:05d}",
            "family": f"PH19 {run_id} family {i % 120:03d}",
            "package_uom": pkg,
            "units_per_package": units,
            "package_price": "",
            "unit_price": price,
            "unit_barcode": f"{prefix}{i:05d}1",
            "package_barcode": f"{prefix}{i:05d}2" if package else "",
            "lot_control_mode": ("REQUIRED" if i % 5 == 0 else "NONE"),
            "expiry_control_mode": ("REQUIRED" if i % 5 == 0 else "NONE"),
        }
        if i % 100 == 0:
            case = (i // 100) % 5
            if case == 0:
                val["name"] = ""
            elif case == 1:
                val["package_uom"] = "BOTTLE"
                val["units_per_package"] = "12"
            elif case == 2:
                val["package_uom"] = "CARTON"
                val["units_per_package"] = "1"
            elif case == 3:
                val["unit_price"] = ""
            else:
                val["lot_control_mode"] = "UNKNOWN"
        return [val[f] for f in CANONICAL_IMPORT_FIELDS]

    for i in range(1, row_count + 1):
        writer.writerow(source_values(i))
        if i < row_count and i % 10_000 == 0:
            writer.writerow([""] * len(CANONICAL_IMPORT_FIELDS))

    sample = source_values(1)
    raw = dict(zip([headers[f] for f in CANONICAL_IMPORT_FIELDS], sample, strict=True))
    normalized = normalize_raw_row(
        raw,
        mapping,
        default_lot_control_mode="NONE",
        default_expiry_control_mode="NONE",
    )
    if not normalized["name"] or not normalized["unit_price"]:
        raise RuntimeError("Generated valid-row normalization failed")
    data = output.getvalue().encode("utf-8-sig")
    return data, mapping, prefix


async def check_local_environment(prefix: str, run_id: str) -> dict[str, int]:
    token, db = await open_tenant_session(COMPANY_ID)
    try:
        info = (await db.execute(text(
            "SELECT current_database() AS db, inet_server_addr() AS host"
        ))).mappings().one()
        host = info["host"]
        if host is None or not ipaddress.ip_address(str(host)).is_loopback:
            raise RuntimeError("Refusing live load on non-loopback PostgreSQL host")
        if str(info["db"]) != "velotrack_db":
            raise RuntimeError("Unexpected database name: not the verified dev DB")
        overlaps = (await db.execute(text(
            "SELECT count(*) FROM product_barcodes WHERE company_id=:company "
            "AND barcode LIKE :prefix"
        ), {"company": COMPANY_ID, "prefix": prefix + "%"})).scalar_one()
        if overlaps:
            raise RuntimeError(
                f"Run-ID barcode namespace is already used ({overlaps} hits): {run_id}"
            )
        active = (await db.execute(text(
            "SELECT count(*) FROM product_import_jobs "
            "WHERE company_id=:company AND status "
            "NOT IN ('COMPLETED','COMPLETED_WITH_ERRORS','FAILED',"
            "'VALIDATION_FAILED','CANCELLED','NEEDS_MAPPING')"
        ), {"company": COMPANY_ID})).scalar_one()
        if active:
            raise RuntimeError(f"Tenant has {active} active import jobs")
        product_count = (await db.execute(text(
            "SELECT count(*) FROM products WHERE company_id=:company"
        ), {"company": COMPANY_ID})).scalar_one()
        variant_count = (await db.execute(text(
            "SELECT count(*) FROM product_variants WHERE company_id=:company"
        ), {"company": COMPANY_ID})).scalar_one()
        return {"parents": int(product_count), "variants": int(variant_count)}
    finally:
        await close_tenant_session(token, db)


async def get_job(job_id: str) -> dict:
    token, db = await open_tenant_session(COMPANY_ID)
    try:
        result = (await db.execute(text(
            "SELECT status,total_rows,processed_rows,valid_rows,failed_rows,"
            "started_at,finished_at FROM product_import_jobs "
            "WHERE company_id=:company AND id=:job"
        ), {"company": COMPANY_ID, "job":job_id})).mappings().one()
        return dict(result)
    finally:
        await close_tenant_session(token, db)


async def final_evidence(job_id: str, count: int) -> dict[str, int]:
    token, db = await open_tenant_session(COMPANY_ID)
    try:
        counts = (await db.execute(text(
            "SELECT status,count(*) AS n,count(DISTINCT product_variant_id) AS variants, "
            "min(row_number) AS first_row,max(row_number) AS last_row "
            "FROM product_import_rows WHERE company_id=:company AND job_id=:job "
            "GROUP BY status ORDER BY status"
        ), {"company": COMPANY_ID, "job":job_id})).mappings().all()
        by_status = {str(r["status"]):int(r["n"]) for r in counts}
        unique_variants = sum(int(r["variants"]) for r in counts)
        last_physical = max((int(r["last_row"]) for r in counts), default=0)
        expected_invalid = count // 100
        expected_valid = count - expected_invalid
        expected_last = 1 + count + ((count - 1) // 10_000)
        print("FINAL_COUNTS=", by_status, "UNIQUE_IMPORTED_VARIANTS=", unique_variants,
              "LAST_PHYSICAL_ROW=", last_physical, flush=True)
        if by_status != {"IMPORTED":expected_valid, "INVALID":expected_invalid}:
            raise AssertionError("Unexpected import result breakdown")
        if unique_variants != expected_valid or last_physical != expected_last:
            raise AssertionError("Source-row fidelity or created-variant mismatch")
        wrong_links = (await db.execute(text(
            "SELECT count(*) FROM product_import_rows r "
            "LEFT JOIN product_variants v "
            " ON v.company_id=r.company_id AND v.id=r.product_variant_id "
            "LEFT JOIN products p "
            " ON p.company_id=v.company_id AND p.id=v.product_id "
            "WHERE r.company_id=:company AND r.job_id=:job AND r.status='IMPORTED' "
            "AND (v.id IS NULL OR p.id IS NULL)"
        ), {"company": COMPANY_ID, "job":job_id})).scalar_one()
        if wrong_links:
            raise AssertionError("Imported rows have missing Product/Variant linkage")
        print("IMPORT_LOAD_LIVE_LINEAGE=PASS",flush=True)
        return {"imported":expected_valid,"invalid":expected_invalid}
    finally:
        await close_tenant_session(token, db)


async def run(args: argparse.Namespace) -> None:
    start = time.perf_counter()
    payload, mapping, prefix = build_source(args.rows, args.run_id)
    request_id = uuid5(NAMESPACE_URL, f"wanasah-phase19:{COMPANY_ID}:{args.run_id}:{args.rows}")
    baseline = await check_local_environment(prefix,args.run_id)
    print("PRECHECK=PASS DB_LOCAL_ONLY=True", "ROWS=",args.rows,
          "SOURCE_BYTES=",len(payload),"EXPECTED_INVALID=",args.rows//100,
          "STARTING_TENANT_COUNTS=",baseline,"REQUEST_ID=",request_id,flush=True)
    if not args.execute:
        print("DRY_RUN=PASS; SOURCE_NOT_SUBMITTED",flush=True)
        return
    token, db = await open_tenant_session(COMPANY_ID)
    try:
        queued = await create_import(
            db,
            company_id=COMPANY_ID,
            actor_id=ACTOR_ID,
            request_id=request_id,
            file_name=f"phase19-{args.run_id}-{args.rows}.csv",
            content_type="text/csv",
            source_stream=io.BytesIO(payload),
            source_size=len(payload),
            source_sha256=hashlib.sha256(payload).hexdigest(),
            default_lot_control_mode="NONE",
            default_expiry_control_mode="NONE",
        )
    finally:
        await close_tenant_session(token,db)
    job_id = str(queued["job_id"])
    print("QUEUED_JOB_ID=",job_id,"QUEUED=",queued, "ADMIT_S=",
          round(time.perf_counter()-start,3),flush=True)
    last_print = 0.
    while time.perf_counter()-start < args.max_wait:
        state = await get_job(job_id)
        now = time.perf_counter()-start
        if now-last_print>=10 or state["status"] in TERMINAL:
            print("PROGRESS=",state["status"],"PROCESSED=",state["processed_rows"],
                  "VALID=",state["valid_rows"],"FAILED=",state["failed_rows"],
                  "ELAPSED_S=",round(now,2),flush=True)
            last_print=now
        if state["status"] in TERMINAL:
            if state["status"] not in ("COMPLETED","COMPLETED_WITH_ERRORS"):
                raise RuntimeError(f"Worker terminal status: {state['status']}")
            evidence = await final_evidence(job_id,args.rows)
            print("FINAL_E2E_LOAD=PASS","ROWS=",args.rows,
                  "IMPORT_S=",round(time.perf_counter()-start,2),
                  "EVIDENCE=",evidence,flush=True)
            return
        await asyncio.sleep(2)
    raise TimeoutError("Job is still pending; inspect job ID, do not resubmit with another request ID")


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rows",type=int,choices=(100,1000,50000),required=True)
    p.add_argument("--run-id",required=True)
    p.add_argument("--execute",action="store_true")
    p.add_argument("--max-wait",type=int,default=1800)
    args=p.parse_args()
    if len(args.run_id)>35 or not all(c.isascii() and (c.isalnum() or c in "-_") for c in args.run_id):
        p.error("run-id must contain 1..35 ASCII letters/digits/-/_")
    if __import__("sys").platform == "win32":
        asyncio.run(run(args),loop_factory=lambda:asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(run(args))


if __name__ == "__main__":
    main()
