# Live Stock R1 PostgreSQL proof gate

Historical proof base: 59b760b59b21b0438ba920067d58b5face2555e9.
Current correction base at verified head: 941847ac5d5bd6578d2070b4f947741d1420a677.
Branch: codex/live-stock-snapshot-integrity-proof (PR #607, DRAFT).
Frozen V1 workflow: trustworthy warehouse/vehicle operational stock visibility.
Historical stage: isolated PostgreSQL reproduction (before F1 release).
Current stage: authorized single-statement list correction, focused PostgreSQL PASS;
independent review completed, release/merge acceptance remains OPEN.
PR #605 was merged and released live_stock.py to the R1 owner.

## Evidence status (historical FAIL vs corrected candidate PASS)

The historical reproduction below is intentionally retained as FAIL evidence;
its 2026-10-30 pre-fix conclusions are not the current PR state.
Current tested SHA: `8ed79adff290a1c9aff014c2a4d007e211968f75`.
See the final independent review section below before citing acceptance.

No result is implied by committing these tests. Read the exact head's Actions
logs and JUnit artifacts. A skipped test or provisioning/collection error leaves
the gate OPEN. Snapshot assertions deliberately fail on an incoherent response;
there are no xfail markers and no expected-failure conversion to green.

The movement job and snapshot job are separate so a red read-integrity gate
cannot be mistaken for physical stock duplication.

## Isolation and invocation

The workflow provisions PostgreSQL 16 in an ephemeral GitHub-hosted runner.
It uses no secrets, production data, local-machine connection, background worker,
schema clone or application isolation changes. The reused pg fixture verifies:
- database wanasah_no_lot_contract_test on 127.0.0.1:55439;
- restricted wanasah_app: not superuser, not BYPASSRLS;
- distinct fixture/migration role, current Alembic heads, FORCE RLS;
- fresh synthetic companies and canonical identities for every test.

Only after that disposable environment has been provisioned, set the explicit
WANASAH_NO_LOT_PG_* URLs and both WANASAH_NO_LOT_PG_GATE=1 and
WANASAH_R1_PG_GATE=1. From wa_backend run:

    python -B -m pytest -p no:cacheprovider -q -s tests/test_live_stock_r1_movement_postgres.py
    python -B -m pytest -p no:cacheprovider -q -s tests/test_live_stock_r1_snapshot_postgres.py

Both files run for FIFO and MOVING_AVERAGE through the existing guarded fixture.
The tests do not perform DDL, cleanup, or direct balance/projection writes.
A closed synthetic route supplies only the existing historical vehicle-source
attribution; these are engine-level tests, not a new route/settlement workflow.

## Independent expected values and reconciliation

Receipt: 20 base units at cost 2 => cost quantity 20 and inventory value 40.
Setup uses the real engine to move 10 W->V. Baseline: W=10,V=10,total=20.
Return uses the real engine to move 10 V->W. Committed: W=20,V=0,total=20.
The immutable ledger reconstructs custody from zero independently of Live Stock.
Each internal movement must have exactly two impacts [-quantity,+quantity].
Reservations change only reserved quantity, never physical total.
Internal movement/replay/rollback must preserve the single receipt cost event,
quantity 20 and value 40 under both accounting methods.

Movement tests cover uncommitted visibility, committed transfer, replay,
changed-input rejection, two simultaneous identical commands, rollback then
same-key retry, a competing reservation, and cross-company destination denial.
Expected race outcomes are an explicit finite set, never a percentage tolerance.

## Historical deterministic read boundaries (pre-correction)

PausingReader delegates every call to the real PostgreSQL AsyncSession and
returns the original real result object unchanged. It pauses only after:
1. the SQL containing inventory_vehicle_page_variant_ids has executed; or
2. the visible_inventory_candidates statement has executed.

The writer then executes the real movement engine on a separate connection and
commits or rolls back before the reader continues. asyncio Events establish the
order; no sleep is used to manufacture a race. Failure to reach a boundary fails
the test rather than silently accepting an unexercised scenario.

Vehicle case: acceptable response pairs are (10,10) or (20,0). (20,10) fails.
Filter case: start W=10,V=10 with stock_state=sellable, pause after candidates,
commit W->V=10. A returned row must still have positive sellable quantity, or
the coherent after snapshot must exclude it. A candidate/detail pair of
matched-before/zero-after fails.
Rollback control must return (10,10).
Restricted reads test explicit W/V grants, same-company wrong warehouse,
foreign warehouse/RLS and committed grant revocation using the same subject.

R1_EVIDENCE lines are emitted before strict read assertions, after committed
physical/ledger/cost assertions. They report the observed response and physical
truth separately. query_boundary_count counts instrumented execute calls only;
it is not an HTTP query-count, latency or EXPLAIN measurement.

## Historical narrow correction proposal (implemented later with authorization)

If PostgreSQL reproduces R1, prefer one bounded list SQL statement containing
candidate selection/filter/seek and the existing warehouse/cost/UOM enrichment,
plus readable vehicle aggregation in that same statement snapshot. Preserve
limit+1 paging, exact company predicates, strict vehicle custody, latest-route
attribution and persisted inventory.read filters before pagination.

Moving only vehicle enrichment into detail fixes the quantity witness but does
not by itself fix candidate/detail filter consistency. Rechecking after paging
can create short/missing pages and is not sufficient proof.

A combined statement could remove two query round trips for restricted list
reads, but no speedup or plan is claimed. Compare exact emitted SQL with
EXPLAIN (ANALYZE, BUFFERS) for 1/50/200 keys and restrictive/broad filters.
Keep enrichment bounded by the page; do not scan the full balance table or
relax location authorization. No global isolation change or cache is proposed.
Lead coordination is required before editing live_stock.py; this branch does
not touch it, the movement engine, costing, authorization, or migrations.

## Executed evidence — 2026-10-30

Tested commit: f8dc600cd9bde08a10f55d058536c73af52eca5b.
[Actions run 40984085495](https://github.com/MohHamdallah1/wanasah/actions/runs/40984085495)
checked out that exact head (not the GitHub synthetic merge SHA).
Both PostgreSQL 16 containers migrated successfully; fixture role/RLS/head checks
and runtime-unchanged checks passed.

- [Movement job](https://github.com/MohHamdallah1/wanasah/actions/runs/40984085495/job/123830853265):
  **10 passed**, 23.13 seconds for the pytest process; FIFO and MOVING_AVERAGE.
  Committed return: W=20,V=0,total=20; 3 movements/5 impacts including setup,
  versus 2 movements/3 impacts before return. Replay adds zero effects.
  Cost quantity=20,value=40,cost-event count=1 throughout.
  Competing reservation won in both executions; transfer was rejected without
  partial effects, followed by successful release and transfer.
- [Snapshot job](https://github.com/MohHamdallah1/wanasah/actions/runs/40984085495/job/123830853502):
  **4 failed, 4 passed**, 18.92 seconds for the pytest process.
  Both methods reproduced W=20,V=10,apparent total=30 while independent
  physical/ledger/cost checks passed at W=20,V=0,total=20.
  Both methods reproduced a sellable-filter result with sellable quantity 0
  after the candidate was selected before a W->V movement.
  Rollback controls and exact read-scope/live-revocation tests passed.
- [Movement JUnit](https://github.com/MohHamdallah1/wanasah/actions/runs/40984085495/artifacts/12946177620)
  and [snapshot JUnit](https://github.com/MohHamdallah1/wanasah/actions/runs/40984085495/artifacts/12945988147)
  were retained even though the overall integrity workflow failed.

The measured pytest durations include fixture creation and are not query latency.
Five instrumented execute boundaries were observed in each raced read; delegated
scalar calls and HTTP authentication are not included. No EXPLAIN/50k or proposed
fix benchmark was run. HTTP login/token admission is outside these domain/read
tests; the persisted capability/location queries and restricted RLS role are real.

Historical pre-fix conclusion: R1 was reproduced as a read inconsistency. The tested canonical
movement path conserves physical custody and ledger/value evidence. The overall
read-integrity gate FAILS and remains a release blocker. This proof branch does
not implement a correction or authorize editing the lead-owned live_stock.py.


## Authorized correction — accepted main c0fe0187

The lead released live_stock.py after F1 was merged. Original reproduction logs
above are immutable historical evidence and remain linked.

Alternatives considered:
- A route-local REPEATABLE READ transaction retains the old query plans, but the
  authenticated request already has an open transaction. Establishing a snapshot
  requires a separate read session (and capability context) or a transaction
  restart. Readiness can perform repair and commit, so the snapshot boundary must
  follow repair and repeat authorization/readiness. This adds session/transaction
  ownership and round trips to one hot read and risks changing revocation timing.
  No global isolation or authentication transaction change is acceptable.
- The implemented bounded statement retains existing candidate/filter builders.
  It materializes limit+1 candidates and limit detail keys, joins restricted
  vehicle totals only for those detail keys, and retains indexed UOM/purchase
  LATERAL enrichment. Candidates, filters, warehouse, vehicle and cost context
  now use the same PostgreSQL statement snapshot under ordinary READ COMMITTED.
  The list remains one page, not a snapshot held across cursor requests.

No movement/costing authority, public quantity meaning or vehicle attribution
changed. The merged F1 batch-detail function is protected by the CI AST scope
guard. All runtime nodes except get_warehouse_inventory must match the current
merge-base exactly; only the seven intended files may differ, and deletion fails.

The original four failing test expectations are unchanged. Their instrumentation
now pauses before/after the combined real statement because the old separate
SQL boundaries no longer exist. Additional explicit before/after controls cover
both quantity and sellable eligibility. No skip or xfail was introduced.

The SQL gate creates 50,000 stocked synthetic variants through bounded canonical
movement/costing batches in the disposable PostgreSQL runner. It captures actual
emitted SQL, parameters, query counts and EXPLAIN (ANALYZE, BUFFERS) plans for
1/50/200 pages, next/deep cursors, owner/restricted access, search and common
filters. Artifacts retain raw plans. It is a synthetic hosted-runner measurement,
not production capacity certification. The jobs subsequently finished successfully on SHA `8ed79adf`; their actual
logs and raw plans were independently reviewed. Release and representative-load
acceptance remain OPEN. See below.


## Independent final code, CI, and EXPLAIN review — 2026-10-30

**Verification target:** draft PR #607, original tested head
`8ed79adff290a1c9aff014c2a4d007e211968f75`, based on
`941847ac5d5bd6578d2070b4f947741d1420a677`.
The baseline failing proof at `f8dc600c` and run
[40984085495](https://github.com/MohHamdallah1/wanasah/actions/runs/40984085495)
remains preserved, **historical FAIL**, never reclassified to a passing run.
The corrected candidate's actual hosted
[run 40986490709](https://github.com/MohHamdallah1/wanasah/actions/runs/40986490709)
checked out `8ed79adf` (artifact names use GitHub's synthetic merge SHA).

### Verified focused results — PASS, not unconditional release signoff

| Scope | Exact job | Verified PostgreSQL 16 result |
| --- | --- | --- |
| Movement/ledger/FIFO+moving average | `123838863718` | 10 passed |
| R1 snapshot/permissions/revocation/FIFO+moving average | `123838863712` | 16 passed |
| CP7/F1 stock list/detail/holds/reservation | `123838863409` | 12 passed |
| 50k SQL/EXPLAIN per costing method | `123838863654` | 2 passed |

The source and seven-file diff were independently checked. Only
`get_warehouse_inventory` in `wa_backend/api/warehouse/live_stock.py` changed
at runtime; CI's merge-base AST scope guard passes, preserving all other
runtime nodes including F1 batch detail. There are no schema, movement-engine,
cost-engine, global isolation, UI, or permission-grant changes.

The materialized candidate CTE selects **at most limit+1 identities**;
its ordered detail-key CTE selects at most `limit <= 200`. The vehicle
aggregate is scoped to those keys, filtered by the tenant, live persisted
`inventory.read` grants, currently readable vehicle locations, and latest
route source warehouse. Warehouse projection, product lifecycle/hold state,
warehouse/vehicle quantities, purchase-cost and UOM enrichment all belong to
**one PostgreSQL READ COMMITTED statement snapshot**. The initial
warehouse authorization, projection-readiness check (which can repair and
commit), and this final statement are distinct queries. The snapshot does
**not** extend to separate cursor pages, other APIs, or concurrent revocation
between the preliminary warehouse authorization and the statement.

Before/after SQL barriers delegate to real DB statements without mocked data.
An interleaved committed V->W transfer produces a coherent W=10,V=10 or
W=20,V=0 response; not W=20,V=10. The original sellable-positive invariant
remains asserted and additional before/after controls pass. Real ledger and
balance cross-checks preserve physical total 20, cost quantity 20, inventory
value 40, exactly one receipt cost event, rollback/idempotency and cross-tenant
denial within the tested paths. No skip/xfail assertion dilution observed.

### Independently inspected raw 50,000-stocked-variant SQL plan artifacts

[Artifact 12947426937](https://github.com/MohHamdallah1/wanasah/actions/runs/40986490709/artifacts/12947426937)
contains both `r1-query-plans-FIFO.json` and
`r1-query-plans-MOVING_AVERAGE.json`: **128 recorded page scenarios each**
(98 single-statement, 30 test-only repeatable-read legacy comparisons).
Across all 196 new-query cases, SQL execution count is exactly **4** for
page sizes 1/50/200 and search/filter/cursor cases; the corresponding
legacy comparison uses 5 (owner) or 6 (restricted) statements. The maximum
returned row count is 200. This proves bounded page results and measured
statement counts, **not** that every predicate avoids scanning large tables.

Selected actual FIFO plans; all durations in **milliseconds of SQL execution**
(not browser time; single-run synthetic host, not p95):

| Query (limit 50) | New full-query SQL total | Legacy RR full-query SQL total | New page statement |
| --- | ---: | ---: | ---: |
| Owner, unfiltered | 0.92 | 0.76 | 0.83 |
| Restricted, unfiltered | 16.28 | 14.90 | 16.15 |
| Owner, broad `Common` | 249.21 | 249.09 | 249.08 |
| Restricted, broad `Common` | 348.92 | 338.99 | 348.77 |
| Restricted, `has_vehicle` | 27.90 | 27.68 | 27.74 |

Additional measured FIFO single-statement scenarios: restricted two-character
`Co` search (50 results) **344.80 ms**, owner minimum-unset filter
**263.46 ms**, restricted no-match out-of-stock **158.86 ms**, and restricted
no-match unavailable **171.65 ms**. Moving-average repeats show the same
scale (restricted `Common` 346.92 ms; `Co` 344.75 ms). Broad-search plans
show about **300k–500k shared-buffer hits** on this warm synthetic database;
many rows are inspected before the bounded page keys are returned.
Sparse/negative filters also inspect many candidates to establish no match.
No assertion or approved SLO bounds elapsed time, and no production-representative
load/concurrency or HTTP/browser latency test was performed. The observed
performance is comparable to, but not a blanket improvement over, legacy SQL.
The repeatable-read comparison is test-only and does not introduce a runtime
transaction-isolation change. No speculative indexes or unbounded loading
are authorized by these findings alone.

### Residual gates and independent recommendation

- **PASS** focused R1 coherence, candidate/detail identity, expected cursor
  order/keyset, bounded returned page, tested capability/location isolation,
  read-revocation, RLS, cost conservation and F1 regressions on the original
  tested SHA. Unverified real-world flows must not inherit this PASS.
- **FAIL** unrelated `CP2 Batch Index` run
  [40986490760](https://github.com/MohHamdallah1/wanasah/actions/runs/40986490760):
  functional steps passed; the old exact-file ownership audit failed on
  legitimate R1 changed files. Assign to CP2 owner; never hide, skip or relax
  security/integrity checks to make the status green.
- **OPEN** HTTP-level login/authentication admission and authorization across
  the actual dependency chain; integration/browser behavior; external
  concurrent grant-revocation timing; production-representative query mix,
  p95/p99 and permitted latency budget; broader stocktake/settlement/offline
  authority paths and Live Stock R2/other closure items.
- **Recommendation:** the minimal R1 correction is **technically acceptable
  for lead code review on the focused evidence**, but **NO-GO for merge/release
  approval until the lead explicitly accepts the documented residual risk
  and addresses blocking CI policy/required gates**. Leave PR DRAFT and
  UNMERGED. This documentation-only commit does not replace or rerun the
  PostgreSQL results cited for `8ed79adf`.
