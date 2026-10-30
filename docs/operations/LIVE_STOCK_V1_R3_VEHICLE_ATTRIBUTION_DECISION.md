# Live Stock V1 R3 — Vehicle Attribution Decision Evidence

**Status:** Evidence for owner decision. No attribution policy change is implemented here.
**Acceptance base:** `4c100550ac3dc3fcf16ecd174e285f3dc84c941f`.

## Current V1 contract

Vehicle inventory remains physically authoritative in the Vehicle `InventoryLocation`. Live Stock's warehouse-level `vehicle_quantity` is a display attribution derived from the Vehicle's latest Dispatch Route `source_location_id`; it is not permanent Warehouse ownership and it does not rewrite inventory or financial history.

The focused PostgreSQL 16 proof exercises two authorized Warehouses (W1/W2), one real Vehicle custody location, real supplier inbound, direct Vehicle Load commands, canonical Dispatch Route creation/closure, Live Stock reads, source disclosure and a persisted Vehicle-location permission revocation.

## Truth matrix

| Stage | Physical W1 | Physical W2 | Physical Vehicle | Latest Route source | Live Stock vehicle attribution | Key interpretation |
|---|---:|---:|---:|---|---|---|
| Direct W2 load, no Route | 100 | 70 | 30 | none | W1=0, W2=0 | Vehicle stock is real but has no Warehouse route attribution. |
| Active Route sourced W1 | 100 | 70 | 30 | W1 | W1=30, W2=0 | Same physical Vehicle stock is displayed under W1 even though its batch came from W2. |
| W1 Route closed; direct W2 add | 100 | 50 | 50 | W1 | W1=50, W2=0 | A later direct W2 load does not change latest-route attribution. |
| Direct unload back to W2 | 100 | 60 | 40 | W1 | W1=40, W2=0 | Physical W2 quantity changes; attribution still follows the historical latest Route. |
| Newer Route sourced W2 | 100 | 60 | 40 | W2 | W1=0, W2=40 | Attribution flips to W2 without a stock movement. |
| Vehicle read permission revoked for restricted reader | 100 | 60 | 40 | W2 | restricted reader sees 0 Vehicle | Visibility changes; physical stock and owner-visible attribution do not. |

At every supported stage the company physical total is 200 base units. The only financial postings are the two immutable supplier `PURCHASE_IN` events: 100 × 2 and 100 × 4, for total inventory value 600. Internal Warehouse↔Vehicle moves and route-attribution changes create no COGS and no second financial ownership ledger.

Batch stock sources remain physical disclosure: the W2 batch reports the actual W2 and Vehicle locations even while the warehouse list attributes the Vehicle quantity to W1. The warehouse summary exposes product/alert counts, not Vehicle provenance, so it must not be interpreted as a Warehouse-ownership statement.

## Canonically blocked / unsupported cases

- Direct Vehicle Load while an active/current workflow owns the Vehicle is denied with `VEHICLE_LOAD_OWNED_BY_WORKFLOW` and HTTP 409. The operator must use the owning Dispatch workflow.
- V1 has no Vehicle→Vehicle direct load command.
- Generic Warehouse transfer balancing is not Vehicle custody authority.
- Live Stock cannot infer permanent Warehouse ownership from a Route source, and it cannot infer per-unit load provenance from the current aggregate Vehicle balance.
- Revoking Vehicle-location `inventory.read` hides Vehicle disclosure for that restricted reader; it does not move or zero stock.

## Owner decision options

### Option A — Keep current latest-Route-source attribution for V1 **(recommended)**

Keep current backend semantics unchanged. Treat `vehicle_quantity` as “Vehicle custody associated with the latest Route source,” never as Warehouse-owned stock. Direct no-Route custody can remain unattributed to a Warehouse until a Route exists.

**Advantages:** smallest and safest V1 scope; no new inventory authority, migration, cost logic or allocation rule; matches the frozen Vehicle contract.
**Trade-off:** a Vehicle loaded directly can temporarily disappear from every Warehouse's `vehicle_quantity`, and a later Route can visually move the whole Vehicle quantity between Warehouses without a physical movement. Operator wording must remain explicit.

### Option B — Add an explicit “unattributed Vehicle custody” display bucket

Keep physical truth unchanged but introduce a separate presentation/read-model category for Vehicle stock with no applicable Route-source attribution.

**Advantages:** makes direct no-Route custody visible without pretending it belongs to a Warehouse.
**Trade-off:** changes Live Stock API/UI semantics and aggregate rules; requires separate owner approval and acceptance work. It is not implemented by this proof.

### Option C — Attribute Vehicle quantity by load provenance

Track/display Vehicle quantities against the Warehouse(s) from which individual units were loaded.

**Advantages:** closer to movement provenance for some questions.
**Trade-off:** substantially more complex after mixed loads, sales, returns, route adjustments and unloads; risks creating a second allocation/ownership concept beside physical and financial authorities. This is not a safe implicit V1 change and likely belongs in a separately designed future policy.

## Recommended safe V1 decision

Approve **Option A** unless the owner explicitly wants a new product semantic. It preserves the current frozen architecture and requires no invented Warehouse ownership.

**Exact unresolved owner decision:** Should V1 keep `vehicle_quantity` as latest-Route-source association, with direct no-Route Vehicle custody intentionally not attributed to any Warehouse, or should a new display semantic such as an explicit unattributed Vehicle bucket be approved? No policy change should be implemented until the owner answers.
