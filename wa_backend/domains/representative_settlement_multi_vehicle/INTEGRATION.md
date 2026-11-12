# M04 #942 — implementation and acceptance boundary

PR #944 stays DRAFT. This document does not claim integrated completion.
Starting MAIN: `3a588fcad0906020b1fc32b3806067aeb7db09b1`.
Merged M02 base: `6a312476858eb6322b79c082d54a1cc97e590228`.
M03 #943 has not merged. No M04 Alembic revision is created yet.

## Implemented independently

- Explicit per-session/per-vehicle read and signed POST count command. Strict
  snapshot, context, epoch revision, movement-watermark and exact line fencing;
  stable UUID/payload replay; actor/capability checks before replay disclosure.
- `COUNT_IN_PLACE` signs immutable checkpoint/epoch/lot/status evidence without
  calling the movement engine. `PHYSICAL_HANDOFF` requires both transfer scopes,
  an active warehouse and explicit receiver confirmation; the existing batch
  movement authority preserves each lot and quality status.
- A count mismatch creates the canonical VEHICLE_RECON header, location lock
  and immutable first count only. No correction, checkpoint or financial close.
  Vehicle-specific review/recount/count/approve delegates preserve the existing
  Stocktake command, password, independent recount, valuation and posting
  authorities. Lost-response retries reconstruct their original attempt rather
  than hashing the later latest attempt. Persistence is bounded/batched.
- The two LEAD-approved `services.py` helpers delegate canonical membership and
  per-location ending snapshots here. Their historical branches remain intact.
  A location seal never marks the entire day reconciled; all signed checkpoint
  coverage is required for that marker. No financial state changes here.
- Legacy `/receive` and its old unqualified variance paths reject canonical
  sessions. Historical one-car physical receipt remains available.
- `schema.py` contains DDL, not an Alembic head: tenant/FORCE RLS, composite
  tenant/vehicle/session FKs, immutable signed history, restricted INSERT/SELECT
  runtime grants and guarded downgrade. Final migration marker must be installed
  LAST; writers fail 503 without it and both scoped keys.
- Per-period shortage price seam resolves every applicable frozen context.
  Missing/ambiguous prices fail closed; the initial WorkSession context cannot
  price another car or silently choose first/last price.
- All-vehicle financial readiness preserves exact checkpoint/epoch coverage,
  movement fences, outstanding reconciliation/transfer guards and later signed
  custody succession. It computes no cash, debt or shortage totals.
- Canonical Vehicle Load ownership helper is prepared to block loads around an
  ended unclosed count while allowing a legitimately later accepted custodian
  after prior inventory is signed. Foreign-file hook is pending approval.

## Verified on the merged M02 base

84 focused tests PASS: 82 rule/controlled-port tests and 2 genuine isolated
PG16.15 restricted-runtime/Bearer tests. The latter use real Alembic schema,
NOBYPASSRLS, FORCE RLS, genuine login, no dependency overrides, tenant/location
denials and same-token revocation. Movement-engine fixtures reach A83/B53;
reading/count-schema rejection leaves balances and movements unchanged. The
historical one-car regression physically hands DAMAGED 2.125 to a warehouse and
replays financial settlement with exactly one audit. These fixtures do NOT
claim real M02/M03 FIELD sales/switching or new M04 signed-write acceptance.

`test_dispatch_m04_write_postgres.py` prepares genuine signed count, simultaneous
identical retries, all-car finance gate, immutable history and status/lot physical
handoff tests. Enable `RUN_M04_WRITES_PG16=1` only after the ordered migration;
schema absence must fail acceptance, never be skipped as a success. These tests
have not yet run against an activated M04 schema.

## Exact pending ownership/approval gates

1. Issue #942 comment 6820841575: Vehicle locks before location guards in
   `api/warehouse/stocktake.py::approve_stocktake_session` and
   `services.py::post_approved_stocktake_adjustments`; replace only that service's
   shortage price call with `period_pricing.resolve_recon_shortage_prices`.
   No other pricing/stock engine edits requested or applied.
2. Comments 6821160574 / 6821240342: legacy scripted/AST test fixture parity.
   New detector SELECT is absent from its historical SQL script. Two start
   harnesses already lack `begin_stocktake_command` on untouched M02 MAIN.
   No shared legacy test has been changed or skipped pending approval.
3. Comment 6821612544: tiny `resolve_vehicle_load_owner` hook to this module's
   canonical helper, reusing the loader's existing under-Vehicle-lock recheck.
4. Comment 6821645684: M03 end-work must freeze its ACTIVE canonical period with
   real signed ending actor/time. Normal end-work must not require the operator
   to postpone the route separately before M04 can count. No Worker1 file edited.
5. After M03 merge + LEAD exact MAIN: ONE M04 revision after M03; exact
   `models.py` index parity (company/session/location VEHICLE_RECON partial key)
   and registration of own checkpoint mappings require LEAD ownership approval.
6. Only then request the tiny `api/dispatch.py::settle_session` custody gate
   replacement. Keep replay before settled guard, WorkSession lock, legacy
   physical receipt branch and session-only financial sums byte-for-byte. No
   joins to periods/vehicles may multiply cash/debt/shortage evidence.

## Final acceptance still required

Actual M02/M03 A100→83 / B60→53 FIELD sales and A/B/A periods; normal end-work;
two signed matched counts with ZERO movements; correctly authorized reviewed
variance; physical DAMAGED handoff; UUID collision/replay and real load/count/
settle races; all-car money counted once; signed-history/RLS protection; S2 with
unchanged vehicle balances and independent counters; exact final HEAD CI.

MERGE READY: NO until all integrated acceptance passes. No Codex, no self-merge.

## Worker2 TAKEOVER — 2026-11-12, independent closure

Owner explicitly paused M05 Draft PR #946 unchanged and assigned Worker2 **same** M04 Draft PR #944 following original Worker3 HEAD `856f0becb9e924fa68a60856ef97b720db351733`. Main remains merged M02 `6a312476858eb6322b79c082d54a1cc97e590228`; M03 PR #943 remains DRAFT/UNMERGED. No M03/Driver, M05/Dashboard/Flutter, owner MAIN, or pre-existing dirty Worker3 worktree was changed. A clean separate detached checkout was used for focused tests. No Codex or self-merge.

### Completed and committed independent integrations

- **Stocktake call-site lock order**: in the VEHICLE_RECON branches of `api/warehouse/stocktake.py::approve_stocktake_session` and `services.py::post_approved_stocktake_adjustments`, after WorkSession lock and **before** location guard, lock sorted canonical session vehicle responsibility via the existing M04 helper. Historical one-vehicle path is unchanged.
- **Frozen period shortage price**: only the VEHICLE_RECON DRIVER_SHORTAGE price call delegates through exact session and **vehicle location** to M04's frozen price seam. Ambiguous, unknown, malformed or mismatched prices require explicit review (no arbitrary first/last route or 500 from missing price rows).
- **Vehicle Load**: `domains/inventory_vehicle_load/service.py::resolve_vehicle_load_owner` checks genuine canonical current vehicle period/custody before legacy route ownership, returns ROUTE/SETTLEMENT_REQUIRED and refuses unsafe ambiguity. Existing under-Vehicle-lock recheck remains.
- **Canonical Backoffice credentials**: stocktake recount verifier authenticates current tenant DASHBOARD `CompanyPrincipal`, verifies current location-level `stocktake.recount` grant, and uses the legacy Driver solely as audit FK. Stocktake approval password uses current active canonical BACKOFFICE principal hash; wrong-password audit remains. Real PG16 regression includes genuine different Driver/principal usernames, FIELD denial, wrong tenant/location/password, canonical password rotation, unchanged legacy password rejection and same-token grant revocation. Stocktake cancellation remains untouched by this bounded approval.
- **Historical AST fixture parity**: old one-car test fixture acknowledges absence of canonical M01 periods and restores its previously missing begin/complete command controls, preserving original assertions without test skips.
- **M05 read-side contract**: new `GET /admin/sessions/{session_id}/inventory-custody/vehicles` supplies bounded, all-or-nothing, capability-scoped exact S1 vehicle/location, period IDs, custody epoch IDs and checkpoint status. It never infers from `DispatchRoute.work_session_id`, leaks quantity, or claims finance-ready. Denies partial location scope with 403 and stale/ambiguous checkpoint evidence with 409. **Endpoint intentionally 503 until ordered M04 migration activates the checkpoint schema**, not a silent legacy fallback.
- **New isolated M04 CI workflow** `.github/workflows/dispatch-m04-vehicle-custody.yml`: focused domain/frozen test gate and genuine restricted PG16+Bearer read/credential gate. It explicitly does NOT run/mark the final writer acceptance before M03 and M04 ordered schema. The shared `dispatch-p0-route-stock-safety.yml` was intentionally **not modified** while Worker1 M03 owns its changes.

### Test evidence and release limits

- Detached clean source on committed HEAD `8c07028610ee4095cca8d4d9ee2fb6b6efd71165`: **112 passed + 31 subtests** from eight focused unit/frozen-compatibility files, no skips; one harmless third-party deprecation warning.
- Genuine isolated local **PostgreSQL 16.15** restricted `wanasah_app` role (NOBYPASSRLS, FORCE RLS) with real `/login` Backoffice Bearer and no dependency overrides: **3/3 M04 read/old physical DAMAGED 2.125 settlement tests passed** on same source. On later HEAD `77842523d0a5f34f5ce31ec0c006d1bfb56b81fd`, after adding only FIELD-denial and principal-password-rotation checks to the credential test, that exact focused PG test **1 passed**, two unaffected tests deselected; prior accepted 2 unchanged tests are not falsely attributed to the newer SHA.
- Compileall Python and `git diff --check` passed on detached worktree. GitHub exact-head CI was queued on last check; only actual job results can be used for CI PASS.
- Prepared `test_dispatch_m04_write_postgres.py` remains **NOT final acceptance**; `RUN_M04_WRITES_PG16` must not be skipped or counted as PASS when its ordered schema is absent.

### Owner continuity policy (overrides old manual restart wording)

Ahmed completes A/B/A WorkSession S1 and presses FIELD End Work. This freezes S1's daily canonical periods without permanently closing/releasing Zone A or changing its long-lived route assignment. Next morning normal FIELD Start Work must automatically resume remaining Zone A shops under the **same route identity** with a new signed daily S2 period/session, fresh daily counters, and unchanged physically carried A83/B53. **No manual Backoffice RESUME/new route launch**; end-day != financial/custody settle. Worker1 M03 owns this actual state machine, not M04. M04 must accept only CLOSED S1 periods and not confuse legitimate future S2 periods with unresolved S1 evidence.

### Remaining NOT MERGE READY blockers

1. M03 #943 accepted/merged by LEAD, exact new MAIN provided with actual signed End Work and automatic next-day S2 continuation (current M03 DRAFT does not prove the owner correction).
2. ONE ordered M04 Alembic revision **after** merged M03 `d7a2e9c3f541`; immutable checkpoint mapping/global metadata, tenant composite FKs/FORCE RLS and exact location-specific VehicleRecon unique index; controlled downgrade refusal.
3. Narrow LEAD-approved original `api/dispatch.py::settle_session` financial readiness delegate, preserving replay-before-settled and once-only session cash/debt/shortage aggregation; never touch M05's `get_active_routes`/readiness paths.
4. Actual M02+M03 full FIELD S1 A100→83/B60→53 A/B/A, End Work/next-day S2, two signed COUNT_IN_PLACE zero movements, variance independent recount, only explicit PHYSICAL_HANDOFF lot+status, 409/ABA/concurrency and revoke, immutable RLS audit, once-only finance, no fake receipt marker; final PG16/Bearer and exact-head CI.
5. Shared P0 exact-path ownership workflow M04 admission **after** Worker1's M03 CI ownership changes merge; preserve negative partial/foreign probes. Existing P0 scope failures are not runtime evidence.

**MERGE READY: NO. PR #944 remains DRAFT, original M05 #946 preserved.**

## Worker2 — REAL M03+M04 integration acceptance (2026-11-12)

**Production staging rule:** M03 #943 still unmerged on M02 MAIN `6a312476858eb6322b79c082d54a1cc97e590228`. Do not add the M04 Alembic revision, `models.py` partial-index parity, `alembic/env.py` global mapping or `api/dispatch.py` finance delegate to this M02-based PR yet. These are ready and genuinely tested **inside private detached overlays only**. Never self merge, modify Worker1 code/branch, fake prior settlement, or let S2 begin before all S1 money+inventory review closes.

### Reproducible integration sources and schema

- Overlay V1: M03 exact `e0c34ce628bbb7703c70f18615b146b580b150b6` + M04 `7c6a9ce8c9475a560a171e819428f5f7a2283d48`. Fast auto source merge with zero file conflicts. Disposable PostgreSQL **16.15** database `wanasah_m04_integrated_942`, distinct privileged migration role and restricted `wanasah_app` NOBYPASSRLS role, using real authenticated Bearer HTTP. **Fresh full Alembic upgrade** M03 `d7a2e9c3f541` then **test-only M04 revision `e4b7c9d2a601` PASS**, all three signed-checkpoint tables have tenant FORCE RLS and immutable triggers. `alembic check` reports **No new upgrade operations detected** with M04 ORM index parity and model registration. No manual `create_all`, no test overrides to auth.
- Overlay V2: M03 exact `6e6e51406014c6f6fd0ef609b7893e454a238427` + M04 `1cbfdf1ba506adee55106b992abb3fab7a5c97b4`, same signed schema, also conflict-free; contains original M03 next-day automatic continuation. Later M03 `43f3ced37b1532fedd884cbf10995c33317486e7` only moved End Work timestamp assignment immediately before signing with exact same timestamp and adapted narrow boundary tests. It has **not** been re-tested in this overlay; final proof must use the accepted merged exact MAIN rather than infer it.
- Narrow finance delegate staged only in overlay `api/dispatch.py::settle_session`: original durable idempotency replay then WorkSession FOR UPDATE, check `has_canonical_session_periods`; if yes `require_financial_custody_ready` (all exact per-vehicle signed checkpoints/epoch coverage/review/fences) and bypass only legacy `REPRESENTATIVE_CUSTODY_RECEIVED` physical handoff requirement for canonical `COUNT_IN_PLACE`. Historical one-car physical handoff path stays untouched. Original incomplete Ending Snapshot check, existing session-only cash/debt/shortage SQL, notes validation, original audit, once-only commit and replay preserved byte-for-byte. No period joins in financial aggregation.

### Genuine targeted test evidence (separate isolated Python processes)

1. M04 final current committed independent HEAD `1cbfdf1ba506adee55106b992abb3fab7a5c97b4`: **114 passed + 31 subtests** across exactly 8 focused domain/legacy files. Previous suite `112 passed`; additional guarded negative tests for new DAMAGED snapshot timestamps and replay-after-Stocktake ORM expiry added.
2. V1 signed-writer PostgreSQL16 HTTP `test_dispatch_m04_write_postgres.py`: **2/2 PASS**, duplicate simultaneous same UUID returns exact same response, count A+B zero inventory movements, once-only money, signed-history immutability; separate explicit PHYSICAL_HANDOFF transfers AVAILABLE 53 and DAMAGED 2.125 from exact same batch and source car to authorized warehouse, one movement each, idempotent duplicate no extra movement. No fake receipt.
3. V1 isolated real variance `test_dispatch_m04_variance_overlay_pg16.py`: **1 PASS**. Incorrect counted A=84 vs 83 creates auditable review and zero movement/checkpoints; wrong Backoffice password 403; canonical approved surplus posts exactly ONE allowed stocktake movement, exact UUID approval replay 200, then A84+B53 signed counts zero extra movements, final finance once, two signed checkpoints.
4. V1 actual 3-period FIELD/Backoffice A100→83 B60→53 from **12+7+5 real sales**, genuine FIELD End Work freezes all 3 CLOSED periods, old offline proof rejected; S2 before settlement 400, financial before 2 counts or after A only 409, both COUNT_IN_PLACE zero stock moves; once-only authenticated Backoffice finance cash **3.000** exactly and original old Visits/cash, same request UUID 200 replay, different UUID 409. **1 PASS**. M03 old HEAD e0c incorrectly returned 400 after settled next-day Start; sent Worker1 evidence #941 comment `6824873763`.
5. V2 M03 HEAD **6e6e5140** with genuinely settled S1 (NO manual is_settled seed), **1 PASS** complete FIELD A/B/A + M04 all-car count/finance + automatic next-local-day **S2 Start 201** on the same existing route and A vehicle, new period/assignment revision 5, original unfinished Zone A Visit appears exactly once, fresh S2 Visit count zero, physical A83/B53 unchanged, Start original UUID retry 201 identical. Corrected Worker1 handoff in #941 comment `6825370215`.
6. M04 all-car authenticated read/credentials PG16 on activated M03+M04 overlay: **3 PASS** (tenant/limited location/valid FIELD denied, canonical password rotation, grant revocation, historical DAMAGED handoff and replay).
7. M04 final future **P0 ownership policy** staged exclusively in V1 overlay: 43 literal exact files including future migration, `models.py`, `api/dispatch.py`, one integrated test and shared P0 workflow; positive exact / **43 missing** negative / **5 foreign** negative all PASS, prior 847,856,861,D07,D11,859 policy tests PASS. Do not broaden existing P0 / M03 allowances. Promote after LEAD merges M03, and use exact final basename, not the overlay-only testing filename.

A combined all-PG-file pytest invocation on Windows saw **one asyncio Proactor/asyncpg disposed-engine event-loop error**, despite each relevant test module **passing in its own fresh pytest process**. Run the final isolated PG16 files in separate processes / independent CI jobs; do not claim this one combined run was green. It was NOT a money/custody failure. Do not disguise it.

### Two source bugs found by genuine M03+M04 writers and fixed on this same PR

- **New historical snapshot** `SessionInventorySnapshot` created for a previously unlisted status/variant must use `created_at=settled_at` from one `utc_now`; otherwise PostgreSQL CHECK `settled_at >= created_at` can fail after SQLAlchemy delayed flush. Updated M04-owned inventory integration and added focused regression.
- **Reviewed variance approval replay**: delegated Stocktake handler commits/rolls back, expiring ORM `StocktakeSession`; reading `recon.reference_number` afterward raised `MissingGreenlet`/HTTP 500 on original UUID retry. Cache immutable `recon_reference,recon_id` before handler. Updated M04-owned variance workflow and added expired-record regression. True PG16 reviewed variance now PASS with same UUID approval replay.

**Release gate remains:** Await owner-approved M03 merge and fresh exact MAIN. Then update same M04 Draft PR #944 with exactly one ordered M04 migration after `d7a2e9c3f541`, M04 ORM/index/metadata matching, narrow actual financial delegate + final protected PG16 tests and exact strict P0 CI ownership; run genuine full A/B/A/S1/S2 on the merged source and final HEAD, all role/race/ABA/immutable proof. **MERGE READY NO until those passes.**
