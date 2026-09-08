# Wanasah Background Workers

## Architecture

- Procrastinate stores queue metadata in PostgreSQL schema `worker_queue`.
- Tenant/business tables remain in `public` and stay protected by existing RLS.
- Every tenant task must receive an explicit `company_id` and open DB work through
  `workers.tenant.tenant_session(company_id)`.
- Queue connections use `search_path=worker_queue`, separating queue SQL from tenant SQL.
- Queues:
  - `maintenance`: short operational/integrity jobs.
  - `notifications`: alert delivery jobs.
  - `reports`: heavy analytical jobs; run on a dedicated worker later.

## Bootstrap

Run from `wa_backend`:

```powershell
python -m workers.bootstrap
python -m procrastinate --app=workers.app.app schema --apply
python -m procrastinate --app=workers.app.app healthchecks
```

## Run workers

```powershell
python -m procrastinate --app=workers.app.app worker maintenance notifications
```

Heavy reports worker later:

```powershell
python -m procrastinate --app=workers.app.app worker reports
```

## Scheduling policy

Critical periodic scheduling is intentionally not coupled to Procrastinate's built-in
`@app.periodic` yet. A deployment scheduler (cron/systemd/Kubernetes/platform scheduler)
will enqueue one idempotent scan job at the required interval; queueing locks will prevent
duplicate scans.



## Heavy Reports Foundation (V1)

### Queue isolation

- `maintenance`: operational monitors and integrity scans.
- `notifications`: notification work.
- `reports`: heavy/read-only reporting only.
- Every business/report job must carry an explicit `company_id`.
- Report tasks must enter through `tenant_session(company_id)`.
- Report business queries must remain read-only. V1 additionally uses PostgreSQL
  `SET TRANSACTION READ ONLY` inside report transactions.

### Official root commands

Run these from the repository root.

PowerShell environment for each new terminal:

```powershell
$env:PYTHONPATH = "$PWD\wa_backend"
```

Operational worker:

```powershell
python -m procrastinate -v --app=workers.app.app worker -q maintenance,notifications -c 4
```

Heavy reports worker:

```powershell
python -m procrastinate -v --app=workers.app.app worker -q reports -c 1
```

Health check:

```powershell
python -m procrastinate --app=workers.app.app healthchecks
```

`reports` starts at concurrency `1` deliberately so heavy reads cannot saturate
PostgreSQL alongside operational jobs. Increase it only after measured production
load proves the database has headroom.

The API process, operational worker, and reports worker are separate processes.
They may initially run on the same server; physical host separation is not required.
