# Wanasah Background Workers — Production Runbook

## Architecture

- Queue metadata lives in PostgreSQL schema `worker_queue`.
- Tenant business tables remain in `public` with PostgreSQL RLS + FORCE RLS.
- Every tenant task carries an explicit `company_id`.
- Tenant database access must go through `workers.tenant.tenant_session(company_id)`.
- `maintenance`: operational monitors and integrity jobs.
- `notifications`: notification delivery.
- `reports`: heavy read-only reporting.

## Production safety contracts

- Workers monitor/alert/report by default. They do not close work sessions, settle custody,
  mutate inventory, cancel business operations, or alter workflow unless explicitly approved.
- Stalled-job automatic retry is allowlisted to known safe/idempotent worker tasks only.
- Report transactions use PostgreSQL `READ ONLY`.
- SystemAuditLog is append-only at PostgreSQL level.
- Same-company monitor scans acquire PostgreSQL transaction advisory locks.

## Periodic scheduling

- stale handshake scan: every 5 minutes
- stale work-session scan: every 15 minutes
- integrity scan: hourly at minute 7
- safe stalled-job recovery: every 10 minutes
- worker-history retention cleanup: daily at 04:13
- Live Stock due-transition scan: every 15 minutes (minute 2/17/32/47)

Scheduling is handled by Procrastinate workers and PostgreSQL. At least one worker must run
for periodic jobs to be deferred.

## Root commands

PowerShell development shell:

```powershell
$env:PYTHONPATH = "$PWD\wa_backend"
```

Bootstrap / health:

```powershell
python -m workers.bootstrap
python -m procrastinate --app=workers.app.app schema --apply
python -m procrastinate --app=workers.app.app healthchecks
```

Operational worker:

```powershell
python -m procrastinate -v --app=workers.app.app worker -q maintenance,notifications -c 4
```

Reports worker:

```powershell
python -m procrastinate -v --app=workers.app.app worker -q reports -c 1
```

## Deployment

Run API, operational worker, and reports worker as separate supervised processes.
Production workers should run on a Unix-like host/container. Windows is for development.
Keep `delete_jobs=never`; scheduled retention removes finished jobs older than 30 days.

## Final Alembic baseline

The baseline must explicitly preserve:
- RLS + FORCE RLS policies
- SystemAuditLog append-only trigger and runtime-role privilege revocations
- worker_queue Procrastinate schema/migrations
