# Phase 19 — official HTTP cancellation while real staging SQL is blocked

Date: 2026-10-01; owner-authorized synthetic isolated Windows rehearsal.

Source: wa_backend/scripts/product_import_phase19_http_cancel_stall_child.py,
run through the existing disposable API/PG16/Worker orchestration.

## Actual setup and observed assertions

- The source developer PG was accessed READ-ONLY for schema/known-empty
  synthetic tenant bootstrap; no historical developer task restarted.
- The test owned and later removed PostgreSQL16 on 127.0.0.1:55446 and
  real Uvicorn on 127.0.0.1:18046 with three dedicated import workers.
- Synthetic 5,000-row CSV, new UUID and isolated company 2, not user Excel.
- Test transaction deliberately took ACCESS EXCLUSIVE lock on
  public.product_import_rows before submitting the job.
- The real Worker reached PARSING and a genuine pg_locks NOT GRANTED
  wait on product_import_rows. This is a server-side SQL lock wait,
  not a mock and not a recreation of historical Windows ClientRead.
- POST /simple-products/imports/{job_id}/cancel with an authorized bearer
  token received HTTP 202 and status CANCELLED while the SQL still waited.
- A second authenticated company's attempt to cancel the job returned 404.
- After releasing the test-owned lock, the Worker observed cancellation
  and rolled back its whole staging transaction: zero persisted rows,
  zero linked variants, zero processed products; SourceStore cleared and
  procrastinate queue delivery ended.
- Original developer source tenant unchanged, disposable PostgreSQL removed,
  disposable worktree removed. No Product/Pricing authority changes.

Exact runner markers:

P19_HTTP_ACTUAL_STAGING_SQL_LOCK_WAIT=PASS
P19_OFFICIAL_HTTP_CANCEL_WHILE_STAGING_LOCKED=PASS
P19_FOREIGN_TENANT_CANCEL_DENIED=PASS
P19_CANCELLED_STAGING_ATOMIC_ROLLBACK=PASS
P19_CANCELLED_SOURCESTORE_CLEAR=PASS
P19_CANCELLED_QUEUE_INACTIVE=PASS
PRODUCT_IMPORT_P19_REAL_HTTP_LOCK_CANCEL=PASS
ORIGINAL_DEV_TENANT_UNMODIFIED=PASS
P19_HTTP_DISPOSABLE_CLUSTER_REMOVED=PASS

## Boundaries

This confirms the official HTTP cancel path cooperates with a real
PostgreSQL SQL-lock-stalled staging transaction. It does NOT claim:
(1) reproduction/diagnosis of September asyncpg ClientRead internal cause;
(2) actual transport abort followed by successful retry of the same job;
(3) pre-ping of an already-dead pooled driver connection;
(4) genuine lost PostgreSQL COMMIT acknowledgement;
(5) future 50k load statistics or customer deployment. Those remain
separate, explicitly tracked release scenarios where required.
