# Phase 19 — concurrent tenant, HTTP admission and bounded Worker evidence

Date: 2026-10-01. Worktree: `wanasah-codex-D7S` only.
Branch: `hardening/v1-import-phase19-tenant-contention-evidence-codex`.
Base: `d7c0fd50298e13803db6040d26d11d06e34f07d9`, latest fetched `origin/main`, containing merged PR #73 and its subsequent plan closure in PR #74.

## Source diagnosis before execution

The remaining umbrella item (formerly line 1122, currently lines 1133–1135) combines several independent proofs. Existing evidence was reviewed and reused:

- D4: real orphan recovery, PARSING cancellation and committed-batch crash/restart recovery. No D4 rerun.
- [PR #71](https://github.com/MohHamdallah1/wanasah/pull/71): real signed-JWT revocation, cross-company HTTP denial, FORCE RLS, tenant/actor composite FK and persisted Audit/Outbox contents. No authorization/correction suite rerun.
- [PR #73](https://github.com/MohHamdallah1/wanasah/pull/73): actual staging connection failure, dead pooled connection/pre-ping, lost staging/execution COMMIT acknowledgement and same-job recovery with exact durable identities. No transport fault rerun.
- Existing D3.2 child already observes company serialization and cross-company queue fairness. This case adds real HTTP request/admission overlap and verifies source reservation under that overlap; it does not rerun the D3.2 load/latency suite.

The source already implements the needed authorities:

1. `infrastructure/queue.py::enqueue_new_import` sets transaction-local tenant context, then locks `(company_id, hashtext(request_id))`. Its replay lookup checks actor, filename, SHA-256, byte size and tracking defaults. Source chunks, capacity reservation, job creation and queue insertion share one transaction.
2. `infrastructure/admission_repository.py` serializes admissions with a tenant transaction advisory lock before source persistence. Tenant/global live-byte reservations use conditional atomic updates. A quota loser rolls back the source/job/delivery and records safe rejection telemetry separately.
3. `defer_import_on_connection` uses company execution lock `product-import:{company_id}` and per-job queueing lock. Company serialization protects the shared Pricing publication authority; cross-company work can overlap.
4. `worker_cli.py` passes `RESOURCE_BUDGET.slots_for(role)` to the real Procrastinate consumer. The production default is two execution slots, one control slot and one maintenance slot. Control/maintenance queues do not consume execution slots.
5. `application/source_service.py` verifies immutable source metadata/bytes before parsing and clears bytes only after atomic staging. QUEUED/PARSING jobs retain their source. Lost COMMIT semantics were already proved in PR #73.
6. `scheduled_work.py` claims bounded indexed pages and inserts maintenance deliveries in the same transaction, using active locks/deduplication. Completion reconciles the candidate with generation CAS.
7. `retention_repository.py` restricts compaction/deletion to terminal tenant-owned jobs at the existing 30/365-day windows, with bounded `FOR UPDATE SKIP LOCKED` batches. `retention_queue.py` executes the existing service with the existing SourceStore through a real maintenance Worker.

**Precise gap:** prior reports did not establish that simultaneous authenticated uploads, same-ID replays and a capacity race preserved distinct tenant SourceStore references while two real execution slots were occupied and additional accepted work waited. Actual scheduler-to-Worker row retention was also unproved in this scope. No production defect was demonstrated by the focused acceptance; no business/runtime code was changed.

## Minimal implementation and isolation

The existing `run_product_import_phase19_http_isolated_gate.py` gained one opt-in `contention` variant, not another cluster/bootstrap harness. The new child reuses its HTTP/process/authentication helpers, synthetic CSV generator and read-only business integrity checker. That checker now accepts an optional `company_id` (default remains 2) so both tenants use the same evidence authority.

Required explicit opt-ins:

```text
WANASAH_P19_HTTP_LOCAL_GATE=1
WANASAH_P19_HTTP_CASE=contention
WANASAH_P19_CONTENTION_CONFIRM=ISOLATED_SYNTHETIC_ONLY
WANASAH_P19_HTTP_SOURCE_ENV_FILE=<existing developer environment file, read only>
python -m scripts.run_product_import_phase19_http_isolated_gate
```

Only the existing guarded parent bootstraps PostgreSQL 16 at `127.0.0.1:55446/p19_http_synthetic`, API at `127.0.0.1:18046`, and execution/control/maintenance Workers. It checks ports before creating an owned temporary cluster, copies schema and the preapproved synthetic fixture under read-only source access, redirects **both** application and migration URLs to the disposable cluster, checks the source afterward and removes only its owned temporary cluster.

The child independently checks both database URLs, API port and explicit confirmation before importing application services. The application role is verified non-superuser/non-BYPASSRLS. There were no original-database Worker writes, owner Excel reads, large imports, user-process termination, Dashboard changes or plan/architecture/handoff edits.

The fixture uses the production-default **2 execution slots** and a test-only **2 active jobs per tenant** limit to expose the quota race with four accepted three-row imports. The production active-job default **25** is unchanged. This is a correctness test of the configured bound, not deployment throughput, a connection census, or a memory/CPU capacity claim.

Test-only PostgreSQL advisory barriers hold four HTTP requests at their actual request locks, then hold the first staging insert for each tenant. The observer releases its barriers before official HTTP cancellation on failure. Owned Workers stop only after execution deliveries drain; no live user Worker is stopped. No transport/crash fault was injected.

## Actual results

The passing run is the unedited [attempt 2 log](PRODUCT_IMPORT_P19_CONTENTION_ATTEMPT2_2026-10-01.log), exit **0**.

| Case | Actual evidence | Result |
| --- | --- | --- |
| Overlapping same-ID HTTP uploads | Four requests simultaneously waiting on the real request advisory locks; identical request ID/body in both tenants; one new job and one replay per company, distinct jobs across companies | PASS |
| Concurrent admission race | Two further competing uploads per company for its remaining fixture slot; exactly two winners overall and two HTTP 429 `PRODUCT_IMPORT_ACTIVE_JOB_LIMIT` losers with `Retry-After: 30` | PASS |
| Atomic retained source | Four distinct tenant/source references; exact original bytes, SHA-256 and size; exactly accepted-byte reservations in tenant/global counters; zero visible partial staging rows | PASS |
| Concurrent isolation | Signed cross-tenant job GET returns 404; actual application-role jobs/sources/chunks reads with tenant context 2 → 3 → 2 show two own records and zero foreign records at each boundary | PASS |
| Bounded real execution and independent roles | Exactly 2 `doing` jobs with distinct company locks, 2 accepted `todo` jobs; one company never owns two doing deliveries; control heartbeat and maintenance scheduler finish while both execution transactions remain blocked and sources remain intact | PASS |
| Completion/no duplication | Four jobs COMPLETED, 3/3 imported each, no INVALID/IMPORT_FAILED; one successful delivery/attempt each; original row numbers 2/3/4 and distinct row identities | PASS |
| Product/Pricing/Audit/Outbox integrity | New-record delta: 12 Product, 12 Variant, 24 price entries, 12 Audit, 12 Outbox. Each job has 3 distinct priced variants and exactly 3 distinct Audit/Outbox aggregates; no duplicate price effectivity/UOM key | PASS |
| Source continuity and locks | Same source identity/hash/size after execution; source cleanup marked/deleted; zero source chunks and zero tenant/global live bytes; job and all row locks acquired with `FOR UPDATE NOWAIT` then rolled back | PASS |
| Actual retention Worker | Two already-completed company-2 synthetic fixtures aged by their `finished_at` only to 31/366 days; native trigger makes registry due; real scheduler defers real maintenance cleanup | PASS |
| Retention effects/isolation | 3 rows compacted with identity/number/variant/status preserved; 3 expired lineage rows removed; all 6 company-3 rows unchanged; exact Product/Variant/Price identities/versions and Audit/Outbox IDs unchanged; next retention deadline reconciled to the future | PASS |
| Source/deployment isolation | `ORIGINAL_DEV_TENANT_UNMODIFIED=PASS`, `P19_HTTP_SOURCE_DEVELOPER_UNMODIFIED=PASS`, `P19_HTTP_DISPOSABLE_CLUSTER_REMOVED=PASS` | PASS |

Business counts are **deltas**, excluding the existing one-Product/one-Variant synthetic seed. The maximum sampled executing count is 2; the deliberately held boundary proves actual simultaneous work rather than inferring it from submitted requests or virtual users. Fixed consumer concurrency in the source supplies the bound between samples. These observations are not p95, an SLA or hardware-scale backpressure certification.

The [attempt 1 log](PRODUCT_IMPORT_P19_CONTENTION_ATTEMPT1_2026-10-01.log) is retained and is **FAIL/incomplete**, not another PASS. Its request-overlap phase passed, then the observer looked for the refusal code under `detail.code`; the real shared HTTP exception handler emits `error.code`. Corrected the observer only. The original database was not written; official cancellation drained the owned imports and the temporary cluster was removed. The passing attempt also accounts for the known synthetic seed in its final business count comparison. No production fix was justified.

## Explicit remaining OPEN scope

- **SourceStore upload-byte expiry via retention remains OPEN.** These healthy imports remove bytes after atomic staging, before terminal retention. The Worker run proves active queued sources survived the scheduler and verifies 30/365-day row cleanup, but cannot establish the 7-day stale failed-source deletion path. No fake FAILED job, resurrected source bytes, policy shortening or old developer job was created to manufacture that evidence.
- Retention racing an actual correction/retry, expired retained failed-source recovery, and scheduler generation races at large candidate volumes are not established by this case. Existing source controls are reviewed, not promoted to runtime PASS.
- Backpressure under sustained overload, larger tenant populations, deployment connection ceilings, CPU/RSS/resource pressure and responsiveness percentiles remain OPEN. Two real execution slots, queued work, quota-race refusal and independent role progress are proved only for this small isolated fixture.
- The combined plan item must remain OPEN until its remaining acceptance scope is explicitly resolved. No plan checkbox was edited here. Previously passing authorization/crash/transport/50k cases were not rerun, and no new fault was necessary.

## Reviewable changes

- `wa_backend/scripts/run_product_import_phase19_http_isolated_gate.py`: guarded new variant and fixture limits; prior variants unchanged.
- `wa_backend/scripts/product_import_phase19_contention_child.py`: small consolidated real-pipeline acceptance, owned barriers, official failure cancellation, evidence assertions.
- `wa_backend/scripts/product_import_business_integrity_gate.py`: parameterized tenant reads, backwards-compatible default 2; no write or business logic.
- This report and the two attempt logs.

Focused actual acceptance PASS, Python AST checks PASS and whitespace/diff review complete. No old gate, benchmark, production migration, Worker transport suite or frontend test was run. Commit/push are on the dedicated branch only; no merge.
