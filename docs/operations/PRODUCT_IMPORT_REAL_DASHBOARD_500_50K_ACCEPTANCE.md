# Product Import — real Dashboard 500 / 50,000 owner acceptance

**OPEN — tests not executed.** These are the owner's local original, untracked Excel files (never modify, reset, clean or re-upload blindly):
- products-import-test-mixed-500-new.xlsx: 500 populated rows + 3 blank source rows; 37,918 bytes.
- products-import-test-mixed-50000-new.xlsx: 50,000 populated rows + 0 blanks; 2,721,548 bytes.
Both retain the official Arabic product sheet and the two original hidden sheets. Read-only preflight found zero Excel formula cells. This does not prove that every input passes the backend's business validation.

**Historical comparison correction:** 50 minutes and 14 minutes were BOTH observed by the owner using the real Dashboard. The separate 255.868-second result was a **synthetic CSV on disposable PostgreSQL** and cannot be compared directly to actual owner Excel on a populated development database.

## Before starting

1. Verify current main has PR #80 (bounded Product-family flush improvement) and PR #81 (atomic SourceStore retention/retry). Keep all uncommitted user files untouched.
2. Confirm the actual intended developer DB name, signed-in tenant and authorized actor. Do not guess company_id from synthetic fixture IDs. Record disk capacity and a quiet baseline window; never reset shared PostgreSQL statistics.
3. Ensure the three supervised Product Import Worker roles are healthy: execution, control and maintenance; see wa_backend/domains/simple_products/imports/RUNBOOK.md. Do NOT start duplicate execution Workers or kill an occupied process. No testing on other customers' jobs.
4. An optional already-implemented sampling switch PRODUCT_IMPORT_PROFILE_EVERY_N_BATCHES=1 for 500, =10 for 50k can be applied **only before safe startup of the approved execution Worker**. It provides bounded SQL/flush/phase records in the execution logs. Setting a variable in a different terminal cannot change an already running Worker. Do not restart active jobs to turn it on.

## Read-only observer

The committed tool wa_backend/scripts/product_import_real_rehearsal_observer.py issues only short, read-only SELECT transactions using the existing application DB role and scoped company, refuses a wrong database name, never opens user Excel or changes Products/Prices/jobs, and records:
- actual job state, counters and original server timestamps from the tenant-scoped job;
- execution/control/maintenance todo/doing queue counts, PostgreSQL client wait-state breakdown, matched API/Worker process PID CPU-time/RSS (only if visible to psutil);
- per-table heap, index and total physical bytes; estimated live/dead tuples, autovacuum/analyze counters and timestamps; size and scan metrics for individual indexes;
- database/global WAL/transaction/deadlock/temp-file counter snapshots, tenant/global SourceStore capacity;
- terminal job row reconciliation and distinct linked Variant/Price/Audit/Outbox evidence.

No raw data, command-line arguments, URLs or credentials are logged. Snapshot/watch output is create-only under an explicitly created operator output directory, not committed into Git.

### Operator PowerShell commands (replace ALL placeholders before execution)

~~~powershell
cd C:\Users\admin\Desktop\wanasah\wa_backend
$python = ".\venv\Scripts\python.exe"
# Only prints database NAME, not the secret URL/password:
& $python -c "from sqlalchemy.engine import make_url; from config import Config; print(make_url(Config.SQLALCHEMY_DATABASE_URI).database)"
$company = <AUTHORIZED_DASHBOARD_COMPANY_ID>
$dbName = "<THE_EXACT_DATABASE_NAME_PRINTED_ABOVE>"
$dir = Join-Path $env:USERPROFILE "Desktop\wanasah-import-evidence-20261001"
New-Item -ItemType Directory -Path $dir -ErrorAction Stop | Out-Null

# BEFORE clicking Upload for the 500-row workbook:
& $python -m scripts.product_import_real_rehearsal_observer snapshot --company-id $company --expected-db $dbName --out "$dir\500-before.json" --os-processes
# Press Upload ONCE in the real Dashboard; copy job_id from the real HTTP 202 response:
$job500 = "<REAL_HTTP_JOB_UUID>"
& $python -m scripts.product_import_real_rehearsal_observer watch --company-id $company --expected-db $dbName --job-id $job500 --out "$dir\500-watch.jsonl" --seconds 5 --max-samples 720 --os-processes
& $python -m scripts.product_import_real_rehearsal_observer snapshot --company-id $company --expected-db $dbName --job-id $job500 --out "$dir\500-after.json" --os-processes
& $python -m scripts.product_import_real_rehearsal_observer compare --before "$dir\500-before.json" --after "$dir\500-after.json" --out "$dir\500-delta.json"

# Only after accepting 500, measure NEW baseline for the 50,000-row workbook:
& $python -m scripts.product_import_real_rehearsal_observer snapshot --company-id $company --expected-db $dbName --out "$dir\50000-before.json" --os-processes
# Press Upload ONCE for the NEW 50,000-row XLSX:
$job50000 = "<REAL_HTTP_JOB_UUID>"
& $python -m scripts.product_import_real_rehearsal_observer watch --company-id $company --expected-db $dbName --job-id $job50000 --out "$dir\50000-watch.jsonl" --seconds 10 --max-samples 720 --os-processes
& $python -m scripts.product_import_real_rehearsal_observer snapshot --company-id $company --expected-db $dbName --job-id $job50000 --out "$dir\50000-after.json" --os-processes
& $python -m scripts.product_import_real_rehearsal_observer compare --before "$dir\50000-before.json" --after "$dir\50000-after.json" --out "$dir\50000-delta.json"
~~~

The template placeholders shown are **not executable commands until explicitly replaced**. The correct job UUID is the one returned by the actual authorized import HTTP 202; do not infer it from old records. Output paths cannot overwrite prior evidence.

## Acceptance and interpretation

Measure **BOTH** real-browser elapsed time from submit to visible completed Product/Price result AND backend job created_at-to-finished_at, noting the 5s/10s sampling uncertainty of intermediate stage transitions. Verify 500 and then 50,000 physical source row counts, visible invalid reasons, imported + invalid + import_failed + pending accounting, number of distinct committed sellable Variants (not a guess at Products master count), effective Price and Audit/Outbox, stored barcodes/leading zeros, no duplicate side effects, SourceStore cleanup/counters, no remaining TODO/DOING delivery for the two jobs, and fresh Product search/filter/receipt. No forced correction/re-upload if an HTTP response was lost; resume the same job.

Watch table/index bytes and growth *per object*, estimated dead tuples, autovacuum cadence, index scans, temp/WAL and client pressure before/after each file. Physical table/index bytes do not necessarily shrink after cleanup; index growth alone is **not proof of bloat**. Shared PostgreSQL global counters may include other tenants; process sampling cannot prove entire worker-tree peak CPU/RSS. Do NOT call one timed 50k run a statistical p50/p95 SLA.

**Stop for code-first diagnosis** if unexpected 5xx/stalls, source/capacity leak, mismatched Product/Variant/Price/Audit/Outbox identity, tenant security/permissions failure, unduly growing index/dead tuples with unserved vacuum, or dashboard completion that differs from persisted status. Attribute to a specific call site or measured stage before running another load test.

This genuine user-dashboard rehearsal is the final **development** performance/quality gate for Product Import. If 500 and 50k complete with sound persistence, UI, and acceptable resource/time measurements, record the real observed evidence and close the development checklist. First-company deployment D7-P/D8-P, recovery, actual target hardware SLO and manual physical screen-reader/touch acceptance remain separately OPEN in docs/operations/PRODUCT_IMPORT_V1_RELEASE_RUNBOOK_2026-09-30.md until executed; they cannot be turned into passed tests by documentation.
