# Wanasah Driver / Dispatch Modularization Plan

## Split legacy API mega-files safely without changing business behavior

**Status:** PLANNED — NOT YET IMPLEMENTED  
**Owner decision date:** 2026-10-10  
**Primary evidence:** `DRIVER_DISPATCH_SEAM_INVENTORY.md`  
**Canonical references:** `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `RUN.txt`, `V1_SCOPE_FREEZE.md`, `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`, `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, `REPRESENTATIVES_VEHICLES_V1_PLAN.md`.

---

# 0. Frozen goals and non-goals

- [ ] `wa_backend/api/driver.py` and `wa_backend/api/dispatch.py` must stop being mega-files.
- [ ] Physical splitting is by responsibility/domain seam, not by arbitrary line count.
- [ ] Public URLs, HTTP methods, response contracts, status strings, idempotency behavior, transaction boundaries, lock ordering, audit evidence, and inventory/accounting semantics must remain stable unless separately approved.
- [ ] Do not mix file movement with unrelated business-rule cleanup.
- [ ] Do not create replacement mega-files, generic `shared.py` dumping grounds, or god-functions in new modules.
- [ ] New Representatives/Vehicles administration must never be added to the legacy mega-files.
- [ ] Existing working Dispatch/Flutter/Inventory business rules are preserved and reused, not reimplemented.
- [ ] Every extracted seam gets focused regression verification before the next high-risk seam starts.
- [ ] No worker may alter the module map or domain ownership independently; changes follow `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`.

---

# 1. Current audited surface

From `DRIVER_DISPATCH_SEAM_INVENTORY.md`:

- [ ] `driver.py`: 13 public endpoints, 11 internal/top-level helpers, 24 top-level functions.
- [ ] `dispatch.py`: 26 public endpoints, 23 internal/top-level helpers, 49 top-level functions.
- [ ] Combined: 39 endpoints, 34 helpers, 73 top-level functions.
- [ ] Highest-risk areas include `driver.update_visit`, `dispatch.dispatch_route`, `dispatch._apply_route_pack_deltas`, `dispatch.update_route_status`, `dispatch.settle_session`, custody handshakes, route cancellation/reversal, shortages, and shop/zone bulk workflows.

**Rule:** the 39 public endpoint contracts form the compatibility baseline for this refactor.

---

# 2. Architecture decisions — frozen by technical lead

These decisions resolve the 10 open questions from `DRIVER_DISPATCH_SEAM_INVENTORY.md`.

## 2.1 Identity vs field-session ownership

- [ ] Shared/company identity owns authentication, principal resolution, token/session credential concerns, and Backoffice-vs-Field Representative identity classification.
- [ ] Field work-session orchestration owns start/end/break/active-session business behavior.
- [ ] A field-session module consumes the authoritative Field Representative identity; it does not recreate authentication logic.
- [ ] `_require_driver_identity` must not survive as a second identity system after the canonical identity migration is complete.

**Dependency:** no final extraction of identity-sensitive driver/session code until the applicable phases of `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md` are complete.

## 2.2 Router compatibility strategy

- [ ] Preserve all current URLs and methods during extraction.
- [ ] Use thin compatibility/aggregation routing during migration so callers do not observe module movement.
- [ ] Do not rename `/driver/*`, `/admin/dispatch/*`, or `/dispatch/*` merely for cleanliness.
- [ ] Final target may expose package-level aggregated routers, but temporary compatibility wiring must be removed before refactor closure.
- [ ] Avoid a risky all-at-once `driver.py -> driver/` or `dispatch.py -> dispatch/` filesystem switch before extracted subrouters are proven.

## 2.3 `_apply_route_pack_deltas` ownership

- [ ] Route desired-state and pack-delta orchestration remains owned by Dispatch route-inventory orchestration.
- [ ] Authoritative stock movement, inventory locks, FEFO/batch authority, and inventory persistence remain owned by Inventory services.
- [ ] Do not move `_apply_route_pack_deltas` wholesale into Inventory.
- [ ] Extract reusable pure inventory primitives only when they are genuinely inventory-owned and already consistent with Inventory authority.

## 2.4 Custody transfer ownership

- [ ] Inventory owns the authoritative physical transfer/movement state and stock mutation.
- [ ] Dispatch owns route/load context and initiation intent.
- [ ] Field Representative workflow owns the actor-side accept/reject/handshake interaction.
- [ ] The application-level custody orchestration must call the Inventory transfer authority; neither Dispatch nor Driver may duplicate stock movement rules.
- [ ] Vehicle custody identity remains separate from inventory quantity authority.

## 2.5 Settlement boundary

- [ ] Keep one authoritative application-level settlement transaction for the V1 workflow.
- [ ] Settlement orchestration may coordinate cash/finance evidence, inventory reconciliation, custody state, route/session closure, and audit.
- [ ] Finance remains owner of financial posting rules.
- [ ] Inventory remains owner of stock/custody reconciliation rules.
- [ ] Dispatch/field-session settlement orchestration coordinates these authorities; it does not absorb their business rules.
- [ ] Do not split settlement into eventually-consistent commits during this refactor.

## 2.6 Read-model ownership

- [ ] Cross-domain dashboard/projection queries may live in explicit `read_models` / query modules because they aggregate multiple domains.
- [ ] Read models do not become write-domain authorities.
- [ ] Preserve batching/query-count behavior; avoid N+1 regressions.
- [ ] Write workflows stay with their owning application/domain services.

## 2.7 Tax/commercial precondition ownership

- [ ] Tax/commercial configuration authority belongs to the existing commercial/tax/settings authority, not Dispatch.
- [ ] Dispatch may call a named precondition/validator from that authority.
- [ ] Do not duplicate 14% tax/commercial settings logic in Dispatch modules.

## 2.8 Shop / Zone module granularity

- [ ] Keep shop/zone operational administration under one bounded package initially because they share locks, route-blocking rules, and archive/move constraints.
- [ ] Inside that package separate responsibilities into small modules such as shops, zones, bulk operations, and local locking/coordination helpers where justified.
- [ ] Do not put all shop/zone/import behavior into one replacement mega-file.
- [ ] A later dedicated Shop/Zone domain extraction may happen separately if needed; this refactor does not force it.

## 2.9 Shortage workflow ownership

- [ ] V1 operational shortage orchestration remains under Dispatch because ownership is currently tied to active routes, representatives, zones, shops, and pending visits.
- [ ] Product lifecycle/replenishment checks remain consumed from their authoritative services.
- [ ] Visit creation/merge rules must not be duplicated inside a generic shortage repository.
- [ ] A future Replenishment domain is possible, but not created merely to complete this refactor.

## 2.10 Field shop capture ownership

- [ ] Field shop capture remains a field-workflow orchestration surface because authorization/context differ from Backoffice administration.
- [ ] Canonical shop validation/persistence rules should be consumed from the shop authority when available.
- [ ] Field capture must not create a second independent Shop business model.

---

# 3. Target responsibility structure

Exact filenames may change only by lead approval, but the responsibility boundaries are frozen.

## 3.1 Driver / field API target

Candidate final public API package:

```text
wa_backend/api/driver/
  __init__.py
  sessions.py
  visits.py
  custody.py
  read_models.py
  commercial_catalog.py
  shop_capture.py
```

Application/domain logic should not be embedded in those routers. Prefer responsibility-focused services under an appropriate domain/application boundary, for example:

```text
wa_backend/domains/field_operations/
  sessions/
  visits/
  custody/
  commercial_catalog/
  shop_capture/
```

or an equivalent structure approved by the lead that matches repository conventions.

### Mandatory rules

- routers are thin;
- validation that is domain-specific lives with the owning service/policy;
- complex persistence/query logic gets named repository/query helpers;
- no raw cross-domain stock mutation in field routers;
- no credential/auth duplication in field modules.

## 3.2 Dispatch API target

Candidate final public API package:

```text
wa_backend/api/dispatch/
  __init__.py
  access.py
  bootstrap.py
  read_models.py
  settlement.py
  route_planning.py
  route_inventory.py
  route_lifecycle.py
  shop_zone/
    __init__.py
    shops.py
    zones.py
    bulk.py
    locking.py
  shortages.py
```

Application/domain logic should live behind thin routers, for example:

```text
wa_backend/domains/dispatch/
  route_planning/
  route_inventory/
  route_lifecycle/
  settlement/
  shortages/
  queries/
```

### Mandatory rules

- Dispatch owns route/assignment/load orchestration, not stock truth.
- Inventory owns quantity/movement authority.
- Representatives/Vehicles domains own their master identities/lifecycle.
- Pricing/UOM/Tax/Product-lifecycle rules are consumed, not copied.
- query/read-model modules remain read-only.

---

# 4. Refactor strategy

Use a **Strangler-style incremental extraction**.

For each seam:

1. freeze current contract/invariants;
2. extract cohesive implementation behind the same public route;
3. keep transaction ownership unchanged;
4. keep lock ordering unchanged;
5. run only the focused acceptance set for that seam;
6. verify no import/route duplication;
7. merge at a stable checkpoint;
8. delete the branch;
9. start the next seam from latest `main`.

Do not perform multiple high-risk god-function decompositions in the same PR.

---

# 5. Execution phases

## Phase 0 — Prerequisites and evidence

- [ ] `DRIVER_DISPATCH_SEAM_INVENTORY.md` merged and current.
- [ ] Record current route table for all 39 endpoints.
- [ ] Record current response-contract snapshots/structural tests where practical.
- [ ] Record current Alembic head and known-good runtime baseline.
- [ ] Ensure required focused test tooling is available before behavioral refactor PRs.
- [ ] Do not reset owner-local unrelated changes.

**Gate 0:** current behavior and public route surface are reproducible.

## Phase 1 — Identity dependency cutover prerequisite

This phase is owned by `IDENTITY_AUTHORIZATION_IS_ADMIN_MIGRATION_PLAN.md`, not by this refactor.

Before extracting driver identity/session code:

- [ ] CompanyPrincipal / Backoffice / Field Representative identity contract is authoritative for the applicable path.
- [ ] field login resolves a Field Representative identity explicitly.
- [ ] Dashboard login resolves Backoffice identity explicitly.
- [ ] `is_admin` is no longer used to infer representative identity.
- [ ] token identity contract needed by field endpoints is frozen.

**Gate 1:** field session extraction will not preserve the legacy `Driver.is_admin` coupling.

## Phase 2 — Low-risk read-only seams first

Extract read-only/query-heavy surfaces before write state machines.

### 2A Driver read models

- [ ] move driver dashboard/pending/history/detail query logic behind dedicated read-model module(s);
- [ ] preserve response fields/nullability/order/status values;
- [ ] preserve batching/query behavior;
- [ ] leave write/session logic untouched.

### 2B Driver commercial catalog read

- [ ] extract route-aware product/pricing/UOM read orchestration;
- [ ] continue consuming pricing/UOM authorities;
- [ ] do not copy commercial calculation logic.

### 2C Dispatch read models

- [ ] extract dispatcher dashboard, active-routes projections, transfer navigation, vehicle/route read projections where mutation-free;
- [ ] preserve query batching and authorization contracts.

**Gate 2:** read-only extractions merged with zero public-contract change.

## Phase 3 — Small cohesive state transitions

### 3A Break toggle

- [ ] extract work-break transition with current open-break/session ownership invariants.

### 3B Dispatch bootstrap/access

- [ ] extract dispatch authorization/bootstrap wiring after capability migration is ready;
- [ ] call commercial/tax authority rather than duplicate it.

### 3C Field shop capture

- [ ] extract field capture orchestration;
- [ ] preserve field-specific authorization/context;
- [ ] consume canonical shop validation rules.

**Gate 3:** small mutations isolated before route/inventory heavy flows.

## Phase 4 — Field sessions

- [ ] extract start session;
- [ ] extract end session;
- [ ] keep route/representative/vehicle/session binding atomic;
- [ ] preserve lock order;
- [ ] preserve opening snapshot/custody expectations;
- [ ] keep active-session read contract stable;
- [ ] do not recreate auth inside session service.

**Gate 4:** Flutter session lifecycle behaves identically under new identity model.

## Phase 5 — Shop / Zone administration

- [ ] extract advisory lock helpers into bounded package-local coordination code;
- [ ] extract Zone lifecycle operations;
- [ ] extract Shop mutations;
- [ ] extract bulk update/import separately from simple mutations;
- [ ] preserve active-route move blocking;
- [ ] preserve phone-field semantics;
- [ ] preserve archive provenance and audit behavior;
- [ ] preserve manual balance audit.

**Gate 5:** shop/zone operational behavior unchanged and no replacement mega-file created.

## Phase 6 — Shortages

- [ ] extract shortage reads;
- [ ] extract shortage create/cancel orchestration;
- [ ] preserve product lifecycle guards;
- [ ] preserve active-route representative resolution;
- [ ] preserve pending-visit merge/duplicate protection;
- [ ] preserve advisory/row-lock order.

**Gate 6:** shortage workflow remains concurrency-safe.

## Phase 7 — Custody handshake

- [ ] extract handshake projections/validation helpers as one cohesive field-custody module;
- [ ] keep signed-delta semantics unchanged;
- [ ] preserve snapshot/source validation;
- [ ] preserve accept/reject/constraint state machine;
- [ ] preserve batch all-or-nothing behavior;
- [ ] call Inventory transfer authority for physical movement.

**Gate 7:** custody transfer behavior and vehicle stock remain identical.

## Phase 8 — Route planning / creation

- [ ] extract vehicle/source-warehouse resolution;
- [ ] extract load-plan calculation/snapshot orchestration;
- [ ] extract route create/assignment orchestration;
- [ ] keep route + representative + vehicle + warehouse + load/custody outcome atomic;
- [ ] preserve uniqueness/concurrent assignment guards;
- [ ] preserve UOM/pack conversion authority.

**Gate 8:** route creation produces the same route/load/custody state under contention.

## Phase 9 — Route inventory

- [ ] extract route/vehicle inventory read helpers not already moved;
- [ ] extract route adjustment orchestration;
- [ ] retain `_apply_route_pack_deltas` semantics under Dispatch route-inventory ownership;
- [ ] keep Inventory as physical movement authority;
- [ ] preserve pending-handshake effective stock;
- [ ] preserve started-session load-plan/snapshot synchronization;
- [ ] preserve inventory lock ordering and FEFO/batch authority.

**Gate 9:** no stock, batch, or custody regression.

## Phase 10 — Route lifecycle / recovery

- [ ] extract normal status transitions;
- [ ] extract force-cancel orchestration;
- [ ] extract undo-end orchestration;
- [ ] preserve transition/reversal symmetry;
- [ ] preserve visit/session/assignment/custody/inventory compensations;
- [ ] preserve audit/reversal provenance.

**Gate 10:** route lifecycle and recovery paths are behaviorally equivalent.

## Phase 11 — Settlement

- [ ] extract settlement report read path;
- [ ] extract settlement mutation as one application transaction;
- [ ] call Finance authority for financial rules;
- [ ] call Inventory reconciliation authority for stock/custody rules;
- [ ] preserve evidence consistency and audit;
- [ ] do not introduce eventual consistency.

**Gate 11:** cash, inventory, custody, and session closure remain consistent.

## Phase 12 — `update_visit` last

`driver.update_visit` is intentionally last because it is the highest-risk cross-domain workflow.

- [ ] freeze direct contract and focused regression cases first;
- [ ] identify orchestration steps without changing their order;
- [ ] extract validation/resolution calls to authoritative domains;
- [ ] keep one authoritative application transaction;
- [ ] preserve pricing/UOM/debt/product-lifecycle behavior;
- [ ] preserve sale/return/correction symmetry;
- [ ] preserve inventory locks, FEFO, batches, movement and COGS ordering;
- [ ] preserve idempotency/mobile retry semantics;
- [ ] preserve audit/evidence atomicity.

**Gate 12:** visit execution/correction/return behavior is equivalent under focused DB acceptance.

## Phase 13 — Final API package conversion and legacy cleanup

Only after all seams have moved:

- [ ] convert final compatibility wiring into the approved `api/driver/` package structure;
- [ ] convert final compatibility wiring into the approved `api/dispatch/` package structure;
- [ ] preserve import surfaces needed by `main.py`/router registration;
- [ ] remove temporary compatibility modules;
- [ ] delete empty legacy `driver.py`/`dispatch.py` files only when no Runtime code depends on them;
- [ ] search repository for stale legacy imports/helpers;
- [ ] ensure no duplicate route registration;
- [ ] ensure no generic shared dumping module was introduced.

**Gate 13:** no legacy mega-file remains and no temporary compatibility debt remains.

---

# 6. Focused acceptance matrix

For each seam, choose only tests tied to its dependencies plus new contract tests where coverage is absent.

Existing anchors include:

- `test_costed_driver_customer_return_c2_db.py`
- `test_costed_driver_sale_correction_real_c2_db.py`
- `test_catalog_sales_identity_a3.py`
- `test_inventory_multi_location_authority.py`
- `test_batch_multilocation_read_acceptance.py`
- `test_batch_reservation_owner_contract.py`
- `test_batch_stock_sources_contract.py`
- `test_product_batch_restrictions.py`
- `test_system_transit_provision_guard.py`
- `test_special_transfer_action_options.py`
- `test_special_action_reason_contract.py`
- `test_pricing_bulk_catalog_b3_db.py`
- `test_catalog_batch_uom_cache_b3.py`
- `test_catalog_tracking_batch_b3.py`
- `test_archive_owner_navigation.py`

Additional mandatory focused coverage where currently absent:

- [ ] 39-route registration/contract check;
- [ ] field session start/end/break contract;
- [ ] dispatch route creation under duplicate/concurrent assignment;
- [ ] route lifecycle transition/reversal contract;
- [ ] custody handshake accept/reject/batch contract;
- [ ] shortage duplicate/pending-visit merge contract;
- [ ] shop/zone active-route blocking contract;
- [ ] settlement consistency contract;
- [ ] `update_visit` sale/return/correction/idempotency contract.

Do not replace code analysis with broad test spam. Tests prove the extracted seam preserved behavior.

---

# 7. Parallel execution rules for this refactor

- [ ] Only one worker owns a given seam at a time.
- [ ] No two workers concurrently edit the same legacy mega-file region or same new module.
- [ ] Do not run Route Lifecycle extraction in parallel with Route Inventory extraction unless the lead has frozen a no-overlap file map.
- [ ] Do not run Field Session extraction in parallel with Identity token/session cutover unless contracts and file ownership are frozen.
- [ ] Read-model extraction is a preferred parallel candidate because it can be isolated from write state machines.
- [ ] Every worker branch starts from latest approved `main`.
- [ ] Primary lead reviews every diff before merge.
- [ ] Merge -> delete branch -> next task starts from new `main`.

---

# 8. Final closure criteria

This plan is complete only when all are true:

- [ ] `driver.py` mega-file is gone or contains no Runtime implementation and no temporary compatibility debt.
- [ ] `dispatch.py` mega-file is gone or contains no Runtime implementation and no temporary compatibility debt.
- [ ] all 39 public endpoint contracts remain intentionally accounted for;
- [ ] no duplicate route registration exists;
- [ ] no new mega-file replaces the old ones;
- [ ] no new god-function was introduced as part of movement;
- [ ] identity/auth logic has one canonical owner;
- [ ] Inventory remains physical stock/custody authority;
- [ ] Dispatch remains route/assignment/load orchestration authority;
- [ ] Field operations remain representative session/visit interaction authority;
- [ ] Finance/Tax/Pricing/UOM/Product lifecycle authorities are consumed, not duplicated;
- [ ] transaction boundaries and lock ordering are preserved or deliberately changed only through a separately approved plan;
- [ ] focused regression gates pass;
- [ ] temporary compatibility imports/modules are removed;
- [ ] final module structure is documented in architecture/module-boundary docs;
- [ ] owner/lead accepts the refactor as a stable checkpoint.
