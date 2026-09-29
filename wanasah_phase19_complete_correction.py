r"""Wanasah V1 Product Import phase-19 test fixture: same-job correction.

Only for the existing developer-test tenant 38 and job in this script.

Run from inside wa_backend:
    .\venv\Scripts\python.exe <download-location>\wanasah_phase19_complete_correction.py
    .\venv\Scripts\python.exe <download-location>\wanasah_phase19_complete_correction.py --execute

The default run is read-only. --execute updates only 15 previously INVALID test
rows using the existing tenant-scoped Product Import correction service. It does
not directly change Product/Price/Barcode tables and does not re-upload products.

The request UUID is deterministic for the exact job+payload; repeating a command
after an unknown result reuses the same idempotency identity.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import selectors
import sys
from collections import Counter
from io import StringIO
from uuid import UUID, NAMESPACE_URL, uuid5

from sqlalchemy import text

from domains.simple_products.imports.application.correction_service import (
    apply_correction_upload,
    build_correction_artifact,
    parse_correction_payload,
)
from domains.simple_products.imports.domain.normalization import normalize_raw_row
from domains.simple_products.imports.infrastructure.repository import (
    close_tenant_session,
    load_job,
    open_tenant_session,
)

COMPANY = 38
JOB = UUID("a586d11e-64fa-4392-9284-c5e62fe81b25")
EXPECTED_ROWS = frozenset((6, 10, 14, 17, 21, 24, 28, 33, 37, 40, 44, 47, 51, 55, 58))
FIXES = {
    10: ("package_uom", "CARTON"),
    14: ("units_per_package", "8"),
    17: ("units_per_package", "12"),
    21: ("units_per_package", "5"),
    24: ("units_per_package", "10"),
    28: ("package_price", ""),
    33: ("package_barcode", ""),
    37: ("unit_price", "1.000"),
    40: ("package_price", ""),
    44: ("unit_barcode", "9988004420261"),
    47: ("unit_barcode", "9988004720262"),
    51: ("lot_control_mode", "NONE"),
    58: ("unit_barcode", "9988005820263"),
}


async def snapshot():
    token, db = await open_tenant_session(COMPANY)
    try:
        job = await load_job(db, company_id=COMPANY, job_id=JOB)
        if job is None:
            raise RuntimeError("The original correction job cannot be found in this tenant.")
        counts = (await db.execute(text("""
            SELECT status, count(*) AS n
            FROM product_import_rows
            WHERE company_id = :company AND job_id = :job
            GROUP BY status
        """), {"company": COMPANY, "job": JOB})).mappings().all()
        imported = set((await db.execute(text("""
            SELECT product_variant_id
            FROM product_import_rows
            WHERE company_id = :company AND job_id = :job AND status = 'IMPORTED'
        """), {"company": COMPANY, "job": JOB})).scalars().all())
        product_count = (await db.execute(text("""
            SELECT count(*) FROM products WHERE company_id = :company
        """), {"company": COMPANY})).scalar_one()
        barcode_count = (await db.execute(text("""
            SELECT count(*) FROM product_barcodes
            WHERE company_id = :company AND is_active IS TRUE
        """), {"company": COMPANY})).scalar_one()
        return job, {r["status"]: int(r["n"]) for r in counts}, imported, int(product_count), int(barcode_count)
    finally:
        await close_tenant_session(token, db)


async def prepare(job):
    artifact = await build_correction_artifact(
        company_id=COMPANY, job_id=JOB, file_format="csv"
    )
    records = list(csv.DictReader(StringIO(artifact.payload.decode("utf-8-sig"))))
    source_headers = list(job.detected_headers or [])
    mapping = dict(job.column_mapping or {})
    physical_rows = {int(row["__wanasah_original_row"]) for row in records}
    if len(records) != 15 or physical_rows != EXPECTED_ROWS:
        raise RuntimeError("Unexpected failed-row set. Aborting without changes.")
    names, barcodes = [], []
    for row in records:
        number = int(row["__wanasah_original_row"])
        if number == 6:
            row[mapping["name"]] = row[mapping["name"]][:140]
        elif number == 55:
            # This row's original duplicate is fixed by changing row 58.
            pass
        else:
            field, value = FIXES[number]
            row[mapping[field]] = value
        cleaned = normalize_raw_row(
            {header: row.get(header) for header in source_headers},
            mapping,
            default_lot_control_mode=job.default_lot_control_mode,
            default_expiry_control_mode=job.default_expiry_control_mode,
        )
        names.append(str(cleaned["name"]).strip().casefold())
        for field in ("unit_barcode", "package_barcode"):
            if cleaned.get(field):
                barcodes.append(str(cleaned[field]))
    if len(names) != len(set(names)) or len(barcodes) != len(set(barcodes)):
        raise RuntimeError("Names or barcodes are not unique within the correction file.")

    token, db = await open_tenant_session(COMPANY)
    try:
        existing_barcodes = (await db.execute(text("""
            SELECT barcode FROM product_barcodes
            WHERE company_id = :company AND is_active IS TRUE
              AND barcode = ANY(:barcodes)
        """), {"company": COMPANY, "barcodes": barcodes})).scalars().all()
        if existing_barcodes:
            raise RuntimeError("Candidate barcodes now conflict with active company barcodes.")
        existing_names = (await db.execute(text("""
            SELECT name FROM products WHERE company_id = :company
        """), {"company": COMPANY})).scalars().all()
        if set(names).intersection(str(v).strip().casefold() for v in existing_names):
            raise RuntimeError("Candidate product names now conflict with existing products.")
    finally:
        await close_tenant_session(token, db)

    out = StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(records[0].keys()))
    writer.writeheader()
    writer.writerows(records)
    payload = ("\ufeff" + out.getvalue()).encode("utf-8")
    parsed = parse_correction_payload(
        file_name="wanasah-phase19-15rows.csv",
        payload=payload,
        source_headers=source_headers,
    )
    if len(parsed) != 15 or len({p.row_identity for p in parsed}) != 15:
        raise RuntimeError("The correction identity contract did not pass.")
    return payload, len(barcodes)


async def main(execute: bool):
    job, counts, imported_ids, product_count, barcode_count = await snapshot()
    print("TARGET_JOB=", JOB, "COMPANY=", COMPANY)
    print("BEFORE_STATUS=", job.status, "ROWS=", counts, "PRODUCT_COUNT=", product_count)
    if job.status == "COMPLETED" and counts == {"IMPORTED": 54}:
        print("ALREADY_COMPLETED=PASS; no correction will be submitted again.")
        return
    if job.status != "COMPLETED_WITH_ERRORS" or counts != {"IMPORTED": 39, "INVALID": 15}:
        raise RuntimeError("The expected safe starting state has changed; no correction attempted.")
    payload, barcode_candidates = await prepare(job)
    digest = hashlib.sha256(payload).hexdigest()
    request_id = uuid5(NAMESPACE_URL, f"wanasah:phase19:{COMPANY}:{JOB}:{digest}")
    print("PREFLIGHT=PASS; CORRECTIONS=15; CANDIDATE_BARCODES=", barcode_candidates)
    print("IDEMPOTENCY_REQUEST_ID=", request_id)
    if not execute:
        print("DRY_RUN_ONLY=PASS; no correction submitted. Add --execute to apply.")
        return
    print("SUBMITTING_EXISTING_JOB_CORRECTION=15", flush=True)
    outcome = await apply_correction_upload(
        company_id=COMPANY,
        actor_id=int(job.created_by),
        job_id=JOB,
        request_id=request_id,
        file_name="wanasah-phase19-15rows.csv",
        payload=payload,
    )
    print("CORRECTION_RECEIPT=", outcome, flush=True)
    if int(outcome["corrected_rows"]) != 15:
        raise RuntimeError("Unexpected correction receipt count.")
    for attempt in range(90):
        await asyncio.sleep(1)
        current, current_counts, current_ids, current_products, current_barcodes = await snapshot()
        if current.status in ("COMPLETED", "COMPLETED_WITH_ERRORS", "VALIDATION_FAILED", "FAILED"):
            print("AFTER_STATUS=", current.status, "ROWS=", current_counts, "PRODUCT_COUNT=", current_products)
            print("OLD_39_IDENTITIES_RETAINED=", imported_ids.issubset(current_ids))
            print("PRODUCT_DELTA=", current_products - product_count,
                  "ACTIVE_BARCODE_DELTA=", current_barcodes - barcode_count)
            if not (
                current.status == "COMPLETED"
                and current_counts == {"IMPORTED": 54}
                and len(current_ids) == 54
                and imported_ids.issubset(current_ids)
                and product_count <= current_products <= product_count + 15
                and current_barcodes == barcode_count + 28
            ):
                raise RuntimeError("The correction worker finished with an unexpected result. Inspect the job before retrying.")
            print("ALL_15_LIVE_CORRECTIONS=PASS")
            return
    print("WORKER_NOT_TERMINAL_WITHIN_VERIFICATION_WINDOW; inspect job, do not create a new import.")
    raise RuntimeError("Pending worker completion; no new request should be submitted with a fresh ID.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="Apply the same-job correction to the developer test tenant")
    opts = parser.parse_args()
    if sys.platform == "win32":
        asyncio.run(main(opts.execute), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(main(opts.execute))
