# Live Stock R1 PostgreSQL proof gate

Assigned base: 59b760b59b21b0438ba920067d58b5face2555e9.
Branch: codex/live-stock-snapshot-integrity-proof.
Frozen V1 workflow: trustworthy warehouse/vehicle operational stock visibility.
Scope: integration tests and isolated CI only. PR #605 owns live_stock.py.

## Evidence status

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

## Deterministic read boundaries

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

## Narrow correction proposal for the lead (not implemented)

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

Conclusion: R1 is reproduced as a read inconsistency. The tested canonical
movement path conserves physical custody and ledger/value evidence. The overall
read-integrity gate FAILS and remains a release blocker. This proof branch does
not implement a correction or authorize editing the lead-owned live_stock.py.
