# P0 System-Wide Physical Inventory Location Truth Audit

**Repository:** `MohHamdallah1/wanasah`  
**Exact audit base:** `ae858c10f04832aaf99df55db15507571986b53e`  
**Audit mode:** READ-ONLY production-code audit. This document is the only audit-branch change.  
**Owner decision:** latest-route-source vehicle attribution is rejected. Presentation-only PR #685 is also rejected as a correction.

## 1. Non-negotiable physical invariant

Every unit of current stock belongs exclusively to its actual current `InventoryLocation`.

- `WAREHOUSE`: physically inside that warehouse.
- `VEHICLE`: physically inside that vehicle.
- `IN_TRANSIT`: physically in the canonical transit custody state.
- `DispatchRoute` source, status, history, assignment and existence are operational workflow facts only. They are never physical-location authority.
- A successful `WAREHOUSE -> VEHICLE` movement decrements the warehouse and increments the vehicle atomically.
- A route create/close/reassign operation with no inventory movement must not move, reattribute, duplicate, hide or manufacture physical stock.
- Loading provenance is not ownership. This audit does not invent per-warehouse ownership for stock that is physically in a vehicle.

## 2. Audit method and evidence boundary

The source audit was performed against the exact starting commit above. GitHub `main` moved during the audit, so default-branch search was used only to discover candidate filenames; every final behavior classification below is grounded by re-reading the affected file at `ae858c10...`.

The bounded PostgreSQL 16 scenario from PR #684 is reused as real failing evidence rather than duplicated. #684 already used real supplier inbound, canonical Vehicle creation, direct Vehicle Load, Dispatch route create/close, location-scoped permissions, FIFO and MOVING_AVERAGE, and a restricted NOSUPERUSER/NOBYPASSRLS runtime role. No redundant 50k benchmark or second equivalent scenario was run for this read-only audit.

## 3. Reused #684 physical truth

| Stage | Physical W1 | Physical W2 | Physical Vehicle | Company physical total | Latest route source | Current Live Stock vehicle attribution |
|---|---:|---:|---:|---:|---|---|
| Supplier inbound complete | 100 | 100 | 0 | 200 | none | none |
| Direct W2 load 30, no Route | 100 | 70 | 30 | 200 | none | W1=0, W2=0 |
| Create W1 Route, no movement | 100 | 70 | 30 | 200 | W1 | W1=30, W2=0 |
| Close W1 Route; direct W2 load 20 | 100 | 50 | 50 | 200 | historical W1 | W1=50, W2=0 |
| Direct unload 10 to W2 | 100 | 60 | 40 | 200 | historical W1 | W1=40, W2=0 |
| Create newer W2 Route, no movement | 100 | 60 | 40 | 200 | W2 | W1=0, W2=40 |
| Revoke restricted reader's Vehicle-location read | unchanged | unchanged | 40 | 200 | W2 | restricted reader sees Vehicle=0 |

Financial truth in the same proof remains company quantity 200 and inventory value 600 from the two supplier receipts (100 x 2 and 100 x 4). Internal Warehouse/Vehicle moves and route-only attribution changes create no second financial ownership or COGS.

This evidence proves a central contradiction in the current read model: route rows can move the *displayed* Vehicle quantity between warehouse rows while no physical or financial movement occurs.

## 4. Prioritized findings

### P0-1 — Live Stock projection assigns Vehicle custody to a Warehouse by latest Route history — FAIL

**Files/functions**
- `wa_backend/domains/live_stock_projection/service.py`
  - `get_live_stock_vehicle_sources`
  - `_live_stock_fact_subqueries`
  - `apply_live_stock_balance_impacts`
  - `refresh_live_stock_vehicle_attribution`
  - candidate/rebuild truth queries using latest Route source

**Current behavior**
- `get_live_stock_vehicle_sources` selects `DispatchRoute.vehicle_id -> DispatchRoute.source_location_id` using the latest Route id.
- It does not require the Route to represent a physical movement and does not restrict attribution to an active Route.
- `vehicle_agg` sums balances physically stored in `VEHICLE` locations, then writes that sum into a projection row keyed by the latest Route's **warehouse** `source_location_id`.
- A Vehicle balance impact with no Route source is skipped from warehouse projections.
- Route create/reassignment invokes `refresh_live_stock_vehicle_attribution`, causing warehouse projection keys to change even without an inventory movement.

**Expected**
Vehicle balances remain Vehicle balances. A warehouse projection may describe only physical stock in that warehouse. Route facts must not allocate Vehicle custody into a warehouse projection key.

**Evidence**
#684: physical 100/60/40 is unchanged while a newer W2 Route flips displayed Vehicle quantity from W1=40 to W2=40 with zero stock movement.

**Smallest safe correction boundary**
Remove `DispatchRoute` from physical Vehicle-location aggregation. Keep existing `InventoryBalance`, movement, FEFO and costing authorities unchanged. If Vehicle custody needs presentation, expose it by actual Vehicle/InventoryLocation in a separate custody read rather than injecting it into a warehouse physical row.

**Recommended owner:** Live Stock backend/read-model owner.

---

### P0-2 — Warehouse Live Stock API exposes route-attributed Vehicle quantity and a cross-location `total_quantity` — FAIL

**Files/functions**
- `wa_backend/api/warehouse/live_stock.py`
  - `_latest_readable_vehicle_sources_subquery`
  - candidate/filter construction
  - `get_warehouse_inventory`
- `wa_backend/schemas.py` — `WarehouseInventoryItem`

**Current behavior**
- `vehicle_quantity` for company-wide readers comes from route-attributed projection `vehicle_packs`.
- Restricted readers recompute readable Vehicle balances but still join them to latest Route source and selected warehouse.
- `has_vehicle` filter membership therefore follows Route history.
- `total_quantity` is built as `AVAILABLE warehouse + blocked warehouse + route-attributed vehicle`; it does not represent the selected warehouse's physical total and excludes damaged warehouse stock.

**Expected**
- Warehouse `on_hand` and every warehouse physical total must describe that exact WAREHOUSE location only.
- Vehicle custody must never be added to a warehouse physical total.
- A company-wide total must be computed once across actual InventoryLocations, not by summing route-associated warehouse rows.

**Evidence**
#684:
- after direct W2 load 30 with no Route, warehouse displayed totals sum to 170 while company physical total is 200;
- after a W1 Route with no movement, W1 `total_quantity=130` while W1 physical stock is 100;
- after newer W2 Route, W2 row changes to include Vehicle 40 with no movement.

**Smallest safe correction boundary**
Keep warehouse-only quantities warehouse-only. Deprecate/redefine the legacy cross-location `total_quantity` only after consumer audit; do not silently retain it as physical truth. No physical movement or cost changes belong in this correction.

**Recommended owner:** Live Stock API/schema owner.

---

### P0-3 — Authorization redaction is indistinguishable from actual zero Vehicle stock — FAIL

**File/function**
- `wa_backend/api/warehouse/live_stock.py` restricted vehicle disclosure path.

**Current behavior**
When a restricted reader loses `inventory.read` on the concrete Vehicle location, the same warehouse row reports `vehicle_quantity=0`.

**Expected**
Authorization may hide stock but must not assert a false physical zero. The contract must distinguish actual zero from not disclosed/unknown, or remove warehouse-associated Vehicle quantity altogether.

**Evidence**
#684: actual Vehicle=40 and Owner sees 40 after revoke; restricted reader sees 0. Physical balances are byte-for-byte unchanged.

**Smallest safe correction boundary**
Do not overload numeric zero as redaction. Prefer eliminating warehouse-attributed Vehicle quantity. If a separate Vehicle-custody read remains permission-sensitive, include an explicit disclosure state and fail closed.

**Recommended owner:** Live Stock API + authorization contract owner.

---

### P1-1 — Warehouse summary/non-active visibility can change because a Route attributes Vehicle presence to a warehouse — FAIL

**Files/functions**
- `wa_backend/domains/live_stock_projection/service.py`
  - `has_vehicle_presence`
  - warehouse summary delta/rebuild logic
- `wa_backend/api/warehouse/live_stock.py`
  - `get_warehouse_inventory_summary`
  - non-active candidate streams

**Current behavior**
For non-active variants, warehouse visibility and `stock_total` can include `has_vehicle_presence` tied to latest Route source. Restricted summary logic repeats latest-route source joins.

**Expected**
A warehouse variant-presence count is based on physical warehouse presence (plus explicitly documented catalog/policy rules), not physical stock in another location. Company Vehicle custody needs its own scope.

**Smallest safe correction boundary**
Remove route-attributed Vehicle presence from warehouse summary/candidate identity. Preserve low-stock and warehouse policy calculations.

**Recommended owner:** Live Stock projection/API owner.

---

### P1-2 — Dashboard renders the rejected route-attributed `vehicle_quantity` — FAIL

**Files/surfaces**
- `dashboard/src/pages/inventory/liveStock/LiveStockTable.tsx`
- `dashboard/src/pages/inventory/liveStock/LiveStockMobileCards.tsx`
- `dashboard/src/pages/inventory/liveStock/LiveStockFilters.tsx`
- `dashboard/src/pages/inventory/liveStock/contracts.ts`
- `dashboard/src/i18n/resources.ts`

**Current behavior**
Desktop and mobile display `product.vehicle_quantity`; the Vehicle filter consumes the backend `vehicle` indicator. Existing copy correctly admits the old number is a route/source association, but the owner has now rejected that semantic itself.

`total_quantity` is parsed as a backward-compatible response field but is not directly rendered by the current Live Stock table/cards.

**Expected**
Dashboard must render physical Warehouse truth and, if Vehicle custody is shown, show it as actual Vehicle custody independently of warehouse identity. No wording change can repair a false allocation.

**Smallest safe correction boundary**
Change Dashboard only after backend contract correction. Do not implement another presentation-only workaround like #685.

**Recommended owner:** Dashboard Live Stock owner after backend contract freezes.

---

### P1-3 — Catalog/archive navigation substitutes Warehouse context for physical Vehicle custody — FAIL

**File/function**
- `wa_backend/domains/inventory_archive_navigation.py`
  - `inventory_archive_target_query`

**Current behavior**
1. For an `INVENTORY_BALANCE` physically in a Vehicle, the navigation projection selects the first readable active Warehouse as a "warehouse shell" and returns that Warehouse `location_id`.
2. For `VEHICLE_RECON` stocktake/lock navigation, it explicitly uses `DispatchRoute.source_location_id` instead of the StocktakeSession's actual Vehicle `location_id`.

These are navigation hints, not mutation authority, but they present/route a physical Vehicle fact through a Warehouse identity that is not its current location.

**Expected**
Preserve the actual `InventoryLocation` identity/type in navigation evidence. If the destination UI cannot open Vehicle custody, return an explicit capability/navigation gap; never manufacture a Warehouse location and never use Route source as physical location.

**Smallest safe correction boundary**
Change only archive-navigation projection/routing. No inventory mutation, lifecycle or stocktake authority change.

**Recommended owner:** Catalog archive/navigation owner with Inventory read owner.

---

### P1-4 — Vehicle implementation contract still freezes the rejected route/source attribution — FAIL / stale contract

**File**
- `docs/architecture/VEHICLES_V1_IMPLEMENTATION_CONTRACT.md` §16

**Current behavior**
The document says Live Stock attribution remains route/source based.

**Expected**
Owner-approved physical-location rule supersedes that sentence. Vehicle master still must not imply warehouse ownership, but Route also must not allocate Vehicle stock to a warehouse.

**Smallest safe correction boundary**
Update the architecture contract only in the implementation correction PR after backend semantics are frozen, so docs and code change together.

**Recommended owner:** architecture/lead.

---

### P2-1 — Legacy `total_quantity` remains in server/client contracts — FAIL-risk

**Files**
- `wa_backend/schemas.py`
- `dashboard/src/pages/inventory/liveStock/contracts.ts`

**Current behavior**
The field remains explicitly backward-compatible and is parsed by Dashboard even though the main table/cards do not render it.

**Expected**
No legacy consumer should infer "physical total" from a value that combines locations.

**Smallest safe correction boundary**
Inventory all consumers, then either make it warehouse-only with a versioned semantic or retire it. Do not rename misleading math without consumer acceptance.

**Recommended owner:** API compatibility owner.

---

## 5. PASS matrix — physical authorities that should be preserved

| Status | File/function or surface | Evidence / current behavior | Preserve during correction |
|---|---|---|---|
| PASS | `wa_backend/models.py` — `InventoryLocation`, `InventoryBalance` | Balance key contains company + actual location + variant + batch + status. Vehicle is a separate `VEHICLE` InventoryLocation. | Yes |
| PASS | `wa_backend/services.py::apply_inventory_movements_batch` | Two-ended PHYSICAL movement decrements source and increments destination under one transaction and records movement impacts. | Yes |
| PASS | `wa_backend/domains/inventory_vehicle_load/service.py::mutate_vehicle_load` | Direct ADD is explicit Warehouse→canonical Vehicle; UNLOAD is Vehicle→explicit Warehouse. No direct balance writes. | Yes |
| PASS | `wa_backend/api/dispatch.py` route create/adjust load movement paths | Actual load/unload specs use warehouse and canonical vehicle locations; Route creation itself can occur without a stock movement. | Preserve movement authority; remove only route-driven read attribution |
| PASS | `wa_backend/api/dispatch.py::get_vehicle_inventory` | Reads actual canonical Vehicle location from InventoryBalance. | Yes |
| PASS | `wa_backend/api/driver.py` sales/sample/exchange/return | Outbound sale leaves Vehicle location; customer return enters Vehicle location. | Yes |
| PASS | `wa_backend/api/driver.py::_load_vehicle_inventory_projection` + `/driver/dashboard` | Flutter FIELD custody is aggregated from actual Vehicle InventoryBalance; snapshots bind to Vehicle location. | Yes |
| PASS | `wa_backend/api/representative_settlement.py` | Ended-session custody reads Vehicle location and moves Vehicle→explicit receiving Warehouse. | Yes |
| PASS | `wa_backend/api/warehouse/stocktake.py` | Warehouse stocktake uses exact Warehouse location; VEHICLE_RECON validates and snapshots exact canonical Vehicle location. | Yes |
| PASS | `wa_backend/api/warehouse/transfers.py` | Transit workflow moves Warehouse→canonical IN_TRANSIT→terminal Warehouse; generic transfer location picker is Warehouse-only. | Yes |
| PASS | `wa_backend/api/warehouse/live_stock.py::get_warehouse_inventory_batches` | Batch detail is scoped to exact selected Warehouse InventoryBalance. | Yes |
| PASS | `wa_backend/api/warehouse/live_stock.py::get_batch_stock_sources` | Physical source disclosure includes actual Warehouses/Vehicles and #684 proves it stays physical even when list attribution is wrong. | Yes |
| PASS | `wa_backend/api/warehouse/live_stock_source_detail.py` | Source detail is exact Warehouse-only location scope. | Yes |
| PASS | `wa_backend/domains/inventory_costing/service.py` | Internal two-ended Warehouse/Vehicle movements are not external cost events; #684 keeps company quantity 200/value 600. | Yes |
| PASS | current Flutter custody consumer | Uses `/driver/dashboard` actual Vehicle-custody inventory, not warehouse Live Stock route attribution. | Yes |

## 6. UNKNOWN / real evidence gaps

| Status | Area | Why it remains UNKNOWN |
|---|---|---|
| UNKNOWN | Future/general company-wide reporting UI | V1 navigation still treats Reports as not fully implemented. The costing state itself is proven company-wide and correct, but there is no single implemented general inventory-total report surface to certify here. |
| UNKNOWN | Every possible dormant/legacy consumer of `WarehouseInventoryItem.total_quantity` | Server and Dashboard contracts retain the field. Main Live Stock table/cards do not render it, but a full compatibility retirement needs a dedicated consumer inventory before changing the wire meaning. |
| UNKNOWN | Unrelated Flutter screens outside current FIELD custody/dashboard path | Relevant custody path is proven actual-location based. This audit found no Live Stock warehouse `vehicle_quantity` consumer in Flutter, but it does not certify every dormant/future mobile file. |

## 7. Clean correction boundaries

### Boundary A — do not touch physical write authority
Do not rewrite `InventoryBalance`, Unified Inventory Movement, FEFO, costing, Sales, Transfers, Stocktake or Representative Settlement to solve this read-model defect. Their physical-location semantics are already correct.

### Boundary B — remove Route from inventory-location truth
The correction must eliminate `DispatchRoute` as an input to:
- Vehicle quantity allocation into warehouse projection rows;
- warehouse `has_vehicle_presence`;
- warehouse Vehicle filter membership;
- warehouse summary/non-active presence;
- route-triggered "vehicle attribution refresh".

Route may remain an operational owner/gate for **which command** is allowed; it may not decide where already-held stock is located.

### Boundary C — no loading-provenance ownership
Do not replace latest Route source with "warehouse where the Vehicle units originally came from." Mixed loads, sales, returns, unloads and adjustments make that a different provenance problem. Current physical location remains the only custody authority.

### Boundary D — separate scopes in the read contract
A Warehouse endpoint returns Warehouse physical stock. A Vehicle-custody read returns Vehicle physical stock. A company total can aggregate both exactly once from actual InventoryLocations. Cross-location totals must never masquerade as one Warehouse's quantity.

### Boundary E — preserve redaction semantics
Missing Vehicle permission is "not disclosed", not physical zero. The corrected contract must make zero/hidden/unknown distinguishable wherever a quantity may be selectively disclosed.

### Boundary F — archive navigation cannot invent a Warehouse
Navigation may point to the real Vehicle/location-specific destination, or report an explicit capability gap. It must not substitute an arbitrary Warehouse or a Route source Warehouse.

## 8. Recommended follow-up correction waves

1. **P0 backend correction:** remove route-based Vehicle attribution from Live Stock projection/API while preserving all physical movement/cost authorities.
2. **Compatibility pass:** audit and freeze the replacement semantics/removal path for `vehicle_quantity`, `total_quantity`, `has_vehicle`, and `has_vehicle_presence`.
3. **Authorization correction:** remove hidden-as-zero behavior from any surviving Vehicle-custody disclosure.
4. **Archive-navigation correction:** preserve real Vehicle/stocktake location identity.
5. **Dashboard integration:** consume the corrected backend contract; no presentation-only workaround.
6. **Architecture documentation:** supersede the stale route/source attribution clause after implementation semantics are accepted.

## 9. Required follow-up PostgreSQL 16 acceptance gates

Use a restricted NOSUPERUSER/NOBYPASSRLS runtime role, existing FORCE RLS and normal tenant/location authorization. No direct balance writes.

### Gate G1 — route-independent physical location
Start W1=100, W2=100, Vehicle=0.

- W2→Vehicle load 30 => W1=100, W2=70, Vehicle=30.
- Create W1 Route with **no movement** => all three remain identical.
- Close W1 Route; W2→Vehicle load 20 => 100/50/50.
- Vehicle→W2 unload 10 => 100/60/40.
- Create newer W2 Route with **no movement** => 100/60/40.
- Route status/reassignment-only actions produce no InventoryMovement and cannot change physical inventory responses.
- Company physical total remains exactly 200 at every checkpoint.

### Gate G2 — warehouse Live Stock truth
At every G1 checkpoint:
- W1 Warehouse physical quantity is exactly W1 InventoryBalance only.
- W2 Warehouse physical quantity is exactly W2 InventoryBalance only.
- No Vehicle quantity is included in a Warehouse physical total.
- Route creation/closure/reassignment cannot change warehouse numeric quantities.

### Gate G3 — actual Vehicle custody
- Vehicle custody remains queryable from the authorized physical Vehicle location with no Route.
- The same Vehicle quantity remains under the Vehicle when a Route is created, closed or replaced.
- Batch/source evidence names the actual W2 and Vehicle locations in the #684 mixed scenario.

### Gate G4 — authorization semantics
- Owner/authorized reader sees the real Vehicle custody.
- Revoked Vehicle-location reader gets explicit hidden/not-disclosed behavior, never fabricated numeric zero.
- Warehouse quantities remain readable/accurate according to Warehouse grants.
- Cross-company and cross-location reads fail closed.

### Gate G5 — filters/summaries
- Warehouse product membership, non-active visibility and summary counts do not change merely because a Route row is created or becomes the newest Route.
- Any surviving Vehicle filter is scoped to actual Vehicle custody, not a selected Warehouse by Route source.

### Gate G6 — archive navigation
- A Vehicle `InventoryBalance` never returns an arbitrary Warehouse as its physical location.
- A `VEHICLE_RECON` stocktake/lock never returns `DispatchRoute.source_location_id` as the custody location.
- Unsupported navigation returns a deterministic capability/navigation gap.

### Gate G7 — financial non-duplication
- Company physical quantity remains 200.
- Financial quantity remains 200.
- Inventory value remains 600 in the #684 two-receipt scenario.
- Warehouse↔Vehicle internal movement and Route-only changes create no extra cost event/COGS.
- No unit is financially or physically counted twice.

### Gate G8 — consumer regression
- Dashboard desktop/mobile consume the corrected contract.
- Flutter FIELD route/custody inventory continues reading actual Vehicle custody.
- No compatibility consumer uses the old cross-location `total_quantity` as Warehouse physical truth.

## 10. Final audit conclusion

The core physical inventory engine is **not** the root defect. It already moves stock between actual InventoryLocations correctly and keeps internal custody movement financially neutral.

The P0 defect is a **read-model/location-attribution layer** that takes real Vehicle balances and attaches them to a Warehouse by latest DispatchRoute source. That behavior leaks into `vehicle_quantity`, `has_vehicle_presence`, Vehicle filters, non-active warehouse visibility and the legacy `total_quantity`. A separate archive-navigation read also substitutes Warehouse context for Vehicle facts.

Therefore the safe correction is narrow but architectural: preserve the physical write/cost authorities, remove Route as inventory-location attribution authority, keep Warehouse/Vehicle/IN_TRANSIT scopes physically separate, and update consumers only after the corrected read contract is frozen.
