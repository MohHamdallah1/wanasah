# Wanasah V1 Completion Audit

**Status:** rolling execution-status companion to `V1_SCOPE_FREEZE.md`  
**Audit date:** 2026-10-05  
**Audited branch:** `main`  
**Audited commit:** `a9dd7b4dde5a29aaf4bfeb6b383e28d70e79c0f5`  
**Canonical V1 scope authority:** `V1_SCOPE_FREEZE.md`

This file does **not** change V1 scope. It measures progress against the already-frozen scope and records the shortest remaining path to `V1 DONE`.

## 1. Current V1 completion score

**Canonical snapshot: 65 / 100 complete.**

This is a weighted engineering/release-readiness score, not a percentage of files or lines of code. A capability scores high only when the end-to-end V1 workflow is substantially implemented and there is meaningful correctness evidence. Existing code without production acceptance does not receive 100%.

| Frozen V1 area | Weight | Current completion | Weighted points | Status |
| --- | ---: | ---: | ---: | --- |
| Identity / company / access / sessions | 7 | 82% | 5.7 | `[~]` |
| Products / Catalog | 11 | 94% | 10.3 | `[~]` |
| Inventory / Warehouses | 17 | 65% | 11.1 | `[~]` |
| Dispatch / routes / shops | 13 | 72% | 9.4 | `[~]` |
| Flutter field application | 15 | 52% | 7.8 | `[~]` |
| Commercial rules / offers / taxes | 7 | 78% | 5.5 | `[~]` |
| Sales / returns / financial truth | 12 | 62% | 7.4 | `[~]` |
| Minimal launch reports | 6 | 30% | 1.8 | `[ ]` |
| Minimal operational settings | 4 | 40% | 1.6 | `[ ]` |
| Production readiness / deployment acceptance | 8 | 58% | 4.6 | `[~]` |
| **Total** | **100** |  | **65.2 → 65** | **`[~]`** |

### Scoring rule

- `[x]` means the frozen V1 boundary is implemented and accepted for its current risk level.
- `[~]` means substantial implementation exists but one or more required V1 gaps or release gates remain.
- `[ ]` means the minimal frozen V1 boundary is materially incomplete.
- V2 work contributes **zero** to this score and is not allowed to delay V1.

The score is intentionally conservative. It is easier to raise it by closing a real workflow than by adding code.

---

## 2. What is already strong / substantially closed

### [x] Product Import engineering

Product Import development engineering is closed for V1. Real owner-run Dashboard evidence includes 500-row, 50,000 mixed, and 50,000 all-valid imports; the final 50k runs are in the accepted ~4-minute class. Deeper import throughput optimization is V2 unless a real regression appears.

### [x] Worker foundation

The operational/reports/product-import worker foundation has recorded isolation, cleanup, recovery, dedupe, bounded tenant discovery, heartbeat, retry, Live Stock recovery and queue-health gates. Do not reopen this foundation without a demonstrated regression.

### [~] Products / Catalog is near the frozen V1 boundary

The current Products area already has structured create/list/detail/family/barcode/import/lifecycle/display-preference surfaces and a large focused Dashboard test set. Current status/lifecycle UX polishing may continue only until the required V1 workflow is clear and safe. Optional cosmetic perfection must not hold V1 open.

### [~] Dashboard business surfaces are not empty prototypes

Current routed surfaces include Operations, Dispatch, Inventory, Products, Commercial Rules and Sales/Returns. Inventory already exposes Live Stock, Inbound, Stocktake, Ledger, Batches, Transfers, Warehouse Locations and Inventory Access.

### [~] Flutter already contains real operational code

Flutter contains login, dashboard, visit list, visit workflow and add-shop screens. It also has a local/offline sync repository, stable request IDs for sales, pending-sync replay, token refresh and local persistence. It therefore needs audit/hardening, not a rewrite from zero.

---

## 3. Closed list of work separating current `main` from V1 DONE

This is the current **closed remaining list**. Do not add another V1 item unless it passes the scope-change guard in `V1_SCOPE_FREEZE.md`.

### A. Inventory correctness: Inbound → Batches & Expiry — V1 BLOCKER/REQUIRED

- [ ] Finish the production audit/hardening of Supplier Inbound / Goods Receipt.
- [ ] Make `lot_control_mode` and `expiry_control_mode` consistent across Catalog, Inbound backend contracts and Dashboard.
- [ ] Remove the current semantic gap where inbound still requires a batch number for products whose lot mode may be `NONE` or `OPTIONAL`.
- [ ] Close required batch/expiry validation, existing-batch metadata conflict, tenant/location identity, idempotency/concurrency and draft-recovery gates.
- [ ] Freeze the inbound batch/expiry contract.
- [ ] Finalize the Batches & Expiry V1 UI only after that frozen contract.

**Stop boundary:** do not build an advanced batch analytics product. Close only sellability/expiry/quality visibility and actions required by the frozen operational workflow.

### B. Financial / tenant truth across real commercial workflows — V1 BLOCKER

- [ ] Complete cross-domain Product Master vs sellable Variant identity, composite-FK and FORCE-RLS negative coverage where it matters to Inventory, Pricing, Sale, reporting and Flutter/offline.
- [ ] Close the genuinely required costing and immutable Sale/Return/retry/COGS scenarios for enabled V1 workflows.
- [ ] Confirm ambiguous/lost-response retries cannot duplicate or corrupt financial/stock truth.
- [ ] Preserve one official valuation/COGS/profit authority; do not create a second accounting truth.

**Stop boundary:** this is correctness work, not a request to build a full accounting/ERP module.

### C. Flutter + Dispatch real end-to-end production workflow — V1 REQUIRED

- [ ] Audit the existing Flutter app against the frozen flow: login → assigned route/visits → shop → visit → sale/return/sample where enabled → durable sync/recovery.
- [ ] Close cross-user/company leakage and exact route/territory/warehouse authorization gaps.
- [ ] Verify offline mutation identity and reconciliation through real network-loss/lost-response scenarios.
- [ ] Add focused Flutter tests for the real V1 workflows. The current Flutter test directory contains only the default counter-style widget smoke test and is not meaningful release evidence.
- [ ] Run one Dashboard → backend → Flutter end-to-end route/visit acceptance with real V1 permissions and retry semantics.
- [ ] Harden existing Dispatch only where the real field workflow proves a gap; do not refactor large stable files merely for cleanliness before launch.

### D. Minimal Reports — V1 REQUIRED

- [ ] Close route/visit completion + visit-result reporting.
- [ ] Close management sales/returns summary.
- [ ] Ensure stock/movement questions not already answered by Inventory surfaces have a usable answer.
- [ ] Close field-user settlement/accountability reporting only to the extent required by the current operating model.

The current sidebar exposes `/reports` as coming soon and there is no active report route. Existing Operations settlement/sales views may satisfy part of the requirement and should be reused rather than building a BI platform.

### E. Minimal Settings — V1 REQUIRED

- [ ] Provide one usable path to all configuration required by V1: company/user/access/branch/location plus only the operational policies consumed by frozen workflows.
- [ ] Reuse existing Inventory Access, Warehouse Locations, product tracking and other existing administration surfaces where possible.

The current sidebar exposes `/settings` as coming soon and there is no active Settings route. A giant generic settings center is not required if existing authoritative surfaces cover the frozen workflow cleanly.

### F. First-company deployment / release acceptance — V1 RELEASE GATE

- [ ] Identify the actual first-company deployment target and expected active-user/import envelope.
- [ ] Rehearse against an independent target/rehearsal database.
- [ ] Produce a real backup and restore the **whole** archive into a separate disposable DB; verify key Product/Variant/Price/Inventory/COGS/Audit/Outbox evidence.
- [ ] Deploy one reviewed immutable application/frontend/worker commit and verify worker code identity.
- [ ] Run the bounded first-company D7-P representative workload: Sale/COGS + Supplier Inbound + Route Launch + Product Import, with persisted reconciliation.
- [ ] Exercise browser/network loss, retry with the same request identity, cancellation, worker restart and session expiry on the actual target.
- [ ] Obtain final owner release sign-off on recovery, worker/schema identity, pilot SLOs, operational alerts and business reconciliation.

Large 1,000-open-connection/multi-company scale certification remains V2 and must not delay this release.

### G. Final integrated V1 gate — LAST STEP

- [ ] One first-company scenario starts from company/admin setup and reaches products/prices → warehouse/inbound/stock → dispatch → Flutter visit/commercial action → return/settlement/report without falling back to WhatsApp/Word/Excel for the frozen core flow.
- [ ] All known V1 BLOCKER items are closed.
- [ ] The required focused security/isolation, stock/financial truth, idempotency/recovery and user-workflow gates pass.
- [ ] Mark all frozen V1 sections `[x]`, declare `V1 DONE`, and stop feature expansion.

---

## 4. What must NOT consume V1 time now

Do not delay V1 for:

- Advanced UOM or multi-level packaging;
- Advanced Pricing workspace/rules;
- generic BI/report builder;
- giant configurable Settings framework;
- extra import channels/connectors;
- further Product Import performance work while the accepted ~4-minute 50k class holds;
- 1,000 truly simultaneous external connections or large multi-company scale certification;
- broad cleanup/refactoring of stable legacy code solely because a cleaner architecture is possible;
- optional animations/cosmetic redesign after a workflow is understandable and safe.

---

## 5. Recommended execution order from here

1. Finish the currently-open Products UX/status polish and stop when its V1 workflow is safe and understandable.
2. Close **Inbound → batch/expiry** correctness and its focused production gate.
3. Close the two cross-domain **financial/tenant truth** responsibilities in `INVENTORY_COMMERCIAL_FOUNDATION_PLAN.md`.
4. Audit/harden **Flutter + Dispatch together** as one real field workflow rather than separately polishing screens.
5. Close **Sales/Returns/Commercial** integration gaps discovered by that real field flow.
6. Implement only the **minimal Reports + Settings** gaps that remain after reusing existing surfaces.
7. Select the first-company target and execute the **deployment/backup/restore/rehearsal** gate.
8. Run the single integrated V1 acceptance, mark the remaining items `[x]`, and stop.

---

## 6. How the score changes

The percentage is updated only when evidence closes part of a frozen workflow. UI polish that does not change V1 usability/safety should not materially change the score.

A useful target sequence is:

- current baseline: **65/100**;
- after Inventory Inbound/Batch-Expiry + finance truth closure: approximately **75–80/100**;
- after Flutter/Dispatch/Sales real end-to-end closure: approximately **88–92/100**;
- after minimal Reports/Settings + first-company deployment gate: **100/100**.

These ranges are planning guidance, not permission to skip a blocker.
