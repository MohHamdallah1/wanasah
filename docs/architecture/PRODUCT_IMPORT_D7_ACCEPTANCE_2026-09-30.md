# D7 — 1,000-request mixed-burst acceptance contract

Decision locked before running the test. This is a local **diagnostic gate**
and an independent **production-like staging release gate**. Do not conflate
1,000 tasks arriving at once with 1,000 database transactions held open.

## D7-L: safe disposable-local gate
- Private PostgreSQL 16 cluster on 127.0.0.1:55445, schema plus approved
  empty tenant-2 synthetic fixture; tenant 3 is generated only in that
  cluster. D1's source-tenant checksum and automatic teardown are mandatory.
- Exactly 1,000 client arrivals released by one event. Client-side admission
  is capped at 10 HTTP requests simultaneously, *by design*, to avoid
  oversubscribing a single workstation and DB_POOL_SIZE=5. Measure queue wait
  separately from active ASGI request latency. **Never describe the 1,000
  arrivals as 1,000 simultaneously active HTTP requests.** A separate
  diagnostic mode can raise the *client* concurrency to 25/50/100 within
  this private database only. If the existing DB pool/HTTP request path
  cannot sustain it, record the exact failure/limiting point; never
  silently weaken timeout, tenant isolation or connection budget.
- Real FastAPI/Pydantic routers, actor/tenant-scoped database sessions and
  service code via HTTPX ASGITransport. Only test authentication is overridden
  to use known synthetic tenant-2 and tenant-3 admins. This is **not**
  Uvicorn/TLS/edge/network capacity testing.
- Fixed 1,000-request composition: 580 catalog GET, 200 own-tenant import
  status GET, 60 cross-tenant import status GET expecting 404, 30 unique
  Sale PUT, 40 unique Supplier Inbound POST, 30 unique Route Launch POST,
  20 unique Product Import multipart POST, 20 exact import-admission replays,
  10 exact Sale replays, 10 exact Supplier Inbound replays.
  Smaller 100-request preflight uses exactly 10% of each group.
- Product Import execution, control and maintenance have separate real worker
  processes; exactly 2 execution slots. Prepare 2 queued imports for company 2
  and one short import for company 3 before starting workers. Release the
  HTTP burst while the first company-2 import is IMPORTING. Prove same-company
  no-double execution; cross-company overlap; short tenant-3 import finishing
  before tenant-2's second long job; every unique import eventually terminal.
- Pre-registered per-operation request UUIDs, explicit idempotent duplicate
  attempts (replay must return the same business result), RLS/404 isolation;
  **Original 1,000-burst failed closed:** 3 unique uploads exceeded the
  existing 10-upload / actor / rolling 60-second admission limit, and their
  3 denied duplicate attempts also returned HTTP 429. This is a deliberately
  rejected request, not a lost accepted import. The revised local gate
  requires the exact PRODUCT_IMPORT_USER_RATE_LIMITED code, positive
  Retry-After header and durable rejection telemetry; verifies zero orphan
  business jobs on refusal; and retries the same request ID and bytes after
  the real quota window until they are durably accepted. NEVER raise or
  disable quotas to manufacture a pass.
- Quota is a **rolling** actor window, never an arbitrary fixed number of
  rejections for a batch that may span the 60-second boundary. A 429 original
  followed by a 202 retry can be correct if the first admission occurs after
  the window expires; the first accepted receipt must have replayed=false,
  subsequent identical request IDs must have replayed=true and the same
  job ID, every 429 must match durable telemetry, and the count of newly
  admitted requests in each rolling window must remain <=10 per actor.
- If an independently sampled blocker counter and its detailed classification
  use separate pg_stat_activity snapshots, do not assert atomic equality;
  classify relation/wait type without logging SQL literals, and distinguish
  query active age from actual time waiting for locks.
- Verify unique Product/Variant and Price/Audit/Outbox lineage for every import;
  exact Sale+Cogs, inbound and route commercial-context persistence with
  no duplicated work, negative stock, or cross-tenant data disclosure.
- Metric dimensions: HTTP service p50/p95/p99 **by operation**; client queue
  wait p50/p95/p99; arrival-to-result p95/p99; elapsed time; accepted/rejected
  by exact expected HTTP status; import queue age / terminal latency;
  max app connections, max running import tasks, sampled DB blockers and WAL.
  Capture hardware CPU/RAM and PostgreSQL effective server settings.
- Before execution, provisional local acceptance: all 1,000 HTTP attempts
  accounted for with exact statuses, zero unexpected 4xx, 5xx or timeouts.
  Exact expected quota 429 + Retry-After + telemetry + eventual idempotent
  admission are an explicit amendment after the retained first 1,000-burst
  failure. Read/denial service p95 <= 3,000ms; write service p95 <=
  5,000ms and p99 <= 10,000ms;
  1,000-request burst completion <= 120s; terminal imports <= 240s after
  burst; max database application-role connections <= 28 and global
  PostgreSQL connections <= 60; import execution <= 2; zero same-company
  overlap, successful cross-company overlap and fairness; all persisted
  lineage/idempotency/financial/tenant invariants exact.
- Fail closed if hardware cannot safely provision private PostgreSQL,
  if any expected fixture is missing, a worker exits early, a watchdog
  expires, a producer unexpectedly throttles the batch, or any integrity
  count mismatches. Do not raise pool sizes to make an overloaded test pass.

## D7-S: real production-like staging **still required**
Run the same business/tenant/queue mix from a separate load-generator
host through Uvicorn (4 configured web workers), the deployed ingress and
network/TLS, against a restored/anonymized production-sized catalogue and
representative price-history/stock distributions with realistic worker and
PostgreSQL resource budgets. Explicitly document CPU, memory, DB
max_connections, pool sizes, autoscaling/admission limits, number of
tenants, client wait/HTTP latency, fairness and error allowance.
For 1,000 arriving clients with bounded backpressure, assess long-tail
admission lag and HTTP 429/503 semantics; for 1,000 genuinely in-flight
HTTP connections, separately test that they remain safe and receive
bounded eventual responses. Re-run RLS, ledger, stock, pricing history,
idempotency, recovery and rollback parity. Do **not** sign off V1
production-scale readiness on D7-L alone. D8 rollout remains separate.
