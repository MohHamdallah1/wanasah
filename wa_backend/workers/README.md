# Wanasah Background Workers — Production Runbook

## Architecture

- Operational/report queue metadata lives in PostgreSQL schema `worker_queue`.
- Product-import queue metadata intentionally lives in `public` so the import business row and queue defer can commit atomically on one connection.
- Tenant business tables remain in `public` with PostgreSQL RLS + FORCE RLS.
- Every tenant task carries an explicit `company_id`.
- Tenant database access goes through `workers.tenant.tenant_session(company_id)`.
- `maintenance`: operational monitors, Live Stock maintenance, recovery, and integrity jobs.
- `notifications`: reserved operational queue; no notification-delivery tasks are registered yet.
- `reports`: heavy read-only reporting.
- `product-import`: separate Procrastinate app for durable product imports.

## Production safety contracts

- Workers do not gain tenant or warehouse authority by running in the background.
- Tenant sessions establish and clear PostgreSQL tenant state fail-closed.
- Company child tasks use transaction advisory locks for same-company serialization where required.
- Global tenant discovery is bounded/keyset-paginated and skips inactive companies.
- Duplicate company child backlog is bounded before defer using active `todo`/`doing` lock state.
- Stalled-job retry is allowlisted to known safe/idempotent tasks only; non-allowlisted stalled jobs fail closed to `failed` for explicit review.
- Worker heartbeat is 10 seconds; stalled timeout is 30 seconds.
- Recovery is available both at process startup and periodically while workers are alive.
- Report transactions use PostgreSQL `READ ONLY`.
- SystemAuditLog remains append-only at PostgreSQL level.
- Live Stock maintenance marks projection `DEGRADED` on failure and reconciles it before returning to `READY`.

## Periodic scheduling

- stale handshake scan: every 5 minutes;
- stale work-session scan: every 15 minutes;
- integrity scan: hourly at minute 7;
- safe operational stalled-job recovery: every 10 minutes;
- worker-history retention cleanup: daily at 04:13;
- Live Stock due-transition scan: every 15 minutes at 2/17/32/47;
- report stalled-job recovery: every 10 minutes;
- product-import stalled-job recovery: every 5 minutes.

Scheduling is handled by Procrastinate and PostgreSQL. Production still requires process supervision so a terminated worker process is restarted.

## Development launchers

From repository root:

```powershell
.\ops\development\run_operational_worker.ps1
```

Optional reports:

```powershell
.\ops\development\run_reports_worker.ps1
```

Optional product import:

```powershell
.\ops\development\run_product_import_worker.ps1
```

Each launcher performs the appropriate startup recovery before entering the long-running worker process.

## Queue bootstrap / health

From `wa_backend` with the backend virtual environment:

```powershell
python -m workers.bootstrap
python -m procrastinate --app=workers.app.app schema --apply
python -m procrastinate --app=workers.app.app healthchecks
```

## Deployment

Run API, operational worker, and report worker as separate supervised processes when those roles are required. Run product-import separately when asynchronous imports are enabled.

Production workers should run on a Unix-like host/container. Windows remains a development environment. Keep completed job retention bounded through the scheduled cleanup task.

## Final Alembic baseline

The baseline must preserve:

- RLS + FORCE RLS policies;
- SystemAuditLog append-only trigger and runtime-role privilege revocations;
- `worker_queue` Procrastinate schema/migrations;
- the explicit product-import public-schema atomic queue contract.
