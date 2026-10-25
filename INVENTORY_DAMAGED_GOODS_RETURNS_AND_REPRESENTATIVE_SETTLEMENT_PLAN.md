# Wanasah — Inventory Damaged Goods, Returns & Representative Settlement Plan

> **Owner decision date:** 2026-10-18
>
> **Status legend:** `[ ]` not started · `[~]` in progress · `[x]` completed with evidence · `[!]` blocked/decision required.
>
> **Execution timing:** this is a canonical implementation plan, not an instruction to jump ahead of the current Inventory page-polish order. Finish the current Warehouse/Inventory surfaces in dependency order. Execute each section only when its owning page/workflow is reached.
>
> **Scope boundary:** V2-only ideas are intentionally not duplicated here. They live in `VERSION_2_FUTURE_FEATURES.md`.
>
> **Authority:** `ARCHITECTURE.md`, `V1_SCOPE_FREEZE.md`, the Unified Inventory Movement authority, Inventory Costing, canonical permissions, and the current Backend contracts remain authoritative. Do not rebuild the Inventory engine to implement this plan.

---

# 0. Owner-approved outcome

The target is one closed operational circle in which no unit of product and no monetary amount becomes unowned, unexplained, or silently lost.

For every affected quantity the system must always be able to answer:

- what product and authoritative Batch/lot identity it belongs to;
- where it is physically located now;
- what stock status it is in now;
- whose custody/responsibility it is under;
- which movement put it there;
- which visit, driver, warehouse user, supplier, customer/shop, work session, or quality decision is relevant;
- whether the physical lifecycle is still open or terminal;
- whether the financial lifecycle is still open or terminal.

**Invariant:** a count mismatch, damaged unit, disposal, vendor return, missing carton, cash difference, retry, or correction must never disappear by making a balance “look right”. Differences remain explicit evidence until resolved through an authorized workflow.

---

# 1. Permanent UX / backend principle

The permanent architecture rule in `ARCHITECTURE.md` applies throughout this plan:

> If the system can derive a fact safely from authoritative backend evidence, do not ask the operator for it.

- [ ] Dashboard and Flutter ask only for business facts that cannot be resolved safely.
- [ ] Technical IDs such as database `batch_id` are never user-facing tasks.
- [ ] FEFO, Batch resolution, supplier provenance, costing, retries, idempotency, locks, reconciliation math, and movement construction remain Backend-owned.
- [ ] Deterministic cases resolve automatically.
- [ ] Genuine ambiguity fails closed and asks for the smallest human-readable discriminator needed; never guess.
- [ ] The UI stays simple because the Backend carries complexity, not because accounting/inventory evidence is omitted.

---

# 2. Current verified technical baseline — preserve, do not rewrite

- [x] `InventoryBalance` is the current physical stock SSOT and separates quantity by company + location + variant + Batch + stock status.
- [x] Unified Inventory Movement is the only approved quantity/status mutation authority.
- [x] Existing stock states include `AVAILABLE`, `QUARANTINED`, `BLOCKED`, `RECALLED`, `DAMAGED`, and `DISPOSAL_PENDING`.
- [x] Warehouse Batch UI already supports quantity-specific stock-status changes; a partial quantity can be isolated without changing the whole Batch.
- [x] Backend already contains terminal final-disposal and final vendor-handover capabilities. Preserve and unify them; do not build a second terminal-action engine.
- [x] Vehicle session inventory reconciliation includes non-AVAILABLE stock such as `DAMAGED` in Ending Snapshot truth.
- [x] Vehicle reconciliation currently seals/counts vehicle inventory but does **not** by itself transfer damaged/remaining goods to a warehouse.
- [x] Operations/Home financial settlement is a separate later phase and is blocked until inventory reconciliation is complete.
- [x] Flutter currently has damaged/expired/factory-defect quantity entry and a 1:1 replacement concept.
- [!] Flutter currently does not send the authoritative Batch identity required by the Backend return contract. Fix this in the Flutter phase without weakening the Backend contract.


---

# 3. Representative settlement — one user-facing entry point

**Owner decision (2026-10-18):** the user-facing settlement of an ended representative work session must start from **one place only: the yellow card on Operations/Home**. Do not make the operator choose between a settlement button on the home page and another settlement button inside Inventory → Stocktake / Reconciliation.

Internally, the single settlement flow may still execute two ordered backend phases:

## 3.1 Internal inventory/custody phase

The existing Vehicle Recon / inventory-reconciliation authority remains the backend owner for physical stock truth:

- [ ] count the physical stock still under Vehicle custody, including non-AVAILABLE stock such as `DAMAGED`;
- [ ] compare expected versus physically received quantities;
- [ ] confirm the real Vehicle → Warehouse custody handoff when the responsible receiver accepts the goods;
- [ ] keep any shortage/overage as explicit reconciliation evidence;
- [ ] post approved inventory corrections only through Unified Inventory Movement;
- [ ] retain exact user, work-session, vehicle, product, Batch, stock-status, quantity, timestamp, and evidence links.

**UI decision:** when this flow is implemented, remove the separate user-facing **Vehicle settlement / Vehicle Recon** start button from the Stocktake page. Stocktake/reconciliation logic may be reused internally, but the operator starts the representative settlement from the yellow card only.

## 3.2 Financial/final phase

After the inventory/custody phase is sealed, the same yellow-card flow continues to the financial close:

- [x] Current Backend already refuses final financial settlement before inventory reconciliation is complete.
- [ ] Actual cash, expected-vs-actual cash difference, required explanation/evidence, and final work-session closure belong here.
- [ ] The financial step consumes the sealed inventory result; it must not recalculate or mutate stock independently.
- [ ] Remove the editable inventory recount from the financial Settlement modal. Inventory is counted once in the internal inventory/custody phase; the final step may show the result read-only for context.
- [ ] Stop sending the legacy `inventory_jard` compatibility payload after Dashboard migration. Backend currently validates it against the sealed AVAILABLE Ending Snapshot but intentionally does not mutate inventory from it.
- [ ] Retire/deprecate that compatibility field only after all supported clients have stopped depending on it.

**Decision:** one visible settlement journey, one entry point, two ordered internal authorities. The detailed yellow-card UX will be designed when Operations/Home reaches its polish phase; do not over-design it now.

## 3.3 Real-world cadence

Do not hard-code the assumption that settlement must happen every calendar day. A company may settle after each shift, daily, every two days, weekly, or according to its approved process. The system must preserve ended-session custody accurately until settlement occurs.

---

# 4. Vehicle → Warehouse custody handoff

The ended-session representative custody handoff is implemented for V1. The broader damaged-goods/shop-return lifecycle in later sections remains open.

**Do not auto-transfer inventory merely because the driver ended work or a reconciliation screen opened.** The movement represents a real responsibility transfer and requires positive receiving confirmation.

Expected sequence:

1. driver/work session ends;
2. vehicle remains authoritative custody for its recorded stock;
3. responsible user starts the representative settlement from the yellow Operations/Home card;
4. the single flow enters its internal inventory/custody stage and shows expected quantities by product + Batch + stock status;
5. receiver counts what is physically presented;
6. receiver confirms actual receipt;
7. matched quantities move from Vehicle custody to the chosen normal receiving warehouse/location using authoritative movement(s);
8. any mismatch stays as explicit reconciliation variance;
9. inventory reconciliation is sealed only according to the approved variance/recount rules;
10. the same yellow-card journey may then continue to its financial/final phase.

Required movement behavior:

- [x] `Vehicle / AVAILABLE → Warehouse / AVAILABLE` for remaining saleable stock that is physically returned.
- [x] `Vehicle / DAMAGED → Warehouse / DAMAGED` for damaged/expired/factory-defect goods physically handed over.
- [x] Preserve other supported non-AVAILABLE states exactly; do not convert status merely because location changes.
- [x] Preserve exact Batch identity and quantity through the handoff.
- [x] Do not use a status change when the real event is a physical location/custody transfer.
- [x] Create immutable movement/audit evidence for sender vehicle/work session and receiving actor.
- [x] Retry/idempotency must never duplicate receipt.

Evidence:
- `wa_backend/api/representative_settlement.py` owns the receiver-confirmed ended-session custody handoff, preserves Batch + stock status, routes discrepancies through Vehicle Recon, writes immutable audit evidence, and uses idempotent Unified Inventory Movement mutations.
- `wa_backend/tests/test_representative_settlement_custody_postgres.py` exercises real PostgreSQL shortage/recount/approval, exact receiver-confirmed handoff, surplus, financial gating, and replay behavior, including DAMAGED custody.
- Dashboard uses the same business flow through `dashboard/src/features/operations/representativeSettlement/`.
- Live local acceptance on 2026-10-25 also exercised the separate active-route/no-WorkSession return path: Route 6 returned ProductVariant 505 quantity 6, Batch 1072, `AVAILABLE → AVAILABLE`, from `Vehicle 12-25132` to `ماركا الشمالية` through `DISPATCH_UNLOAD`. FIFO state stayed at 20 units / JOD 2.680000 and `WHOLE_PRODUCT_QUALITY_CUSTODY_BLOCKER` cleared.

If expected damaged quantity is 4 and the receiver confirms only 3, the missing 1 does not disappear. It remains a recorded difference requiring the existing reconciliation/recount/approval path and attributable evidence.

After reconciliation, reloading the representative vehicle with saleable stock is a **new custody/load operation**, not an edit of the just-closed reconciliation.


---

# 5. Damaged goods from shops — V1 field workflow

The normal V1 distributor workflow is **1:1 replacement**.

Example:

`Shop gives 2 damaged cartons → representative receives 2 damaged cartons → representative gives 2 saleable replacement cartons`.

This is not a new sale and must not silently change the shop's debt or cash position merely because a replacement occurred.

Required field behavior:

- [ ] Representative selects the product and damaged quantity using simple cartons/packs controls.
- [ ] Supported business reasons remain human-readable, including damaged, expired, and factory defect as defined by the Backend contract.
- [ ] Returned goods enter the representative vehicle custody as non-sellable damaged stock.
- [ ] Replacement goods leave the vehicle from saleable AVAILABLE stock through Backend-authoritative allocation.
- [ ] 1:1 quantity equivalence is validated by the Backend using canonical UOM conversion; Flutter does not calculate authority.
- [ ] Source shop, visit, representative, work session, reason, product, resolved Batch, quantity, and movement evidence are retained.
- [ ] Damaged stock cannot become sellable merely because the mobile visit closed.
- [ ] The same operation must remain safe through offline save/retry/replay; one customer exchange may produce its movements exactly once.

The current Flutter experience is substantially behind the Backend and will be polished only after Backend + Dashboard Inventory foundations are complete. Do not move the business authority into Flutter to bridge the delay.

Damaged goods may also be discovered **inside a warehouse itself**, without any shop/visit/representative origin. That path must use the same downstream lifecycle without inventing fake field evidence:

- [ ] Warehouse user identifies product + exact affected quantity and the minimum real Batch/lot evidence required by tracking rules.
- [ ] The quantity changes from its current saleable/controlled state into the appropriate non-sellable status through the same inventory authority.
- [ ] Record warehouse actor, location, Batch, quantity, reason, and evidence.
- [ ] Do not create a fake Visit, Driver, or customer just to reuse the field-return workflow.
- [ ] From that point onward, release/disposal/vendor-return handling is the same closed-loop lifecycle as damaged goods received from a vehicle.

---

# 6. Batch identity without operator complexity

The Backend needs the correct Batch for a returned tracked product because expiry, supplier provenance, costing, disposition, and audit depend on it. The representative must **not** be asked for a database `batch_id`.

Resolution order:

- [ ] If the product is not lot-tracked, resolve the approved internal/no-lot identity without asking the representative for fake supplier-lot data.
- [ ] For tracked products, first resolve from authoritative server evidence when one answer is deterministic: prior movement/sale evidence, shop/visit context, product tracking evidence, and other approved provenance.
- [ ] If a supported scan carries real lot/expiry information, consume that evidence automatically.
- [ ] Never assume an ordinary product EAN/UPC barcode contains lot or expiry information.
- [ ] If multiple Batch candidates remain, ask only for the smallest business fact that distinguishes them, such as printed lot/production identity or expiry evidence when sufficient.
- [ ] Present names/dates/lot values, never technical IDs.
- [ ] If ambiguity remains after the minimal prompt, fail closed instead of assigning the return to a guessed Batch.

**Current contract gap to close later:** Backend `VisitReturnInput` requires `batch_id`, while current Flutter return payload omits it. The fix is an operator-simple resolution flow plus the correct hidden contract field, not relaxing Backend integrity.

---

# 7. Three quality-action scopes — keep them distinct and connected

These are three different business scopes and must remain visible in the implementation plan so future page work does not collapse them accidentally.

## 7.1 Product-level safety

Use when the problem applies to the whole Product/SKU regardless of one Batch.

- Product/Catalog page is the natural owner.
- Whole-product hold/safety actions may affect downstream sellability across Batches according to Backend authority.

## 7.2 Batch-level disposition

Use when the decision applies to an entire Batch/lot.

- Batches page is the natural owner.
- Batch disposition remains separate from a location-specific partial quantity status change.

## 7.3 Quantity-level stock status

Use when only a subset of one Batch at one location is affected.

Example: Batch A has 100 cartons AVAILABLE; isolate only 7.

Result: `93 AVAILABLE + 7 QUARANTINED` in the same location/Batch.

- [x] The current Batches UI already has a quantity-entry Stock Status action capable of this pattern.
- [ ] Preserve quantity-level actions when Batches UI is polished; do not regress to whole-Batch-only controls.
- [ ] Product-level safety → relevant Batch context → quantity-level status must have clear contextual navigation/deep-links.
- [ ] Do not duplicate mutation authority across Product, Batch, and Live Stock pages merely to make navigation convenient.

**Decision:** keep ownership distributed by business scope, but make navigation obvious enough that an operator never has to guess which page owns the action.


---

# 8. Quality destinations UI — accepted V1 design

The current three-destination concept must not force a company to create or select separate warehouses merely to quarantine, hold damaged goods, dispose of goods, or prepare a vendor return.

## 8.1 Default operating model

A single warehouse may simultaneously contain:

- AVAILABLE stock;
- QUARANTINED stock;
- DAMAGED stock;
- DISPOSAL_PENDING stock.

Location and stock status are separate dimensions.

- [ ] Do **not** introduce a mutually exclusive V1 warehouse type such as Sale / Quarantine / Returns / Scrap. One normal warehouse may carry all supported stock states at the same time.

The safe V1 default for:

- quarantine handling;
- damaged/disposal handling;
- vendor-return staging;

is **the same current inventory location**.

No warehouse transfer occurs merely because the stock status changes inside that location.

## 8.2 Warehouse Management UX

Keep the **وجهات الجودة / Quality destinations** button in Warehouse Management, but it is a bounded configuration utility, not a new full page.

Required UX:

- [ ] Clicking the button opens a compact modal/panel comparable in scale to the Add Warehouse flow.
- [ ] Do not keep Quality destinations as a permanent card under the warehouse list.
- [ ] Do not open a separate full-page workspace for these three simple settings in V1.
- [x] Do not show a search box above the three settings; it has no useful purpose in the default in-place model.
- [ ] Present the three handling categories clearly.
- [ ] Show the effective default as **same location** rather than forcing a warehouse dropdown.
- [ ] Do not tell a one-warehouse company that it must create another warehouse for quarantine/returns/disposal.
- [ ] Keep the button permission-gated by the exact Backend capability.
- [ ] The UI must explain only what the operator needs to act; no internal policy/version terminology.

Any future custom-location capability is outside this plan and is tracked only in `VERSION_2_FUTURE_FEATURES.md`.

---

# 9. Warehouse quality lifecycle after damaged goods arrive

Once damaged/expired/factory-defect goods have been physically accepted from the vehicle into warehouse custody, they remain visible and non-sellable until an authorized final decision is completed.

The normal terminal choices are:

## 9.1 Release / return to saleable stock

Use only after an authorized inspection decides the goods are actually safe/useable.

- [ ] Change the exact eligible quantity back to `AVAILABLE` through status-change authority.
- [ ] Preserve Batch, location, quantity, inspection reason/evidence, actor, and audit.
- [ ] Release may be partial; a Batch or damaged bucket does not have to be released all at once.

## 9.2 Disposal

- [ ] Move the approved quantity into the existing `DISPOSAL_PENDING` lifecycle before physical disposal when the current terminal contract requires staging.
- [ ] Final disposal is an explicit confirmation that the goods were actually destroyed/discarded.
- [ ] Final disposal creates authoritative physical outbound movement with no destination inventory location.
- [ ] Quantity leaves company physical stock exactly once.
- [ ] Record actor, quantity, Batch, source location/status, reason, timestamp, and required human evidence.
- [ ] Do not represent “moved to the same warehouse” as disposal.

## 9.3 Return to vendor

- [ ] Determine the supplier/vendor from authoritative inbound/Batch provenance whenever deterministic; operator does not choose a supplier merely to make the screen proceed.
- [ ] Keep the quantity non-sellable while awaiting physical handover.
- [ ] Final vendor handover is an explicit real-world confirmation.
- [ ] Final handover creates authoritative physical outbound movement with no destination company inventory location.
- [ ] Preserve supplier, Batch, original receipt/provenance, quantity, handover reference/evidence, actor, and timestamp.

**Rule:** a status such as DAMAGED or QUARANTINED is not a terminal business outcome by itself. It is a controlled holding state until release, disposal, or vendor handover is closed.

---

# 10. Financial closure — physical closure alone is not enough

A quality/return case is not fully closed merely because inventory moved.

## 10.1 1:1 shop replacement

- [ ] The shop's damaged-goods exchange itself does not create a new cash sale or silently change the customer's debt.
- [ ] The saleable replacement leaving the vehicle is still a real inventory/cost event.
- [ ] The damaged goods entering company custody remain inventory value/evidence until their final outcome is known.
- [ ] Preserve zero-revenue replacement semantics separately from inventory cost.

## 10.2 Goods released as usable

If inspection returns the goods to AVAILABLE, there is no disposal loss. Preserve the status-change evidence; do not create a fictitious expense.

## 10.3 Goods finally disposed

- [ ] Final disposal must reduce physical quantity and authoritative inventory valuation consistently.
- [ ] Inventory Costing remains the valuation authority.
- [ ] The financial lifecycle must record the resulting damaged-goods/loss resolution rather than leaving a quantity/value disappearance with no business explanation.
- [ ] When the accounting/GL authority is available, the financial resolution must map to the approved loss/expense vs inventory posting without a second shadow ledger.

## 10.4 Goods returned to supplier

- [ ] Vendor handover reduces company physical inventory and inventory value through the authoritative costing path.
- [ ] If the supplier is expected to compensate the company, do not call the case financially closed at physical handover.
- [ ] Keep an explicit supplier-claim/credit resolution open until the approved recovery is received, such as supplier credit or replacement stock under the future/current purchasing authority as applicable.
- [ ] Tie the financial recovery to the original Batch/supplier provenance and terminal handover evidence.
- [ ] Do not treat a recoverable supplier defect as an unexplained company loss.

**Closed means both:** terminal inventory outcome + terminal financial resolution, where a financial obligation/recovery exists.


---

# 11. Implementation order — do not invert dependencies

This plan is intentionally executed **after** the relevant Warehouse/Inventory foundation is polished. Do not jump directly into Flutter or terminal-quality workflows while their upstream pages/contracts are still being changed.

Required order:

1. **Warehouse Management**
   - finish warehouse master UX and lifecycle;
   - keep Quality destinations as the bounded button/modal defined above;
   - preserve same-location default behavior.

2. **Live Stock**
   - trusted operational visibility by location/status/Batch;
   - no mutation authority duplicated here.

3. **Inbound / Batches / Expiry**
   - preserve supplier/Batch provenance and tracking truth;
   - preserve the three quality scopes;
   - verify partial quantity status actions remain reachable and understandable.

4. **Transfers / custody**
   - preserve normal warehouse↔warehouse and warehouse↔vehicle movements;
   - no fake quality transfers to the same location.

5. **Stocktake / Vehicle reconciliation**
   - build the missing Vehicle→Warehouse explicit handoff;
   - count all supported statuses, including DAMAGED;
   - preserve discrepancies and responsibility evidence.

6. **Quality / damaged goods / vendor return**
   - unify release, disposal, and vendor-return terminal paths around the existing movement engine;
   - do not rebuild already accepted Backend primitives.

7. **Financial closure**
   - connect terminal physical outcomes to authoritative costing and required loss/vendor-claim resolution;
   - final Operations settlement remains after inventory reconciliation.

8. **Flutter/mobile**
   - only after Backend + Dashboard contracts are stable;
   - repair the return Batch contract;
   - simplify representative UX around the finished Backend;
   - preserve offline/idempotent replay and do not duplicate authority in Dart.

This ordering does not forbid fixing a proven blocker earlier, but it forbids designing downstream truth around unfinished upstream assumptions.

---

# 12. Flutter acceptance requirements when its phase begins

- [ ] Representative can record a 1:1 damaged/expired/factory-defect exchange with the fewest practical inputs.
- [ ] Partial carton/pack quantities remain supported.
- [ ] Backend resolves Batch automatically whenever safe.
- [ ] If ambiguity remains, Flutter asks one minimal human-readable question and sends the resolved hidden identity afterward.
- [ ] No technical Batch IDs, FEFO choices, costing choices, or supplier IDs are exposed.
- [ ] Offline operation stores one durable business command with stable idempotency identity.
- [ ] Retry/replay cannot duplicate replacement outbound or damaged inbound.
- [ ] Vehicle inventory projection shows returned DAMAGED custody accurately.
- [ ] End-of-session/reconciliation data sent to Dashboard remains consistent with the same Unified Inventory truth.
- [ ] Corrections/reopening completed visits reverse and reapply both saleable and damaged-return inventory evidence correctly.

---

# 13. Acceptance matrix — no silent loss

The feature is not complete until end-to-end acceptance proves all of the following.

## 13.1 Quantity and status

- [ ] Partial quantity quarantine from one Batch.
- [ ] Partial release back to AVAILABLE.
- [ ] Partial damaged handling.
- [ ] Partial disposal and final disposal.
- [ ] Partial vendor return and final handover.
- [ ] No reservation survives in a forbidden non-AVAILABLE state.
- [ ] No movement creates negative stock or duplicate terminal quantity.

## 13.2 Representative / vehicle custody

- [ ] Shop 1:1 exchange creates one replacement outbound and one damaged inbound.
- [ ] Returned damaged goods are visible in vehicle custody.
- [x] Vehicle reconciliation includes DAMAGED and all supported states.
- [x] Matching handoff moves exact quantities to warehouse.
- [x] Short/over receipt remains variance; no quantity is silently discarded.
- [x] Receiving actor and originating work session/vehicle remain attributable.

## 13.3 Batch and provenance

- [ ] Correct Batch retained from field return through warehouse disposition.
- [ ] No-lot product does not force fake lot input.
- [ ] Ambiguous tracked return fails closed until minimal evidence resolves it.
- [ ] Supplier/vendor provenance is never selected by guessing.
- [ ] Cross-company Batch/vendor evidence cannot leak.

## 13.4 Financial truth

- [ ] 1:1 replacement does not create fake customer revenue/cash.
- [ ] Disposal removes the correct inventory value and produces an explicit loss resolution.
- [ ] Vendor handover removes the correct inventory value and opens/links any required supplier recovery.
- [ ] Supplier recovery closes only when authoritative credit/replacement evidence is received.
- [ ] Work-session cash shortage/overage remains explicit and attributable.
- [ ] No financial settlement can bypass required inventory reconciliation.

## 13.5 Concurrency, retry, and audit

- [ ] Every mutation is idempotent.
- [ ] Unknown-outcome retry safely replays the same operation.
- [ ] Lock ordering remains canonical.
- [ ] Real PostgreSQL acceptance covers movement/status/costing/reconciliation transitions.
- [ ] Ledger and audit evidence can reconstruct the complete lifecycle.
- [ ] Tenant/location/capability negative tests fail closed.

---

# 14. Definition of done

This plan is complete only when a real example can be traced without gaps:

`Supplier receipt → warehouse Batch → vehicle load → shop → damaged 1:1 exchange → vehicle DAMAGED custody → responsible employee physically receives it → warehouse DAMAGED custody → inspection decision → release OR disposal OR vendor handover → financial resolution where required → immutable Ledger/audit trail.`

At every arrow the system must prove **who, what, how much, which Batch, where, when, why, and what happened next**.

No quantity may disappear because of settlement.
No cash difference may disappear because of a status change.
No vendor claim may disappear because stock left the building.
No client screen may guess an identity the Backend cannot prove.

---

# 15. Preservation rule

- This document is the canonical closed-loop implementation plan for the discussed V1 quality/damaged/return/settlement work.
- Do not delete it after one UI change or one Backend endpoint passes.
- Update checkboxes only with implementation + focused acceptance evidence.
- If a later product decision changes one of these owner-approved rules, update this file and the relevant architecture/scope source in the same reviewed change.
- V2-only extensions remain in `VERSION_2_FUTURE_FEATURES.md`; do not silently pull them back into this plan.
