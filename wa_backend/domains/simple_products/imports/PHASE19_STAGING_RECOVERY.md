# Phase 19.2 staging stall recovery

Date: 2026-10-01. Branch: `hardening/v1-import-phase19-staging-recovery-codex`.
Base: `a2031f0` (origin/main at branch creation; local main was not checked out).
Historical 50k driver root cause and real PostgreSQL acceptance: **OPEN**.

## Source diagnosis

`source_service.prepare_import_source` verifies immutable bytes, finishes the
parser into a disposable spool, then invokes one staging transaction.
`staging_service` deletes/reinserts staged rows, reconciles the actual count,
locks/transitions the job and commits before SourceStore cleanup.

At `repository.insert_staged_rows.flush`, each explicit 500-row multi-VALUES
statement awaited `AsyncSession.execute` without a staging deadline.
Rollback/close and the initial tenant query likewise had no staging deadline.
The shared engine bounds pool checkout, but that does not bound query/driver
waiting. The Windows launcher uses SelectorEventLoop for Psycopg compatibility;
changing loops or batch size again is not evidence of an asyncpg fix.

The existing Phase 19.2 historical evidence records an active INSERT / ClientRead
for >285 seconds, PARSING for ~477 seconds, and no committed rows. A server waiting
for client protocol data is consistent with a stalled transmission; it does NOT
independently prove which asyncpg/SQLAlchemy/Windows component caused it. No new
real incident was reproduced here. The proven defect fixed is indefinite
application waiting/recovery, not that historical driver defect.

## Implemented contract

- `infrastructure/staging_io.py` uses the existing engine/pool and public
  SQLAlchemy checkout event; capture precedes the existing RLS setup callback.
  ContextVar scope prevents other sessions/tenants from attaching to the guard.
  A checkout arriving after the deadline is terminated/rejected before tenant SQL.
  Checkin clears transport ownership through public pool-record info. A late
  cancellation after COMMIT cannot terminate a returned connection borrowed by
  another company; this ownership rule has a dedicated focused test.
- Each awaited staging DB step, including each 500-row INSERT, has **120 s**.
  Rollback/close/invalidation and cancellation drain have independent **10 s**
  budgets. These are operational wait budgets, not a whole-import SLA, row limit
  or proof of acceptable throughput. No total deadline rejects a progressing 50k.
  120 s is a conservative per-step watchdog above the recorded historical
  ~10.4 s whole-staging exercise and below the observed >285 s stuck wait;
  the current hardware/driver must validate this policy in the small rehearsal.
- On deadline or coroutine cancellation, terminate ONLY the captured, owned
  asyncpg transport through its synchronous public API, then cancel/drain the
  operation. Merely wrapping execute in wait_for would await driver cancellation
  and could itself hang. No pg_cancel_backend/pg_terminate_backend, worker kill,
  alternate connection pool, polling process or parallel measurement tool.
- The original STAGING_BATCH_BEGIN / STAGING_SQL markers remain the per-batch
  evidence. Source-safe ABORT records identify the operation and whether its
  transport was captured. PENDING explicitly reports failure to drain; it is
  never reported as rollback success. No cells, paths, SQL or parameters added.
- `PRODUCT_IMPORT_STAGING_TIMEOUT` is a retryable JOB/system error through the
  existing classifier and queue retry strategy (four attempts). Exhaustion uses
  the existing retryable FAILED/resume-status contract. Never fabricate row errors.
- One staging commit and the same-transaction row-count assertion remain.
  Pre-commit failure cannot clean SourceStore. Task cancellation propagates as
  CancelledError; tenant context and the disposable spool are released.
- A missing COMMIT acknowledgement is ambiguous: disconnect does not establish
  rollback of a commit that already reached PostgreSQL. Retry reads durable job
  state through the existing source/state authority. A committed VALIDATING/
  NEEDS_MAPPING job resumes without replacing row identities; retained-source
  cleanup is idempotent. No new status, idempotency table or business transition.
- Official cancellation still locks the scoped job through its existing service.
  A stuck INSERT can no longer hold that session indefinitely. Once the original
  transaction releases locks, CANCELLED remains terminal; runtime failure cannot
  overwrite it and a subsequent delivery performs existing cancelled-source
  cleanup. Actual HTTP lock-wait/cancellation readback remains unverified.

The client bound assumes a responsive event loop. Before pool checkout supplies
an owned transport (e.g. connection establishment/pre-ping), cancellation/drain
is bounded but physical pool/server release is not asserted. Late checkout is
rejected. Server lock release also depends on PostgreSQL observing disconnect.
PENDING / owned_connection=0 requires operational investigation, not a guessed
backend termination. Other services/SourceStore Psycopg waits are unchanged.

## Focused evidence actually executed

Windows SelectorEventLoop; Python 3.12.14, SQLAlchemy 2.0.40, asyncpg 0.29.0.
`tests.test_product_import_phase19_staging_integrity`: **10/10 PASS**, 0.765 s.
Five existing affected integrity/batch/redaction checks plus five new recovery
checks: cancel-channel stall, tenant setup/capture/context reset, timeout plus
stalled rollback, task cancellation retaining source, and lost-COMMIT-response
durable resume without restaging. The two-row synthetic CSV uses real parsing/
spooling and the real staging orchestration; DB/transport/SourceStore are doubles.
Test deadlines are 20–50 ms, cleanup 20 ms, outer guard 1 s.
After late-checkout rejection/hook-order verification, the affected five cases
passed in 0.236 s. After enforcing pool checkin ownership, only the six affected
recovery cases were run: **6/6 PASS**, 0.373 s. This is **11 distinct checks**,
not a second full suite or live database gate.
No live SQL connection was permitted; dotenv and bytecode writes were disabled.
These measurements are test wall times, not PostgreSQL or import throughput.

## Acceptance still OPEN / before the final 50k

D7S has no backend .env/.env.test/venv or DATABASE_URL/DATABASE_URL_TEST.
Read-only process inspection found PostgreSQL/API processes but no identified
D7S/import worker. No database isolation, runtime role, synthetic tenant or worker
configuration was established. No source payload/user workbook was opened, no
live write, migration, worker launch/restart or medium/50k workload was performed.

Provide an owner-approved development scope and current canonical execution/
control workers. First run a small synthetic import and targeted official
cancellation/timeout rehearsal; read back rollback, source retention/cleanup,
job versions and queue retry/replay. Inspect the last unmatched existing batch
BEGIN and PostgreSQL wait/query state. Use a medium size only if needed to
reproduce the driver symptom; record timings and waits on the same launcher.
Resolve that cause and prove row fidelity, tenant/RLS, atomic commit and ambiguous
commit recovery before the owner's final 50k. The user's two Excel files remain
reserved for that later acceptance. No Dashboard or business logic was modified.
