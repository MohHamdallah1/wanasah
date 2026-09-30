# D7 — Mixed request load: local acceptance and staging blocker

**Date:** 2026-09-30
**Status:** D7-L (guarded local) PASS; **overall Gate D7 remains OPEN**
until D7-S is executed on production-like staging.
**Branch:** `hardening/v1-import-concurrency-diagnostics-20260930`.
This report is evidence for the actual application/worker implementations
under a private synthetic environment, not a production capacity claim.

## Exact test meaning

- One private PostgreSQL 16 database on `127.0.0.1:55445/d1_mix`,
  recreated from the approved synthetic tenant fixture and deleted after
  each run; tenant 3 is generated **only** inside this private cluster.
- HTTPX `ASGITransport` invokes real FastAPI routers, validation,
  domain services, and tenant-bound database sessions inside one local
  ASGI process. Only authentication identity is replaced by an explicit
  synthetic test header. There is no real Uvicorn worker, TCP/TLS, CDN,
  production gateway, or end-user JWT throughput proof in D7-L.
- Each HTTP burst creates 100/500/1,000 asyncio tasks and releases them
  from one barrier. Actual concurrent **admitted test-client calls** are
  intentionally limited to 10 or 20; duplicate-request scenarios wait for
  their original completion. **These are NOT 1,000 simultaneous active HTTP
  connections or database transactions, and the admission semaphore belongs
  to the test harness, not to the production HTTP application.**
- All three actual Product Import roles (execution, control, maintenance)
  run separately; execution concurrency remains 2. Each run uses real
  company-2 and company-3 import sources, actual sale/inbound/route business
  commands, and persisted RLS/inventory/price/audit/outbox evidence.
- Reviewed provisional local targets: exact expected responses, no
  unexpected HTTP statuses or timeouts; service p95 <= 3s for reads and
  <= 5s for writes, write p99 <= 10s, burst <= 120s, all admitted imports
  eventually terminal, max application DB connections <= 28, total <= 60,
  import execution <= 2, no same-company overlap, independent-company
  overlap and short-job fairness. The pre-existing 10 uploads per actor
  per rolling 60 seconds remains enforced.

The exact 1,000-request mix: 580 catalog GET; 200 owned import-status GET;
60 other-company import-status GET (404 expected); 30 committed Sale PUT;
40 committed Supplier Inbound POST; 30 Route Launch POST; 20 distinct
Product Import POST; 20 replay attempts of those POSTs; 10 Sale replays;
10 Inbound replays. Smaller runs are proportional.

## Captured local evidence

| Run | HTTP attempts / active calls | HTTP burst (s) | Catalog service p95 (ms) | Sale service p95 (ms) | Peak app / total DB connections | Sampled blocker edges |
|---|---:|---:|---:|---:|---:|---:|
| Preflight | 100 / 10 | 3.593 | 473.42 | 1700.35 | 18 / 19 | 7 |
| Bounded 1,000 | 1000 / 10 | 30.901 | 437.51 | 1600.40 | 21 / 22 | 111 |
| Intermediate | 500 / 20 | 16.282 | 853.57 | 3036.41 | 19 / 20 | 92 |
| 20-active saturation | 1000 / 20 | 54.843 | 1724.51 | 4062.67 | 19 / 20 | 182 |
| Post-instrumentation preflight | 100 / 10 | 6.656 | 790.18 | 2629.51 | 18 / 19 | 13 |

All **five successful runs** satisfied their local targets; the source
developer tenant remained unchanged and each private DB was stopped
and removed. The last preflight verifies the additional queue-wait
p50/p95/p99, end-to-end p95/p99, sampled physical-resource, import
terminal latency, and classified PG lock telemetry fields in the
retained executable gate. It ran on a 4-physical-core/8-logical-core,
15.71GiB-RAM workstation with observed machine CPU p95 89.2% and a
minimum of 2.33GiB available RAM. Its 6.656-second burst versus
the earlier 3.593-second preflight illustrates local measurement
variation. No server-side production HTTP backpressure is proven.

**Significant observation:** doubling test-client admission from 10 to
20 in the 1,000-arrival case **increased** measured burst completion
time from 30.901 to 54.843 seconds in these individual runs, rather
than improving it. This is a *diagnostic observation* from one Windows
workstation, not proof that 10 is the correct production admission limit
or that 20 is universally slower. Do not raise web pools, worker counts
or PostgreSQL limits by guesswork.

- At 1000/10, catalog p95 service time was 437.51ms but catalog
  test-client queue-wait p95 was **28,726.41ms**.
- At 1000/20, catalog p95 service time was 1724.51ms but catalog
  test-client queue-wait p95 was **50,695.61ms**.
- Sale p95 at 1000/20 was **4062.67ms** (under the preapproved 5s
  *service-time* threshold). The percentile of arrival-to-result is
  different: replay/deferred requests can complete much later.
- Peak Product Import tasks executing: **2**. Independent-company
  overlap PASS, same-company double execution FALSE, company 3's
  short job completed before company 2's second long job.
- In the 1000/20 run: 30/30 real sales, 30/30 COGS effects, 40/40
  supplier inbound movements, 30/30 persisted route commercial contexts,
  60/60 other-tenant status requests denied, bidirectional RLS proof,
  **0** negative inventory balances; 23 Product Import jobs eventually
  terminal with **3819 imported Product/Price/Audit/Outbox lineages**
  and 31 intentionally invalid rows; **0 duplicate import jobs**.
  Business effects are checked in PostgreSQL, never inferred from HTTP
  response codes alone.
- At 1000/20, **5** measured HTTP 429 attempts corresponded to **5**
  durable admission-rejection rows. Three distinct imports were first
  refused. One was correctly admitted on its subsequent in-burst
  replay **after the unchanged rolling window advanced**; the other
  two were accepted by explicit later retries. All three then produced
  one job per original request ID/source and subsequent 202/replayed
  receipts. Maximum admitted imports per actor in any rolling 60s
  interval was **10**, as configured. No quota was disabled or raised.
- At 1000/10, three initial unique imports and their three replays
  were rejected by the original quota (six 429 attempts); later all
  three were accepted with the original request ID after the window,
  also without duplicate business state.

### What the database lock samples actually show

The 1000/20 run collected **182** blocker-edge observations in **617**
polling samples (not 182 unique incidents or seconds of blocking).
Redacted classification:

- 144: `Lock/transactionid/transactionid/unresolved`.
- 21: `Lock/tuple/tuple/work_sessions`.
- 17: `Lock/advisory/advisory/unresolved`.

The largest **active SQL query age while blocked** observed was
1829.8ms. Query age is **not** pure blocked duration. These samples
document real contention under this synthetic mix, including a
`work_sessions` relation hotspot. They do not establish which
business operation or statement caused every transaction-ID/advisory
wait, and do not justify deleting locks or rewriting session/stock
authority. No deadlock/timeout or ledger corruption was observed.
The latest local profiler also exposes its oldest-*observed* queued
job age; this value depends on polling and Procrastinate's scheduling
states and must **not** be interpreted as a guaranteed maximum queue
latency. D7-S must collect wait duration, blockers, normalized statement
identities and production queueing ages if response thresholds regress.

### Fail-closed harness correction — no production change

An initial 1000/20 execution **failed** a test assertion
`denied replay admitted early`. Investigation showed a legitimate
transition from first HTTP 429 to **HTTP 202** because the actor's
60-second rolling window elapsed between two requests. The original
test incorrectly required the replay to remain denied indefinitely.
No business, admission, pricing, worker or DB-production code was
changed. The D7 harness now requires:

1. Each 429 includes `PRODUCT_IMPORT_USER_RATE_LIMITED` and
   a positive `Retry-After`, and is persisted as one rejection row.
2. First successful admission after a 429 must have
   `replayed=false`; subsequent calls with exactly the same
   request ID/source must return `replayed=true` and the same
   `job_id`.
3. A denied request must not create a Product Import business job.
4. No actor receives more than 10 import admissions in any
   60-second rolling window (queried independently from persisted jobs).
5. All distinct imports finish, with no duplicate jobs or effects.

The rerun after these amendments passed the complete 1000/20 mix.
The earlier failed test and corrected assertion are retained in this
report for reviewability.

## Engineering conclusion and release boundary

**D7-L = PASS**, including synthetic cross-company safety, genuine
business transactions, stable idempotency, bounded local worker/DB
capacity, real admission denials and later recoveries. This is a
valuable reproducible regression gate and no production business
logic change was needed.

**Overall Gate D7 = OPEN.** The plan specifically demands
**1,000 concurrent mixed submissions on production-like staging**.
This workstation's client-semaphore test is insufficient to certify
that claim. The following must be measured *in D7-S*, not presumed:

- Dedicated load-generator machine and a deployment matching the
  actual Uvicorn worker count, database/queue pools, gateway/TLS
  limits, CPU/memory, and PostgreSQL max connections.
- 1,000 simultaneously opened HTTP connections, plus a separately
  bounded-admission scenario with 1,000 arrivals; differentiate
  accepted, queued, throttled and failed work with end-to-end
  p50/p95/p99 including admission delay.
- Realistically sized catalogues, pricing revision histories and
  long-running stock/import workload, not the synthetic small seed.
- Connection utilization, lock waits (including `work_sessions`),
  sustained throughput, fairness, failures, worker restart behavior,
  RLS, ledger/COGS, historical pricing, idempotency and rollback.
- A reviewed release threshold appropriate to staged capacity and
  explicit operator approval; preserve safety by applying backpressure
  instead of simply starting unlimited workers.

See the frozen acceptance contract
`docs/architecture/PRODUCT_IMPORT_D7_ACCEPTANCE_2026-09-30.md`.
D8 production rollout must not begin merely on D7-L's green status.

## Reproduction

From `wa_backend`, with its virtual environment and the known safe
local development `.env`:

```powershell
$env:WANASAH_D1_LOCAL_GATE="1"
$env:WANASAH_D7_BURST="1"
$env:WANASAH_D7_REQUESTS="1000"
$env:WANASAH_D7_CLIENT_INFLIGHT="10"
$env:WANASAH_D1_IMPORT_ROWS="3000"
$env:WANASAH_D1_SOURCE_ENV_FILE=(Resolve-Path ".\.env").Path
python -m scripts.run_product_import_d1_isolated_gate
python -m unittest tests.test_product_import_d7_contract
```

To reproduce the diagnostic 20-client-admission case, change
`WANASAH_D7_CLIENT_INFLIGHT` to `20`; never change the
production Import quota or launch against live customer data.
The runner requires explicit opt-in, private-port availability, the
validated source connection, and cleanup; it refuses an already-used
private listener. Logs of unsuccessful tests do not constitute PASS.
