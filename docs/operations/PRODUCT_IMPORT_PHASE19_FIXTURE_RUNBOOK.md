# Phase 19 — synthetic Product Import fixtures

**Scope: CSV input generation only.** The tool NEVER connects to HTTP,
PostgreSQL, the queue or the Worker, and never publishes Products/Prices.
This is not a substitute for the real 19.1/19.2 acceptance run.

Source: wa_backend/tools/product_import/phase19_fixture.py

From the wa_backend project directory, with its existing virtual environment:

~~~powershell
.\.venv\Scripts\python.exe -m tools.product_import.phase19_fixture --output-dir "$env:TEMP\wanasah-phase19-fixtures" --tenant-label qa-sandbox --rows 100 --locale mixed --confirm-development-only
~~~

For a new 50,000-row fixture, change --rows 100 to --rows 50000.
Each invocation defaults to a new random run id. To reproduce the exact
offline source, provide --run-id explicitly, but the tool refuses to
overwrite an existing source or manifest. Use a fresh run id for EACH
real HTTP import. Do not reuse historical successful identifiers.

The authoritative AR/EN source headers drive the fixture. A mixed run
combines English/Arabic source headers and multilingual data values while
mapping the 10 canonical import fields. Every product explicitly chooses
no outer package or an actual Carton/Case, with appropriate quantity and
pricing values; mix tracking and barcode formats (including leading zeroes).
Every 31 source data rows an EMPTY physical CSV line is inserted; it does
not count toward the 50,000-product maximum. Every 25th product row has one
of four intentional invalid cases: missing name, no price, carton without
a unit factor, or outer barcode without outer packaging.

The sidecar .manifest.json records: run id, synthetic tenant label, SHA-256,
source size, physical last Excel/CSV row number, blank-row count, distinct
within-run barcodes and injected defect counts. **Injected defects are not
actual final worker validation counts.** Other failures (tenant UOM policy,
prices, existing barcode collisions) can occur only at real validation.

**Before using the 50k fixture:** 19.1 authenticated HTTP/PostgreSQL/Worker
acceptance must close, and staging-hang diagnosis/intermediate checks must
permit a final owner-approved synthetic development-only run. Verify the
specific target tenant's UOM/price policy and source-data isolation, record
DB/Product/Variant/Price/Audit baselines and current worker version. Never
mix test rows into an actual customer tenant or infer a 50k E2E PASS from
this offline generator.

Offline regression: wa_backend/tests/test_product_import_phase19_fixture_generator.py.
