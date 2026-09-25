# Worker Foundation Audit — 2026-09-26

Scope: worker foundation only. This audit does not change business workflows or product semantics.

## Closed contracts

- [x] **Permanent tooling layout:** development launchers live under `ops/development/`; executable gates remain under `wa_backend/scripts/`.
- [x] **Company isolation:** tenant jobs establish both application `tenant_context` and PostgreSQL `app.current_tenant` before tenant queries.
- [x] **Connection cleanup:** tenant state is cleared before pooled connections are returned; failed cleanup invalidates the connection.
- [x] **Warehouse isolation:** a tenant worker cannot read or update another company's warehouse, and a foreign warehouse ID cannot make Live Stock maintenance cross the tenant boundary.
- [x] **Database locking:** same company + same worker namespace is serialized with transaction advisory locks; different companies/namespaces remain independent.
- [x] **Duplicate scheduling:** company jobs are not repeatedly deferred while an equivalent `todo` or `doing` job already exists.
- [x] **Recovery-compatible dedupe:** child jobs use execution locks without retry-hostile queueing locks; queued-successor collisions are handled explicitly for periodic jobs.
- [x] **Bounded tenant discovery:** global scans keyset-page active companies in bounded batches instead of loading all tenants at once.
- [x] **Heartbeat contract:** worker heartbeat is 10 seconds and stalled-worker timeout is 30 seconds.
- [x] **Allowlisted retry:** only explicitly safe/idempotent worker tasks are automatically retried after process failure.
- [x] **Startup recovery:** operational, reports, and product-import launchers recover safe stalled jobs before entering the long-running worker process.
- [x] **Periodic recovery:** operational recovery runs every 10 minutes; reports recovery runs every 10 minutes on the reports queue; product-import recovery runs every 5 minutes while workers are alive.
- [x] **Worker-process failure:** a stalled safe operational job is returned to `todo`; a non-allowlisted stalled job is failed closed to `failed` for explicit operator review.
- [x] **Queued-successor recovery:** if a stalled periodic job already has a queued successor with the same queueing lock, the stale predecessor is failed and the successor is preserved.
- [x] **Product-import crash recovery:** the separate product-import Procrastinate app recovers a stalled `process_product_import` job.
- [x] **Product-import atomicity:** its queue metadata remains explicitly in `public` so the durable import record and queue defer can share one PostgreSQL transaction.
- [x] **Reports safety:** report work remains tenant-scoped and PostgreSQL `READ ONLY`, with dedicated startup and periodic recovery.
- [x] **Live Stock fail-closed behavior:** a maintenance exception marks the affected company projection `DEGRADED` without degrading another company.
- [x] **Live Stock recovery:** a subsequent healthy maintenance pass reconciles `DEGRADED` back to `READY`.
- [x] **Scheduling:** stale handshakes, stale sessions, integrity, Live Stock transitions, operational/report/product-import stalled recovery, and cleanup retain explicit periodic schedules.
- [x] **Current notification topology:** `notifications` is wired into the operational process but currently has no registered delivery task; this is documented rather than implied otherwise.
- [x] **Queue health:** both the operational/report app and product-import app pass Procrastinate configuration, database, and schema healthchecks.

## Evidence

- `DEV_OPERATIONAL_WORKER_GATE=PASS` — 9 checks.
- `WORKER_FOUNDATION_STATIC_GATE=PASS` — 20 checks.
- `WORKER_FOUNDATION_RUNTIME_GATE=PASS` — 16 checks.
- `STAGE821_LIVE_STOCK_PROJECTOR_RUNTIME_GATE=PASS` — 17 checks.
- `STAGE823_LIVE_STOCK_READ_MODEL_GATE=PASS` — 15 checks.
- `PRODUCT_IMPORT_TRACKING_GATE=PASS` — 20 checks.
- `STAGE73_PRODUCT_UX_I18N_NETWORK_GATE=PASS` — 18 checks.
- `STAGE7_SIMPLE_PRODUCTS_GATE=PASS` — 38 checks.
- Operational, reports, and product-import startup recovery commands all completed successfully.
- Procrastinate healthchecks passed for both queue apps.

## Development commands

Operational worker, required for full development background maintenance:

```powershell
.\ops\development\run_operational_worker.ps1
```

Reports worker, when report jobs are being exercised:

```powershell
.\ops\development\run_reports_worker.ps1
```

Product-import worker, when asynchronous imports are being exercised:

```powershell
.\ops\development\run_product_import_worker.ps1
```

The launchers are authoritative. Do not additionally run their underlying Procrastinate worker commands in another terminal.
