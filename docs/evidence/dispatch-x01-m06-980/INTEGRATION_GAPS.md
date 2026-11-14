# X01 / M06 focused real integration evidence — Issue #980

**Baseline:** frozen [C03 PR #978](https://github.com/MohHamdallah1/wanasah/pull/978) at `7853816ac2d9fd618b9eee5451e2f23db420fd23`. New independent branch is test/evidence-only. Historical [M06 PR #948](https://github.com/MohHamdallah1/wanasah/pull/948) at `f67c2ffa859ac66a356a1920b16ebad2562ed5e2` was read, **not cherry-picked, run again, or edited**.

## Acceptance source matrix

| Stage | Evidence | Status |
|---|---|---|
| Historical stocked vehicle blocked; manager + independent FIELD physical signature, same-company snapshot, no implicit movement; authoritative availability changes | Already certified C02/C03, 8 real C03 Chromium images; X01 uses exact production helper `accept_prepared_vehicle_by_real_http` as real signed prerequisite | **PASS, now composed into X01** |
| Largest unambiguous configured outer UOM plus exact BASE remainder; 3 × 8 + 3 = 27 | **NEW** X01 signed UOM GET and immutable launch `inventory_base=27`, current 25; foreign GET denied | **PASS** |
| Load +2, then reverse unload -3, full BASE/batch/status ledger and no cost creation; lost-201 lookup and UUID replay; foreign denial | **NEW** X01 actual PostgreSQL restricted RLS/HTTP route and adjust writes; original UUID replay does not inflate stock; end balance 24 | **PASS** |
| Same vehicle after C03 and UOM operations: POSTPONE releases car; RESUME with original signed epoch; no stock movement | **NEW** X01 real signed M02 lifecycle on that exact loaded vehicle | **PASS** |
| One S1 A→B→A, visits/sales 12/7/5, cash 3.000, COUNT_IN_PLACE both cars, deny S2 until full settlement, S2 with carried A83/B53 | **Previously accepted** M06 PR #948: real restricted PG16 1/1, Flutter signed client 1/1, Chromium 4/4, 11/11 CI. **Not repeated** | **PREVIOUS PASS; NOT run inside X01's new fixture** |
| A single newly executed post-C03/UOM S1→A→B→A→two-car settlement→S2 physical browser sequence | Not represented by the small new bridge test or the old M06 independent fixture. Do not claim evidence that has not been produced. | **INTEGRATION LIMIT / LEAD DECISION** |
| AR/EN × 1440/390 visual owner signoff | Existing 8 C03 before/after and M06 12 real screenshots. See `OWNER_VISUAL_ACCEPTANCE.md` | **PENDING OWNER** |
| Main-target D15 historical BEFORE gate and dependency sequencing | Separate Worker2 #976/#979 and LEAD workflow ownership; #978 and M06 #948 remain independent | **PENDING LEAD** |

## New local X01 PG16 proof

**One new test:** `wa_backend/tests/test_dispatch_x01_custody_uom_m06_bridge_postgres.py::test_x01_signed_custody_then_uom_load_unload_and_m06_reentry_no_phantom_stock[FIFO]`.

**Result:** **1 passed; 0 failures; 0 skips**, 28.65 seconds, on a fresh **isolated PostgreSQL 16.15** cluster bound to 127.0.0.1:55439 and a disposable database `wanasah_no_lot_contract_test`; migrations to repository head `e4b7c9d2a601` and Alembic no-drift **PASS**. Runtime role `wanasah_app` returned `rolsuper=false`, `rolbypassrls=false`; `inventory_movements`, `vehicle_custody_epochs` and `dispatch_route_execution_periods` all reported `relrowsecurity=true` and `relforcerowsecurity=true`. Synthetic credentials and the independent FIELD proof were never committed.

**Observed real state:** blocked stocked car 25 BASE → true FIELD physical confirm and manager ACCEPTED, **zero movements** on custody; UOM factor eight + three base reaches signed target **27 BASE** (+2 physical); a lost *committed* 201 recovers by original operation UUID and replay is movement-identical; actual signed adjustment returns three BASE to warehouse, final vehicle **24**; adjustment replay is movement-identical; POSTPONE → RESUME retains inventory exactly unchanged; cross-company foreign manager and unsigned launches rejected. Backoffice stock/car data remained company-scoped.

**Local non-failing warnings:** pytest configuration reported an unknown `asyncio_default_test_loop_scope` option under the temporary pytest-asyncio installation, and Starlette reported a `python_multipart` deprecation; neither skipped tests nor invalidated RLS/HTTP assertions.

**CI separation:** X01 adds a new test file with opt-in `RUN_X01_M06_PG16=1`. Existing GitHub workflow YAML was NOT edited. Default PR CI alone may not execute this opt-in new database gate. LEAD owns an exact-path dedicated X01 CI job/allowlist if official remote execution is required. Never describe unrelated green workflows as X01 PG16 execution.

**Never merge standalone:** LEAD must coordinate all stacked C01/C02, C03, U02/U03, D15 and M06 before main promotion. No company, location, inventory or role safety checks are bypassed. Owner visual sign-off remains explicitly pending.
