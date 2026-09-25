# Worker Foundation Audit — 2026-09-26

Status: CLOSED

Scope: worker foundation only. This audit did not authorize new business workflows.

## Completed controls

- [x] Company isolation remains fail-closed for background jobs.
  - Tenant jobs enter through `tenant_session(company_id)`.
  - `tenant_context` and PostgreSQL `app.current_tenant` are established before tenant queries.
  - Tenant state is cleared or the connection is invalidated before pool return.
  - Runtime proof: company A could read its warehouse but could neither read nor update company B's warehouse.

- [x] Warehouse/location isolation remains preserved.
  - Background execution does not grant implicit location authority.
  - Live Stock warehouse-scoped maintenance returned zero work when asked for another tenant's warehouse.
  - Existing backend/RLS location checks remain authoritative.

- [x] Same-company execution locks are safe.
  - PostgreSQL transaction advisory locks serialize the same `namespace + company_id`.
  - Different companies and different namespaces remain independently executable.

- [x] Duplicate worker backlog is bounded.
  - Global scans use one shared bounded scheduler.
  - Active companies are scanned with keyset pagination in pages of 1000.
  - Inactive companies are excluded.
  - Child defer checks existing `todo/doing` jobs by stable company lock before queueing.
  - Child jobs keep execution `lock` without a retry-hostile `queueing_lock`.

- [x] Retry policy is explicit and safe.
  - Product import retains bounded exception retry: maximum 4 attempts with exponential wait.
  - Crash recovery is allowlisted to known idempotent/safe tasks.
  - Unknown/non-idempotent stalled jobs are not replayed; after worker death they fail closed to `failed` for operator review.

- [x] Worker-process failure is detectable.
  - Worker heartbeat is explicitly 10 seconds.
  - Stalled-worker timeout is explicitly 30 seconds.
  - Recovery uses Procrastinate heartbeat state instead of elapsed-job guesses.

- [x] Recovery works after process loss.
  - Startup recovery runs before each development worker role starts.
  - Operational recovery is periodic every 10 minutes.
  - Report recovery is periodic every 10 minutes on the reports queue.
  - Product-import recovery is periodic every 5 minutes on its own app/queue.
  - A stalled periodic predecessor with a queued successor is failed and superseded safely instead of colliding on the queueing lock.
  - Runtime proof covered operational and product-import process-crash recovery.

- [x] Live Stock worker failure remains fail-closed and recoverable.
  - Refresh failure marks only the affected company projection `DEGRADED`.
  - Another company remains unchanged.
  - A later healthy maintenance pass reconciles the projection back to `READY`.

- [x] Scheduling is bounded and explicit.
  - stale handshake: every 5 minutes.
  - stale work session: every 15 minutes.
  - integrity: hourly at minute 7.
  - Live Stock transitions: minute 2/17/32/47.
  - operational stalled recovery: every 10 minutes.
  - reports stalled recovery: every 10 minutes.
  - product-import stalled recovery: every 5 minutes.
  - cleanup: daily at 04:13.

- [x] Worker roles have canonical development launchers.
  - `ops/development/run_operational_worker.ps1`
  - `ops/development/run_reports_worker.ps1`
  - `ops/development/run_product_import_worker.ps1`
  - Launchers run role-specific startup recovery before the long-running worker.

## Queue topology

- Operational and report jobs use Procrastinate schema `worker_queue`.
- Product import intentionally uses its own Procrastinate app in `public` so the queue defer and `product_import_jobs` mutation can share one PostgreSQL transaction. This is an explicit atomicity exception, not an accidental schema leak.
- `notifications` is currently reserved queue wiring; there are no registered notification-delivery tasks yet.

## Verification evidence

- `DEV_OPERATIONAL_WORKER_GATE=PASS` — 9 checks.
- `WORKER_FOUNDATION_STATIC_GATE=PASS` — 20 checks.
- `WORKER_FOUNDATION_RUNTIME_GATE=PASS` — 16 checks.
- `STAGE821_LIVE_STOCK_PROJECTOR_RUNTIME_GATE=PASS` — 17 checks.
- `STAGE823_LIVE_STOCK_READ_MODEL_GATE=PASS` — 15 checks.
- `PRODUCT_IMPORT_TRACKING_GATE=PASS` — 20 checks.
- `STAGE73_PRODUCT_UX_I18N_NETWORK_GATE=PASS` — 18 checks.
- `STAGE7_SIMPLE_PRODUCTS_GATE=PASS` — 38 checks.
- Operational startup recovery: clean.
- Reports startup recovery: clean.
- Product-import startup recovery: clean.
- Operational Procrastinate healthchecks: OK.
- Product-import Procrastinate healthchecks: OK.

## Production boundary

The worker foundation is hardened at application level. Process supervision in production remains deployment-specific: the selected production environment must run/restart the API and required worker roles as supervised services. No application code should assume that a human keeps terminals open in production.
