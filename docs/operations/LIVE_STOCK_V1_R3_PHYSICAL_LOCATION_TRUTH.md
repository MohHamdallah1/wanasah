# Live Stock V1 R3 — Owner-approved physical-location inventory truth

**Status:** P0 correction contract. The owner rejected latest-Route vehicle-to-Warehouse attribution.
**Exact correction base:** `ae858c10f04832aaf99df55db15507571986b53e`.
**Evidence predecessor:** PR #684 remains factual evidence of the rejected behavior. Its recommendation is superseded.
**Rejected workaround:** PR #685 must not be merged as a substitute for this correction.

## Non-negotiable authority

`InventoryBalance` at its canonical `InventoryLocation` is the only quantity/location authority.

- WAREHOUSE balance is physically inside that Warehouse.
- VEHICLE balance is physically inside that Vehicle custody location.
- IN_TRANSIT belongs to its explicit transit location/state.
- A DispatchRoute is workflow metadata. Its source, status, age, reassignment, creation or closure never owns or reallocates physical stock.
- Warehouse -> Vehicle movement atomically decreases the Warehouse location and increases the Vehicle location.
- Internal Warehouse/Vehicle movement does not create COGS or a second financial ownership ledger.

## Corrected Live Stock contract

### Warehouse projection

Projection version 2 is Warehouse-physical-only.

`InventoryLiveStockProjection.vehicle_packs` and `has_vehicle_presence` remain database compatibility columns for this V1 schema, but projection v2 always writes them as zero/false and never uses them for sparse membership, summaries, filters, candidate discovery, rebuild truth, movement attribution or public quantity truth.

A persisted projection version 1 is not READY under v2. Reads fail closed until the canonical projection rebuild completes. This prevents stale latest-Route attribution from surviving deployment.

### Vehicle custody disclosure

The existing Warehouse Live Stock response keeps a separate `vehicle_quantity` disclosure only as a cross-location compatibility field. It is **not Warehouse-specific** and it is never added to `total_quantity`.

It is read directly from authorized active canonical VEHICLE InventoryLocations in the same inventory read, without a DispatchRoute join.

`vehicle_quantity_scope` is explicit:

- `COMPANY_WIDE`: the caller has company-wide `inventory.read`; numeric value covers all canonical Vehicle custody in the company.
- `AUTHORIZED_LOCATIONS`: the caller is location-scoped; numeric value covers only Vehicle locations the caller may read.
- `NO_ACCESS`: the caller has no readable Vehicle custody location. `vehicle_quantity` is `null`, never fake numeric zero.

A numeric zero therefore means known zero inside the declared readable scope. `null + NO_ACCESS` means no Vehicle disclosure authority. Read-model unavailability remains an HTTP fail-closed condition rather than an invented quantity.

The `has_vehicle` filter means “positive physical custody in the caller's readable Vehicle locations”, independent of selected Warehouse and Route.

### Warehouse total

`total_quantity` is retained as a compatibility name but is redefined to selected-Warehouse physical on-hand only, across physical statuses. It never includes Vehicle custody.

`total_quantity_scope` is always `WAREHOUSE_PHYSICAL`.

This makes it safe to sum distinct Warehouse physical totals without duplicating Vehicle custody. Company-wide physical inventory is Warehouse + Vehicle + any other canonical physical location exactly once.

### Vehicle-only/nonactive visibility

Vehicle custody can make a nonactive product visible because custody still exists, but the quantity remains in the separate Vehicle disclosure. This does not create Warehouse ownership.

Batch/source disclosure continues to enumerate actual physical InventoryLocations and statuses.

## Removed Route coupling

The correction removes:

- latest DispatchRoute source lookup from projection aggregation;
- Route-derived Vehicle candidate keys;
- Route-derived Vehicle sparse membership and summaries;
- Route-derived `vehicle_packs` incremental updates;
- Dispatch Route create/update hooks that refreshed vehicle attribution;
- selected-Warehouse Route joins from Vehicle filters, list membership, totals and permission-scoped disclosure.

Route workflow locks and `VEHICLE_LOAD_OWNED_BY_WORKFLOW` remain intact. They control whether a movement command is legal; they do not decide where posted stock is located.

## Required truth matrix

| Stage | Physical W1 | Physical W2 | Physical Vehicle | W1 Warehouse total | W2 Warehouse total | Separate Vehicle custody |
|---|---:|---:|---:|---:|---:|---:|
| Direct W2 load, no Route | 100 | 70 | 30 | 100 | 70 | 30 |
| Create W1 Route | 100 | 70 | 30 | 100 | 70 | 30 |
| Close W1 Route + legal W2 load | 100 | 50 | 50 | 100 | 50 | 50 |
| W2 unload 10 | 100 | 60 | 40 | 100 | 60 | 40 |
| Create newer W2 Route | 100 | 60 | 40 | 100 | 60 | 40 |

At each required stage: physical total = 200. Financial quantity = 200 and inventory value = 600 from the two original PURCHASE_IN events. Route operations add no financial event and no physical movement.

## Permission and multi-location rules

- Revoking Warehouse access denies that Warehouse read; it does not affect other physical locations.
- Revoking all readable Vehicle locations returns `vehicle_quantity=null` with `NO_ACCESS`; it does not alter physical stock.
- One Vehicle may contain batches loaded from different Warehouses. Current custody remains the Vehicle, not either origin Warehouse.
- Multiple Vehicles are aggregated once in the separate Vehicle-custody disclosure.
- A Vehicle with no Route is still visible through authorized Vehicle-custody reads and batch/source physical disclosure.
- No Route creation/closure/reassignment may change a quantity, candidate association, or Warehouse total.

## Deployment/readiness requirement

Because semantic projection version changed from 1 to 2, deploy must run the canonical Live Stock company rebuild before considering Live Stock READY. Until rebuild, readiness is intentionally fail-closed.

No schema migration is needed: the legacy Vehicle projection columns are retained only for storage compatibility and neutralized by v2.

## Mandatory Dashboard integration dependency

This backend correction deliberately does not edit #673-owned frontend/browser files.

Before overall closure/merge to production, the Dashboard consumer owned by #673 (or a coordinated successor PR after #673) must:

1. accept nullable `vehicle_quantity`;
2. consume `vehicle_quantity_scope` and distinguish NO_ACCESS from numeric zero;
3. treat `total_quantity` as WAREHOUSE_PHYSICAL only;
4. stop any copy/tooltip implying latest Route or Warehouse-attributed Vehicle quantity;
5. explain that Vehicle custody is a separate permission-scoped physical bucket;
6. keep `has_vehicle` semantics as physical readable Vehicle custody independent of selected Warehouse;
7. re-run Arabic/English, desktop/mobile and real-browser acceptance against this API.

The concrete Dashboard consumers that must be coordinated are:

- `dashboard/src/pages/inventory/liveStock/contracts.ts`: accept nullable Vehicle custody plus both scope fields.
- `dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx`: stop presenting the Vehicle value as Warehouse-attributed quantity.
- `dashboard/src/pages/inventory/liveStock/LiveStockMobileCards.tsx`: same physical-custody disclosure on mobile.
- `dashboard/src/pages/inventory/MainInventory.tsx`: keep the `has_vehicle` filter wording/behavior explicitly cross-vehicle-scope rather than selected-Warehouse ownership.
- Live Stock fixtures/tests that still encode `total_quantity = warehouse + vehicle` or always-numeric `vehicle_quantity`.
- #673's real-browser support/journey must be rerun against the corrected API after those consumer changes; this PR deliberately does not edit its owned files.

Until that dependency passes, backend truth can be reviewed independently but **overall Live Stock R3 closure is not merge-ready**.
