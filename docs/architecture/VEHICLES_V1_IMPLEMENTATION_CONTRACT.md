# Vehicles V1 Implementation Contract

**Status:** FROZEN FOR IMPLEMENTATION  
**Freeze date:** 2026-10-14  
**Base SHA audited:** `c4010598f48e92d3a609d3b58476f2d9dc26be4a`  
**Authority:** `ARCHITECTURE.md`, `.rules`, `AGENTS.md`, `V1_SCOPE_FREEZE.md`, `PARALLEL_EXECUTION_LEADERSHIP_PROTOCOL.md`, `REPRESENTATIVES_VEHICLES_V1_PLAN.md`, `docs/architecture/VEHICLE_MASTER_SCOPE_AND_VISIBILITY_DECISION.md`.

This document freezes the exact V1 Vehicle administration contract after a source-first audit of the current Vehicle, Dispatch, WorkSession, InventoryLocation, transfer, reconciliation, stocktake, authorization, Live Stock, and Dashboard paths. Workers must not broaden or reinterpret it.

---

## 1. Source audit closure

The audit established the following current runtime facts:

- `Vehicle` already exists as company-owned master data with `company_id`, `plate_number`, optional `vehicle_type`, `current_mileage`, optional `next_oil_change`, optional `license_expiry_date`, `maintenance_status`, and `is_active`.
- `(company_id, plate_number)` is already unique and `(company_id, id)` is tenant-guarded.
- `DispatchRoute` stores `vehicle_id` and `source_location_id` independently. Source warehouse is route/workflow data, not Vehicle ownership.
- active/waiting/postponed Dispatch routes already have a unique-per-vehicle database invariant.
- `InventoryLocation` already enforces `location_type='VEHICLE'` when `vehicle_id` is present and requires a `vehicle_id` for VEHICLE locations.
- `uq_active_inventory_location_vehicle` already prevents more than one active VEHICLE location for the same `(company_id, vehicle_id)`.
- existing Driver session start, Dispatch inventory/load flows, reconciliation, stocktake, and Live Stock all resolve the Vehicle custody location through `(company_id, vehicle_id, location_type='VEHICLE')`.
- Dispatch already refuses unresolved Vehicle custody reuse when a WorkSession tied through a route has not completed inventory reconciliation.
- Warehouse deactivation code already proves the relevant Inventory invariants for a location: nonzero on-hand/reserved stock, unfinished transfers, unreleased InventoryLock, active Stocktake, and unfinished route references.
- transfer-destination policies are validated to WAREHOUSE locations, so a VEHICLE location is not a valid published special-transfer destination policy target.
- `maintenance_status='In_Maintenance'` currently exists as stored Vehicle state but current Dispatch runtime does not consistently enforce it. V1 must make eligibility backend-authoritative.
- the canonical permission catalog currently has no `vehicle.*` capability family.
- the current Dashboard Vehicles tab is a disabled placeholder and the page navigation is currently gated only by `representative.read`.

No Vehicle CRUD implementation currently owns atomic Vehicle + VEHICLE InventoryLocation creation.

---

## 2. Master ownership and future visibility seam

Frozen rules:

- Vehicle master ownership is **Company**.
- Do not add `Vehicle.warehouse_id` or equivalent permanent warehouse ownership in V1.
- Do not add Vehicle↔Warehouse assignment tables or assignment UI in V1.
- The Vehicle's authoritative VEHICLE InventoryLocation is custody identity, not organizational warehouse ownership.
- Source warehouse remains explicit on Dispatch/load workflow records.
- Vehicle administration queries must live behind dedicated query/application seams. V1 company-wide visibility must not be hardcoded in a way that prevents a future additional warehouse-scope predicate.
- Do not reuse `dispatch_access.vehicle_filter()` as Vehicle-master visibility authority. That helper represents current Dispatch/custody-location authorization semantics.
- Future warehouse-filtered Vehicle visibility will intersect Vehicle capability with applicable warehouse scope. V1 must leave a clean insertion seam for that predicate without implementing the V2 policy.

---

## 3. Frozen capability family

V1 capability codes are:

- `vehicle.read`
- `vehicle.manage`

Both are **company-level capability authority in V1** and must be registered in the canonical permission catalog and `COMPANY_ONLY` set.

Semantics:

- `vehicle.read`: list/detail/search Vehicle master data.
- `vehicle.manage`: create/update/maintenance-state/deactivate/reactivate Vehicle master data.
- Company Owner receives authority only through canonical Owner subject behavior.
- Backoffice users receive authority through canonical Roles.
- FIELD Representatives receive no Dashboard Vehicle administration authority merely because they operate Vehicles.
- warehouse/location access alone never grants either Vehicle capability.
- no `Driver.is_admin`, role-string shortcut, client-supplied `company_id`, or frontend-only filter is authority.

---

## 4. Frozen backend ownership

New Vehicle administration starts in dedicated target modules:

```text
wa_backend/domains/vehicles/
  __init__.py
  contracts.py
  repository.py
  queries.py
  management.py
  custody.py
  lifecycle_guards.py
  lifecycle.py

wa_backend/api/vehicles/
  __init__.py
  schemas.py
  read.py
  management.py
  lifecycle.py
```

Responsibilities:

- `contracts.py`: domain/application commands, views, and Vehicle errors only.
- `repository.py`: Vehicle-owned persistence/query primitives only.
- `queries.py`: bounded list/detail/search read models and future visibility-predicate seam.
- `management.py`: create/update orchestration only.
- `custody.py`: the Vehicle-to-authoritative-VEHICLE-location invariant and orchestration against existing Inventory authority; no balance mutation.
- `lifecycle_guards.py`: source-derived deactivation/maintenance safety blockers only.
- `lifecycle.py`: deactivate/reactivate state transitions and audit/idempotency orchestration.
- API modules remain thin HTTP adapters.

`dispatch.py`, `driver.py`, and `services.py` are not Vehicle CRUD extension points. Existing operational behavior may consume the new Vehicle seam later, but new master-management business logic must not be dumped into those legacy files.

`main.py` may receive only the dedicated `api.vehicles` router mount.

---

## 5. Persistence change allowed in V1

The current legacy `vehicles` table has no optimistic-concurrency column. V1 adds:

- `Vehicle.version`: positive integer, non-null, default/server-default `1`.

Do **not** fabricate historical Vehicle creation/update timestamps for existing rows in V1. The current table predates this administration surface and there is no truthful historical timestamp source. Adding fake `created_at` values would create false history.

The existing fields remain authoritative and no Vehicle identity rewrite occurs.

---

## 6. Frozen public Vehicle view

List/detail/create/update responses expose:

- `id`
- `plate_number`
- `vehicle_type`
- `current_mileage`
- `next_oil_change`
- `license_expiry_date`
- `maintenance_status`
- `is_active`
- `version`
- `custody_ready`

`custody_ready` is a business readiness projection only. It must never expose a raw InventoryLocation ID. It means the Vehicle has exactly one tenant-valid VEHICLE custody location in the state expected for the Vehicle lifecycle; ambiguous/missing/inconsistent custody returns false or a fail-closed integrity error where mutation safety requires it.

Do not expose `company_id`, internal InventoryLocation IDs/codes, audit actor IDs, or legacy Driver IDs.

---

## 7. Frozen HTTP surface

```text
GET   /vehicles
GET   /vehicles/{vehicle_id}
POST  /vehicles
PATCH /vehicles/{vehicle_id}
POST  /vehicles/{vehicle_id}/deactivate
POST  /vehicles/{vehicle_id}/reactivate
```

No hard-delete route.

Capability mapping:

- GET routes -> `vehicle.read`
- create/update/lifecycle -> `vehicle.manage`

Tenant authority always comes from `BackofficeCapabilityAccess.company_id`.

Read-only routes must not load a legacy Driver solely for provenance.

---

## 8. Frozen list contract

`GET /vehicles`

Query parameters:

- `search`: optional, 2..100 characters; searches plate number and vehicle type.
- `active`: optional boolean; omitted = all.
- `maintenance_status`: optional exact enum `Active | In_Maintenance`.
- `cursor`: optional opaque cursor, max 512 characters.
- `limit`: default 30, min 1, max 100.

Ordering is deterministic:

1. active + operational (`maintenance_status='Active'`) first;
2. active + in-maintenance next;
3. inactive last;
4. normalized plate number;
5. Vehicle id tie-breaker.

Cursor identity must be bound to the current tenant/filter/search scope. Clients/tests must not depend on cursor encoding.

No heavy InventoryBalance join is allowed for the list. Custody readiness is derived from the Vehicle↔InventoryLocation mapping only.

---

## 9. Frozen field validation

### Plate number

- required on create;
- non-empty after trim;
- max 20 characters, preserving current storage contract;
- trim surrounding whitespace but do not destroy meaningful internal formatting;
- no NUL;
- company-scoped uniqueness remains database-backed.

V1 does not introduce a speculative country-specific plate parser or silently rewrite plate format.

### Vehicle type

- optional;
- trim when present;
- max 50;
- blank normalizes to null.

### Mileage/basic maintenance fields

- `current_mileage`: integer >= 0, default 0 on create.
- `next_oil_change`: optional integer >= 0.
- `license_expiry_date`: optional date.

V1 does not invent fleet-maintenance scheduling, work orders, fuel, cost accounting, or automatic odometer policies.

### Maintenance status

Exact stored V1 enum remains:

- `Active`
- `In_Maintenance`

No additional lifecycle meanings are silently encoded into this field.

---

## 10. Frozen create contract

`POST /vehicles` -> `201` + Vehicle view.

Request includes:

- `request_id: UUID`
- `plate_number`
- optional `vehicle_type`
- optional `current_mileage` (default 0)
- optional `next_oil_change`
- optional `license_expiry_date`
- optional `maintenance_status` (default `Active`)

Creation always creates an active Vehicle master and its active custody mapping. If an operator needs to take it out of service, lifecycle/maintenance commands are explicit after creation.

Atomic transaction:

1. reserve idempotency identity;
2. create Vehicle and flush its stable id;
3. create exactly one linked `InventoryLocation` with:
   - same `company_id`;
   - `branch_id = NULL`;
   - `location_type = 'VEHICLE'`;
   - `vehicle_id = Vehicle.id`;
   - `system_role = NULL`;
   - `is_system_managed = FALSE` as required by the current database constraint;
   - stable internal generated code not derived from mutable plate ownership semantics;
   - business name may reflect the plate for diagnostics;
   - `is_active = TRUE`;
4. add audit evidence;
5. complete idempotency record;
6. commit once.

Any failure rolls back Vehicle, custody location, audit, and idempotency together.

Retries with the same request identity must replay the same result and never create a second Vehicle or location.

Vehicle CRUD never writes `InventoryBalance` directly.

---

## 11. Frozen update contract

`PATCH /vehicles/{vehicle_id}` -> `200` + Vehicle view.

Request contains:

- `request_id: UUID`
- `expected_version: positive integer`
- any subset of mutable basic fields:
  - `plate_number`
  - `vehicle_type`
  - `current_mileage`
  - `next_oil_change`
  - `license_expiry_date`
  - `maintenance_status`

`is_active` is not mutated through PATCH; lifecycle routes own active/inactive state.

Rules:

- same-company target only; cross-company/missing target is fail-closed and indistinguishable.
- row is locked for mutation.
- `expected_version` mismatch -> deterministic `409` version conflict.
- company plate uniqueness remains enforced under races.
- update is minimal-diff.
- every successful material change increments Vehicle.version exactly once.
- plate changes may update the existing custody location's display name only; they never replace its ID/code or create a second location.
- maintenance changes never recreate/move custody or mutate balances.

---

## 12. Maintenance eligibility rule

The current database stores `In_Maintenance`, but existing Dispatch does not consistently enforce it. V1 closes that gap.

Backend rule:

- a Vehicle is Dispatch-assignable/activatable only when `Vehicle.is_active == true`, `Vehicle.maintenance_status == 'Active'`, and its canonical VEHICLE custody location is active/valid.
- direct API calls must not bypass this rule.
- changing a Vehicle to `In_Maintenance` is blocked while it has an active/waiting/postponed route or an unreconciled WorkSession tied through a route.
- maintenance status does **not** destroy or deactivate custody by itself and does not silently move stock.
- stock may remain in a Vehicle that is in maintenance; Inventory remains stock authority. Operational transfer/reconciliation workflows must be used when stock should be removed.
- changing back to `Active` does not create/replace custody.

This is operational eligibility, not permanent warehouse assignment.

---

## 13. Frozen deactivate blocker matrix

`POST /vehicles/{vehicle_id}/deactivate`

Request:

- `request_id: UUID`
- `expected_version: positive integer`

Before state change, resolve exactly one canonical Vehicle custody location and acquire locks/guards in a deterministic order compatible with current Dispatch/Inventory paths.

Deactivation is blocked by any of:

1. `DispatchRoute` using the Vehicle in `active`, `waiting`, or `postponed` state.
2. any WorkSession tied through a route for this Vehicle whose `inventory_reconciled_at IS NULL`; this includes an active session and an ended session still awaiting inventory reconciliation.
3. nonzero `InventoryBalance.on_hand_quantity` or `reserved_quantity` in the Vehicle custody location.
4. any transfer where that location is source/destination and status is not one of `POSTED`, `REJECTED`, `CANCELLED`.
5. any unreleased `InventoryLock` on the Vehicle custody location.
6. any Stocktake on that location in `DRAFT`, `COUNTING`, `PENDING_REVIEW`, `RECOUNT_REQUIRED`, or `APPROVED`, including VEHICLE_RECON.
7. missing, duplicate/ambiguous, wrong-tenant, wrong-type, or otherwise inconsistent custody mapping.

A WorkSession that has completed inventory reconciliation but is only awaiting independent financial settlement does **not** by itself block Vehicle deactivation; current Dispatch already treats inventory reconciliation as the physical custody release boundary.

Published transfer-destination policy is not a Vehicle blocker because current policy validation requires its destination locations to be active WAREHOUSE locations.

On success, atomically:

- `Vehicle.is_active = false`;
- increment Vehicle.version;
- deactivate the **same** authoritative VEHICLE InventoryLocation and increment its location version;
- add audit evidence;
- complete idempotency;
- commit once.

No balances/history are deleted.

Blocker responses use deterministic code + business message + safe context; no raw internal jargon is required in normal Dashboard copy.

---

## 14. Frozen reactivate contract

`POST /vehicles/{vehicle_id}/reactivate`

Request:

- `request_id: UUID`
- `expected_version: positive integer`

Rules:

- same-company target only;
- Vehicle must currently be inactive;
- resolve the same historical canonical VEHICLE custody location;
- if custody is missing or ambiguous, fail closed rather than creating a replacement;
- reactivate that same location;
- reactivate Vehicle;
- increment Vehicle and InventoryLocation versions appropriately;
- audit + idempotency in the same transaction.

Reactivation must never create a second custody location.

Maintenance status is preserved across deactivate/reactivate. Reactivation does not imply `maintenance_status='Active'`.

---

## 15. Audit/idempotency/provenance

All Vehicle mutations use the existing durable `OperationIdempotency` mechanism rather than a parallel system.

A legacy Backoffice Driver locator may be loaded only when an existing audit/idempotency provenance field genuinely requires `Driver.id`. It is never Vehicle authority or tenant authority.

Request hashes must exclude secrets (there are no Vehicle credentials) and include the material command identity.

Audit must be atomic with each successful mutation.

---

## 16. Dispatch/Inventory integration rule

Vehicle administration does not move stock.

Existing Dispatch remains owner of route/source-warehouse choice and route assignment workflow. Existing Inventory remains owner of balance/movement/transfer/stocktake/reconciliation truth.

Required integration change after the Vehicle master backend is stable:

- Dispatch selectors consume canonical active/eligible Vehicle records.
- route creation and route mutation must enforce `is_active && maintenance_status == 'Active'` server-side, not only in UI filtering.
- explicit `source_location_id` remains mandatory and independent from Vehicle identity.
- active-route uniqueness remains the existing database invariant.
- session start continues requiring a valid active VEHICLE custody location.
- Live Stock attribution remains route/source based and is not replaced by Vehicle master warehouse ownership.

Do not refactor unrelated Dispatch logic during this phase.

---

## 17. Frozen Dashboard ownership

```text
dashboard/src/pages/representatives-vehicles/
  RepresentativesVehiclesPage.tsx       # shared page shell/tab selection only
  vehicles/
    contracts.ts                         # Vehicle DTO/query/form types only
    api.ts                               # Vehicle HTTP client only
    useVehicles.ts                       # list/query/pagination state only
    VehiclesTab.tsx                      # Vehicle tab composition only
    VehicleTable.tsx                     # table/list rendering only
    VehicleForm.tsx                      # create/edit form only
    VehicleRowActions.tsx                # row action menu only
    VehicleLifecycleActions.tsx          # deactivate/reactivate controller/modal only
```

Additional small files are allowed only when they preserve Single Responsibility. Do not collapse these responsibilities into `RepresentativesVehiclesPage.tsx`.

Page/navigation rules:

- `/representatives-vehicles` remains the shared page.
- navigation is visible to Company Owner or users with `representative.read` **or** `vehicle.read`.
- the page allows access to whichever tab the user is authorized to read; one capability never grants the other.
- Vehicle-only users must not need `representative.read` to reach the page.
- remove the gated Vehicle placeholder only when the real Vehicles tab is available.

Vehicle list:

- plate;
- optional type;
- active/inactive;
- operational/maintenance state;
- custody readiness business wording;
- actions.

No raw location ID, warehouse-assignment column, permanent representative selector, GPS/fuel/fleet-cost UI, or hard-delete action.

UI remains Arabic-first, English-ready, RTL/LTR, keyboard-first, compact, and Western-digit friendly.

---

## 18. First implementation waves

Contracts are now stable enough for bounded parallel work.

### Wave 1A — persistence + capabilities + backend foundation

Own:

- Vehicle version migration and Vehicle model version field only;
- `vehicle.read` / `vehicle.manage` permission catalog + database provisioning;
- dedicated `domains/vehicles/**` and `api/vehicles/**` backend implementation;
- focused backend architecture/contract/unit tests;
- `main.py` router mount only as required.

Do not touch Dashboard or broad Dispatch implementation.

### Wave 1B — Dashboard Vehicle feature against frozen API

May start only after the HTTP wire contract from Wave 1A is confirmed unchanged by lead review.

Own:

- `dashboard/src/pages/representatives-vehicles/vehicles/**`;
- the minimal shared page-shell tab wiring;
- exact Vehicle i18n keys;
- sidebar gating change required for `vehicle.read`;
- focused frontend tests.

Do not modify backend/Dispatch.

### Wave 2 — Dispatch eligibility integration

Starts from the stable merged Vehicle backend.

Own only the smallest Dispatch/authorization seams needed to consume canonical Vehicle eligibility, while preserving route/source-warehouse and inventory behavior.

### Adversarial gate

After each meaningful backend/integration PR, an independent specialist review should attempt to break tenant isolation, capability scope, idempotency, Vehicle/location atomicity, lock ordering, lifecycle blockers, Dispatch bypasses, and duplicate-location prevention before lead merge approval.

---

## 19. Focused acceptance required before backend merge

- capability catalog contains `vehicle.read` / `vehicle.manage` with company-only semantics;
- Owner allowed through canonical Owner authority;
- missing capability denied;
- same-company read/create/update/lifecycle works;
- cross-company IDs fail closed;
- duplicate plate rejected under normal and racing create paths;
- create retry/lost-response replay never duplicates Vehicle or custody location;
- forced custody-location creation failure rolls back Vehicle and idempotency atomically;
- exactly one canonical Vehicle custody mapping after create;
- update expected-version conflict proven;
- update never replaces custody location;
- maintenance status finite enum proven;
- maintenance/Dispatch backend bypass rejection proven when integration wave lands;
- open route blocker proven;
- active/ended-unreconciled WorkSession blocker proven;
- nonzero/reserved stock blocker proven;
- unfinished transfer blocker proven;
- active lock blocker proven;
- active Stocktake/VEHICLE_RECON blocker proven;
- inventory-reconciled but financially pending session does not falsely block physical Vehicle reuse/deactivation;
- deactivate preserves history and disables same custody location;
- reactivate reuses exact same custody location;
- no Vehicle CRUD direct `InventoryBalance` mutation;
- bounded list pagination/filter ordering and no N+1/heavy stock join;
- dedicated module architecture; no new Vehicle business logic dumped into `dispatch.py`/`driver.py`.

---

## 20. Explicit V1 non-goals

- GPS/telematics;
- fuel management;
- advanced maintenance scheduling/work orders;
- fleet cost accounting;
- permanent Vehicle↔Representative assignment;
- permanent Vehicle↔Warehouse ownership;
- VehicleWarehouseAssignment or equivalent policy product;
- multi-warehouse Vehicle assignment UI;
- company toggle for warehouse-filtered Vehicle visibility;
- hard delete;
- general Dispatch/Driver mega-file refactor.

Any newly discovered requirement that changes these boundaries must stop and return to the lead/owner before implementation.
