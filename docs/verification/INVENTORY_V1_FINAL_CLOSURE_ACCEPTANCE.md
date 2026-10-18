# Inventory V1 independent final-closure acceptance

Status: **BLOCKED / NOT CLOSED**. This is an acceptance-worker artifact, not plan approval.
Assigned base: `8231ca07f945feb61737e7b4ac6150846cba60a8`.
Assigned branch: `codex/inventory-v1-closure-acceptance`.

## Frozen scope

Only the four remaining master-plan entries are in scope:

| Master entry | Required outcome | Coverage / outstanding evidence |
| --- | --- | --- |
| CP8.2 (line 580 at assigned base) | Compact permission-gated Quality destinations utility; same-location default | Backend one-Warehouse status/staging cases prepared. Compact Warehouse utility DOM acceptance awaits implementation. |
| CP9 (line 613) | One Operations/Home yellow-card settlement entry; inventory phase internal | Real Stocktake DOM rejects a duplicate vehicle-settlement start, in Arabic and English. Positive yellow-card inventory-to-finance journey awaits Backend contract. |
| CP14.1 (line 789) | One-Warehouse quarantine, DAMAGED, disposal/vendor staging | Real PostgreSQL quantity status, transaction rollback, concurrency, replay, payload conflict, capability revocation, location/tenant isolation and Ledger checks. Default staging cases are strict failures until integrated. |
| CP14.6 (line 828) | Exact Vehicle-to-Warehouse handoff, preserved variance, later financial close without recount | Existing field route no-auto-transfer/variance checks and real HTTP financial isolation/bypass regression. Financial modal DOM prohibits editable stock recount. Positive receiver handoff and post-handoff financial close remain unwired. |

Authorities read at the assigned base:
`V1_SCOPE_FREEZE.md`, `ARCHITECTURE.md`, `.rules`,
`.cursor/rules/business-workflow-protection.mdc`, `AGENTS.md`,
`PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`,
`INVENTORY_WAREHOUSE_V1_END_TO_END_CLOSURE_PLAN.md`, and
`INVENTORY_DAMAGED_GOODS_RETURNS_AND_REPRESENTATIVE_SETTLEMENT_PLAN.md`.
No plan checkbox or production file is changed. Flutter, terminal disposal/vendor
exit, costing redesign, account grants and other completed master items are outside this assignment.

## Independently observed baseline gaps

1. `services.resolve_special_transfer_direction_context` requires a published
   destination policy and rejects an explicit source-equals-destination with
   `SPECIAL_TRANSFER_SAME_LOCATION`. The base policy DTO rejects null defaults.
   The existing low-level whole-product IN_PLACE policy does not prove the public
   quantity/default-policy workflow or the compact Warehouse utility.
2. Stocktake exposes its own visible Vehicle Recon start. Operations currently
   opens the financial report/modal, rather than an integrated receiver phase.
3. The field reconciliation DTO accepts aggregate product quantities only.
   An exact aggregate match seals snapshots without a receiver-confirmed
   Vehicle-to-Warehouse movement. A mismatch opens VEHICLE_RECON but does not prove
   exact Batch/status receiving evidence or custody handoff.
4. `dispatch.settle_session` checks the old inventory seal/snapshot, with no
   receiver-handoff evidence requirement. It can financially close while the
   AVAILABLE/DAMAGED balances remain on the Vehicle.
5. The financial modal still has editable carton/loose-pack stock counts and
   Operations sends `inventory_jard`. Backend compatibility validation must remain
   until supported clients migrate; acceptance does not authorize deleting it.
6. Financial settlement has no request-id payload binding or stored replay result.
   A duplicate 409 plus no second mutation is not proof of durable lost-response recovery.

## Prepared executable coverage

`wa_backend/tests/test_inventory_v1_final_closure_acceptance_postgres.py` uses the
accepted CP8 disposable PostgreSQL fixture and its strict URL, runtime-role,
migration-head checks. It then creates separate canonical, non-Owner tenants with
exactly one Warehouse each, a distinct Vehicle custody location and real field identity.
All balances come from the movement engine; no balance or completed handoff is fabricated.
Runtime uses NOSUPERUSER/NOBYPASSRLS, with forced-RLS checks and cross-tenant reads.

Nine collected cases cover:
- same-location QUARANTINED quantity split and preserved DAMAGED opening stock; exact Batch/status and Ledger;
- failure after a real movement before commit, then successful retry of the same request;
- concurrent duplicates, lost-response replay, different payload rejection and revoked replay;
- default disposal/vendor staging of AVAILABLE and DAMAGED in the only Warehouse, with no transit/external exit;
- denied capability and opaque foreign/missing work-session financial requests through
  the real FastAPI capability dependency and canonical subject resolver;
- unsealed financial rejection with unchanged balances, movements, snapshots, seal and audit;
- aggregate field reconciliation/retry without automatic custody transfer;
- one persistent variance review on retry, and financial refusal while unresolved;
- financial refusal when only the legacy aggregate seal exists and no receiver confirmed handoff.

The four staging cases use the null-destination DTO published on the quality worker
branch below; they fail on the assigned base rather than silently skipping.
They do not assert that an entirely unpublished policy must automatically work.
The policy provisioning is fixture setup, not a requirement to expose draft/publish
internals to the operator. Before closure, verify the effective default through the
actual Warehouse utility and discovery APIs as well.

`dashboard/src/test/inventory-v1-final-closure-acceptance.test.tsx` renders real
Stocktake and financial modal components (four Arabic/English DOM cases).
Only access/read transport boundaries are mocked; the visible action and quantity
widgets are real. These tests establish neither login nor positive yellow-card handoff.
The numeric-input assertion permits editable cash and read-only stock context.

The dedicated workflow runs the tests on GitHub-hosted runners and disposable
PostgreSQL 16 with a fresh Alembic bootstrap. It uploads JUnit even on failure,
rejects skipped/missing Backend cases, and proves the exact four-file acceptance-only
delta from the assigned base. No xfail, continue-on-error, simulated database,
seed execution against a user database, or runtime repair is used.

## Exact contracts still needed from implementation owners

No endpoint, DTO, permission or evidence-column names are invented for the missing
receiver flow. Before wiring its positive acceptance, obtain and pin:
- Yellow-card eligibility/read contract for an ended, unsealed session; server-owned
  expected rows by product + Batch + status; destination Warehouse and receiving actor.
- The receiver confirmation command, exact capability/location scopes, stable operation
  identity, changed-input conflict, response/recovery contract and evidence links.
- Relationship between receiving, variance recount/approval, final inventory seal and
  financial readiness; treatment of a legitimate no-stock session.
- Financial request/recovery contract that consumes the sealed handoff without another
  stock count, preserves the legacy supported-client boundary and returns safe errors.

Required positive PostgreSQL journeys after those contracts exist:
- Expected AVAILABLE 6 + DAMAGED 4; receive 6 + 4 into the one Warehouse. Move exact
  Batch/status quantities once, preserve company total/value, clear those Vehicle
  portions, link work session/Vehicle/receiver and expose both custody legs in Ledger.
- Expected DAMAGED 4, received 3: keep the missing 1 explicit alongside expected,
  physically received, variance, recount/approval history. Do not erase it by counting
  Warehouse stock as evidence of what was handed over. AVAILABLE remains AVAILABLE;
  DAMAGED remains DAMAGED; every additional supported status is preserved.
- Different Batch/status inputs with equal product totals must not conceal a variance.
  Concurrent receivers, double-click, timeout/lost response, changed payload, stale
  scope/capability, foreign tenant, wrong Vehicle/Batch/Warehouse, reserved stock and
  failure after the first real movement must produce no partial/duplicate handoff.
- Financial close before handoff or with unresolved variance must fail atomically.
  After a real approved seal, close with actual cash/required difference notes, no
  `inventory_jard` from Dashboard and no changes to balances, movements, sealed snapshots
  or custody links. Reconcile/replay ambiguous results without duplicate financial audit.
- Reload a Vehicle only as a separate new custody/load operation; never reopen/edit the
  closed handoff. Verify permission denial on the actual APIs, not a mocked can() check.
- Compact quality utility must work with one Warehouse in both locales, exact capability
  gating, effective same-location defaults, safe retry and no permanent settings card.

These are **pending coverage / acceptance blockers**, not green tests and not waivers.
Do not declare the four master items closed on the nine-case baseline alone.

## Implementation-branch readiness observed remotely

- Quality: `sol/inventory-quality-destinations-v1-closure` at
  `651c71c27f288093de5c629ac29c6946f78a096c`: draft backend changes add nullable
  destinations and in-place staging. Not integrated or accepted by this worker;
  compact Warehouse UI not present in that observed diff.
- Dashboard: `sol/representative-settlement-v1-dashboard` at
  `4f3885f8abb42c10db21e8c3549861640667c0b5`: removes duplicate Stocktake entry
  and editable financial recount, stops sending inventory_jard. It does not supply
  the missing positive yellow-card receiver API flow.
- Backend: `sol/representative-settlement-v1-backend` still at assigned base
  `8231ca07f945feb61737e7b4ac6150846cba60a8`: receiver command/evidence unavailable.
- No implementation branch was merged, copied or cherry-picked into acceptance.
  Tests execute the acceptance branch source, not the unintegrated worker snapshots.
  Lead must supply a combined candidate and exact receiver contracts for final acceptance.

## Execution evidence

First run on `3e050e1db785acee2d17e66abc28fa080c95d9d0`
([run 39135564836](https://github.com/MohHamdallah1/wanasah/actions/runs/39135564836))
exposed a fixture error: CP8 seeds explicit Vehicle IDs without advancing the sequence,
so this worker's automatic Vehicle IDs collided. Fixed in this test fixture only,
using a disjoint company-unique synthetic ID; accepted fixtures/runtime are untouched.

It also exposed an invalid acceptance assumption: the existing generic status command
deliberately forbids AVAILABLE-to-DAMAGED. The plan preserves that command matrix;
it does not authorize a new manual damage classification route. The test now checks
QUARANTINED via the supported command and DAMAGED via real movement opening evidence
and both same-Warehouse staging purposes. Positive DAMAGED custody receipt remains
blocked on the receiver contract; no status guard is relaxed.

The initial financial bypass case independently reached HTTP 200 without handoff,
rather than required 409. All four real DOM checks reached the expected business
assertions and failed (duplicate start, three editable numeric fields instead of cash
alone). Lint and exact four-file scope passed. These are distinct from fixture errors.
The initial push run was superseded by the PR-triggered run; no cancelled overall
run is reported as a completed acceptance pass.

PR #399 was opened against main, then closed unmerged because the assigned base itself
already contains 13 commits / 22 inherited files ahead of main. Review only the four-file
delta from the assigned base; this worker proposes no inherited runtime change.
Final corrected-fixture execution evidence is pending.
Expected baseline failures are real closure failures: null-policy staging, duplicate
Stocktake entry, editable financial stock recount and financial close without handoff.
Fixture/import/infrastructure failures must be repaired in tests/workflow and reported
separately; they cannot count as proof of these business gaps.
