# Catalog / Inventory Workflow Boundaries

**Status:** CANONICAL ARCHITECTURE COMPANION  
**Owner decision:** 2026-10-04  
**Scope:** Dashboard UX ownership, backend domain ownership, cross-module navigation, multi-warehouse behavior, batch/quality workflows, future fleet/driver integration.

This document is a companion to `ARCHITECTURE.md`. It does not replace the repository-wide constitution. Where there is any conflict, `ARCHITECTURE.md`, `.rules`, and the workflow-protection rule remain authoritative.

## 1. Why this document exists

Wanasah is evolving toward a Strict Modular Monolith. Catalog and Inventory are closely related, but they must not become one mixed module.

The architecture rule is:

> **Catalog owns what the product is and whether the company intends to sell/use it. Inventory owns where physical stock is, which batch it belongs to, and what physical action happens to quantities.**

A page may display a warning sourced from another domain, but it must not silently become the mutation authority for that other domain.

This boundary is especially important for companies with many warehouses, vehicles, representatives, and future operational modules.

---

## 2. Domain ownership

### 2.1 Catalog / Products owns

Catalog is **company-wide**, not warehouse-specific.

It owns:
- Product master identity.
- Sellable variant/SKU identity.
- Product name and family/category assignment.
- UOM/package identity and catalog packaging metadata.
- Barcode identity.
- Tracking policy/defaults for lot and expiry behavior.
- Simple catalog price workflow where currently assigned to Products UI; Pricing remains the backend authority for published pricing semantics.
- Product lifecycle/business availability such as Active, temporarily stopped, out of use, archived.
- A company-wide safety/quality hold that affects the **whole product**, when the problem scope is explicitly the entire product.
- Import and catalog maintenance workflows.

Catalog does **not** own:
- Physical quantities.
- Warehouse balances.
- Batch inventory actions.
- Reservations.
- Transfers.
- Stocktakes.
- Supplier receipt stock movement.
- Vehicle/representative custody quantities.

### 2.2 Inventory / Warehouse owns

Inventory is the physical stock authority. `InventoryBalance` and the Unified Inventory Movement Engine remain authoritative.

It owns:
- Stock by exact warehouse/location.
- Batch/lot identity as it affects physical stock control.
- Batch disposition and batch-level sellability restrictions.
- Expiry and batch-operational handling.
- Reserved quantities.
- Physical movements.
- Warehouse-to-warehouse transfers.
- Warehouse-to-vehicle / custody movements where supported.
- Recall/quality-related physical quantity operations.
- Supplier inbound stock posting.
- Stocktake and reconciliation.
- Inventory ledger/movement evidence.

Inventory does **not** own:
- Renaming a product.
- Changing product family/category.
- Editing barcode identity.
- Catalog lifecycle definition.
- Archiving the catalog record.

### 2.3 Dispatch / Fleet / People future ownership

Future driver, representative, vehicle, route, and fleet modules must remain separate owners of their master data and operational assignment.

Examples:
- Fleet/Dispatch owns vehicle identity, active/inactive state, route assignment, and operational availability.
- People/Users owns representative/driver identity and employment/access context.
- Inventory may reference a vehicle or custody location through a stable public contract, but must not create/edit the vehicle master.
- Products must not depend on driver or vehicle internals.

A vehicle may function as an inventory location/custody endpoint, but **vehicle identity authority and stock authority remain separate**.

---

## 3. Page responsibilities

### 3.1 Products page

**Purpose:** manage the company-wide catalog.

Allowed responsibilities:
- Add/import product.
- Rename product.
- Change family/category.
- Edit supported catalog pricing UI.
- Manage barcode identity.
- Manage tracking policy.
- Temporarily stop/resume sale of the product company-wide.
- Mark product out of use / restore it.
- Archive the catalog record when backend preconditions allow.
- Start a company-wide quality/safety issue for the whole product.
- Show concise warnings that inventory owns, such as: `1 batch unavailable for sale`.
- Deep-link the user to the owning Inventory workflow.

Forbidden responsibilities:
- Change a batch disposition.
- Move quantity.
- Release reservation.
- Return stock to supplier.
- Dispose stock.
- Perform warehouse transfer.
- Perform stocktake/reconciliation.
- Pretend Live Stock is an action page.

**Rule:**

> Products may **show** an inventory problem, but Products must not **process** the physical inventory problem.

### 3.2 Live Stock page

**Purpose:** read-only operational stock truth for the selected warehouse/location.

It answers:
- What is in this warehouse now?
- How much is available, reserved, unavailable, damaged, recalled, or otherwise restricted?
- Where is the quantity?

It is **not** the place for multi-step corrective actions.

Live Stock may deep-link to the correct action owner, but a button that says the user must fix something must not open Live Stock if Live Stock cannot perform that action.

### 3.3 Batches & Expiry page

**Purpose:** manage one batch/lot and its operational quality/expiry state, scoped through Inventory authority.

It owns user-facing workflows such as:
- `عزل الدفعة للفحص` — temporary isolation while the batch is being checked.
- `منع بيع الدفعة` — stronger restriction; the batch is not directly returned to sale from this decision without the allowed next transition.
- `استبعاد الدفعة من البيع نهائيًا` — confirmed final batch-level decision; this batch will not return to sale.
- `السماح ببيع الدفعة من جديد` when the current backend transition permits it.

When quantity exists, the same Inventory-owned workflow must show concrete quantity actions rather than telling the user to “process” stock elsewhere.

Examples of physical actions, subject to backend policy/permissions:
- Move to quarantine.
- Return to supplier.
- Send for disposal.
- Collect/return quantity from custody/vehicle.
- Execute the approved transfer path required by the company policy.

### 3.4 Inbound page

**Purpose:** receive physical goods into the explicitly selected warehouse.

It owns:
- Supplier receipt stock entry.
- Batch/expiry capture required for the receipt.
- Actual purchase quantity/UOM/cost evidence required by existing costing rules.

It does not create or redefine catalog identity except through an explicitly approved catalog contract.

### 3.5 Transfers page

**Purpose:** move existing physical stock between authorized locations.

It owns:
- Source/destination selection under exact-location permission checks.
- Warehouse/vehicle/custody movement workflows supported by the backend.
- Transfer lifecycle and evidence.

It does not redefine product or batch business identity.

### 3.6 Stocktake / Reconciliation page

**Purpose:** compare physical reality with system stock and apply the approved stocktake/reconciliation workflow.

It is not a generic escape hatch for product lifecycle blockers.

### 3.7 Warehouse Management page

**Purpose:** warehouse/location master and warehouse operational configuration.

It owns:
- Warehouse/location identity and activation.
- Warehouse-scoped policy/configuration that belongs to Inventory.
- Location-level operational enablement where the backend defines it.

---

## 4. Scope rules: company vs warehouse

### Company-wide

These decisions are company-wide:
- Product identity.
- Product lifecycle/business availability.
- Whole-product quality/safety hold.
- Catalog archive state.

They must not require the Products page to select a warehouse.

### Location-scoped

These are location-specific:
- Stock balances.
- Reservations.
- Physical movement.
- Inbound.
- Transfer source/destination.
- Stocktake.
- Vehicle/custody quantity.

Every mutation must enforce exact location authority in the backend.

### Batch scope

A batch restriction may be logically company-wide for that batch identity while physical quantity remains distributed across many locations.

Therefore:
- The batch decision can make the batch unavailable for sale everywhere it exists.
- Physical handling must still be executed per authorized location/source.
- A company-wide summary may list affected locations, but it must never bypass location permissions.

---

## 5. Product-wide quality/safety flow

The user-facing UI must not expose backend implementation words such as `RECALL`, `close-recall`, or `RECALL_RETURN`.

### Entry from Products

Use:

**`مشكلة جودة أو سلامة`**

Then ask:

**`أين توجد المشكلة؟`**
- `دفعة محددة`
- `المنتج بالكامل`

If the user selects `دفعة محددة`, Products deep-links to Batches & Expiry and does not mutate the batch itself.

If the user selects `المنتج بالكامل`, Catalog may apply the company-wide product hold through its existing backend authority.

### Resolution when the whole product was stopped

The user sees two human decisions:

1. **`تبين أن المنتج سليم`**
   - Used when the whole-product alarm was false or the issue did not actually include the whole product.
   - Restores the product-level hold if backend safety guards allow it.
   - Existing batch restrictions remain independent and visible.

2. **`المشكلة مؤكدة — التعامل مع الكميات الحالية`**
   - Opens an Inventory-owned workflow.
   - Inventory shows affected quantities by warehouse/vehicle/custody location.
   - The user gets concrete allowed actions for each quantity.
   - No generic phrase such as “عالج الكمية” is acceptable without a specific action.

After the affected physical quantities and open operations are resolved, the business choice must be expressed in user language:
- `السماح ببيع المنتج من جديد`, if future stock of this product may be sold.
- `التوقف عن استخدام المنتج`, if the company no longer wants the product.

The UI must not say `إغلاق السحب`, `إنهاء الاستدعاء`, or `إرجاع الكمية ضمن السحب`.

Backend codes may remain unchanged internally.

---

## 6. Batch quality/expiry flow

### State 1 — normal

Batch can be sold if all Inventory sellability rules permit it.

### State 2 — `عزل الدفعة للفحص`

Use when there is uncertainty such as:
- suspected expiry issue;
- suspected damage;
- quality inspection required;
- labeling concern;
- temperature/storage concern.

The batch is unavailable for sale while under inspection.

### State 3 — `منع بيع الدفعة`

Use when a stronger restriction is required and the batch must not be used while the company decides the final outcome.

The UI must explain that this is stronger than inspection isolation and is not the simple “inspection passed → return to sale” path.

### State 4 — `استبعاد الدفعة من البيع نهائيًا`

Use when the company has confirmed that this batch must not return to sale.

The next user decision concerns the physical quantities, not the batch label itself:
- return to supplier;
- disposal;
- approved quarantine/collection path;
- custody/vehicle collection as required.

The backend may continue to use canonical codes such as `QUARANTINED`, `BLOCKED`, and `RECALLED`; the UI translates them into the business language above.

---

## 7. Cross-module communication rules

### 7.1 No sibling page UI imports

A Products component must not import Inventory page implementation components merely to reuse a workflow UI.

Bad target pattern:

`pages/products/... -> pages/inventory/.../SomeInventoryActionPanel`

Likewise Inventory must not import internal Products UI to mutate Catalog.

### 7.2 Reuse contracts, not page internals

Cross-module reuse is allowed through:
- backend application/public contracts;
- stable DTOs;
- pure domain-independent UI primitives;
- route/navigation intent contracts;
- documented query summaries.

### 7.3 Navigation is not authority

A route/query/local UI hint may preselect a product, batch, warehouse, or tab, but:
- it never grants access;
- it never authorizes a mutation;
- the backend re-checks company and exact-location permissions.

### 7.4 Do not use localStorage as the long-term cross-module workflow bus

LocalStorage may preserve UI preference, but it must not become the canonical contract for “Products tells Inventory what business operation to execute”.

Target direction:
- explicit route/navigation intent;
- bounded parameters such as product/variant/batch/location identifiers;
- Inventory resolves and validates the target under its own authority.

---

## 8. Frontend ownership target

Target responsibilities:

- `dashboard/src/pages/products/`
  - Products page composition.
  - Product lifecycle UI.
  - Catalog warnings/summaries.
  - Product-owned actions.

- `dashboard/src/pages/inventory/`
  - Inventory page composition.
  - Live Stock.
  - Batches & Expiry.
  - Inbound.
  - Transfers.
  - Stocktake.
  - Warehouse management.

Shared cross-page code must be small and non-authoritative:
- generic form controls;
- formatting;
- navigation intent types/helpers;
- transport/error utilities.

Do not create a generic “shared business logic” dumping ground.

---

## 9. Future scalability rules

### Multiple warehouses

The system must assume a company can have many warehouses.

- Products remains company-wide.
- Inventory actions require explicit warehouse/location context.
- A company-wide incident can summarize many locations, but each mutation remains location-authorized.
- No mass implicit warehouse assignment.

### Drivers and representatives

When drivers/representatives are added:
- their identity belongs outside Catalog and Inventory;
- Inventory consumes custody/location identity through a public contract;
- product availability must not depend on UI knowledge of a specific driver;
- stock with a representative/vehicle remains physical Inventory truth.

### Vehicles

When vehicles are added/expanded:
- Fleet owns vehicle master and operational assignment;
- Inventory may treat the vehicle as an authorized stock/custody location;
- transfers to/from vehicles use Inventory movement authority;
- Product page never manages vehicle stock.

### Purchasing / suppliers

If Purchasing becomes a first-class module later:
- supplier master / purchase-order lifecycle belongs to Purchasing;
- Inventory Inbound owns the physical receipt/posting contract;
- Costing retains its own financial authority as already defined in the architecture constitution.

---

## 10. UX rules derived from the boundary

1. Never expose backend state-machine terminology when a normal business phrase exists.
2. Never tell the user to “process/handle” something without showing the concrete next action.
3. Never send a user to a read-only page to perform a mutation.
4. Warnings should deep-link to the owning workflow and preserve enough context to locate the affected record.
5. Product status and batch status are independent:
   - a product can be available while one batch is unavailable for sale;
   - a product-wide hold can stop all sales while batch evidence remains separate.
6. Zero stock does not mean the product is stopped.
7. A batch restriction does not mean the entire product is inactive.
8. The UI may summarize cross-domain facts, but the owning domain performs the mutation.

---

## 11. Explicit anti-patterns

Do not introduce or preserve as target architecture:
- Products mutating batch disposition.
- Products performing inventory transfers.
- Inventory changing product name/family/barcode/lifecycle.
- `Products -> Inventory UI component` imports for business workflows.
- `Inventory -> Products UI component` imports for business workflows.
- LocalStorage as a business command bus between modules.
- A blocker button that opens a page incapable of resolving the blocker.
- Generic “معالجة” instructions with no concrete action.
- Company-wide mutation based only on a selected warehouse UI context.
- Location-scoped mutation without backend exact-location authorization.

---

## 12. Acceptance test for any future feature

Before adding a new workflow, answer:

1. Who owns the business truth: Catalog, Inventory, Pricing, Sales, Dispatch/Fleet, Purchasing, or another module?
2. Is the decision company-wide or location-scoped?
3. Which page is the action owner?
4. Is another page only displaying a warning/summary?
5. Does the navigation preserve context without becoming authority?
6. Does the backend re-check tenant and exact-location access?
7. Are we importing a sibling page's internal UI/business code? If yes, stop and redesign the boundary.
8. Can this design still work with 1 company + many warehouses + many vehicles + many representatives?

If these questions do not have clear answers, implementation should pause until the flow is defined.