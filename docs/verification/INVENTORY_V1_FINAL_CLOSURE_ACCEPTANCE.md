# Inventory V1 independent final-closure acceptance

**Verdict: NOT CLOSED.** Only acceptance tests, workflow and this audit are changed.
Assigned base: `8231ca07f945feb61737e7b4ac6150846cba60a8`.
Existing branch: `codex/inventory-v1-closure-acceptance`.
No runtime, migrations, plan checkboxes, identity permissions or user database is modified.

## Four remaining master entries

| Entry at assigned base | Required acceptance | Prepared coverage / remaining blocker |
| --- | --- | --- |
| CP8.2, line 580 | Compact permission-gated Quality destinations utility with same-location default | Public policy/staging tests prepared; utility end-to-end/default discovery and account-scope UI verification still required. |
| CP9, line 613 | One Operations/Home yellow-card entry; internal inventory/custody phase | Real bilingual Stocktake DOM rejects duplicate start. Positive yellow-card receiver-to-financial journey is not implemented in observed Dashboard worker. |
| CP14.1, line 789 | One-Warehouse quarantine/DAMAGED/disposal/vendor staging | Strict PostgreSQL quantity/staging, status preservation, retries, concurrency, rollback, authorization, RLS and Ledger assertions. |
| CP14.6, line 828 | Exact Vehicle-to-Warehouse handoff, explicit variance, later financial close without recount | Positive receiver, exact-status variance, rollback/replay and financial no-stock-mutation tests now use the actual Backend worker contract; combined-candidate acceptance remains required. |

Authorities read at the assigned base: `V1_SCOPE_FREEZE.md`, `ARCHITECTURE.md`,
`.rules`, `.cursor/rules/business-workflow-protection.mdc`, `AGENTS.md`,
`PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`,
`INVENTORY_WAREHOUSE_V1_END_TO_END_CLOSURE_PLAN.md`, and
`INVENTORY_DAMAGED_GOODS_RETURNS_AND_REPRESENTATIVE_SETTLEMENT_PLAN.md`.
Completed master items, Flutter, terminal financial disposal/vendor exits and costing
redesign are not reopened. No unchecked item is marked accepted.

## Baseline findings

- Default policy DTO rejects null destinations. Explicit source-equals-destination
  special handling raises `SPECIAL_TRANSFER_SAME_LOCATION`. Existing low-level
  whole-product IN_PLACE behavior does not prove the public default-policy workflow.
- Stocktake exposes a separate Vehicle Recon start. Operations opens financial
  settlement directly; its current entry cannot start an unsealed receiver workflow.
- Field aggregate matching seals Ending Snapshot without moving remaining Vehicle
  stock. Variance opens VEHICLE_RECON but does not prove exact receiving custody.
- Financial close checks the old seal, without a receiving-handoff check. The
  independent real HTTP test reproduced 200 while 6 AVAILABLE + 4 DAMAGED remained
  on the Vehicle and no responsible receiver had confirmed handoff.
- Financial modal has two editable stock count widgets beside cash; Operations
  sends legacy `inventory_jard`. Keep Backend compatibility until supported clients migrate.
- Financial close DTO still has no stable request ID/payload binding or original
  response replay. A repeated 409 alone does not establish safe lost-response recovery.

These are assigned-base findings. Worker branches contain proposed fixes; they must
not be represented as already integrated or accepted.

## Tests and isolated GitHub execution

The Backend file contains **13 cases**: four baseline invariants, four default
staging cases, one legacy-seal bypass regression, and four receiver contract cases.
Fixtures create canonical non-Owner operators, a real separate Field identity,
two isolated tenants, exactly one Warehouse per tenant and distinct Vehicle custody.
All starting stock uses Unified Inventory Movement, never direct balance writes.
The accepted CP8 fixture supplies strict disposable PostgreSQL 16 URL/runtime-role
and Alembic-head checks. Forced RLS and foreign-tenant invisibility are asserted.
No production seed/bootstrap is run.

Coverage includes:
- QUARANTINED quantity split; existing DAMAGED remains separate; exact Batch/Ledger;
- abort after a real status movement, same-ID retry, concurrent duplicates,
  changed payload conflict, denied locations/tenant and revoked-capability replay;
- same-Warehouse default disposal/vendor staging of AVAILABLE and DAMAGED, preserving
  total quantity/status and creating no transit or terminal exit;
- actual FastAPI capability dependencies and canonical subject resolution for financial
  and receiver routes; only authentication identity and restricted DB are overridden;
- no implicit handoff on field aggregate match/opening a receiver preview;
- persisted aggregate variance and no premature financial close;
- exact 6 AVAILABLE + 4 DAMAGED receiver handoff, concurrent replay, immutable actor/
  work-session/Batch/status evidence and visibility from both custody Ledger locations;
- financial close after real receiving seal without changing balances, movements,
  snapshots or seal, and without sending inventory_jard;
- DAMAGED expected 4 / actual 3 / variance -1 retained; equal product totals with
  AVAILABLE 5 + DAMAGED 5 must still create status-specific variance evidence;
- failure between first/second real custody movements rolls everything back, then
  same-ID retry succeeds; fresh duplicate and revoked permission fail safely.

The frontend file has **four real DOM cases** (Arabic/English): no independent
Stocktake representative start; financial cash remains editable while stock recount
does not. Access/read boundaries are mocked; Stocktake and numeric widgets are real.
These tests do not prove a positive yellow-card journey.

The workflow tests pinned workers independently by checking out their exact source
and overlaying **only this worker's test file** in the disposable GitHub runner.
It does not merge, cherry-pick, push or alter their runtime. Git diff checks verify
runtime is unchanged. The acceptance branch also retains strict baseline execution.

| Job | Exact source | Selected cases |
| --- | --- | --- |
| PostgreSQL assigned-base | Acceptance commit (runtime equals assigned base) | All 13; missing receiver module is an explicit failure, never skip |
| PostgreSQL receiver-worker | `f4bb3834cad5312c40b118882bb2dca5bbd664f8` | 9 receiver/financial/status/field cases |
| PostgreSQL quality-worker | `02b5ea4cd59b653ff66c3f4b7662c342b3b7c8ed` | 5 one-Warehouse status/default-staging cases |
| Dashboard assigned-base | Acceptance commit | 4 DOM cases |
| Dashboard worker | `4f3885f8abb42c10db21e8c3549861640667c0b5` | Same 4 DOM cases |
| Acceptance scope | Assigned base to acceptance HEAD | Exactly four new test/workflow/audit files; diff whitespace check |

Case counts are enforced per PostgreSQL selection; skipped coverage fails. JUnit is
uploaded even on failure. There is no xfail, continue-on-error or simulated database.
Independent worker passes cannot establish a combined-candidate release pass.

## Actual receiver contract observed on Backend worker

`GET /admin/sessions/{id}/inventory-custody`:
`settlement.read` plus `inventory.read` at Vehicle location. Returns opaque
`line_key`, public Batch, stock status and expected quantity, plus received/review/seal state.

`POST /admin/sessions/{id}/inventory-custody/receive`:
`settlement.execute`, Vehicle `inventory.read`/`transfer.send` and receiving
Warehouse `transfer.destination`; discrepancy creation also needs Vehicle
`stocktake.start`/`stocktake.count`.
Body: request_id, destination_location_id, receiver_confirms_handoff=true,
items[{line_key,actual_quantity}], notes.
Successful states: CUSTODY_RECEIVED or REVIEW_REQUIRED. Variance persists canonical
Stocktake session/attempt/lines; exact receiving uses PHYSICAL movements with unchanged
status, work_session_id and REPRESENTATIVE_CUSTODY_RECEIPT reference.
The proposed financial guard requires REPRESENTATIVE_CUSTODY_RECEIVED audit evidence.

No new endpoint or business authority was invented by this acceptance worker.
The Backend worker's own tests are supporting evidence, not substituted for independent tests.

## Remaining closure blockers / unverified contracts

1. Supply a lead-approved combined candidate. No worker snapshot is integrated here.
2. Positive yellow-card entry for ended/unsealed sessions, receiver submission,
   variance/recount/approval and continuation into financial close are still absent
   in observed Dashboard worker. Removing the extra button alone is insufficient.
3. Verify compact quality utility/default discovery with one Warehouse, exact
   capability gating, changed company, retry, keyboard/phone and both locales.
4. Complete the variance lifecycle through independent recount/approval and then
   exact physical receiving; retain original 4/3/-1 history. Test a real later reload
   as a separate new custody/load, never as an edit to the closed handoff.
5. Prove financial timeout/lost-response reconciliation, changed-input protection and
   one financial audit. Existing schema has no request ID; no retry guarantee is inferred.
6. Complete stale authorization/destination deactivation races, wrong Batch/Vehicle,
   reservations, additional supported statuses, empty-stock sessions and original-request
   recovery after financial closure. Do not fabricate a handoff audit or sealed snapshot.
7. Check canonical API error code/context/request ID in the full app, not only the
   isolated router harness; full app wiring and the integrated UI remain unverified.

## Execution evidence

- Initial `3e050e1` run exposed test-fixture Vehicle sequence collisions. Fixed only
  this worker's fixture with disjoint company-unique synthetic IDs.
- An initial test incorrectly assumed generic AVAILABLE-to-DAMAGED reclassification.
  The accepted transition matrix intentionally forbids it; no plan authorizes widening
  it. Coverage now preserves that matrix and tests DAMAGED opening/staging/receiving
  evidence through the real movement authority. No runtime status guard was relaxed.
- Corrected fixture at `b0ff10677f16323c9c29aa9ee57eb10fa67e7113`,
  [run 39135872839](https://github.com/MohHamdallah1/wanasah/actions/runs/39135872839):
  PostgreSQL **4 passed / 5 failed / 0 skipped / 0 setup errors**; failures are four
  null-default DTO cases and the reproduced financial handoff bypass. Dashboard
  **4 failed** at intended assertions; lint and exact four-file scope passed.
- Receiver implementation appeared during this audit; the four new receiver cases
  and pinned worker execution were then added. Their results are pending.
- PR #399 was opened against main and closed unmerged because the assigned base
  already includes 13 commits / 22 inherited files ahead of main. The worker delta
  is four files; inherited production changes are not proposed by this worker.

**No final acceptance or plan closure is granted by this artifact.**
