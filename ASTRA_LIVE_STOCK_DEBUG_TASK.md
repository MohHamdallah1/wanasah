You are acting as a senior performance/debugging engineer on an existing production-grade Flutter + FastAPI + PostgreSQL system.

GOAL
Find and fix the REAL root cause of a Live Stock HTTP performance regression.

Do not guess.
Do not propose speculative indexes.
Do not refactor unrelated code.
Use the minimum number of tokens and tool calls needed.
Inspect only files directly relevant to the bottleneck first.

REPOSITORY
Current branch:
codex/stage823-live-stock-read-performance

Main backend:
wa_backend/

Primary hot path:
GET /warehouse/inventory/cursor?location_id=119&limit=50

Mixed HTTP load also includes:
GET /warehouse/inventory/alerts/summary?location_id=119

Benchmark command:
python scripts/gate_live_stock_scale.py --company-id 38 --location-id 119

TARGET
Real HTTP:
- 4 Uvicorn workers
- concurrency = 20
- requests = 100
- total DB connection budget = 20
- p95 <= 500 ms
- errors = 0

DO NOT weaken these acceptance criteria.

CURRENT FAILURE
Latest corrected benchmark still fails:

CHECKS=20
FAILURES=1
FAIL: HTTP_LOAD_P95:726.4>500.0
LIVE_STOCK_SCALE_GATE=FAIL

The gate was recently corrected so Linux and Windows use the SAME real HTTP load generator.
Verify the current code before trusting old benchmark results.

KNOWN DATASET
Approx:
- companies: 1065
- variants in benchmark company: 10121
- global variants: 110187
- location balances: 14938
- location policies: 10120

IMPORTANT OBSERVATIONS ALREADY PROVEN

1. Isolated SQL/read-path performance is generally fast.

Typical isolated results:
- live_50 p95: ~19-44 ms
- live_200 p95: ~36-68 ms
- summary p95: ~9-16 ms
- alerts_summary p95: ~8-15 ms
- only_alerts_50 p95: ~26-40 ms
- search_50 p95: ~52-93 ms
- cursor_page_2 p95: ~40-68 ms

So do NOT assume a basic single-query SQL problem without evidence.

2. Under in-process ASGI concurrency=5, latency rises substantially:
Typical:
- cursor p95: ~236-280 ms
- alerts p95: ~113-185 ms
- pool wait p95: ~20-105 ms
- SQL p95: ~127-196 ms

3. Under real 4-worker Uvicorn / C20 / 100 requests, p95 becomes ~600-800 ms.

4. On Windows, persistent HTTP connections caused severe worker imbalance.
Examples:
worker hits:
70 / 15 / 10 / 5
or
50 / 25 / 15 / 10

When forcing Connection: close, requests distributed almost evenly and p95 dropped to ~299-317 ms.

Example:
21 / 27 / 27 / 25
p95 ≈ 299 ms

5. A 2-worker x 10 DB-connections diagnostic improved persistent p95 from ~750-800 ms to ~540 ms, but still failed.
Worker distribution was still badly skewed:
80 / 20.

This suggests worker connection pinning + per-process DB pool fragmentation may be involved, but this is NOT yet accepted as the complete root cause.

6. Do NOT simply increase PostgreSQL pool size.
Total application DB connection budget must remain 20 unless measurement proves otherwise.

7. Do NOT lower workers/concurrency/requests/threshold merely to make the test pass.

IMPORTANT CODE FACTS

A. InventoryLiveStockProjection already has these indexes:

ix_live_stock_projection_alert_seek:
(company_id, warehouse_location_id, variant_name, product_variant_id)
WHERE is_low_stock IS TRUE

ix_live_stock_projection_nonactive_seek:
(company_id, warehouse_location_id, variant_name, product_variant_id)
WHERE lifecycle_status <> 'ACTIVE'
AND (has_warehouse_presence IS TRUE OR has_vehicle_presence IS TRUE)

ix_live_stock_projection_transition:
(company_id, next_transition_date, warehouse_location_id, product_variant_id)
WHERE next_transition_date IS NOT NULL

ix_live_stock_projection_warehouse_transition:
(company_id, warehouse_location_id, next_transition_date, product_variant_id)
WHERE next_transition_date IS NOT NULL

ix_live_stock_projection_variant:
(company_id, product_variant_id, warehouse_location_id)

B. The alerts query DOES explicitly filter:
InventoryLiveStockProjection.is_low_stock.is_(True)

So do not claim the partial alert index is unusable without EXPLAIN evidence.

C. assert_live_stock_projection_ready() does NOT COUNT all products.
It reads precomputed summary rows from:
- InventoryLiveStockCompanySummary
- InventoryLiveStockWarehouseSummary

and performs a due-transition EXISTS check against InventoryLiveStockProjection.

Do not claim it scans all 110k global products unless EXPLAIN ANALYZE proves it.

D. A real bug was already fixed in:
wa_backend/api/warehouse.py
_build_visible_inventory_stmt()

Previously:
candidate_filters was prepended with company_id before checking:
if company_wide_inventory_read and not candidate_filters

which made the optimized company-wide fast path unreachable.

It was corrected by preserving:
extra_candidate_filters = tuple(candidate_filters)

and checking:
if company_wide_inventory_read and not extra_candidate_filters

Do not revert this.

E. For company-wide first-page/no-search reads, there is an intended fast path:
- active ProductVariant stream
- non-active projection stream
- each ordered/limited before UNION ALL
- final ordered LIMIT

Restricted actors use a different path and MUST preserve vehicle visibility/security semantics.

CRITICAL CORRECTNESS RULES
Never sacrifice these for speed:

- Tenant isolation must remain exact.
- Restricted actors must never see global projected vehicle quantity they are not authorized to see.
- Active variants must remain visible even with zero stock.
- Non-active visibility semantics must remain unchanged.
- Live inventory must not be served from stale cache.
- Projection readiness must remain fail-closed.
- No OFFSET pagination.
- No exact COUNT added to cursor pages.
- No N+1.
- No UI redesign.
- No business-logic rewrite unless required by the proven bottleneck.

FILES TO INSPECT FIRST
Do NOT read the entire repository first.

Start with only:

1. wa_backend/scripts/gate_live_stock_scale.py
2. wa_backend/scripts/stage823_benchmark_app.py
3. wa_backend/api/warehouse.py
   Focus on:
   - _build_visible_inventory_stmt
   - get_warehouse_inventory
   - cursor endpoint
   - alerts summary
   - permission/readiness dependencies
4. wa_backend/domains/live_stock_projection/service.py
   Focus on:
   - assert_live_stock_projection_ready
5. wa_backend/database.py
6. wa_backend/config.py
7. wa_backend/main.py
   Focus on middleware/dependencies executed per request.

Only inspect additional files if evidence points there.

IMPORTANT BENCHMARK NOTE
The gate had an old platform inconsistency:
Windows used stdlib threaded HTTP client while Linux used httpx_async.

That was fixed.

Verify the current gate contains a comment similar to:
"Use the same load generator on every OS"

The real Uvicorn benchmark should now use the same stdlib threaded client across platforms.

Do not use old httpx_async Linux results as final evidence.

YOUR TASK — STRICT ORDER

PHASE 1 — VERIFY
Spend very few tokens.

Confirm:
- current branch/code is the latest version
- benchmark really uses the same client across OSes
- exact worker/pool topology
- exact request mix
- exact middleware/dependencies executed for cursor and alerts

Do not edit yet.

PHASE 2 — LOCALIZE THE BOTTLENECK
Do not run broad random experiments.

Use the smallest set of measurements needed to separate:

A. HTTP/keep-alive worker distribution
B. DB pool wait / per-worker pool fragmentation
C. authentication/permission dependencies
D. readiness query
E. candidate query
F. detail/enrichment query
G. serialization/Python work
H. middleware
I. cross-process contention

Prefer existing instrumentation.
Add temporary instrumentation only if necessary.

For SQL suspects:
use EXPLAIN (ANALYZE, BUFFERS).

Never recommend an index based only on reading ORM code.

For worker/pool suspects:
measure per-worker:
- request count
- server p95
- pool wait p95
- SQL p95 if practical

The important question is:
WHY does the same request path that is fast in isolation become >500 ms under real C20 multi-worker persistent load?

PHASE 3 — PROVE ROOT CAUSE
Before editing production logic, state in <=10 lines:

ROOT CAUSE:
EVIDENCE:
WHY PREVIOUS TESTS BEHAVED THIS WAY:
PROPOSED FIX:

If evidence is insufficient, run ONE targeted diagnostic, not a large investigation.

PHASE 4 — IMPLEMENT
Once root cause is proven:

- make the smallest production-safe change
- preserve all correctness/security semantics
- do not increase total DB budget above 20 without hard evidence
- do not change acceptance thresholds
- do not hide the issue by disabling keep-alive
- do not reduce concurrency just to pass
- do not add speculative indexes
- avoid architectural refactors unless absolutely necessary

You are allowed to edit files and run tests after proving the cause.

Do NOT commit, merge, or create a PR unless explicitly asked.

PHASE 5 — VERIFY
Run:

python scripts/gate_live_stock_scale.py --company-id 38 --location-id 119

Acceptance:
HTTP p95 <= 500 ms
errors = 0
workers = 4
concurrency = 20
requests = 100
DB connection budget = 20

Then run the directly relevant correctness/regression gates for the changed area.

OUTPUT STYLE
Be concise.
Do not narrate every file you read.
Do not dump large code sections.
Do not repeat project history.

Return only:

1. Root cause
2. Evidence
3. Files changed
4. Exact change
5. Benchmark before/after
6. Remaining risk, if any

If you cannot prove the root cause, explicitly say:
"ROOT CAUSE NOT YET PROVEN"

Then give the SINGLE highest-value diagnostic command/change needed next.

TOKEN BUDGET RULE
Optimize aggressively for low token usage:
- targeted file reads
- targeted grep/search
- no repository-wide review
- no long explanations
- no repeating known facts
- do not analyze unrelated frontend/business modules