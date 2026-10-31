# Live Stock projection v1 → physical-location v2: operator rollout acceptance

**Status:** acceptance and safe deployment instructions, NOT permission to deploy. These PostgreSQL 16 acceptances change no production records. The original v1→v2 projection proof started from `70e13b3f6f75777d9d3802dddb478446bf868f09`; the real backup/restore rehearsal starts from exact main `1e4a83c685ae2a7a2cdafb53783683079e9bbb7d`.

## Findings from the current implementation

- `domains/live_stock_projection/service.py` already sets `PROJECTION_VERSION = 2`. No schema replacement, migration rewrite or new production authority is justified by this acceptance alone.
- `assert_live_stock_projection_ready` checks **both** `inventory_live_stock_company_summaries` and the selected active `inventory_live_stock_warehouse_summaries` have `projection_state='READY'` and `projection_version=2`; missing, v1, BUILDING and DEGRADED summaries fail closed. A due temporal transition is repaired through a separate bounded path. Do not mistake a raw row for an authorized READY response.
- `api/warehouse/live_stock.py::_require_live_stock_read_model_ready` translates the not-ready exception to HTTP **503** with stable `LIVE_STOCK_PROJECTION_NOT_READY`; route authentication, tenant and location authorization precede exposure of stock. The Dashboard must not interpret 503, `null` or `NO_ACCESS` as numeric zero.
- `rebuild_live_stock_company` is the existing canonical company operation. It takes a transaction-scoped exclusive **company projection advisory lock**, iterates **active WAREHOUSE** locations in sorted order, repairs by stable variant-ID batches (`batch_size` 1..10,000), compares to authoritative InventoryBalance/Batches/Policies, verifies truth, sets warehouse summaries then company summary READY. Old projection-only sparse keys are included and removed where no longer justified. Vehicle legacy compatibility columns are neutralized in v2; VEHICLE and IN_TRANSIT remain their own physical InventoryLocations.
- The rebuild function **does not commit**. The authorized caller must control one DB transaction and commit only after every warehouse verifies. A rollback must leave the entire company at its prior observable state. A second rebuild is allowed for recovery and must be idempotent. The operation **does not** mutate InventoryBalance, InventoryMovement, costing or physical custody.
- This repository has projector runtime test gates and automatic reconciliation/task code; **do not** run those test fixture scripts or workers against production, and never run as a tenantless superuser. No existing operator-authenticated production HTTP rebuild command was confirmed by this audit. The one-time operational invocation below requires operator authorization and an approved restricted runtime connection.

## Rollout sequence (per company, never tenant-wide guessing)

1. **Release stop / prerequisites:** confirm the installed release contains the v2 Warehouse physical-location read contract and Dashboard compatibility (`vehicle_quantity=null` means unauthorized; `total_quantity_scope=WAREHOUSE_PHYSICAL`), that deployed backend/clients are version-compatible, and that the exact company ID and its active Warehouse locations are approved for this operation. Validate current main/PR status, no conflicting old producers, and an operational maintenance window. Route-based stock attribution is prohibited.
2. **Verified restore point:** take a production-appropriate consistent PostgreSQL backup/snapshot **before** any release or rebuild; check the snapshot completion, source database identity, restore method, credentials and restore rehearsal/verification against a non-production target. Merely having a backup filename is not verification. Capture baseline company-scoped counts and hashes of `inventory_balances`, `inventory_movements`, `inventory_cost_events`, active Warehouses, VEHICLE/IN_TRANSIT locations, and existing company/warehouse projection versions, without disclosing another tenant.
3. **Read traffic is fail-closed:** deploy compatible v2 API first with Live Stock blocked from claiming ready while persisted v1 summaries exist. Test bearer GET `/warehouse/inventory/cursor?location_id=<authorized warehouse>&limit=50`: v1 company/warehouse summaries must return 503 `LIVE_STOCK_PROJECTION_NOT_READY`, request correlation ID, and **no** `items`. A tenant/location without access must remain denied; do not bypass authorization for a status page. Do not force summary version from 1 to 2 with SQL.
4. **Execute only canonical scoped rebuild:** under change approval and a restricted `NOBYPASSRLS` application DB role, start one company-scoped transaction. Establish the canonical tenant context and session-local `app.current_tenant`, confirm its numeric identity, then call **only** `rebuild_live_stock_company(db, company_id=approved_company_id, batch_size=1000)`. Call `assert_live_stock_projection_ready` for **each active Warehouse** before commit; check the reported company id and warehouse count. Commit only when all checks succeed. One bounded batch is 1,000 variant keys; it is **not** a promise of bounded total transaction duration. Set a deliberate maintenance timeout and monitor locks, workload and DB resources. No company loop, no shared tenantless session, no job queue or background worker.
5. **Verify from a fresh transaction/real API:** read every active Warehouse summary for version 2/READY, inspect canonical InventoryBalance by physical location, and compare Warehouse projection `warehouse_on_hand` and `warehouse_reserved` with canonical Warehouse-only source. Independently total VEHICLE and IN_TRANSIT balances at their respective physical locations. Confirm cross-tenant and location-restricted bearer reads; company-wide/authorized Vehicle custody scope; no-access Vehicle=`null` not zero; Route presence/status must not move projected quantities. Verify new movement/cost-event counts are **unchanged** by rebuild and the company timezone date matches readiness.
6. **Repeatability / completion:** perform a second authorized company rebuild in the same safe operating window only when needed for acceptance; expect `drifted_keys=0` and `summary_repairs=0` without added movement/cost events. Retain a company-scoped audit of release SHA, approved operator, UTC timestamps, backup verification, report counters, HTTP request IDs, RLS evidence and checks. Enable Live Stock only after these checks and a separate release-owner decision.

## Failure and rollback rules

- **Before commit** (timeout, killed process, bad source, mismatch or lost connection): PostgreSQL rolls back the transaction. The old v1 summary remains v1 and v2 readers stay HTTP 503. Investigate the error/locks; repeat the **same canonical company rebuild** after resolving it. Never force READY or write a zero placeholder. If an unexpected partial commit is suspected, read company and each Warehouse summary version/state and compare source balances before attempting anything.
- **After commit** (new source movement, authorization revocation, due date or DEGRADED state): stop claiming READY where readiness rejects. Diagnose the specific tenant/location; use existing canonical repair/reconciliation with the required authority and verification, not manual stock or route corrections. Do not replay physical movements to make the projection appear ready.
- **Application rollback**: reverting only the backend to code that interprets `vehicle_packs` as Warehouse-owned is unsafe. Keep stock reads fail-closed until the rollback's schema/reader contract is proven safe. If a true database restore is necessary, treat it as a separate controlled recovery with full post-backup movement/financial reconciliation; NEVER silently overwrite production transactions. Backup recovery requires incident/change approval.
- **Unknown/unauthorized**: do not present old cached v1, partial projected rows or inaccessible Vehicle custody as zero. A READINESS=false company remains unavailable, not empty.

## Real non-production backup/restore rehearsal

The missing restore rehearsal is covered by `wa_backend/tests/test_live_stock_v2_restore_rehearsal_postgres.py` and `.github/workflows/live-stock-v2-restore-rehearsal.yml`. This gate reuses the #700 canonical seed/rebuild helpers and production `rebuild_live_stock_company`; it does **not** add another projection algorithm, manual READY path, movement replay, costing repair, authorization shortcut or RLS exception.

The workflow creates one PostgreSQL 16 container with a migration role plus `wanasah_app NOSUPERUSER NOBYPASSRLS`. It migrates a disposable source database, seeds the same canonical two-tenant physical truth used by #700 (Warehouse, Vehicle, IN_TRANSIT, route-independent custody and actual costing evidence), persists a schema-valid v1 projection, and records per-company SHA-256 fingerprints of canonical locations/batches/balances/movements/cost layers/cost events/cost state/idempotency plus projection state. The source is verified fail-closed through real FastAPI bearer reads before backup.

The backup and restore are actual PostgreSQL custom-format operations into a **different empty database** in the same disposable PG16 container. The executable core is:

```bash
docker exec live-stock-v2-restore pg_dump \
  -U v2_restore_admin -p 55439 \
  -d wanasah_no_lot_contract_test -Fc \
  > /tmp/live-stock-v2-source.dump

docker exec live-stock-v2-restore createdb \
  -U v2_restore_admin -p 55439 wanasah_live_stock_v2_restore_test

docker exec -i live-stock-v2-restore pg_restore \
  -U v2_restore_admin -p 55439 \
  --no-owner --exit-on-error \
  -d wanasah_live_stock_v2_restore_test \
  < /tmp/live-stock-v2-source.dump
```

The restore job checks that the dump is non-empty, records its SHA-256, inspects the archive for canonical balance/movement/cost/projection table data, and then starts a **fresh test process** whose `DATABASE_URL` points only at `wanasah_live_stock_v2_restore_test`. That fresh process verifies Alembic heads, `wanasah_app` remains non-superuser/non-BYPASSRLS, FORCE RLS remains active on authoritative and projection tables, every pre-backup canonical fingerprint and Warehouse/Vehicle/IN_TRANSIT quantity matches exactly, and a tenant session cannot see the other company's balances.

Recovery is then exercised on the restored v1 snapshot itself. Fresh owner and restricted-reader bearer requests remain HTTP 503 `LIVE_STOCK_PROJECTION_NOT_READY` before a successful rebuild while the unrelated company remains readable. The test injects failure on the second Warehouse inside the existing canonical company rebuild, rolls the transaction back, and requires the entire projection fingerprint/version/state to equal the pre-recovery restored v1 snapshot. Canonical balance/movement/cost/idempotency fingerprints and physical custody must also remain byte-equivalent, proving an interrupted recovery cannot leave false READY or replay stock movements.

Only after that negative proof does the rehearsal execute `rebuild_live_stock_company(..., batch_size=1)`, call `assert_live_stock_projection_ready` for every active Warehouse and commit. Fresh post-recovery logins must then read W1=91, W2=63, company-wide Vehicle=42 for the owner, authorized Vehicle=35 for the restricted reader, preserve IN_TRANSIT=4, deny cross-company locations, and keep the foreign company unchanged. A second canonical rebuild must report zero drift/summary repairs while all authoritative movement/cost fingerprints remain identical.

GitHub runs the focused restore check as:

```bash
python -B -m pytest -p no:cacheprovider -q -s \
  tests/test_live_stock_v2_restore_rehearsal_postgres.py::test_prepare_backup_source

DATABASE_URL=postgresql+asyncpg://wanasah_app@127.0.0.1:55439/wanasah_live_stock_v2_restore_test \
DATABASE_URL_MIGRATION=postgresql+asyncpg://v2_restore_admin@127.0.0.1:55439/wanasah_live_stock_v2_restore_test \
python -B -m pytest -p no:cacheprovider -q -s \
  tests/test_live_stock_v2_restore_rehearsal_postgres.py::test_restored_backup_recovers_v1_to_v2_without_authoritative_replay
```

### Production-only prerequisites still open

This disposable rehearsal closes the repository-level **backup/restore mechanics** gap only. Production still requires explicit release/change approval; a production-approved backup/snapshot method and credentials; a verified production-target restore location; production database size, dump/restore duration, lock and maintenance-window budgets; confirmation that deployed API/Dashboard/mobile clients are compatible; approved per-company restricted execution authority; final integrated-main CI; and an incident-specific reconciliation plan for any transactions created after the chosen restore point. A real production restore must never silently discard post-backup inventory or financial events. Nothing in this rehearsal authorizes deploying v2, running a rebuild against production, or restoring customer data.

## Isolated acceptance coverage and limits

`wa_backend/tests/test_live_stock_v2_rollout_readiness_postgres.py` is guarded by `WANASAH_LIVE_STOCK_V2_ROLLOUT_PG_GATE=1` and the fixture's exact `127.0.0.1:55439/wanasah_no_lot_contract_test` identity, restricted non-bypass runtime role, FORCE RLS and fresh Alembic head. It seeds two tenants, Warehouse W1/W2, independent Vehicle1/Vehicle2, mixed origin/lot receipts, actual IN_TRANSIT movement and a W1 Route on a Vehicle holding W2 stock. It persists an intentionally stale schema-valid v1 projection row and READY v1 summary versions **in the disposable fixture only**. It proves actual HTTP bearer 503 prior to rebuild, a deliberately interrupted atomic rollback and another 503, bounded canonical rebuild to READY, precise W1/W2/Vehicle/IN_TRANSIT and scoped bearer results, tenant denial, no movement/cost duplication and repeated rebuild zero drift for FIFO and moving average.

The #700 synthetic v1 seed still demonstrates stale v1 persisted data with old Vehicle attribution and is not an executed binary downgrade. The dedicated restore rehearsal now adds an actual disposable PostgreSQL16 `pg_dump` → separate-database `pg_restore` replay and performs the canonical recovery against that restored v1 snapshot. Neither test is a production restore certificate: they cannot certify a production company's unique size, backup storage, credentials, restore target, maintenance timing, post-backup transaction reconciliation, deployment permissions, network concurrency or peak-load behavior. Operational certification and owner approval remain separate prerequisites.
