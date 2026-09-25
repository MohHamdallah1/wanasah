# Development workers

This document is the canonical development runbook for background workers.

## Normal full development runtime

A normal runtime that exercises background maintenance uses separate long-running processes:

1. Backend API.
2. Dashboard.
3. Operational worker — required for periodic maintenance and notification jobs.

From the repository root, start the operational worker in its own PowerShell terminal:

```powershell
.\ops\development\run_operational_worker.ps1
```

The script deliberately uses the backend virtual environment directly and starts:

```text
workers.app.app
queues: maintenance,notifications
```

Do not replace this with the product-import worker. The product-import queue uses a different Procrastinate app and does not own the operational periodic tasks.

The operational worker imports the maintenance task set, including the Live Stock time-transition scan. Procrastinate's periodic deferrer is therefore expected to run with this worker.

## Optional workers

Reports can be isolated in a separate terminal when report jobs are being exercised:

```powershell
cd wa_backend
.\venv\Scripts\python.exe -m procrastinate --app=workers.app.app worker -q reports
```

Product import uses its own worker app:

```powershell
cd wa_backend
.\venv\Scripts\python.exe -m procrastinate --app=product_import_queue.app worker -q product-import
```

One worker can listen to multiple queues. A terminal is not required per task; the operational worker intentionally listens to both `maintenance` and `notifications`.

## Isolation boundary

The queue infrastructure uses the dedicated `worker_queue` schema. Tenant-specific jobs must still establish their company context through the worker task/session authority before accessing tenant tables. Starting the worker never bypasses tenant RLS or warehouse authorization.

This runbook only fixes the development startup contract. Production process supervision, restart policy, health checks, and deployment topology are finalized with the production deployment environment.
