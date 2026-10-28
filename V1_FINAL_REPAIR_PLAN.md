# Wanasah V1 Final Repair Plan

**Status:** ACTIVE V1 RELEASE CLOSURE  
**Base checkpoint when created:** `f40330c15cb6f876856da015438935d24e4848a9`

This file tracks only the remaining V1 blockers discovered during final Dashboard acceptance.

## Acceptance rule

A repair is **not complete because code was merged**.

Mark an item `[x]` only after all three are true:

1. the primary technical lead reviewed and accepted the actual diff;
2. focused automated tests/gates passed;
3. the owner performed the listed quick live Dashboard acceptance and confirmed the behavior.

If live acceptance fails, keep the item open and continue from the actual defect.

## Remaining V1 blockers

### [x] 1. Inbound RECALL UX / i18n closure

**Status:** accepted by owner in live Dashboard after PR #572. The later unrelated Inbound search-isolation defect was repaired separately in PR #575.

Frozen behavior:

- `ACTIVE + RECALL` must remain blocked from new supplier inbound.
- The Dashboard must not show a raw English backend message while Arabic is active.
- The error must be clear and operator-facing.
- The inbound row must communicate the block before submit and prevent normal inbound entry.
- Do not show an "remove this product from the receipt draft" action for a recalled product. Once RECALL is known, the row must directly show the blocked state without requiring an operator cleanup click; stale local draft input for that recalled product must not keep blocking the receipt flow.
- RECALL rows must be stably partitioned to the bottom of the currently loaded inbound table so blocked products do not disrupt active receiving rows. When the hold is released, the product returns to its normal table order.
- `ACTIVE + SALES_HOLD` must remain inbound-eligible.
- Backend lifecycle authority remains unchanged.

Quick live Dashboard acceptance:

- Open Inbound in Arabic.
- Find a product currently under a quality/safety RECALL.
- Confirm the row clearly explains that new inbound is blocked and normal inbound entry is disabled.
- Confirm no remove-draft button is shown and no stale recalled draft blocks other valid receipt work.
- Confirm recalled products appear after active inbound-eligible products; release the hold and confirm the product returns to normal ordering.
- Confirm no English/raw technical error is shown.
- Confirm another `SALES_HOLD` product can still be received when otherwise eligible.

### [x] 2. Route Launch and Vehicle Load use one quantity/UOM meaning

**Status:** owner live flow accepted and independently verified against the live database. Route Launch stored the exact 30-base-unit target and Vehicle Load reported the same 30 base units.

Frozen behavior:

- canonical base quantity remains inventory truth;
- Route Launch and Vehicle Load must not interpret the same number differently;
- use existing UOM authority / ProductUomConversion rather than a new conversion engine;
- no ambiguous unlabeled quantity input;
- legacy `packs_per_carton` compatibility must not remain the authority for the new Route Launch path.

Quick live Dashboard acceptance:

- Load a known product into a free Vehicle.
- Verify Vehicle Load and Route Launch describe the same physical quantity using clear unit labels.
- Change the target using the displayed unit and confirm the resulting physical quantity is exactly what the operator intended.

### [x] 3. Preserve loose remainder during Route Launch

**Status:** owner live flow accepted and independently verified against the live database. The tested product has 1 pack = 8 base units; 30 base units therefore include a 6-unit loose remainder. Relaunch at unchanged target produced zero inventory movements and preserved all 30 units.

Regression case:

- current Vehicle stock = 20 base units;
- commercial conversion = 1 package = 8 base units;
- exact current stock = 2 packages + 4 base units.

Required:

- opening Route Launch must preserve all 20 base units;
- no remainder may be silently dropped;
- launching without changing the target must produce delta = 0;
- no automatic return of 4 units to the Warehouse.

Quick live Dashboard acceptance:

- Prepare or use a Vehicle with the equivalent of 2 packages + 4 loose base units.
- Open Route Launch.
- Do not change its load.
- Launch the route.
- Verify Vehicle custody still contains the full original quantity and the Warehouse did not receive a false remainder return.

### [x] 4. Show current / target / delta before Route Launch

**Status:** accepted by owner in live Dashboard and independently verified against the live database. The 30→25 preview showed a 5-unit Vehicle→Warehouse return; execution produced exactly one 5-base-unit DISPATCH_UNLOAD movement, leaving Vehicle=25 and Warehouse=5.

Required:

- show current Vehicle load;
- show target load;
- show exact delta before launch;
- clearly state whether a positive delta will move Warehouse → Vehicle;
- clearly state whether a negative delta will move Vehicle → Warehouse;
- unchanged target must show zero movement;
- Warehouse selection remains the actual movement authority;
- FEFO, batches, locks, permissions, lifecycle safety and movement truth remain backend-owned.

Quick live Dashboard acceptance:

- Pick a Vehicle with existing load and an authorized Warehouse.
- Verify unchanged target shows zero movement.
- Increase one product and verify the UI shows the exact pull from Warehouse.
- Decrease one product and verify the UI shows the exact return to Warehouse.
- Execute and verify both resulting balances match the preview.

### [x] 5. Repair stale Warehouse Route Manifest gate

**Status:** accepted. Automated manifest/route acceptance is green; owner confirmed the live Warehouse code-suggestion entry point. Opening-valuation routes remain covered by focused acceptance and are not surfaced on the current company because costing is already active, so no destructive reset was performed merely to force that one-time bootstrap UI.

Original confirmed failure:

`WAREHOUSE_ROUTE_MANIFEST=FAIL: route count mismatch: baseline=45, extensions=13, package=63`

Accepted repair evidence:

- five legitimate V1 routes were reconstructed from accepted history;
- the extensions manifest now records 18 explicit post-baseline routes;
- final gate result is baseline=45, extensions=18, package=63;
- exact runtime order passes and duplicate method+path routes remain zero.

Required:

- identify the five current routes missing from the accepted manifest;
- classify why each exists;
- preserve legitimate production routes;
- repair the semantic manifest/gate rather than deleting or reverting valid routes to satisfy an old count;
- run the manifest gate and related focused route tests.

Quick live Dashboard acceptance:

- After the gate is green, smoke-test the affected Inventory/Warehouse Dashboard entry points represented by the newly classified routes.
- Confirm the pages/actions still open and route to their intended workflow.
- The automated manifest gate remains mandatory; Dashboard smoke alone is not sufficient for this item.

### [ ] 6. Active-route Adjust Load must use canonical quantity/UOM meaning

**Status:** newly confirmed V1 correctness blocker during final live acceptance.

Owner-frozen compatibility decision (2026-10-27): the new Dashboard contract uses
decimal-string `delta_base` and canonical UOM metadata. DIRECT preserves the
Product quantity scale/step exactly. Bound-session HANDSHAKE rejects non-integral
base deltas before creating headers/reservations while the separately owned FIELD
contract remains integer-only. Legacy `delta_cartons` retains its old meaning;
mixing the two request forms is forbidden. Terminal accept/reject/cancel must
reconcile the plan to physical Vehicle base custody plus remaining pending net.
Direct returns reuse the accepted unload safety authority; the Dashboard radar
uses canonical signed base/UOM evidence. This item remains open until diff review,
automated gates and owner live acceptance are complete.

Canonical handshakes persist `commercial_context.quantity_contract = CANONICAL_BASE_V1`.
FIELD compatibility exposes their signed integral base quantity as zero cartons and
all base units in `delta_packs`; absent markers preserve legacy splitting. Canonical
radar validity/presentation does not depend on legacy `packs_per_carton`.

Owner-authorized narrow FIELD custody extension (2026-10-27): pending-transfer
responses and session-refresh custody evidence carry canonical base/UOM metadata.
Flutter preserves that evidence in additive SQLite v11 columns, formats the exact
server-provided display factor or true base UOM, and retains canonical local retry
context. Unmarked rows keep legacy presentation. Transfer decisions still carry
only transfer identity and decision; Backend lines remain quantity authority.
Item 6 stays OPEN for lead diff review, passing gates and owner live acceptance.

Owner-approved display selection correction (2026-10-27): shared UOM authority
selects the unique largest reachable non-base UOM whose exact factor to base is
an integer greater than one, including chained conversions. Equal-largest ties
or no candidate retain base-UOM display. Canonical Route Launch, Adjust Load,
radar and FIELD consume this through existing metadata; presentation remains
one display UOM plus the exact base remainder, without multi-level decomposition.
Stock/movement quantities remain BASE and unmarked historical transfers keep
their legacy presentation. This does not open Advanced UOM configuration scope.

Owner-approved permanent discovery closure (2026-10-28), superseding the
initial PR #582 fixed-80 containment: `/dispatch/init` no longer owns or returns
Products, and DispatchBoard holds no company catalog. Route Launch, Adjust Load
and Route Management use cursor discovery over the shared Inventory source-stock
authority; Shortages use REPLENISHMENT_NEW without requiring Warehouse stock.
80 is only a page size. Signed cursors bind tenant, purpose/eligibility, actual
route/source/vehicle/session and normalized query; immutable-ID seek navigation
has no deep OFFSET. The browser keeps one page plus current/pending/selected pins.
Adjust Load retains bounded draft hydration and exact base/UOM command authority.
Normal in-flight commands show progress; only persisted/ambiguous commands show
recovery and retain the same request identity. Disposable PostgreSQL and Dashboard
evidence is recorded in `DISPATCH_V1_AUDIT_NOTES.md`. No live DB was accessed.
Item 6 remains OPEN until lead review and owner live acceptance.

Confirmed evidence:

- the active-route `Adjust load / تعديل الحمولة` workflow still reads and writes integer `delta_cartons`;
- its backend conversion is still driven by legacy `packs_per_carton`;
- the UI labels that unit as `كرتونة`;
- the live test product `شعيرية ممتاز 750 مل تجربة وناسة هـ-00019` has canonical base UOM `حبة` and commercial conversion `1 باكيت = 8 حبات`, while legacy `packs_per_carton = 8`;
- therefore the active-route adjustment surface can describe the same physical 8-base-unit quantity as a carton while Route Launch correctly describes it as a pack.

Required:

- preserve the separate business purpose: Route Launch sets the load target before a new route, while Adjust Load changes custody during an existing route;
- migrate active-route load adjustment away from legacy `packs_per_carton` quantity authority;
- use canonical base quantity plus existing UOM authority / ProductUomConversion;
- preserve loose base-unit remainder exactly;
- show clear current quantity, requested delta/target, and resulting quantity with correct unit labels;
- retain current session/handshake, inventory movement, FEFO/batch, permissions, lifecycle, idempotency, audit and custody authority;
- do not create a duplicate inventory mutation path.

Quick live Dashboard acceptance:

- Open an active route whose Vehicle has a product with a known commercial conversion such as `1 باكيت = 8 حبات`.
- Open `تعديل الحمولة`.
- Confirm the current physical quantity is described with the same UOM meaning as Vehicle Load and Route Launch.
- Increase and decrease by an exact base/commercial amount and confirm preview plus resulting Vehicle/Warehouse balances match without losing loose remainder.

## Explicit V2 deferrals — do not reopen for V1

These are already documented in `V1_SCOPE_FREEZE.md` and `VERSION_2_FUTURE_FEATURES.md`:

- Vehicle Load benchmark/search hardening for the extreme case of about 50,000 stock-bearing products in one Warehouse.
Dispatch full-catalog transport removal is **no longer deferred**: the owner promoted it to V1 on 2026-10-28, including all four purpose-correct cursor pickers and recovery UX. See item 6 above.

These V2 deferrals do **not** defer any quantity, UOM, custody, authorization, lifecycle or inventory-correctness defect.
