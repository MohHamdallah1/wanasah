# Phase 19 — measured 50,000-row synthetic HTTP/Worker/PostgreSQL acceptance

Date: 2026-10-01. One authorized synthetic development rehearsal on the Windows development machine, NOT a customer deployment.

## Isolation

- The tested commit was ce863e9, based on main 3a77f95 (PR #65). Only the disposable test harness changed, not Product or Pricing production logic.
- Opt-in environment: WANASAH_P19_HTTP_LOCAL_GATE=1, WANASAH_P19_HTTP_CASE=final50k, WANASAH_P19_INTERMEDIATE_ROWS=50000, WANASAH_P19_FINAL_50K_CONFIRM=ISOLATED_SYNTHETIC_ONLY.
- Disposable PostgreSQL 16 at 127.0.0.1:55446, temporary FastAPI at 127.0.0.1:18046, synthetic tenant 2 with execution/control/maintenance Workers. The existing developer DB was read only during bootstrap and its source tenant verified unchanged afterward.
- New CSV from build_source(50000, fresh unique run ID): 8,045,007 bytes, under the 8 MiB import limit. The owner's two reserved Excel files were NOT read or used. An older job was NOT reused or recovered.
- The 5k and 10k intermediate live HTTP tests already passed (PR #65) before the final run. The historical September ClientRead driver cause did NOT reproduce; its specific mechanism is not proven.

## Real persisted result

| Measurement | Observed |
| --- | ---: |
| HTTP admission | 202 |
| Source records | 50,000 |
| IMPORTED rows and unique ProductVariants | 49,500 |
| Deliberately INVALID rows | 500 |
| Unexpected IMPORT_FAILED | 0 |
| Price variants | 49,500 |
| ProductVariant audit events | 49,500 |
| Transactional outbox events | 49,500 |
| Unique physical staged rows | 50,000 |
| First actual physical source row | 2 |
| Last actual physical source row (including four blank lines) | 50005 |
| Final status | COMPLETED_WITH_ERRORS |
| SourceStore cleared | yes |
| Queue deliveries active after completion | 0 |
| HTTP upload admission duration | 0.358 seconds |
| HTTP admission to terminal | **255.868 seconds** |
| Overall source throughput | approximately 195.4 source rows/second |
| Maximum PostgreSQL client sessions at sampled polls | 21 |
| PostgreSQL lock waiters at sampled polls | 0 |

Coarse HTTP-observed states, seconds after admission: QUEUED 0.395;
PARSING 1.162; VALIDATING 23.571; IMPORTING 39.375;
COMPLETED_WITH_ERRORS 255.868.
These are first-observed status timestamps, NOT exact parser, SQL, validation,
pricing or CPU-bound phase timings.

Authoritative PostgreSQL readback confirmed the counts above.
The isolated runner printed:

- P19_REAL_QUEUE_50000_SYNTHETIC=PASS
- ORIGINAL_DEV_TENANT_UNMODIFIED=PASS
- P19_HTTP_SOURCE_DEVELOPER_UNMODIFIED=PASS
- P19_HTTP_DISPOSABLE_CLUSTER_REMOVED=PASS
- FINAL_50K_GATE_EXIT=0
- FINAL_50K_WORKTREE_REMOVED

## Honest limitations / still-open acceptance

**Do not treat the reported process RSS/CPU sampler as accurate.**
The initial sampler observed approximately 4.17 MiB for each Windows launcher,
which is implausibly low for the child Python/Worker process tree.
It does not establish actual peak application/Worker memory and cannot be
used to invent a hardware p95/resource SLA. Per-statement DB round-trip counts,
WAL/index-churn metrics, exact per-phase times and repeated-sample p50/p95 were
also not measured. One final run is not a statistical percentile estimate.

This is a synthetic CSV with exactly 1% deliberately invalid data, not the
owner's Excel files or the near-100% invalid edge case. The historical
ClientRead causal mechanism remains unknown; a source-level 120-second
bounded staging guard and real short-deadline PostgreSQL lock-release
acceptance mitigate indefinite waiting, without proving that cause.
The separate official HTTP-cancel-during-an-actual-stalled-staging-step,
browser mobile/RTL/LTR/accessibility, some broad RLS/security negatives,
and first-company deployment still require their own evidence.
