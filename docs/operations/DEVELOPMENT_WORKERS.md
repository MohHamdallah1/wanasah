# Development workers

This document is the canonical development runbook for Wanasah background workers.

## Normal full development runtime

A normal development runtime that exercises operational background work uses separate long-running processes:

1. Backend API.
2. Dashboard.
3. Operational worker — required for periodic maintenance.

From the repository root, start the operational worker in its own PowerShell terminal:

```powershell
.\ops\development\run_operational_worker.ps1
```

The launcher uses the backend virtual environment directly, runs safe stalled-job recovery first, then starts:

```text
app: workers.app.app
queues: maintenance,notifications
```

Do not also run the equivalent long Procrastinate command manually. The launcher is the development authority.

### What the operational worker currently executes

- `maintenance`: stale-handshake monitoring, stale-session monitoring, integrity checks, Live Stock time transitions, safe stalled-job recovery, cleanup, and health work.
- `notifications`: reserved queue wiring. There are currently no registered notification-delivery tasks on this queue.

The worker intentionally listens to both queues so notification tasks can be added later without changing the operational process contract.

## Optional workers

### Reports

When report jobs are being exercised, run the reports worker in its own terminal:

```powershell
.\ops\development\run_reports_worker.ps1
```

It runs report-only startup recovery, then listens to:

```text
app: workers.app.app
queue: reports
```

Report transactions remain PostgreSQL `READ ONLY`.

### Product import

When asynchronous product imports are being exercised, run:

```powershell
.\ops\development\run_product_import_worker.ps1
```

It runs product-import startup recovery, then listens to:

```text
app: product_import_queue.app
queue: product-import
```

Product import is deliberately a separate Procrastinate app. Its queue metadata remains in the `public` schema because enqueueing the durable import record and its queue job share one PostgreSQL transaction. This preserves atomicity between `product_import_jobs` and the queue entry.

## Queue and tenant isolation

The operational/report queue infrastructure uses the dedicated `worker_queue` schema. Product-import queue metadata is the explicit atomicity exception described above.

Tenant-specific operational work must:

- carry an explicit `company_id`;
- enter through `workers.tenant.tenant_session(company_id)`;
- establish `tenant_context` and PostgreSQL `app.current_tenant` before tenant queries;
- clear tenant state before returning a connection to the pool;
- use company-scoped database advisory locks when same-company execution must serialize.

A tenant-scoped worker never gains warehouse authority merely because it runs in the background. RLS and explicit company/location predicates remain authoritative.

## Scheduling and duplicate control

Global periodic scans use Procrastinate global locks and queueing locks. Company discovery is keyset-paginated and limited to active companies.

Company child jobs use a stable company execution lock. Before defer, the scheduler checks the bounded company page for existing `todo` or `doing` jobs using the same lock. This prevents unbounded duplicate backlog while keeping stalled-job retry compatible with Procrastinate's queueing-lock uniqueness rules.

## Failure and recovery

Worker heartbeat is explicitly pinned to 10 seconds and a worker is considered stalled after 30 seconds.

Recovery is allowlisted. Unknown or non-idempotent stalled jobs are never replayed automatically; after the owning worker is confirmed dead they fail closed to `failed` for explicit operator review.

Recovery has two layers:

1. **Startup recovery** in every development launcher, covering total worker/process loss.
2. **Periodic recovery** while the operational/product-import worker is alive.

If a stalled periodic job already has a queued successor with the same queueing lock, recovery fails the stale predecessor and keeps the queued successor instead of causing a queueing-lock collision.

Live Stock maintenance fails closed: a refresh failure marks the company projection `DEGRADED`; a later successful maintenance pass reconciles it back to `READY`.

## Current schedules

- stale handshake scan: every 5 minutes;
- stale work-session scan: every 15 minutes;
- integrity scan: hourly at minute 7;
- operational stalled-job recovery: every 10 minutes;
- worker-history cleanup: daily at 04:13;
- Live Stock due-transition scan: minute 2/17/32/47;
- report stalled-job recovery: every 10 minutes;
- product-import stalled-job recovery: every 5 minutes.

Production process supervision/restart policy remains a deployment concern and will be bound to the selected production environment. The worker code and launch/recovery contracts here are environment-independent foundations.
