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

### [ ] 1. Inbound RECALL UX / i18n closure

**Status:** initial fix merged in PR #568; owner live acceptance found two final UX refinements still required.  
**Worker:** next bounded inbound follow-up worker.

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

### [ ] 2. Route Launch and Vehicle Load use one quantity/UOM meaning

**Status:** implemented and merged in PR #569; pending owner live Dashboard acceptance before `[x]`.

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

### [ ] 3. Preserve loose remainder during Route Launch

**Status:** implemented and merged in PR #569; pending owner live Dashboard acceptance before `[x]`.

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

### [ ] 4. Show current / target / delta before Route Launch

**Status:** implemented and merged in PR #569; pending owner live Dashboard acceptance before `[x]`.

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

### [ ] 5. Repair stale Warehouse Route Manifest gate

**Status:** implemented and merged in PR #571; automated gate is green, pending owner live Dashboard smoke acceptance before `[x]`.

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

## Explicit V2 deferrals — do not reopen for V1

These are already documented in `V1_SCOPE_FREEZE.md` and `VERSION_2_FUTURE_FEATURES.md`:

- Vehicle Load benchmark/search hardening for the extreme case of about 50,000 stock-bearing products in one Warehouse.
- Removing the full product catalog from `/dispatch/init` and replacing it with bounded server-side Dispatch product search.

These V2 deferrals do **not** defer any quantity, UOM, custody, authorization, lifecycle or inventory-correctness defect.
