# Inventory V1 combined-candidate final gate

**State: PREPARED, NOT ACCEPTED. No combined candidate SHA has been supplied.**
Acceptance branch: `codex/inventory-v1-closure-acceptance`.
This assignment starts at `da045688c1778d1b5c2c2c3da62fb480555b5617`.
Frozen negative-control source: `8231ca07f945feb61737e7b4ac6150846cba60a8`.
All former worker-SHA matrix entries are removed. Earlier pinned-worker results are
historical evidence at the preceding audit commit, not current or final truth.

## Lead invocation and authoritative result

Run `.github/workflows/inventory-v1-final-closure-acceptance.yml` from this acceptance
branch with required workflow_dispatch input `candidate_sha`: one full 40-character
commit SHA in this repository containing the lead's combined implementation.

```sh
gh workflow run inventory-v1-final-closure-acceptance.yml \
  --repo MohHamdallah1/wanasah \
  --ref codex/inventory-v1-closure-acceptance \
  -f candidate_sha=FULL_40_CHARACTER_COMBINED_COMMIT_SHA
```

Do not supply a branch name or short SHA. The source must descend from the approved
frozen base. Both Backend and Dashboard check out the SAME candidate commit and
verify its resolved HEAD. The harness is separately checked out at this run's exact
acceptance SHA. Only acceptance test files are overlaid in disposable GitHub runners;
no runtime patch, source merge, cherry-pick or branch mutation constructs a candidate.

The only authoritative success is the job **Final combined-candidate verdict**:
`FINAL_INVENTORY_V1_COMBINED_ACCEPTANCE=PASS`.
It requires scope/self-check success, both verified frozen negative-control reports,
and both candidate reports with identical candidate/harness SHA provenance.
Missing SHA, missing/mixed reports, partial execution, test failures, setup errors,
skips/xfails, duplicate cases or wrong case counts cannot produce PASS.
A normal push validates harness preparation and baseline evidence, but is deliberately
RED at the candidate/final gate when no lead SHA is provided. That is not release failure evidence.

## Coverage required on the combined candidate

| Suite | Executed cases | Source and requirements |
| --- | --- | --- |
| PostgreSQL baseline | 13 | Frozen base; exactly 4 passing invariants and 9 identified negative-control failures |
| DOM baseline | 4 | Frozen base; exactly 4 identified duplicate-entry/recount failures |
| PostgreSQL candidate | 23 | ALL original 13 plus 10 combined contracts; no selection filter |
| DOM candidate | 16 | Original 4 plus 5 complete journey and 7 quality truth cases; no selection filter |
| Gate verifier unit tests | 7 | Missing/mixed provenance, failures, skips/errors, omitted financial case, partial/duplicate execution and false negative controls |

The baseline verifier checks failure identity AND diagnostic evidence. A generic
nonzero pytest/Vitest exit, import error or broken fixture does not count as a known
business failure. The original assertions remain unchanged; they are executed as
ordinary strict tests, never xfail or continue-on-error. Baseline evidence is recorded
separately from candidate acceptance.

The baseline-only environment flag preserves the old financial request shape solely
to reproduce frozen negative evidence. Candidate mode forbids that flag and always
sends request_id. No runtime-schema detection or legacy request fallback can turn a
candidate green. Expected case counts are acceptance-owned, not candidate-supplied.

### Complete representative journey

The API tests use actual FastAPI routes/canonical capability dependencies and the
restricted PostgreSQL runtime identity. Only authenticated test identities and
database connection boundaries are overridden. Full-app route registration is checked.
Synthetic actors have distinct principal/profile/operational IDs and no Owner link.

Required evidence:
- Preview both AVAILABLE and DAMAGED by exact public Batch/status; preview does not receive.
- Explicit receiver confirmation transfers exact Vehicle-to-Warehouse quantities once,
  preserves statuses, work session and actor evidence, exposes Warehouse Ledger context
  and immutable before/after impacts for both custody locations.
- Preserve DAMAGED expected 4 / actual 3 / variance -1. Equal aggregate totals with
  different status quantities must not conceal a variance.
- Initial actor cannot perform the required independent recount; authorize another
  canonical user, return a blind count sheet, submit an independent attempt, then
  approve through the business WorkSession endpoints. Original and recount evidence
  remain 4/3/-1 after approval and handoff.
- Approval does not itself receive stock or enable financial close. A later explicit
  receiver command moves AVAILABLE 6 + DAMAGED 3 after the approved shortage.
- Later reload calls the real POST /dispatch/route command, creates a distinct active
  route/new pre-session load with DISPATCH_LOAD evidence and no old work_session_id.
  Old route, seal, snapshots, financial audit and closed settlement stay immutable.
  Recovering the old receiving command must not consume the newly loaded stock.
- Fresh/revoked/foreign/wrong-scope commands fail; abort between custody movements
  rolls the entire transaction back; identical request retry recovers once.

Commercial evidence for shortage/reload is arranged in test fixtures: effective
published price/assignment, immutable old route context, explicit zero tax publication
and published commercial rounding. No price/tax/custody service is mocked and no
completed receiving audit, inventory seal or balance is fabricated.

The positive DOM tests render the real OperationsDashboard, FleetRadar, CommandCenter
and settlement components. Only authenticated transport/access boundaries are mocked.
They start with an ended UNSEALED work session and require an enabled single yellow-card
entry, preview, actual status counts, receiving and later financial close. A discrepancy
journey switches canonical test identity for recount, then returns to the reviewer for
approval and explicit handoff. Arabic and English are both exercised.
The established Stocktake test still forbids a second settlement start.
Accessible business labels are required for counts, Warehouse, confirmation, cash,
authorizer/recount and approval; tests never require database/Stocktake IDs from users.
No test-only settlement component or mocked workflow hook can bypass missing UI wiring.

### Strict financial lost-response contract

`test_financial_lost_response_requires_bound_original_success_replay` first completes
a REAL receiver handoff, then submits PUT /admin/sessions/{id}/settle with:
request_id, actual_cash and notes, and NO inventory_jard.
It deliberately drops the response AFTER the server returns success/commits.
Required outcomes:
1. Identical same-ID sequential/concurrent retries return HTTP 200 and the ORIGINAL
   success payload, not a generic already-closed 409.
2. Changed amount/notes with that same ID returns 409.
3. A fresh request ID after closure returns 409.
4. Exactly one FINANCIAL_SETTLEMENT audit/effect exists.
5. Balance, movement, sealed snapshot and seal evidence do not change during close/replay.
The DOM lost-response case also requires identical wire identity/payload on retry,
one financial effect, and no inventory_jard in any mutation.
These are required positive assertions. No state-idempotency-only fallback is accepted.

### Quality destinations

Four new first-action cases start with exactly one Warehouse and NO destination-policy
rows. Opening the policy state is read-only. Quarantine, AVAILABLE disposal, DAMAGED
disposal and DAMAGED vendor staging must work through the public command without
prior draft/publish/setup or artificial Warehouse creation; only the mutation may
materialize immutable effective-default policy evidence. Quantity/status stays exact.

Separate legacy coverage creates a legitimate second Warehouse and publishes an
explicit policy through canonical APIs. GET leaves its identity/revision/payload
unchanged, real special dispatch routes there, and normal receipt posts stock there.
No legacy policy is replaced with the default to make the test pass.

Capability/tenant/location checks include denied policy reads, foreign-vs-missing
opaque references, no partial policy on rejection, other-company invisibility,
revoked explicit-reference location.read and revoked inventory.transfer_policy.manage.
Existing command authorization/replay/transaction tests remain active.

DOM quality cases open the real Warehouse utility with one Warehouse and require:
GET-only opening; no permanent extra setup workspace/picker; per-locale direction;
explicit legacy destinations shown truthfully; mixed defaults truthfully per field;
no previous-company routing while a new scope loads; exact capability gating.
An unknown/loading policy MUST NOT be falsely labelled same-location/default.
This last assertion deliberately catches a misleading default flash before a legacy
policy response is known. Opening must never silently rewrite the policy.

## Expected red results until runtime work lands

Current remote observations are diagnostics only, not final candidate pins:
- The observed Backend settlement DTO rejects request_id. The strict financial
  lost-response test will fail at FINANCIAL_STABLE_ID_CONTRACT_REQUIRED (422);
  candidate financial journeys expecting the new request contract also remain red.
- The observed Dashboard still enables settlement only after old inventory sealing
  and opens the financial report directly. Positive unsealed yellow-card and
  end-to-end variance/lost-response DOM tests must fail until that wiring lands.
- The observed quality card renders same-location/default before its read completes;
  the explicit-legacy loading and company-switch tests must stay red until truth is known.
- Missing receiver/recount routes, missing quality default migration/first-action
  handling, absent real reload commercial evidence or broken full-app wiring will
  fail their concrete contracts, never be silently deselected.
- No combined candidate was supplied in this request. No combined-candidate PASS is claimed.

## Scope and execution record

Owned paths are two PostgreSQL test files, three DOM test files, the pure report
verifier and its unit tests, this audit and the workflow (nine files total from the
original frozen base). The workflow proves ancestry and exact path ownership from
both the original base and this assignment's starting HEAD, plus git diff --check.
No production runtime, migration, plan checkbox, application grant, local machine
or user database is modified. No merge, new branch or PR is required.

Preparation CI results will be recorded after the acceptance-only push. Full positive
candidate execution awaits the lead-supplied SHA. Updating only this evidence document
does not rerun unchanged acceptance source.
