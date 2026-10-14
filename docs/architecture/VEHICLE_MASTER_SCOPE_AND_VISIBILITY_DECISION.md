# Vehicle Master Scope & Operational Visibility Decision

**Status:** CANONICAL ARCHITECTURE DECISION FOR VEHICLES  
**Decision date:** 2026-10-14  
**Applies to:** Vehicle administration, Dispatch vehicle selection, warehouse-scoped Backoffice visibility, Inventory vehicle custody, and future vehicle/warehouse policy configuration.  
**Companions:** `ARCHITECTURE.md`, `.rules`, `AGENTS.md`, `V1_SCOPE_FREEZE.md`, `REPRESENTATIVES_VEHICLES_V1_PLAN.md`.

## 1. Core decision

A Vehicle is **company-owned master data**. A warehouse is never the permanent owner of the Vehicle master record.

Therefore:

- `Vehicle.company_id` remains the tenant/master ownership boundary.
- A Vehicle keeps the same stable identity when it works from a different warehouse.
- Moving operational responsibility from one warehouse to another must not require creating a new Vehicle.
- A Vehicle is not permanently assigned to one Representative.
- A Vehicle is not permanently assigned to one warehouse.
- The source warehouse for a route/load/day is selected by the concrete operational workflow, not encoded as permanent Vehicle ownership.
- Vehicle administration must never imply that every Backoffice user automatically sees every company Vehicle.

The architecture must keep **master ownership**, **operational association**, and **user visibility/authorization** as separate concepts.

## 2. Three separate concepts

### 2.1 Master ownership

The Vehicle belongs to the Company.

This answers: **Who owns this asset inside Wanasah?**

Answer: the Company tenant.

### 2.2 Operational warehouse association

A Company may later choose to associate a Vehicle with one warehouse or several warehouses for operational organization and visibility.

This answers: **Which warehouse teams normally operate or manage this Vehicle?**

This association is optional policy/configuration. It is not Vehicle ownership and must not be hardcoded as a mandatory `warehouse_id` on the Vehicle master contract.

### 2.3 User authorization and visibility

A user sees/manages Vehicles only when canonical capability **and** applicable scope allow it.

Warehouse membership/scope by itself never grants Vehicle administration. Vehicle capability by itself must not bypass a configured warehouse-visibility policy.

The backend remains authoritative; frontend filtering is never the security boundary.

## 3. V1 boundary

V1 must build the foundation correctly without turning Vehicles into a fleet-management or organization-policy product.

### Required in V1

- Vehicle remains a company-level master entity.
- No mandatory warehouse ownership field is introduced into Vehicle.
- Vehicle administration uses canonical Backoffice capability authorization and tenant scope.
- The implementation must not hardcode an assumption that future visibility can only ever be company-wide.
- Read/query/application boundaries must be designed so an additional authorized scope filter can be introduced later without changing Vehicle identity or rewriting Vehicle business logic.
- Every usable Vehicle keeps exactly one authoritative Inventory custody location of type `VEHICLE` according to the Inventory contract.
- That VEHICLE InventoryLocation belongs to the Vehicle custody model; it is not replaced when the Vehicle is later associated with another warehouse.
- Route/load/source-warehouse selection remains owned by the operational Dispatch/Inventory workflow.
- Company Owner / explicitly company-wide authorized users can see the company Vehicle set allowed by their capability.
- No hard delete; lifecycle/history/custody remain durable.

### Explicitly not required in V1 unless the first-company workflow proves it necessary

- A Dashboard setting that assigns every Vehicle to a warehouse.
- A `VehicleWarehouseAssignment` table or any exact equivalent schema.
- Mandatory primary warehouse per Vehicle.
- Multi-warehouse Vehicle assignment UI.
- Historical/effective-dated Vehicle/warehouse assignment management.
- A company toggle that switches between company-wide and warehouse-filtered Vehicle visibility.
- Advanced fleet organizational policies.

These are V2/default-deferred capabilities under `V1_SCOPE_FREEZE.md` unless the owner explicitly promotes them through scope change control or the first-company V1 workflow demonstrates a real blocker.

## 4. Future-ready optional policy

If/when the feature is promoted later, the preferred semantics are:

- The Company can leave Vehicle/warehouse association **disabled**. In that mode, Vehicle visibility remains governed by Vehicle capability and existing authorized company scope.
- The Company can optionally enable warehouse-based Vehicle organization/visibility from the Dashboard.
- A Vehicle may be associated with one or multiple warehouses according to company policy; the architecture must not force one-to-one ownership.
- The association is independent from `Vehicle.company_id` and does not change the Vehicle identity.
- Changing an association does not create a new Vehicle.
- Changing an association does not create a second VEHICLE InventoryLocation.
- Changing an association is not itself an inventory transfer and must not move stock silently.
- A route/load can still use an authorized source warehouse according to the Dispatch/Inventory workflow; warehouse association does not replace route/load authority.
- Warehouse association must not automatically grant a user warehouse access or Vehicle capability.
- A future query can apply the intersection of canonical Vehicle capability and configured organizational scope without rewriting Vehicle domain semantics.

Exact schema/table names are deliberately **not frozen yet**. When this V2 feature is promoted, the lead must inspect the then-current authorization/scope framework and choose the smallest canonical representation rather than introducing a premature table in V1.

## 5. Visibility hierarchy to preserve

The intended business behavior is:

1. **Company Owner** — may see/manage all company Vehicles allowed by canonical Owner authority, while still obeying structural/business invariants.
2. **Company-wide fleet/vehicle administrator** — may see the company Vehicle set granted by the Vehicle capability and company-wide scope.
3. **Warehouse-scoped manager, when warehouse-based Vehicle visibility is enabled** — sees only Vehicles associated with warehouses inside that manager's authorized warehouse scope.
4. **Manager of multiple warehouses** — sees the union of Vehicles associated with the warehouses that are actually inside the manager's authorized scope.
5. **User with Vehicle capability but no matching warehouse scope under an enabled warehouse policy** — sees no warehouse-scoped Vehicles; the backend fails closed rather than falling back to all company Vehicles.
6. **User without Vehicle read capability** — sees no Vehicles regardless of warehouse access.

Important: a warehouse scope never grants Vehicle access by itself, and Vehicle capability never overrides tenant/location/organizational scope.

## 6. Inventory custody is independent

The Vehicle's authoritative InventoryLocation of type `VEHICLE` represents **stock custody inside that Vehicle**, not permanent warehouse ownership.

Consequences:

- one Vehicle -> one authoritative Vehicle custody location;
- warehouse association changes do not recreate that custody location;
- stock inside the Vehicle stays governed by Inventory balances/movements;
- relocating organizational responsibility never silently moves stock;
- actual stock loading/unloading/transfer remains an Inventory/Dispatch operation;
- deactivation must respect stock, route, transfer, reconciliation, stocktake, and other current blockers before state changes are allowed.

## 7. Backend design requirement now

V1 code must avoid future-hostile shortcuts such as:

- mandatory `Vehicle.warehouse_id` ownership;
- `WHERE company_id = ...` followed by an assumption that every authorized user always receives every Vehicle forever;
- UI-only warehouse filtering;
- copying Warehouse authorization rules into the Vehicles domain;
- creating separate Vehicle records for the same physical asset when operational warehouse responsibility changes;
- creating a new VEHICLE InventoryLocation when warehouse association changes.

Instead, keep Vehicle queries/services behind explicit application/repository seams so future scope predicates can be added through canonical authorization/scope contracts.

## 8. V1 implementation rule for the upcoming Vehicles phase

Before Vehicles code is written, the technical lead must inspect current Vehicle, Dispatch, InventoryLocation, WorkSession, transfer, reconciliation, stocktake, and capability code, then freeze the exact V1 HTTP/application contract.

That contract must preserve this decision:

> **Vehicle master ownership is Company-wide. Operational warehouse association and user visibility are independent, optional scope/policy concerns. V1 builds the future-ready boundary but does not implement the optional warehouse-assignment product unless a real V1 blocker requires it.**
