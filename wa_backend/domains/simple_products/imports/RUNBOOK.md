# Product Import V1 Operational Runbook

## Canonical worker launch

Run from PowerShell:

```powershell
cd wa_backend
.\scripts\run_product_import_worker.ps1
```

The launcher imports `domains.simple_products.imports.infrastructure.queue.app`,
listens only to the `product-import` queue, and uses
`PRODUCT_IMPORT_WORKER_SLOTS_PER_PROCESS` as the worker concurrency (default `1`).
The runtime monitor uses the same value for capacity calculations; keep the two
values aligned.

Do not launch Product Import through a root-level compatibility module.

## Health and readiness

- Authenticated readiness: `GET /simple-products/import-worker/readiness`.
- `READY` requires a live worker that has proven it consumes the Product Import
  queue through the queue-local heartbeat registry.
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

1. Do not manually mutate Product Import row/job states.
2. Check readiness and queue-age/stuck-stage telemetry.
3. Restore database/worker availability.
4. Let Procrastinate retry transient jobs and stalled safe deliveries.
5. Replaying the same durable job is safe; imported rows are not replayed.
6. If the job is terminal, use the supported Retry/Correction flows rather than
   editing staging rows directly.

## Release verification

Before deployment run at minimum:

```powershell
python scripts/gate_product_import_architecture.py
python scripts/gate_product_import_phase17_final.py
python scripts/gate_product_import_phase18_cleanup.py
python -m unittest discover -s tests -p "test_product_import*.py"
```

Also run the Dashboard production build because Product Import contracts and
polling/realtime behavior are consumed by the Dashboard.

## Canonical supporting documents

- `ARCHITECTURE.md` — platform/module constitution.
- `domains/simple_products/imports/README.md` — Product Import module contract.
- `domains/simple_products/imports/PHASE13_RUNTIME.md` — runtime/concurrency.
- `domains/simple_products/imports/PHASE15_DATABASE.md` — database/index health.
- `PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md` — completed hardening plan.
