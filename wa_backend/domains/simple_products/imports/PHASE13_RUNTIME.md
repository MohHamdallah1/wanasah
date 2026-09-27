# Product Import Phase 13 runtime contract

## Company serialization decision

Product Import deliberately retains the Procrastinate lock
`product-import:{company_id}`.

This is not a generic performance shortcut. Import execution calls the existing
`create_products_and_prices` authority. That authority resolves or creates the
company-default PriceBook/assignment and publishes a PricePublication against
the shared PriceBook version. Two imports for the same company can therefore
race on one shared Pricing aggregate even when their source rows are unrelated.

Until the Pricing authority exposes a narrower concurrency contract that proves
parallel publication against the same default PriceBook safe, reducing the
Product Import lock would weaken existing Product/Pricing invariants. Imports
for different companies remain concurrent because the lock is company-scoped.

## Backpressure

Upload admission remains the durable backpressure authority. Active jobs are
counted per company across QUEUED, PARSING, NEEDS_MAPPING, VALIDATING,
IMPORTING and RETRYING. `PRODUCT_IMPORT_MAX_ACTIVE_JOBS_PER_TENANT` defaults
to 25. Admission is serialized with the existing tenant advisory lock so
concurrent requests cannot race past the limit.

## Progress transport

Product Import state remains authoritative in `product_import_jobs`.
The Phase 13 database trigger emits only coarse job-level progress/state
changes. PostgreSQL NOTIFY is transaction-aware, so rolled-back updates are
never announced. The relay coalesces bursts for 250 ms and keeps only the
latest version per company/job before broadcasting.

The WebSocket registry is keyed by authenticated `(company_id, job_id)`.
Subscription authorization verifies the authenticated tenant, the exact job,
and `catalog.read`; no client-supplied company identifier is trusted.
HTTP status remains the fallback and reconciliation authority.

## Worker observability

Global runtime telemetry records only Procrastinate workers that have proven
they consume the `product-import` queue. A queue-local heartbeat task registers
the worker id, and readiness joins that registry back to Procrastinate's live
worker heartbeat. This avoids treating an unrelated healthy worker as Product
Import-ready.

Metrics include healthy Product Import worker processes, configured worker
slots, running/queued Product Import jobs, available slots, and oldest queue
age. `PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS` must match the deployed worker
concurrency (default 1). These global values are for server observability only
and are not exposed as tenant data.

Tenant capacity telemetry also records oldest active-stage and oldest queued-job
age. Stuck-stage warnings use `PRODUCT_IMPORT_STUCK_STAGE_SECONDS` (default
900 seconds). Queue-age warnings use
`PRODUCT_IMPORT_QUEUE_AGE_ALERT_SECONDS` (default 120 seconds).

The authenticated readiness endpoint exposes only a safe READY/UNAVAILABLE
signal; it does not leak cross-tenant queue counts.

## Cancellation semantics

Cancellation transitions an active job to terminal `CANCELLED` while holding
the Product Import job row lock.

Validation and execution already hold that same row lock for every bounded
transaction (500 validation rows / 100 execution rows). A cancellation request
therefore waits for the current transaction to commit or roll back. The next
batch observes CANCELLED and stops. Product/Pricing creation, row outcome and
idempotency evidence remain in one transaction, so cancellation never cuts a
row batch in half.

If cancellation arrives during source staging, staging sees CANCELLED before
its commit and rolls the staging transaction back. The source is then cleaned
through the existing SourceStore lifecycle. Already committed imported rows are
retained as valid lineage; cancellation prevents only future row effects.
Duplicate delivery after cancellation is a no-op.
