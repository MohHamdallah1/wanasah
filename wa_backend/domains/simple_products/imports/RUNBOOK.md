# Product Import V1 Operational Runbook

## Canonical worker launch

Run each role as an **independent supervised process**, from PowerShell:

```powershell
cd wa_backend
.\scripts\run_product_import_worker.ps1 -Role execution
.\scripts\run_product_import_worker.ps1 -Role control
.\scripts\run_product_import_worker.ps1 -Role maintenance
```

These are three foreground commands for three supervisor services (or three
development terminals), not sequential commands in one terminal. Starting only
execution is an incomplete deployment. The development wrapper delegates here;
do not start both wrappers for the same role. No launcher restarts an existing
process or increases execution concurrency.

All roles use the SAME Procrastinate App and public schema:

| Role | Queue | Work | Slots per process |
|---|---|---|---|
| execution | `product-import` | Imports and execution-presence proof | `PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS`, default **2** |
| control | `product-import-control` | Stalled recovery and runtime health heartbeat | `PRODUCT_IMPORT_CONTROL_WORKER_SLOTS`, default 1 |
| maintenance | `product-import-maintenance` | Capacity/table monitoring, retention and their schedulers | `PRODUCT_IMPORT_MAINTENANCE_WORKER_SLOTS`, default 1 |

D3.2 authorizes **one execution process with two slots**, not unlimited worker
processes. Same-company jobs remain serialized by
`product-import:{company_id}`; an independent company may use the other slot.
Keep the execution slot setting identical in API and worker environments because
readiness capacity uses that setting. All roles need independent process
supervision/restart policies.

Product Import queue connectors are explicitly bounded to 1..2 connections per
role instead of Psycopg's former implicit 4..4 default. The Product Import
subsystem has a fail-closed 16-connection envelope. The deployment-wide Config
also reserves web + operational workers + Product Import together: current
defaults are 20 + 10 + 16 = **46 reserved connections** inside a
`DB_DEPLOYMENT_CONNECTION_BUDGET` of 60. Production must set that deployment
budget below its actual PostgreSQL `max_connections` with separate
admin/failover headroom. Do not raise slots, queue pool sizes, or worker process
counts independently; rerun D3.2 on production-like capacity first.

On Linux, each service runs the backend virtual environment's Python, working
directory `wa_backend`, with the corresponding role:

```text
python -m domains.simple_products.imports.infrastructure.worker_cli --role execution
python -m domains.simple_products.imports.infrastructure.worker_cli --role control
python -m domains.simple_products.imports.infrastructure.worker_cli --role maintenance
```

Startup recovery runs before each consumer, protected by the same PostgreSQL
advisory mutex as scheduled recovery and `workers.recover_cli product-import`.
Concurrent startup recovery reports `recovery_in_progress` instead of racing.
The existing allowlist and retry/failure handling are unchanged. Native
Procrastinate periodic deferral and native worker heartbeats run independently
of task slots; no application polling loop was introduced.

Do not launch Product Import through a root-level compatibility module.

## Health and readiness

- Authenticated readiness: `GET /simple-products/import-worker/readiness`.
- `READY` requires a live worker that has proven it consumes ONLY the execution
  queue through an import or execution-presence heartbeat. The existing heartbeat
  task name has its original periodic identity on control, plus a distinct
  `execution-presence` periodic identity on execution. Their queueing/execution
  locks differ. Control heartbeats report health and never register their worker.
- Presence proof can wait behind an import: that import already registers the
  execution worker, whose native Procrastinate heartbeat maintains liveness.
  A newly idle execution process becomes ready after its presence task runs.
- API READY is execution readiness, not proof of the whole topology. Verify
  all three supervisor processes and control-health log freshness independently.
- Queue-age, oldest-job, stuck-stage, worker-slot and table-health metrics are
  emitted by the Product Import monitoring tasks.
- A readiness failure or queue-age alert is an operational signal, not permission
  to bypass admission, tenant locks, retries, or idempotency.

## Execution semantics

- Queue payloads carry `company_id` and durable `job_id`; tenant context is
  re-established server-side for every worker step.
- Source bytes are read only through the immutable `SourceStore` contract and
  are hash/size verified before parsing.
- Parsing/staging is transactional. A crash cannot commit a half-staged source.
- Validation is best-effort across rows and bounded in batches; invalid rows are
  recorded without blocking unrelated valid rows.
- Product/Pricing writes are atomic per successful execution unit and protected
  by durable row identity + operation idempotency.
- Duplicate delivery and post-commit retry replay durable results instead of
  creating a Product twice.
- Transient/database failures retry as job/system failures; they are never
  converted into fake row validation errors.
- Required permissions are revalidated during execution. Revocation after
  queueing fails closed before further Product/Pricing writes.
- Cancellation is terminal and shares the same job-row transaction boundary as
  validation/execution batches.

## Company serialization

The company-scoped queue lock remains intentional because execution reaches the
company-default Pricing publication authority. Different companies may execute
concurrently; two imports for the same company remain serialized until Pricing
exposes a narrower proven-safe concurrency contract.

## Recovery

1. Do not manually mutate Product Import row/job states or create queue rows by hand.
2. Check readiness and queue-age/stuck-stage telemetry, then restore database and
   worker availability.
3. Control recovery first lets Procrastinate retry safe stalled deliveries, then
   reconciles stale active `product_import_jobs` that have **no** TODO/DOING
   `wanasah.process_product_import` delivery. This closes the durable business-job /
   queue-delivery gap without enumerating all companies.
4. Every process delivery has `queueing_lock=product-import-job:{job_id}` for one
   active delivery per durable import. The separate `product-import:{company_id}`
   execution lock still serializes same-company Product/Pricing work. Procrastinate's
   queueing-lock uniqueness is scoped to TODO rows, so supported retries after a
   finished/failed delivery remain possible.
5. Orphan discovery is bounded and indexed. Migration `a42c9f17e6b3` exposes only
   company/job identifiers through a fixed-search-path `SECURITY DEFINER` boundary,
   uses `FOR UPDATE SKIP LOCKED`, excludes live TODO/DOING delivery, and computes
   staleness using the database session clock rather than a worker-host timestamp.
6. Startup and periodic reconciliation share the existing global Product Import
   recovery advisory mutex. A concurrent legitimate producer is harmlessly
   deduplicated by the job queueing lock.
7. Replaying the same durable job is safe: committed execution batches use the
   existing idempotency envelope, and already-imported rows are not recreated.
8. If the job is terminal, use the supported Retry/Correction flows rather than
   editing staging rows directly.

**Deployment order:** apply migration `a42c9f17e6b3` before starting D4-capable
workers. The new worker intentionally fails closed if its recovery database
contract is absent.

## Automatic scheduling and historical failures

Keep the existing cadence: recovery every five minutes, heartbeat every minute,
capacity sweep every five minutes, retention sweep hourly at minute 17. Multiple
processes retain Procrastinate's atomic periodic `(task, periodic_id, timestamp)`
deduplication. Migration `d31c7a940e62` replaces tenant discovery with
`product_import_schedule_candidates`, keyed by `(company_id, task_kind)` and
indexed by `(task_kind, next_due_at, company_id)`. Deploy this migration before
the revised maintenance consumers; it requires the privileged migration role
and resolves runtime grants from `DATABASE_URL`. No migration was run here.

Four narrow transactional trigger sources maintain candidates: job lifecycle /
source-reference changes, immutable-source insertion/deletion state, tenant
live-byte changes, and admission-rejection insertion. They cover both ORM and
raw-SQL writers, including legacy job payloads. Progress-only updates and source
chunks do not register events. Row staging/correction is covered by the parent
job lifecycle; retention row compaction/deletion is reconciled after cleanup.
The migration seeds only existing relevant import records, including future
7/30/365-day retention deadlines. It does not enumerate Companies.

Each scheduler claims up to ten pages of 1,000 due candidates using the ordered
due index and `FOR UPDATE SKIP LOCKED`. One control connection serves a run.
Claim advancement and queue insertion share a transaction. The advancement
(5 minutes / 1 hour) keeps failed or lost deliveries recoverable; it is not an
eligibility sweep. Remaining due pages wait for the next existing cadence.
Company children retain execution locks, matching queueing locks and original
retry policies. A batched active-lock probe also recognizes legacy jobs without
queueing locks. Only `AlreadyEnqueued` is treated as deduplication, inside a
savepoint. Global capacity/table metrics, recovery and heartbeat remain global.

After successful tenant work, normal tenant/RLS context reads the candidate
generation BEFORE computing the next deadline. A generation-checked completion
retires empty candidates or records the next actual retention deadline; capacity
recurs only while live sources, nonzero counters, active jobs or recent
rejections require monitoring. Events and successful rescheduling advance a
global sequence generation, preventing stale completion and delete/reinsert ABA.
Legacy company-only task payloads need no conversion. No tenant session is
opened by candidate discovery.

The registry has FORCE RLS for tenant reads; runtime has no direct mutation
privileges. SECURITY DEFINER functions use a fixed safe search_path and fully
qualified relations, with PUBLIC execution revoked. The bounded claim function
exposes only scheduling metadata; completion verifies the current tenant.
Event functions inspect NEW/OLD only, never other tenants' business rows.
All business-table FORCE RLS remains unchanged. The one-time bootstrap requires
a privileged migration role and locks the four event sources until commit so
concurrent writers cannot fall between bootstrap and trigger installation.
Do not downgrade this migration while these maintenance consumers are running.
Independent review must validate RLS/grants, concurrent registration/completion,
claim rollback/deduplication, legacy delivery, and retention boundary behavior.

The historical 139,934 successful / 9,176 failed capacity tasks and 16,875 starts
in two hours establish workload, not an exception cause. Source inspection finds
no evidence that can attribute those failures to a particular SQL statement,
permission, driver or schema version. Read-only forensic follow-up must correlate
failed task IDs/timestamps with sanitized server exception class/SQLSTATE and the
worker release. Do not print tokens, connection strings or customer contents.
The 49 TODO / 1 DOING snapshot did not capture task identities.

## D3.1 rollout, pending jobs and rollback

1. Independent review/acceptance comes first; this implementation has not run
   tests, queue jobs, database commands or process restarts. Verify three-role
   isolation under a long import and long retention task; test readiness with
   ONLY control alive, duplicate scheduling, crash recovery and legacy jobs.
2. Record the expected commit and application source fingerprint from the
   intended immutable checkout. The entrypoint's `--print-code-identity` prints
   them without opening a database connection. Every actual worker logs
   `PRODUCT_IMPORT_WORKER_CODE` with PID, role, queue, slots, commit and fingerprint.
   Packaged deployments without Git must supply the build's full commit SHA in
   `WANASAH_RELEASE_COMMIT`; checkouts may resolve HEAD automatically. The
   fingerprint covers domain, worker and root backend Python source files.
   Compare EACH new process's startup record, PID/start time and supervisor
   command. Merely inspecting HEAD or file modification time is insufficient.
3. Use an approved admission pause during cutover; preserve status/retry evidence.
   Inventory active/scheduled jobs by queue, task, status and worker; preserve
   IDs, args, locks, attempts, scheduled times and events. Do not delete, relabel,
   re-enqueue or mutate historical records. Do not infer backlog types from counts.
4. Prefer waiting for active imports/retention to finish before stopping old
   consumers. Request graceful SIGTERM/SIGINT (Ctrl+C in a development terminal),
   delivered to Python, not just its shell wrapper. The existing 60-second
   graceful timeout remains: longer running jobs may be aborted by Procrastinate
   and need recovery. Do not call that business cancellation or promise an
   unlimited drain. Allow the supervisor time to complete cleanup; verify exit.
5. Stop ALL old public-app workers/periodic producers before activating the new
   release. Mixed-version rollout is unsupported: old producers route new tasks
   to the old queue and old heartbeat code could corrupt readiness classification.
   Start control and maintenance as independent services, then execution with
   the reviewed D3.2 slot setting (default 2). Verify startup recovery, the
   connection-budget log fields and all code fingerprints.
6. Persisted jobs keep their stored queue and exact task identity; decorator
   changes affect only future deferrals. The execution consumer retains all task
   registrations and therefore drains legacy maintenance/control jobs on
   `product-import`, including future scheduled retries, without orphaning them.
   Meanwhile NEW control tasks have independent capacity. Keep admission paused
   until no legacy maintenance/control TODO/DOING jobs remain on execution,
   including future-dated retries. If waiting is unacceptable, queue relocation
   needs a separately approved operation; this change does not perform one.
7. Reopen admission only after legacy drain, positive execution readiness, fresh
   control-health output, live maintenance service and independently accepted
   capacity/recovery gates. Queue-slot isolation is then effective; it does not
   guarantee zero PostgreSQL resource contention or cross-tenant import fairness.
8. Rollback: pause admission, stop new producers/consumers gracefully and inspect
   all THREE queues. A pre-D3 binary must not be deployed while new-queue jobs
   remain without consumers. Drain them using this compatible release first
   (including scheduled retries), then stop and recheck before reverting. If
   complete drain is impossible, retain the compatible consumers and request a
   reviewed rollback/migration procedure. Never delete jobs to permit rollback.

Keep checkouts immutable while workers run. Restart/reverify every role after a
code change. Process supervision, not queue tasks, must restart a dead control
worker; it cannot recover itself while absent.

## Terminal Procrastinate history retention — separate approval boundary

`delete_jobs="never"` remains in place. Business source/detail/lineage retention
does not prune `public.procrastinate_jobs`, events or periodic-deferral history.
No historical queue records are deleted by D3.1. A permanent policy needs owner
approval for evidence age/archival, failed-job preservation, bounded deletion,
FK cascades and periodic scheduling history. Any needed indexes/schema changes
require a separate migration. Do not reuse the operational `worker_queue`
cleanup blindly or add ad-hoc DELETE/VACUUM/REINDEX.

## Release verification

Before deployment run at minimum:

```powershell
python scripts/gate_product_import_architecture.py
python scripts/gate_product_import_d31_event_scheduler.py
python scripts/gate_product_import_d32_resources.py
python scripts/gate_product_import_phase17_final.py
python scripts/gate_product_import_phase18_cleanup.py
python -m unittest discover -s tests -p "test_product_import*.py"
```

On an isolated/local PostgreSQL release database, also run the opt-in D3.1
concurrency/RLS contract:

```powershell
$env:WANASAH_D31_SCHEDULER_DB_GATE="1"
python -m unittest tests.test_product_import_d31_schedule_candidates_db
```

Run the D3.2 mixed short/long concurrency gate only on the guarded disposable
PostgreSQL runner:

```powershell
$env:WANASAH_D32_LOCAL_GATE="1"
$env:WANASAH_D32_SOURCE_ENV_FILE=(Resolve-Path ".\.env").Path
python -m scripts.run_product_import_d32_isolated_gate
```

It must prove independent-company overlap, same-company serialization,
short-job fairness, bounded interactive-read p95/WAL, the full three-role
connection envelope, and that the original developer tenant remains unchanged.

Run D4 recovery acceptance only through its guarded disposable PostgreSQL runner:

```powershell
$env:WANASAH_D4_LOCAL_GATE="1"
$env:WANASAH_D4_SOURCE_ENV_FILE=(Resolve-Path ".\.env").Path
python -m scripts.run_product_import_d4_isolated_gate
```

It must prove orphaned business-job delivery reconciliation, staging cancellation,
hard worker crash/retry, source cleanup, and exact Product/Price/Audit/Outbox
non-duplication. Never simulate these failures against a production/customer
database.

Also run the Dashboard production build because Product Import contracts and
polling/realtime behavior are consumed by the Dashboard.

## Canonical supporting documents

- `ARCHITECTURE.md` — platform/module constitution.
- `domains/simple_products/imports/README.md` — Product Import module contract.
- `domains/simple_products/imports/PHASE13_RUNTIME.md` — runtime/concurrency.
- `domains/simple_products/imports/PHASE15_DATABASE.md` — database/index health.
- `PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md` — completed hardening plan.

## WebSocket authentication and logging (D5)
Product Import's exact-job realtime endpoint no longer accepts access tokens in
URLs. Browser clients connect with a query-free URL, send a short-lived access JWT
in the first frame, and retain HTTP polling until `WS_AUTHENTICATED` arrives.
See `docs/operations/WEBSOCKET_SECURITY_D5.md` for shared dispatch/import auth,
Origin, incident response, proxy logging and release verification. Never log
token-bearing query strings at reverse proxies, CDNs or gateways.


## Phase 19.3: inline rejected-row correction contract

This is an additive transport adapter for the existing same-job correction
authority. The file `GET/POST /simple-products/imports/{job_id}/correction`
and diagnostic `/errors` contracts are unchanged. Both new endpoints require
the same **catalog.manage + catalog.publish + pricing.manage** permissions as
file correction; company/job lookup precedes reading mutation input.

### Read a page

`GET /simple-products/imports/{job_id}/correction/rows?after_row=0&limit=50`

- `after_row`: exclusive **original physical Excel/source row number**, >= 0.
- `limit`: default 50, 1..100. This is a transport budget, not a maximum
  rejected-row count or a business rule. No total-count scan is performed.
- Optional `expected_job_version` pins subsequent pages/drafts to the first
  page's `job_version`; a changed job returns 409
  `PRODUCT_IMPORT_CORRECTION_STALE_JOB`.
- Rows are ordered by physical row number, only `INVALID`/`IMPORT_FAILED`.
  `IMPORTED` and other successful/pending rows are not listed.
- Response:

```json
{
  "job_id": "00000000-0000-4000-8000-000000000001",
  "job_version": 7,
  "status": "COMPLETED_WITH_ERRORS",
  "fields": ["name", "unit_price", "unit_barcode"],
  "items": [{
    "row_identity": "00000000-0000-4000-8000-000000000002",
    "row_number": 23,
    "version": 3,
    "status": "INVALID",
    "values": {"name": "", "unit_price": "1.50", "unit_barcode": "000123"},
    "errors": [{
      "row_number": 23,
      "code": "IMPORT_NAME_REQUIRED",
      "field": "name",
      "message": "Product name is required."
    }],
    "editable": true,
    "unavailable_reason": null
  }],
  "next_after_row": null
}
```

`fields` and `values` use canonical language-neutral names for **mapped**
source cells only. Values retain stored scalar types (string/number/boolean/null).
Unmapped source columns, source-cell metadata, normalized data and persisted
technical error messages are never exposed. Error code/field and regenerated
safe fallback text use existing import error authority; the list currently has
one recorded error and is **not exhaustive**. Revalidation can reveal another
error. Frontend localization uses code/field, not message matching.

`editable=false` and `unavailable_reason` explicitly distinguish:
`ROW_DETAILS_EXPIRED`, `JOB_NOT_CORRECTABLE`, `MAPPING_UNAVAILABLE`,
`ROW_VALUES_TOO_LARGE`. Expired/oversized values are `{}`; never interpret
these as original empty cells. Expiry uses the existing full-row-detail policy
(currently 30 days from terminal `finished_at`) even before cleanup runs, as
well as the stored `compacted_at` marker. A deleted lineage row is no longer listed;
retention does not reconstruct source values.

The projected values for one row are limited to **64 KiB in PostgreSQL before
transfer**. Oversized values are withheld, never truncated. The entire page is
bounded to **256 KiB UTF-8 JSON**, possibly returning fewer than `limit` items.
Use `next_after_row` until null; never infer end from a short page. At most 101
small row projections enter Python. Existing correction-file flow remains the
alternative for large rows and large error sets where retained details exist.

### Save literal edited cells

`POST /simple-products/imports/{job_id}/correction/rows`,
`Content-Type: application/json`:

```json
{
  "request_id": "00000000-0000-4000-8000-000000000003",
  "expected_job_version": 7,
  "rows": [{
    "row_identity": "00000000-0000-4000-8000-000000000002",
    "expected_version": 3,
    "values": {"name": "Corrected name", "unit_barcode": "000123"}
  }]
}
```

- 1..100 distinct row identities, total request body <= 256 KiB.
- `values` is a nonempty subset of mapped canonical fields. Edited values are
  **literal text or null**, never numbers/objects/formula metadata. Send barcode
  text to preserve leading zeros; blank/null retains existing normalization
  behavior. Omitted cells are unchanged. No row number, company id, product id,
  normalized data, mapping or metadata fields may be supplied.
- `expected_version` and `expected_job_version` are positive integers.
  Every target must belong to the authorized job/company, be a rejected row,
  retain original details, and match its version. The entire save fails if any
  target fails; there is no partial batch acceptance.
- Generate one `request_id` per logical save and persist it together with the
  exact body under company/user/job scope. On timeout/disconnect/503, replay
  **the same body/id**, including old expected versions. Do not invent a new id.
  The existing `PRODUCT_IMPORT_CORRECTION` operation table/advisory lock owns
  replay; canonical intent hash includes job, versions and edited cells.
  Completed replay is checked before mutable job state, row state or retention.
  Actor or changed-content reuse fails closed.
- 202 ACK:

```json
{
  "job_id": "00000000-0000-4000-8000-000000000001",
  "status": "VALIDATING",
  "corrected_rows": 1,
  "replayed": false,
  "message": "Correction accepted for revalidation."
}
```

202 is **queue acceptance**, not successful Product creation. Resume the existing
job watcher. Wait for the next correctable terminal state before another save,
then refresh pages/versions. The same job id and physical row identities remain.
Only edited rejected rows become STAGED; existing validation/execution and
Product/Pricing/UOM/Tracking authority process them. Already imported Products
remain immutable and are not reimported.

### Error contract and concurrency

In the deployed application, errors use the existing canonical envelope:
`{message, request_id, error: {code, message, context, request_id}}`.
Read `error.code`, `error.context.correlation_id` and `error.request_id`.
The router supplies safe structured HTTPException detail; the existing central
handler converts it to this envelope. Framework query/path errors have code
`VALIDATION_ERROR`, with safe `error.context.field/type` and request id.
Authentication/permission failures continue through that same handler.

| HTTP | Code | Frontend action |
| --- | --- | --- |
| 404 | PRODUCT_IMPORT_NOT_FOUND | Job unavailable in current company |
| 409 | PRODUCT_IMPORT_CORRECTION_STALE_JOB / PRODUCT_IMPORT_CORRECTION_STALE_ROW | Keep draft; refresh and reconcile versions |
| 409 | PRODUCT_IMPORT_CORRECTION_ROW_NOT_EDITABLE | Do not edit successful/unknown/pending targets |
| 409 | PRODUCT_IMPORT_CORRECTION_REQUEST_REUSED | Preserve original request identity/body; reject changed retry |
| 409 | PRODUCT_IMPORT_CORRECTION_CONFLICT | Refresh current job state |
| 410 | PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED | Disable editing; details cannot be recovered by this API |
| 422 | PRODUCT_IMPORT_CORRECTION_FIELD_INVALID | Only mapped canonical fields may be sent |
| 422 | PRODUCT_IMPORT_CORRECTION_ROWS_INVALID | Fix request shape/duplicates/literal values |
| 413 | PRODUCT_IMPORT_CORRECTION_PAYLOAD_TOO_LARGE | Save fewer edited rows |
| 415 | PRODUCT_IMPORT_CORRECTION_CONTENT_TYPE_INVALID | Send JSON |
| 503 | PRODUCT_IMPORT_QUEUE_UNAVAILABLE | Outcome may be unknown; replay the same body/id |

Lock order is unchanged: tenant context -> durable correction idempotency ->
job FOR UPDATE -> target rows in physical order -> row/job update -> queue
defer -> idempotency completion, all within one PostgreSQL transaction. The
short page read holds a job FOR SHARE lock to keep mapping/status/version stable.
Target row locks and a version/retention predicate protect against concurrent
compaction. SQL merges edited source cells and removes source metadata **only
for explicitly edited cells** (they are now literal input); untouched cells,
unmapped columns and metadata are preserved. SourceStore bytes are unchanged.

No new validation engine, Product/Pricing write path, source upload, idempotency
store, migration, worker launcher or business transition was introduced.
The existing correction operation record captures actor/input hash and replay
response; downstream Product/Pricing audit/outbox remain existing authorities.
Existing application admission/rate limiting is not replaced by this adapter.

Focused acceptance: run only `tests.test_product_import_inline_correction`.
Its in-process HTTP/persistence doubles verify contracts, safe failures, bounds,
version/retention rejection and authority/replay ordering, without a live DB or
worker. Real PostgreSQL FORCE RLS, transaction rollback/lock races, queue-to-worker
completion and authenticated deployed HTTP remain release acceptance work; do
not label them PASS from these focused tests.


## Phase 19.5 single source-only V1 import gate (no PostgreSQL)

From the repository root on the existing **Windows development machine**:


```powershell
& .\wa_backend\scripts\run_product_import_v1_source_gate.ps1
```

This runs one bounded package of pre-existing real parser/source-semantics,
inline/file correction, staging SQL isolation, immutable/idempotent correction,
small/mixed synthetic fixture, and Dashboard error/draft/cancel/locale tests,
then the TypeScript type-check, targeted ESLint and **production Vite build**.
Only the explicitly named Phase 8 no-DB classes are selected: its sibling
integration class would write to a database and is NOT included.

The runner sets deliberately unreachable synthetic loopback PostgreSQL/Redis
URLs in its process for the selected double-based tests and restores prior
environment variables afterwards. It never invokes a Worker launcher,
HTTP import, migration, real DB integration or 5k/50k job. A passing result
prints `P19_SOURCE_GATE=PASS` and
`P19_REAL_HTTP_POSTGRES_WORKER_BROWSER_50K=OPEN`. If a selected
test/build step fails it stops immediately; do not misreport a partial
step as an overall PASS.

**Closure boundary:** this command can establish one repeatable **code-only**
gate independent of Codex's staging recovery and the eventual rehearsal
environment. It cannot prove browser keyboard/mobile/screen-reader behavior,
authenticated tenant/RLS isolation, network replay, PostgreSQL/Worker
commit/rollback, resource-pressure/cancel recovery, or 50,000-row throughput.
Those remain the original Phase 19.1, 19.2, 19.4–19.5 OPEN acceptance
items until observed against the owner-authorized synthetic rehearsal
tenant. The separate first-customer D7-P/D8-P release runbook remains OPEN.


## Phase 19: live HTTP plus PostgreSQL/Worker on a disposable Windows cluster

From wa_backend on the reviewed checkout run these PowerShell commands:

    $env:WANASAH_P19_HTTP_LOCAL_GATE = "1"
    $env:WANASAH_P19_HTTP_SOURCE_ENV_FILE = (Resolve-Path ".\.env").Path
    .\venv\Scripts\python.exe -m scripts.run_product_import_phase19_http_isolated_gate

This is real signed-bearer HTTP on 127.0.0.1:18046, a real isolated
PostgreSQL 16 instance on 127.0.0.1:55446, and all three dedicated
execution/control/maintenance workers. The parent REFUSES a different source
DB, occupied ports, or a nonempty synthetic tenant. It copies only the
preapproved EMPTY developer tenant-2 fixture, creates tenant-3 solely inside
the new disposable cluster, and never starts recovery on the developer DB.
Existing developer DB historical jobs are explicitly NOT available for
this rehearsal. Backend Alembic HEAD is checked and migrations applied
only to the disposable cluster. After exit, it verifies the source synthetic
tenant is unchanged and removes its dedicated workers/API/DB/logs.

On Windows a dedicated isolated Uvicorn entrypoint uses SelectorEventLoop:
default ProactorEventLoop is incompatible with the application's async
Psycopg queue connector. Production API sources are not rewritten.

Test coverage: small same-job signed real HTTP imports and inline correction;
official server-generated CSV and XLSX correction artifacts with unchanged
identity metadata; actual HTTP/worker replay with the exact request ID and
body after an intentionally dropped TCP response; persisted actor-role
403 and cross-tenant 404; forged/preimported-row 409; physical row numbers;
immutable previously successful Product/Variant/row versions, pricing
publication IDs and active barcodes; and unique Variant/Pricing/Audit/Outbox
readback. A separate 1-row case tests a *second new validation error*
after the first is fixed. This is NOT browser/mobile/RTL/manual acceptance,
an intentionally induced 120s ClientRead timeout, a medium/50k performance
measurement, or first-customer D7-P/D8-P signoff.
