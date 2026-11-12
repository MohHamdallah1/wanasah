# M04 #942 integration boundary (phase 1; not acceptance)

Exact starting MAIN: `3a588fcad0906020b1fc32b3806067aeb7db09b1`.
Worker3 only owns this module, small `api/representative_settlement.py`
adapters, new `tests/test_dispatch_m04_*.py`, and an ordered **later** M04
Alembic revision. No implementation in Worker1/Worker2 files is authorized.

## Verified independent evidence

- `test_dispatch_m04_domain.py`: strict mode/signature contracts, explicit
  canonical A/B/A period/epoch coverage, exact location/lot/status counts,
  stock/context ABA fencing and request hash rules.
- `test_dispatch_m04_read_postgres.py`: Alembic-migrated PG16.15 restricted
  `wanasah_app` NOBYPASSRLS, FORCE RLS, genuine `/login` Bearer requests through
  the real application without dependency overrides, two vehicle count sheets,
  company/location denials and immediate same-token location revocation.
  Movement-engine **fixtures** reach A83/B53; reads leave balances/movements
  byte-for-byte unchanged. This is NOT execution of M02/M03 or a real sale.
- M03 source contract preserves pre-session signed custody epochs with nullable
  `related_session_id`. Resolve these only via an explicit canonical session
  period with exact representative/vehicle/location and containing time
  interval; reject multiple matches or a different explicit session. No last
  route fallback or mutation of prior accepted custody evidence.

## Required shared seams — LEAD ownership / explicit approval

These are source-proven blockers, not permission to edit shared files:

1. `models.py:StocktakeSession.__table_args__` has partial unique index
   `uq_vehicle_recon_work_session(company_id, related_work_session_id)`.
   It must include `location_id` while preserving the non-CANCELLED
   VEHICLE_RECON predicate, with ORM/migration parity. Otherwise A's variance
   prevents B's independent variance. The existing per-location active-count
   guard remains unchanged. Only add the ordered revision after M02 is merged.
2. `services.py:validate_vehicle_recon_work_session` resolves membership from
   `DispatchRoute.work_session_id` + mutable `vehicle_id`. For canonical M01
   sessions, delegate membership to the explicit ended-session period/epoch
   resolver in this module; preserve the old single-car branch for historical
   sessions. Never overwrite route links or use arbitrary POSTED stocktakes.
3. `services.py:_seal_vehicle_inventory_reconciliation` rejects snapshots at
   any other vehicle location and marks the entire session reconciled after
   one car. Canonical sessions need location-specific snapshot closure; a
   WorkSession-wide seal can only follow all signed per-vehicle checkpoints.
   `post_approved_stocktake_adjustments` must keep its existing approval,
   independent recount, shortage valuation and movement authority unchanged.
4. M03 already reported `SessionInventorySnapshot`'s unique key lacks
   `location_id`, and `WorkSession.commercial_context_id` is uniquely tied to
   one session. Await LEAD-owned resolution; do not edit `models.py` here.
   End-work must also close/freeze canonical active periods before counting;
   current M04 deliberately rejects ACTIVE/HISTORICAL/NEEDS_REVIEW periods.
5. **Only after M02 merge and approval of the exact hunk**, replace the custody
   evidence gate in `api/dispatch.py:settle_session` with a narrow delegate:

   ```python
   if await has_canonical_session_periods(db, company_id=company_id, session_id=session.id):
       await require_financial_custody_ready(db, access=access, session_id=session.id)
   else:
       # Preserve the existing historical single-vehicle physical receipt gate.
       ...
   ```

   Keep `begin_idempotent_operation` and exact replay **before** the settled
   guard, and the session FOR UPDATE lock. Keep the existing session-only
   Visit cash/debt/shortage aggregation once, with no period/vehicle join.
   This module's gate does not calculate money or authorize a fake warehouse
   receipt. Final precise placement also requires the all-location snapshot
   seal from item 3 before the existing inventory-reconciled guard.

## Deferred activation, not a fallback

- Checkpoint SQLAlchemy mapping is designed but deliberately unregistered
  from global metadata/runtime: no M04 migration may fork M02's Alembic head.
- `record_vehicle_count` and `CanonicalInventoryCustody` are not reachable
  through HTTP until the ordered migration, Inventory seams and mutation
  acceptance pass. No partial in-place endpoint or phantom received marker.
- The explicit new read route uses M01 only. Existing physical `/receive`,
  variance/recount endpoints and financial settle behavior remain unchanged.
- Before mutation activation, old single-vehicle `/receive` and variance
  adapters must reject canonical multi-vehicle sessions and route them to the
  exact-vehicle command. Otherwise a legacy last-route lookup could receive
  one car while ignoring another. Preserve historical single-vehicle behavior.
- Final required gate remains OPEN: actual M02+M03 A/B/A FIELD execution,
  two signed checkpoints, same-car reviewed variance, real DAMAGED/lot handoff,
  nonce/replay/different-body rejection, count/load/settle races, all-vehicle
  financial close exactly once, surviving physical stock and S2 zero counters,
  restricted PG16 + authenticated Bearer, exact HEAD CI.

Keep the PR DRAFT. MERGE READY: NO until all above passes on merged MAIN.
