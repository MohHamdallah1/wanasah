# Phase 19: atomic Retention / Retry evidence (2026-10-01)

Worktree: `C:/Users/admin/Desktop/wanasah-codex-D7S`.
Branch: `codex/v1-import-phase19-retention-retry-atomic`.
Base: fetched `origin/main`, `37384b29963e35ce2d3fb9a97de531de7b934faa` (PR #80; includes merged PR #78).
No changes to the import plan, architecture, handoff, Dashboard, retention policy, product or pricing authorities.

## Confirmed source defect

Previously, `fetch_expired_source_ids` read terminal jobs without a retained job lock. The application closed that ORM transaction before SourceStore's independent transaction deleted chunks, marked source metadata and decremented capacity. A third transaction marked jobs without checking current status/expiry. Meanwhile `retry_failed_import` locked the job, but did not check retained source metadata or the seven-day terminal retention window. Retry could clear `finished_at` and enqueue parsing between these cleanup transactions, losing its immutable source.

The same missing parent-job lock existed in 30-day row compaction / 365-day lineage deletion. Correction already locks job then rows and checks retention under that job lock. Cleanup locking only individual rows could erase a different rejected row while Correction held the job across the retention boundary. Existing locks did not prohibit either race.

## Narrow fix and transaction contract

* Lock eligible terminal jobs with `FOR UPDATE OF jobs SKIP LOCKED`, ordered by `finished_at, id`, inside the source cleanup transaction.
* Reuse SourceStore's existing batch deletion/capacity implementation through `delete_source_bytes_batch_on_connection`. Standalone cleanup delegates to this same implementation.
* On that SAME connection/transaction: select and lock eligible jobs -> source locks in source-id order -> delete chunks / mark source deleted -> decrement tenant then global capacity -> recheck terminal status and cutoff when marking jobs. Any error or marker-count mismatch rolls back the entire batch. The application counts the batch only after commit.
* Retry holds its existing job lock, then (for QUEUED/PARSING) locks/checks same-company source metadata and job deletion marker. Expiry is checked with PostgreSQL wall time AFTER acquiring locks, against the original terminal `finished_at`; waiting must not extend eligibility. Transition and existing stable queue lock remain in the same transaction.
* VALIDATING/IMPORTING reuse staged rows without requiring upload bytes. The 30-day guard applies only when STAGED/VALID rows still require heavy JSON. Already imported checkpoints may finalize from durable counters even after row compaction; they do not recreate products.
* Row compaction and lineage deletion now select/lock eligible jobs first, then bounded rows. Correction keeps its existing validation, durable request id, row identity/version and product/pricing authority.

Retention remains 7 days for upload bytes, 30 days for full row detail and 365 days for compact lineage, measured from terminal `finished_at`. Batch ceilings remain unchanged. No schema/migration or authorization changes.

## Locks, isolation, capacity and recovery

Source cleanup and parsing Retry use job -> source. Row cleanup and Correction use job -> rows. Cleanup orders multiple source locks by id, then uses tenant capacity -> global capacity; admission already holds its tenant capacity row before global reservation. Cleanup's parent-job selection skips existing job locks rather than waiting while holding child/capacity locks. Ordinary SourceStore cleanup does not simultaneously hold a source lock and subsequently acquire a job lock: its job marker is a later transaction.

Every new database operation retains explicit `company_id` filtering and the application's transaction-local `app.current_tenant` GUC. No privileged migration/admin connection is used by production code. Existing RLS remains authoritative. Missing/deleted sources are rejected instead of silently requeued; capacity decrements apply only to locked live sources, with existing underflow/row-count integrity checks. Repeated cleanup of deleted metadata cannot decrement twice.

If Retry wins while its required data is still eligible, its committed active state/cleared `finished_at` excludes the job from cleanup. If cleanup wins, Retry waits for the job lock, then sees deleted source/marker and refuses. Rollback restores chunks, metadata, capacity and marker together. Completed business checkpoints continue to use existing idempotent execution. No parallel correction/validation engine was introduced.

## HTTP contract

`POST /simple-products/imports/{job_id}/retry` remains body-free and returns existing HTTP 202 `ImportActionResponse` on acceptance/state replay. Manage permission and same-company ownership checks are unchanged.

| HTTP | Stable error code | `error.context.reason` | Meaning |
|---|---|---|---|
| 410 | `PRODUCT_IMPORT_RETRY_SOURCE_UNAVAILABLE` | `SOURCE_UNAVAILABLE` | Parsing needs missing/deleted source or a cleared source marker. |
| 410 | `PRODUCT_IMPORT_RETRY_SOURCE_UNAVAILABLE` | `RETENTION_EXPIRED` | Parsing needs source beyond the seven-day window, even if cleanup has not run. |
| 410 | `PRODUCT_IMPORT_RETRY_DETAILS_EXPIRED` | `RETENTION_EXPIRED` | Pending staged/valid rows require details beyond the thirty-day window. |

The canonical error contains a safe message and correlation id. Source message: “The original import source is unavailable or has expired. Upload the file as a new import.” Row detail message: “The retained import row details have expired. Upload the remaining rows as a new import.” No SQL, credentials or raw cell contents are returned. Rejection changes neither job version/state, source/counters nor queue.

## Actual evidence (not mock acceptance)

Reused `run_product_import_phase19_http_isolated_gate.py` with the explicitly confirmed `retentionretry` variant and a small child case. PostgreSQL 16 was created at `127.0.0.1:55446/p19_http_synthetic`; actual HTTP API at port 18046, actual maintenance Worker and synthetic tenants 2/3. Both child database URLs are checked before any app import/write. The existing runner reads the approved developer source/schema only; Workers connect exclusively to disposable PostgreSQL. No execution Worker ran against the original developer database. No owner Excel files or previous concurrency/load suites were used.

| Case | Result | Direct evidence |
|---|---|---|
| Expired FAILED parsing source, bytes still retained | PASS | Actual HTTP 410 `RETENTION_EXPIRED`, unchanged state and counters. |
| Cleanup in progress vs overlapping HTTP Retry | PASS | Real maintenance trigger paused after tentative chunk/counter changes and before marker. Observer saw only old committed state. `pg_blocking_pids` showed HTTP Retry waiting on maintenance job lock. After release/commit: 410 `SOURCE_UNAVAILABLE`, job remained FAILED, source deleted/marked, no chunks. |
| Capacity and foreign source | PASS | Deleted exactly 284 live bytes; remaining tenant counters `(2,284),(3,284)` and global 568 matched retained chunks. Foreign company-3 source unchanged; foreign HTTP job read 404. |
| Repeated cleanup / lock release | PASS | Second real maintenance delivery made no further capacity decrement. Job/source/tenant/global rows all accepted observer `FOR UPDATE NOWAIT` after completion. |
| Eligible fresh / staged source-free retries | PASS | Six-day parsing retry and eight-day staged retry returned 202; same-state replay did not increment version or create a second execution delivery. Retained fresh source unchanged. |
| Correction held across actual 30-day boundary | PASS | Official HTTP correction acquired parent job + first rejected row before expiry. While paused past expiry, actual maintenance skipped the job, including the other unlocked rejected row. After save/replay, active VALIDATING job was not compacted. Product/Variant/Price identities+versions and Audit/Outbox ids unchanged; PostgreSQL deadlocks delta 0. |
| Pending details vs completed checkpoint (essential regression) | PASS | Thirty-one-day pending staged row refused. One synthetic valid product was saved by the existing execution authority; a real PostgreSQL serialization failure (40001) affected ONLY final job completion, after product/row commit. Existing runtime failure authority recorded FAILED/IMPORTING. Real maintenance compacted the imported row. HTTP Retry/replay accepted; existing execution authority completed from durable counters without changing Product/Variant/Price/Audit/Outbox snapshot or capacity. |

### Logs and bounded reruns

1. `PRODUCT_IMPORT_P19_RETENTION_RETRY_ATTEMPT1_2026-10-01.log`: source/Retry/capacity subcases above emitted PASS. **Overall invocation failed** in Correction replay observation: the test incorrectly expected identical full responses, although existing replay intentionally changes `replayed` false -> true. Its cleanup observation also used nonexistent queue column `queue` instead of `queue_name`. No production failure was hidden. Disposable PostgreSQL stopped; the maintenance Worker exited naturally. Two remaining idle API/launcher processes were scoped by this run's environment/private log directory and closed; no Worker was forcibly terminated. A stopped, partially removed temp diagnostic directory `wanasah_p19_http_disposable_x06_3qtn` may remain from that failed cleanup.
2. `PRODUCT_IMPORT_P19_RETENTION_RETRY_ATTEMPT2_2026-10-01.log`: corrected observers, **Correction-only** invocation exit 0 / PASS, original developer tenant unchanged and disposable cluster removed. Source/Retry tests were not repeated.
3. `PRODUCT_IMPORT_P19_RETENTION_RETRY_CHECKPOINT_ATTEMPT1_2026-10-01.log`: additional checkpoint regression overall FAIL: its fixture manually executed after HTTP had already enqueued an unconsumed delivery, so the existing queue's uniqueness correctly prevented another delivery (503). This was a test-fixture defect. Disposable cluster removed.
4. `PRODUCT_IMPORT_P19_RETENTION_RETRY_CHECKPOINT_ATTEMPT2_2026-10-01.log`: corrected synthetic fixture starts staged without an initial queue delivery; **checkpoint-only** invocation exit 0 / PASS, original developer tenant unchanged and disposable cluster removed. No source race or Correction case rerun.

The source/Retry acceptance predates only the final narrowing of the thirty-day detail guard to pending rows; its parsing/deletion branch did not change afterward. The final checkpoint run specifically verifies that refinement, including rejection of a pending expired row. These independent actual assertions are the evidence; the failed first invocation is not described as a full gate PASS.

Focused rerun contract (from `wa_backend`, using existing installed runtime): set `WANASAH_P19_HTTP_LOCAL_GATE=1`, developer env path in `WANASAH_P19_HTTP_SOURCE_ENV_FILE`, `WANASAH_P19_HTTP_CASE=retentionretry`, `WANASAH_P19_RETENTION_RETRY_CONFIRM=ISOLATED_SYNTHETIC_ONLY`; run `python -m scripts.run_product_import_phase19_http_isolated_gate`. Default child case `all` covers source race + Correction; `WANASAH_P19_RETENTION_RETRY_CASE=correction` or `checkpoint` runs only the corresponding necessary regression. This is not a command to run on staging/production or an invitation to repeat passed gates.

## Scope and remaining proof limits

Production files: imports `api/router.py`, `domain/errors.py`, `application/source_store.py`, `application/retention_service.py`, `infrastructure/postgres_source_store.py`, `infrastructure/retention_repository.py`, `infrastructure/queue.py`. Existing Phase-12 source layout assertion was updated to the new atomic delegation but its old full gate was NOT run. Existing isolated runner gained one explicit variant; one focused child and this report/raw logs were added.

The final source review and focused PostgreSQL cases address the reported race and its Correction overlap. They do not claim a production/staging deployment PASS, universal deadlock absence, throughput SLA or new proof of old crash/COMMIT/network scenarios. Previously merged PR #78 evidence was not rerun. Full deployment acceptance and plan closure remain owner review items; no checkboxes or unrelated plan items were edited. The one-product checkpoint proof directly invokes existing validation/execution authority on real PostgreSQL, rather than claiming an execution-Worker delivery proof. The maintenance race itself uses a real queued maintenance Worker.

Final review: Python AST parsing passed for all ten changed Python files; `git diff --check` passed. Four raw logs were checked for bearer/JWT/database credential patterns before staging. No owned disposable Python processes or listeners on ports 55446/18046 remained. No active Git hooks were configured. Protected plan/architecture/handoff/Frontend paths are absent from the diff.
