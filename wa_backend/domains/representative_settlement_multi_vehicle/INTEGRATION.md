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
