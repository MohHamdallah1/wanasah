# Phase 19 — Real HTTP zero-row and near-total invalid edge acceptance

Date: 2026-10-01. Full disposable PostgreSQL16 + real FastAPI +
three import Worker roles; synthetic-only test data.

## Source-first cases and observed outcome

1. **Header-only CSV, zero product rows.** Submitted to actual official
   HTTP import endpoint; either rejected at ingress or finished in an
   explicit failure/validation-failure status, without any persisted
   ProductImportRows or newly created products. Observed marker:
   P19_REAL_HTTP_ZERO_PRODUCT_ROWS_REJECTED=PASS.
2. **1,000 actual data rows, 999 deliberately blank names and 1
   initially valid product.** Real HTTP POST202 and Worker execution
   reached COMPLETED_WITH_ERRORS, with 1 IMPORTED, 999 INVALID,
   0 IMPORT_FAILED. Exactly one distinct imported Variant, one Price,
   one ProductVariant Audit and one Outbox record, original physical
   row numbers 2..1001 with 1000 distinct source row identities.
   SourceStore cleared, no active queue tasks. Markers:
   P19_REAL_HTTP_1000_ROWS_999_INVALID=PASS,
   P19_EDGE_1000_PERSISTED_VARIANT_PRICE_AUDIT_OUTBOX=PASS,
   P19_HIGH_INVALID_SOURCESTORE_AND_QUEUE=PASS.

These are read back from the *real disposable* PostgreSQL DB, not
mocked business objects or a UI counter.

Combined with earlier verified isolated evidence:
- PR #64: signed HTTP 100-row job, 99/1 then same-job correction to
  100/100; representative active barcode and immutable previously
  imported Product/Variant/Pricing readback, duplicate replay denied.
- PR #65: single real 5,000-row (4950/50) and 10,000-row (9900/100)
  intermediate queue runs.
- PR #66: one measured real 50,000-row (49500/500) run with 50,000
  distinct source physical row numbers, four true blank lines,
  49,500 unique saved variants and Price/Audit/Outbox each.

No customer or developer Product was written. The source developer
test tenant was verified unchanged and the temporary DB and worktree
were removed. The owner's reserved 500/50k Excel files were not used.
This covers the 0/100/1k/50k source-size sequence and a deliberately
99.9%-invalid case; it does not claim a statistical p95, full barcode
table census for the 50k run, or real user browser accessibility.

## Repetition

From wa_backend, with the preapproved EMPTY developer source tenant
and both disposable ports 55446 (PG) and 18046 (API) free:

~~~powershell
$env:WANASAH_P19_HTTP_LOCAL_GATE = '1'
$env:WANASAH_P19_HTTP_SOURCE_ENV_FILE = (Resolve-Path '.\.env').Path
$env:WANASAH_P19_HTTP_CASE = 'edges'
$env:WANASAH_P19_EDGES_CONFIRM = 'ISOLATED_SYNTHETIC_ONLY'
.\venv\Scripts\python.exe -m scripts.run_product_import_phase19_http_isolated_gate
~~~

The gate refuses source databases other than the whitelisted local
developer DB, and refuses an unexpected disposable target or absent
explicit opt-in. Never point it at actual customer data or use a saved
user-supplied import file.
