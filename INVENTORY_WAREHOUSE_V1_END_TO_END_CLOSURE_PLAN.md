# Wanasah — Inventory / Warehouses V1 End-to-End Closure Plan

> **Status legend**
> - `[ ]` Not started
> - `[~]` In progress
> - `[x]` Completed with evidence
> - `[!]` Blocked / explicit decision required
>
> **Baseline audited main:** `5da83d8895faf42e9679295b206b0c0c8547802c`
>
> **Execution rule:** لا يتم تحويل أي بند إلى `[x]` بسبب وجود كود فقط. الإغلاق يحتاج Implementation + focused validation + regression review + evidence مناسب للبند.
>
> **Authority rule:** `V1_SCOPE_FREEZE.md` + `ARCHITECTURE.md` + قواعد الهوية/الصلاحيات هي السلطة المعمارية والنطاقية. `RUN.txt` يبقى ملاحظات/تتبع للمالك وليس الخطة الأساسية.
>
> **Backend → UI rule:** كل Capability تشغيلية مطلوبة للمستخدم في V1 تُغلق End-to-End في نفس الموجة: Backend authority → API contract → Dashboard path → permission gating → tests/acceptance. لا نصلح Backend ثم نترك واجهته إلى نهاية المشروع.
>
> **No endpoint mirroring rule:** ليس كل Endpoint يجب أن يتحول إلى زر. Internal primitives / compatibility endpoints / helper reads تبقى داخلية عندما لا توجد لها User Action مستقلة.
>
> **Final polish rule:** بعد اكتمال الوظائف والـcontracts والصلاحيات نعمل Wave مستقلة لإعادة هندسة وصقل واجهة Inventory بالكامل. الـpolish النهائي لا يسبق صحة المنطق.

---

# 0. Scope and frozen boundaries

هذه الخطة هي **الخطة التنفيذية الشاملة لكل Inventory / Warehouses V1 من الخلف إلى الأمام**، وليست خطة لتبويبين فقط.

تشمل:

- Warehouse/location setup and lifecycle.
- Branches المرتبطة بالمستودعات.
- Product ↔ Location assignment / operational flags.
- Live Stock.
- Supplier Inbound / Goods Receipt.
- Costing policy required by inbound/commercial correctness.
- Lot / Batch / Expiry.
- Batch disposition and warehouse stock-status movements.
- Quality handling destinations and terminal quality actions.
- Warehouse/Vehicle transfers where Inventory owns the stock movement side.
- Stocktake / reconciliation / corrections.
- Inventory Ledger and authoritative adjustments.
- Minimum-stock policy currently used by V1 workflows.
- Shelf-life/sellability policy where already part of inventory truth.
- Inventory/Backoffice capability enforcement and location scope.
- Cross-module seams with Catalog, Suppliers, Vehicles, Dispatch, Pricing/COGS and Company timezone only where Inventory correctness depends on them.
- Dashboard contracts, i18n, RTL/LTR, keyboard, responsive behavior, error states, performance and production acceptance.

## 0.1 Explicit non-goals

- [ ] Do not build a generalized WMS beyond frozen V1.
- [ ] Do not build generalized IAM inside Inventory.
- [ ] Do not reintroduce generic `.is_admin` / manager shortcuts.
- [ ] Do not merge FieldRepresentative identity with Backoffice identity.
- [ ] Do not expose every backend endpoint merely because it exists.
- [ ] Do not replace authoritative inventory movement rules with React-side business logic.
- [ ] Do not expand into advanced forecasting, replenishment, procurement planning, barcode automation, GS1 lot ingestion, warehouse robotics, or generalized multi-warehouse optimization unless separately promoted.
- [ ] Do not redesign Dispatch or Vehicles inside this plan; only preserve Inventory seams they depend on.

---

# 1. Frozen architecture invariants

## 1.1 Inventory truth

- [ ] `InventoryBalance` remains the current-stock SSOT.
- [ ] Every quantity/status mutation continues through the Unified Inventory Movement authority.
- [ ] No UI convenience may directly mutate balances or bypass movement invariants.
- [ ] Quantities remain exact decimal-safe values; no float business math.
- [ ] Reservation invariants remain enforced, including no reservations in non-AVAILABLE buckets.

## 1.2 Tenant and location isolation

- [ ] Every read/write is explicitly scoped by canonical `company_id`.
- [ ] Location-sensitive operations use canonical location-capability semantics.
- [ ] Filtering/scoping occurs before pagination and aggregation.
- [ ] RLS remains defense-in-depth, not the only isolation mechanism.
- [ ] Cross-company existence must not leak through 404/403 differences beyond frozen contracts.

## 1.3 Canonical identity and authorization

- [ ] Request authority comes from `BackofficeCapabilityAccess` / canonical Backoffice subject.
- [ ] `access.company_id` is tenant authority.
- [ ] Company Owner authority comes only from canonical owner state.
- [ ] Legacy `Driver` may remain only where existing audit/provenance/idempotency storage genuinely requires a legacy actor id.
- [ ] No authority decision may depend on principal/profile/Driver numeric ID equality assumptions.
- [ ] Read-only endpoints must not load legacy Driver unnecessarily.

## 1.4 Product and lifecycle rules

- [ ] Catalog remains authority for product/variant identity, lifecycle and tracking modes.
- [ ] Product-location operational flags remain respected for inbound/outbound behavior.
- [ ] Product lifecycle guards remain authoritative.
- [ ] `lot_control_mode` and `expiry_control_mode` must not drift between Catalog, Inbound, Live Stock and Batches UI.

## 1.5 Time and sellability

- [ ] Company-local date remains authoritative for date-only inventory rules.
- [ ] `batch_sellability_predicate` remains central SQL authority for sellability.
- [ ] React does not independently reconstruct sellability truth.
- [ ] Visual warning thresholds are not allowed to change business sellability.

---

# 2. Audited Backend → UI map

This map is the execution inventory. A backend capability marked "internal" does not automatically require a new control.

| Domain | Backend authority | Current UI owner | Closure intent |
|---|---|---|---|
| Warehouse setup | `/warehouse/setup-status`, `/warehouse/locations*` | `MainInventory`, `TabWarehouseLocations` | keep + harden |
| Branches | `/warehouse/branches/*` | `BranchManagementModal`, `BranchSelector` | fix capability parity |
| Product-location | `/warehouse/product-locations*` | `ProductLocationManager` | validate end-to-end |
| Live Stock | `/warehouse/inventory/cursor`, summary, families, product batches | `MainInventory`, `Tab1LiveStock` | acceptance + UX later |
| Alert summary | `/warehouse/inventory/alerts/summary` | auxiliary/no dedicated action | internal/optional read |
| Inbound options | `/warehouse/inbound/options` | `Tab2Inbound` | keep |
| Costing policy | `/warehouse/costing-policy` | `Tab2Inbound` | keep + acceptance |
| Goods receipt | `POST /warehouse/inbound` | `Tab2Inbound`, `useInboundPosting` | **critical contract fix** |
| Batch drill-down | `/warehouse/inventory/{variant}/batches` | `TabBatches` | keep as drill-down |
| Batch-wide disposition | `/warehouse/batches/{batch_id}/disposition` | `BatchDispositionManager` | validate |
| Stock-status change | `/warehouse/inventory/status-change` | no runtime UI | **must surface safely** |
| Batch stock sources | `/warehouse/batches/{batch_id}/stock-sources` | `BatchQuantityActions` | validate |
| Special transfer | `/warehouse/unified/transfer/special/dispatch` | batch actions | validate |
| Quality source/candidates | `/warehouse/variants/*/quality-*` | quality hooks | validate |
| Product quality resolve | `/warehouse/quality/products/*/resolve-*` | quality command UI | validate |
| Disposal confirm | `/warehouse/quality/disposal/confirm` | terminal batch action | validate |
| Vendor-return confirm | `/warehouse/quality/vendor-return/confirm` | terminal batch action | validate |
| Quality staging primitive | `/warehouse/quality/stage` | intentionally not direct UI | keep internal |
| Transfer destination policy | `/warehouse/operational-policy/transfer-destinations*` | `QualityHandlingDestinationsCard` | validate |
| Unified transfers | `/warehouse/unified/transfer*`, `/warehouse/unified/transfers*` | `TabTransfers` | acceptance |
| Stocktake | `/warehouse/unified/stocktake*` | `Tab3Stocktake` | acceptance |
| Ledger | `/warehouse/ledger/cursor` | `Tab4Ledger` | acceptance |
| Ledger correction | `/warehouse/ledger/{entry_id}/adjust` | Ledger adjustment UI | acceptance |
| Minimum stock bulk | `/warehouse/inventory/minimum-stock/bulk*` | `StockMinimumManager` | fix capability parity |
| Minimum stock single | `/warehouse/inventory/{variant}/minimum-stock` | no dedicated standalone control | keep backend; bulk UI may cover |
| Capabilities | `/inventory/access/me`, location capabilities | inventory shell/hooks | keep canonical |
| Roles/grants | `/inventory/access/*` | `TabInventoryAccess` | keep temporarily; Backoffice seam |

---

# 3. Execution model and parallel-work rules

## 3.1 Primary-lead responsibility

- [ ] Primary ChatGPT lead assigns exact branch + exact write ownership before each parallel wave.
- [ ] Workers do not broaden scope or make architecture decisions independently.
- [ ] Every worker starts from an explicitly named main SHA.
- [ ] No worker merges to `main`.
- [ ] Main integration happens only after independent acceptance at a stability point.

## 3.2 Recommended parallel streams

The exact files are assigned per wave; these are ownership categories, not blanket permissions.

**Conversation / Worker A — Backend contracts and authority**
- Inbound, Batches read models/actions, warehouse capability correctness, focused backend tests.

**Conversation / Worker B — Dashboard contract/UI implementation**
- The corresponding Inventory UI slice for the active backend wave, i18n keys and focused frontend tests.

**Conversation / Worker C — Independent acceptance / regression**
- Cross-tenant/capability/runtime acceptance, contract comparison, migration/real PostgreSQL where needed, no production-code ownership unless explicitly reassigned.

**Codex — bounded support**
- Focused code audit, test authoring, query-plan/performance evidence, mechanical i18n extraction, or isolated implementation with explicit write ownership.

- [ ] Never have two workers own the same runtime file simultaneously.
- [ ] Never mix broad UI redesign with business-rule changes in the same PR unless unavoidable.
- [ ] Every wave ends in a clean checkpoint before the next dependency wave.

---

# CHECKPOINT 0 — Baseline freeze and evidence map

- [x] Audit current `main` at `5da83d8895faf42e9679295b206b0c0c8547802c` from Backend → UI.
- [x] Confirm V1 Inventory scope in `V1_SCOPE_FREEZE.md`.
- [x] Confirm Inbound is upstream of final Batches & Expiry closure.
- [x] Confirm real `lot_control_mode` mismatch in Inbound.
- [x] Confirm `/warehouse/inventory/status-change` exists with no direct runtime Dashboard path.
- [x] Confirm Branch backend uses `branch.*` capabilities while current Branch UI is owner-only.
- [x] Confirm Minimum Stock backend uses `inventory.minimum_stock.manage` while current UI entry is owner-only.
- [x] Confirm Transfers, Stocktake and Ledger already have substantial Backend → UI coverage.
- [x] Confirm Quality staging primitive is intentionally not a direct modern UI action.
- [ ] Record the exact starting SHA for each implementation wave when work begins.

**Checkpoint 0 gate:** no runtime changes; plan becomes the master Inventory/Warehouse V1 closure tracker.

---

# CHECKPOINT 1 — Inbound / Goods Receipt contract closure

This is the first runtime wave. Do not finalize Batches UX before this checkpoint closes.

## 1.1 Lot-control semantics

- [ ] Audit `InboundBatchItem.batch_number` against `ProductVariant.lot_control_mode`.
- [ ] Add `lot_control_mode` to the authoritative inbound variant rules/contract where required.
- [ ] Freeze exact semantics for `NONE / OPTIONAL / REQUIRED`.
- [ ] `REQUIRED`: real supplier/internal lot identity is required.
- [ ] `OPTIONAL`: real lot may be supplied; absence is accepted safely.
- [ ] `NONE`: user must not be forced to invent a lot/batch number.
- [ ] Define a safe internal identity strategy for non-lot-tracked receipts while preserving `ProductBatch` / `InventoryBalance` referential integrity and uniqueness.
- [ ] Internal identity for `NONE` must not be presented as fake supplier lot data.
- [ ] Same product + same real batch must preserve metadata consistency.
- [ ] Duplicate product + batch identity + UOM lines remain fail-closed.

## 1.2 Expiry semantics

- [ ] Preserve `expiry_control_mode=REQUIRED` → expiry required.
- [ ] Preserve `expiry_control_mode=NONE` → expiry rejected/hidden.
- [ ] Preserve `OPTIONAL` → missing or valid expiry accepted.
- [ ] Production date cannot be after expiry date.
- [ ] Production date future rule remains company-local-date aware.
- [ ] Expired stock cannot enter AVAILABLE inventory.
- [ ] Existing batch metadata conflict remains fail-closed.
- [ ] Production-date semantics are explicit for all tracking modes.

## 1.3 Cross-path parity

- [ ] Interactive Dashboard receipt and any bulk/integration receipt path enforce the same lot/expiry semantics.
- [ ] Product Import tracking defaults/modes cannot create data that Inbound later interprets differently.
- [ ] Catalog API, Dashboard Catalog contract, Inbound API and Dashboard Inbound contract use the same stable mode values.

## 1.4 UOM / costing / supplier / lifecycle preservation

- [ ] Preserve exact direct UOM conversion requirements.
- [ ] Preserve `quantity_scale` / `quantity_step` validation.
- [ ] Preserve Supplier requirement and supplier permission checks.
- [ ] Preserve ProductLocation inbound flags and product lifecycle guards.
- [ ] Preserve MOVING_AVERAGE / FIFO policy behavior.
- [ ] Preserve first-receipt costing activation/locking.
- [ ] Preserve idempotency and advisory/row lock behavior.
- [ ] Preserve audit/domain-event/provenance behavior.

## 1.5 Inbound UI reflection — same checkpoint

- [ ] UI receives `lot_control_mode` and `expiry_control_mode` without guessing.
- [ ] Batch/Lot field is hidden/optional/required according to product mode.
- [ ] Expiry field is hidden/optional/required according to product mode.
- [ ] Production date visibility/requirement follows frozen contract.
- [ ] Requiredness is visually explicit before submit.
- [ ] Irrelevant fields do not consume operator time.
- [ ] Existing-batch conflict explains exactly which metadata conflicts.
- [ ] Document defaults are offered only where logically valid.
- [ ] Repeated metadata entry is minimized without changing truth.
- [ ] Validation focuses/scrolls to the exact invalid row.
- [ ] Enter/keyboard workflow remains high-volume friendly.
- [ ] Draft recovery remains scoped by company + actor + warehouse.

## 1.6 Inbound tests / gate

- [ ] Backend tests: lot NONE/OPTIONAL/REQUIRED.
- [ ] Backend tests: expiry NONE/OPTIONAL/REQUIRED.
- [ ] Existing-batch metadata conflict.
- [ ] Cross-tenant identity isolation.
- [ ] Concurrent receipt/idempotency.
- [ ] UOM exactness regression.
- [ ] Supplier permission regression.
- [ ] Frontend contract parser tests.
- [ ] Frontend draft-recovery tests.
- [ ] UI field visibility/requiredness tests.
- [ ] RTL/LTR focused acceptance.
- [ ] Typecheck/build/diff-check.
- [ ] Real runtime receipt acceptance with representative mode combinations.

**Checkpoint 1 gate:** Inbound contract frozen and production-safe before Checkpoint 2.

---

# CHECKPOINT 2 — Batches & Expiry read model and page foundation

## 2.1 Preserve existing drill-down endpoint

- [ ] Keep `GET /warehouse/inventory/{product_variant_id}/batches` as product drill-down.
- [ ] Preserve company/location/product isolation.
- [ ] Preserve bounded keyset pagination.
- [ ] Preserve `(expiry_date ASC NULLS LAST, id ASC)` ordering unless a measured contract change is explicitly approved.
- [ ] Preserve company-local date calculation.

## 2.2 Batch-centric warehouse index

- [ ] Implement/freeze a dedicated warehouse batch-index read path for the main Batches page.
- [ ] Do not use Live Stock product pagination as the primary Batches page source.
- [ ] Default scope returns batches with relevant current presence in selected warehouse.
- [ ] Explicit `company_id` + `location_id` at every candidate stage.
- [ ] Keyset pagination only; hard page bounds.
- [ ] No unbounded `.all()`.
- [ ] No N+1.
- [ ] Filters applied in SQL before pagination.
- [ ] Search by product name, SKU and real batch/lot identity.
- [ ] Search escaping covers `%`, `_`, `\`.
- [ ] Multi-token behavior documented/tested.

## 2.3 Required filters and sorting

- [ ] All.
- [ ] Expired.
- [ ] Expires today.
- [ ] Expiring soon.
- [ ] Sellable.
- [ ] Not sellable.
- [ ] RELEASED / QUARANTINED / BLOCKED / RECALLED.
- [ ] Has unavailable quantity.
- [ ] Has DAMAGED quantity.
- [ ] Has DISPOSAL_PENDING quantity.
- [ ] No expiry/not applicable.
- [ ] Product family.
- [ ] Optional product filter.
- [ ] Sort expiry soonest/latest.
- [ ] Sort product A→Z / Z→A.
- [ ] Sort batch identity.
- [ ] Sort largest unavailable quantity if operationally useful and performant.
- [ ] Default sort chosen for operational usefulness.

## 2.4 Response contract / explainability

- [ ] Batch identity + product/variant identity.
- [ ] Product name, SKU, family.
- [ ] Production/expiry dates.
- [ ] `days_to_expiry`.
- [ ] `lot_control_mode` / `expiry_control_mode` where needed for display.
- [ ] Effective `minimum_remaining_shelf_life_days`.
- [ ] Explicit sellability boolean/state.
- [ ] Stable sellability reason code(s).
- [ ] `disposition`, reason and revision.
- [ ] On-hand / reserved / available-for-sale / unavailable quantities.
- [ ] Per-stock-status quantities.
- [ ] Display UOM metadata.
- [ ] Cost/latest purchase evidence only according to approved visibility policy.
- [ ] No translated presentation strings in API contract.

## 2.5 Summary/attention counters

- [ ] Total relevant batches.
- [ ] Expired.
- [ ] Expiring soon.
- [ ] Non-sellable.
- [ ] Quarantined.
- [ ] Blocked.
- [ ] Recalled.
- [ ] Damaged/disposal attention.
- [ ] Measure aggregation cost before choosing direct query vs projection.

## 2.6 Page data behavior

- [ ] Batches page defaults to batch-centric list.
- [ ] Product is a filter/drill-down, not mandatory first selection.
- [ ] Do not auto-select arbitrary product in default batch-centric mode.
- [ ] First-load error is distinct from empty state.
- [ ] Continuation failure preserves loaded rows.
- [ ] Inline retry for failed continuation.
- [ ] Abort stale requests on filter/search/location changes.
- [ ] Defensive row de-duplication.
- [ ] Automatic continuation/infinite loading where suitable.
- [ ] Tab refresh timestamp refers to Batches data, not Live Stock.

**Checkpoint 2 gate:** final Batches read foundation is authoritative, scalable and independent from Live Stock product paging.

---

# CHECKPOINT 3 — Batches operational actions closure

## 3.1 Separate business concepts in UI

Batch-wide disposition is a company-wide batch fact:
- `RELEASED`
- `QUARANTINED`
- `BLOCKED`
- `RECALLED`

Warehouse stock status is location-specific quantity state:
- `AVAILABLE`
- `QUARANTINED`
- `BLOCKED`
- `RECALLED`
- `DAMAGED`
- `DISPOSAL_PENDING`

- [ ] UI never labels both concepts with one ambiguous "Status".
- [ ] Company-wide scope is explicit before batch disposition mutation.
- [ ] Location scope is explicit before stock-status quantity mutation.

## 3.2 Batch-wide disposition

- [ ] Surface only when `batch.disposition` allows it.
- [ ] Preserve expected revision / optimistic concurrency.
- [ ] Require reason.
- [ ] Preserve transition matrix.
- [ ] Preserve audit/domain event/idempotency.
- [ ] Revision conflict offers refresh/retry UX.
- [ ] Current/last reason visible where useful.

## 3.3 Warehouse stock-status change — audited missing UI

- [ ] Add a direct Dashboard flow for `POST /warehouse/inventory/status-change`.
- [ ] Show only with `inventory.status_change` at the selected location.
- [ ] Operate on a specific batch/product/location quantity.
- [ ] Preserve base-UOM/exact-quantity contract.
- [ ] Require reason.
- [ ] Clearly show source bucket → destination bucket.
- [ ] Do not allow impossible transitions in UI; Backend remains final authority.
- [ ] After success refresh affected batch row, Batches summary, Live Stock snapshot and Ledger evidence as appropriate.

## 3.4 Quality / special-transfer actions

- [ ] Preserve batch stock-source read contract.
- [ ] Preserve reservation evidence and owner linking.
- [ ] Preserve `transfer.special.quarantine`.
- [ ] Preserve `transfer.special.recall_return`.
- [ ] Preserve `transfer.special.return_to_vendor`.
- [ ] Preserve `transfer.special.disposal`.
- [ ] Preserve terminal disposal confirmation.
- [ ] Preserve vendor-return handover confirmation.
- [ ] Preserve whole-product quality preview/resolve paths.
- [ ] Keep `/warehouse/quality/stage` internal unless a proven operator need requires a direct UI path.
- [ ] Never duplicate the same quality command in Catalog and Inventory in conflicting ways.

## 3.5 Detail surface

- [ ] Batch identity/product.
- [ ] Dates and expiry explanation.
- [ ] Sellability reason(s).
- [ ] Company-wide disposition/reason.
- [ ] Warehouse quantity breakdown.
- [ ] Reservations/source evidence.
- [ ] Purchase/cost evidence if authorized.
- [ ] Allowed actions derived from capabilities.
- [ ] Relevant Ledger/Transfer references where useful.

**Checkpoint 3 gate:** every V1 batch mutation has one clear, permission-correct UI route.

---

# CHECKPOINT 4 — Warehouse locations and branches closure

## 4.1 Warehouse lifecycle

- [ ] Validate create/update/activate/deactivate contracts against current UI.
- [ ] Preserve version checks/idempotency.
- [ ] Preserve system-location protection.
- [ ] Preserve duplicate/reserved code rules.
- [ ] Preserve Live Stock projection rebuild/removal on lifecycle changes.
- [ ] Preserve branch-active constraint on warehouse assignment.

## 4.2 Deactivation blockers

UI must present useful operator-facing explanations for backend blockers without weakening them:

- [ ] Inventory balance/reservations.
- [ ] Open transfer.
- [ ] Active inventory lock.
- [ ] Open stocktake.
- [ ] Published transfer-destination operational policy.
- [ ] Open/non-final Dispatch route using the warehouse as source.
- [ ] Any additional authoritative blocker found during implementation audit.

## 4.3 Branch capability mismatch — audited blocker

Backend authority:
- `branch.read`
- `branch.create`
- `branch.update`
- `branch.state`

- [ ] Remove generic CompanyOwner-only UI gating where capability grants should allow the action.
- [ ] Branch manager visibility derives from relevant `branch.*` capability.
- [ ] Create/edit/state buttons derive from exact capability.
- [ ] Backend remains authoritative even if UI state is stale.
- [ ] Non-owner Backoffice acceptance proves granted capabilities work.
- [ ] Denied user acceptance proves controls are hidden/disabled safely and API rejects direct calls.

## 4.4 Warehouse list UX functional baseline

- [ ] Search remains server-backed and scoped before pagination.
- [ ] Cursor behavior remains correct.
- [ ] Branch label/state stays consistent after branch mutation.
- [ ] Location capability checks are batched where appropriate.
- [ ] Do not redesign visual hierarchy yet beyond what is needed for clear functionality.

**Checkpoint 4 gate:** warehouse + branch management is capability-correct for Backoffice, not Owner-only by UI accident.

---

# CHECKPOINT 5 — Product ↔ Location assignment closure

- [ ] Validate `product_location.read` and `product_location.manage` UI parity.
- [ ] Preserve company/location/product isolation.
- [ ] Preserve product lifecycle restrictions.
- [ ] Preserve operational flags such as inbound/outbound enablement.
- [ ] Preserve reference/deletion blockers and locks.
- [ ] Product assignment changes refresh affected Inventory views safely.
- [ ] Product page remains the natural product-centric management surface; Inventory may link/focus it but does not duplicate a second conflicting editor.
- [ ] Non-owner capability acceptance.

**Checkpoint 5 gate:** ProductLocation truth is consistent between Products and Inventory.

---

# CHECKPOINT 6 — Stock policy, minimum stock and shelf-life policy

## 6.1 Minimum stock capability mismatch — audited blocker

- [ ] Use `inventory.minimum_stock.manage`, not CompanyOwner-only UI gating.
- [ ] Preserve required `inventory.read` at target location where backend requires it.
- [ ] Bulk preview and apply remain the primary high-volume UI path.
- [ ] Single-product backend endpoint stays available; add a standalone UI only if it improves an existing workflow rather than duplicating bulk UI.
- [ ] Preserve exact UOM conversion.
- [ ] Preserve expected/current minimum conflict handling.
- [ ] Preserve ProductLocation requirement.
- [ ] Preserve target-quantity constraint.
- [ ] Preserve projection refresh after policy change.

## 6.2 Shelf-life sellability policy

- [ ] Audit current creation/update paths for `minimum_remaining_shelf_life_days`.
- [ ] Show effective value where it materially explains non-sellability.
- [ ] Decide whether V1 needs operator-editable shelf-life policy for the first company.
- [ ] If editable in V1, use a dedicated explicit capability/policy path and audit trail.
- [ ] If not required in V1, do not invent a generalized company-default/override center; keep read-only explainability and track richer management for later.
- [ ] Never mix business sellability cutoff with visual expiry-warning preference.

## 6.3 Cost visibility decision

- [ ] Audit where purchase/cost fields are currently exposed under `inventory.read`.
- [ ] Decide whether V1 requires a dedicated cost-visibility capability.
- [ ] If introduced, enforce server-side omission/redaction and UI hiding together.
- [ ] If not introduced, document the frozen V1 visibility rule explicitly.

**Checkpoint 6 gate:** policy controls are capability-correct and explainable without scope creep.

---

# CHECKPOINT 7 — Live Stock closure

Live Stock is primarily an operational read surface; avoid turning it into a second management center.

- [ ] Validate warehouse selection/setup-status behavior.
- [ ] Validate `inventory.read` location scoping.
- [ ] Validate company-wide vs restricted vehicle-presence semantics.
- [ ] Preserve summary, families and cursor read paths.
- [ ] Preserve server-side search/filter/order semantics.
- [ ] Preserve low-stock indicators from authoritative policy/projection.
- [ ] Preserve batch drill-down links.
- [ ] Preserve cost display according to Checkpoint 6 decision.
- [ ] Preserve warm-session cache scoping by tenant/location/user context.
- [ ] No stale cache may leak after company/location/auth change.
- [ ] Keep alert-summary endpoint auxiliary unless a proven UI need justifies dedicated rendering.
- [ ] First-load / refresh / continuation errors remain distinct and recoverable.
- [ ] Performance evidence for normal and large product counts.

**Checkpoint 7 gate:** Live Stock is trusted operational visibility, not a source of mutation truth.

---

# CHECKPOINT 8 — Transfers and quality-destination policy closure

## 8.1 Unified transfers

- [ ] Validate source/destination location discovery and capability filtering.
- [ ] Validate source inventory cursor/search.
- [ ] Validate FEFO authority.
- [ ] Validate override options and exact override capabilities.
- [ ] Validate dispatch/send.
- [ ] Validate receive.
- [ ] Validate cancel.
- [ ] Validate reject.
- [ ] Validate transfer list/detail.
- [ ] Preserve warehouse ↔ vehicle behavior where supported.
- [ ] Preserve reservations and release semantics.
- [ ] Preserve idempotency and lock ordering.
- [ ] Preserve product lifecycle and ProductLocation outbound/inbound constraints.

## 8.2 Quality handling destinations

- [ ] Validate read/draft/publish of transfer-destination operational policy.
- [ ] Use `inventory.transfer_policy.manage` exactly.
- [ ] Validate quarantine/disposal/vendor-return destination semantics.
- [ ] Warehouse deactivation must remain blocked while referenced by published policy.
- [ ] Quality action UI provides configuration path only when destination setup is actually the blocker.

## 8.3 UX acceptance

- [ ] Clear source/destination/purpose terminology.
- [ ] Clear transfer lifecycle statuses.
- [ ] No duplicate action surfaces.
- [ ] Partial/failed continuation does not clear good data.
- [ ] RTL/LTR + keyboard + phone-width acceptance.

**Checkpoint 8 gate:** Transfers are complete enough for real V1 distribution operations.

---

# CHECKPOINT 9 — Stocktake / reconciliation closure

- [ ] Validate active sessions list.
- [ ] Validate session context.
- [ ] Validate start flow.
- [ ] Validate count sheet.
- [ ] Validate count submission.
- [ ] Validate review.
- [ ] Validate approve.
- [ ] Validate recount.
- [ ] Validate cancel.
- [ ] Validate cycle-count batch candidates.
- [ ] Validate Vehicle Recon candidates and strict vehicle/location eligibility.
- [ ] Preserve independent capabilities: `stocktake.read/start/count/review/approve/recount/cancel`.
- [ ] Preserve inventory locks and release semantics.
- [ ] Preserve adjustment posting through authoritative movement path.
- [ ] Preserve tenant/location isolation before candidate selection.
- [ ] Warehouse deactivation remains blocked by non-final stocktake.
- [ ] Runtime acceptance covers normal count, variance, recount and cancellation.

**Checkpoint 9 gate:** stock correction is never an ad-hoc balance edit.

---

# CHECKPOINT 10 — Ledger and authoritative adjustment closure

- [ ] Validate cursor-based Ledger read.
- [ ] Preserve company/location capability scope.
- [ ] Preserve filters/search/reference semantics.
- [ ] Preserve movement identity, source/destination, status and evidence.
- [ ] Preserve costing/supplier evidence where exposed.
- [ ] Validate Ledger adjustment command and its exact permission.
- [ ] Adjustment must create authoritative movement/evidence; never edit historical movement rows silently.
- [ ] Conflict/idempotency behavior is understandable in UI.
- [ ] Cross-links from Batches/Transfers/Stocktake resolve to relevant evidence where practical.
- [ ] Export is not introduced unless already frozen in V1 scope.

**Checkpoint 10 gate:** Ledger is reliable audit/history, not a mutation shortcut.

---

# CHECKPOINT 11 — Inventory permissions / Backoffice seam

Current Inventory access APIs already manage canonical Backoffice role/grant data while some storage still bridges legacy Driver ids.

- [ ] Keep `/inventory/access/me` and location-capability reads as canonical Inventory UI inputs.
- [ ] Keep owner-only role/grant administration behavior where backend intentionally requires CompanyOwner.
- [ ] Do not broaden owner-only grants without an explicit authorization design decision.
- [ ] Validate roles and permission catalog.
- [ ] Validate company grants.
- [ ] Validate location grants.
- [ ] Validate Warehouse and Vehicle location scope.
- [ ] Validate canonical Backoffice target identity → legacy grant-storage bridge without ID-equality assumptions.
- [ ] Do not add user creation/password/deactivation to this Inventory tab; that belongs to future/next Backoffice Users Administration work.
- [ ] At final Inventory UI redesign, decide whether `Permissions` remains a tab, becomes a link, or moves into Backoffice Administration; do not duplicate the permission system.

**Checkpoint 11 gate:** Inventory consumes canonical permissions correctly and leaves generalized staff lifecycle to the proper module.

---

# CHECKPOINT 12 — Cross-cutting i18n, accessibility, security and performance

This checkpoint is cumulative. Individual waves must improve their touched paths immediately; final gate verifies the whole module.

## 12.1 i18n

- [ ] No new hardcoded user-facing Arabic/English in touched React code.
- [ ] Existing hardcoded strings in active Inventory paths are migrated in bounded batches.
- [ ] Stable namespaces for Inventory shell, Live Stock, Inbound, Batches, Transfers, Stocktake, Ledger, Warehouses and access UI.
- [ ] Backend machine contracts use stable codes/enums, not translated text.
- [ ] UI translates known business error codes.
- [ ] Frontend logic never branches on translated backend message text.
- [ ] Dates use locale-safe formatters.
- [ ] Numbers/currency use existing exact locale-safe formatters.
- [ ] Western digits remain consistent where owner-approved UI convention requires them.

## 12.2 RTL/LTR and accessibility

- [ ] Full RTL and LTR smoke coverage.
- [ ] Keyboard-first navigation for dense workflows.
- [ ] Visible focus.
- [ ] Escape closes modal/sheet where appropriate.
- [ ] Focus enters opened dialogs and returns safely.
- [ ] No status is communicated by color alone.
- [ ] Icon buttons have translated accessible labels/tooltips.
- [ ] Long labels do not break layout.
- [ ] Phone-width layout remains usable; horizontal table scrolling is deliberate, not accidental.

## 12.3 Security

- [ ] Cross-tenant negative tests for major reads/writes.
- [ ] Location-scope negative tests.
- [ ] Capability-denied direct API tests even when UI hides the action.
- [ ] No generic Owner/admin bypass outside canonical subject rules.
- [ ] No sensitive cost/identity data leaks through over-broad responses.
- [ ] Cursor/tamper validation where cursors encode scope.

## 12.4 Performance

- [ ] Hard page bounds everywhere.
- [ ] No N+1 on primary list paths.
- [ ] Search/filter conditions execute before pagination.
- [ ] Query count is stable for page size.
- [ ] Measure p50/p95/p99 on important read paths.
- [ ] EXPLAIN representative search/filter/sort combinations.
- [ ] Add indexes only from measured evidence.
- [ ] Large-company paths do not depend on unbounded in-memory lists.
- [ ] No regression to accepted Product Import performance or shared DB health from Inventory changes.

---

# CHECKPOINT 13 — Final Inventory information architecture and UI polish

**This checkpoint starts only after functional Checkpoints 1–12 are stable.**

The goal is not to repaint the current 8-tab shell. The goal is to make the operational model obvious.

## 13.1 Proposed information hierarchy

Organize concepts mentally into:

**Daily operations**
- Live Stock
- Goods Receipt / Inbound
- Transfers
- Stocktake

**Control / investigation**
- Batches & Expiry
- Ledger

**Setup / administration**
- Warehouses / Branches
- Quality destination policy
- Minimum-stock/policy controls where appropriate
- Permissions link/surface according to Checkpoint 11 decision

- [ ] Validate final IA with owner before large structural refactor.
- [ ] Preserve deep links/navigation state during IA change.
- [ ] Preserve capability-driven visibility.

## 13.2 Shell/top-level UX

- [ ] Match accepted Products/Representatives page-level quality: compact, edge-aligned, no unnecessary nested cards.
- [ ] Clear primary action for the active workflow.
- [ ] Avoid 8 equal-weight tabs if grouping/navigation can reduce cognitive load.
- [ ] Selected warehouse/context always obvious.
- [ ] Active-tab refresh only refreshes that workflow's authoritative data.
- [ ] No duplicate toolbars/action lists.
- [ ] Search belongs visually with the list it controls.
- [ ] Infinite scroll used where it improves operator flow; do not replace keyset backend semantics with unbounded client loading.

## 13.3 Batches final presentation

- [ ] Batch-centric default list.
- [ ] Compact attention counters.
- [ ] Clear expiry severity.
- [ ] Clear sellability explanation.
- [ ] Separate batch disposition vs quantity status.
- [ ] Optional secondary columns/detail drawer or expansion.
- [ ] Cost columns only according to frozen visibility rule.
- [ ] User/company display preferences never change business truth.

## 13.4 Warehouse setup final presentation

- [ ] Warehouse CRUD/lifecycle is understandable without reading backend terminology.
- [ ] Branch management is discoverable but not visually dominant.
- [ ] Quality destinations and policy controls appear as setup, not daily stock actions.
- [ ] Deactivation blockers display actionable references.

## 13.5 Density and consistency

- [ ] Consistent row height, button hierarchy, dropdown behavior and empty states.
- [ ] Western digits.
- [ ] Arabic alignment and English LTR parity.
- [ ] Compact desktop-first operator density without sacrificing phone usability.
- [ ] No mega-component regression; keep page-level feature folders and bounded components.

**Checkpoint 13 gate:** owner accepts the final Inventory/Warehouses UX, not just technical correctness.

---

# CHECKPOINT 14 — End-to-end operational acceptance

Run from a realistic company setup, not isolated component demos.

## 14.1 Warehouse setup journey

- [ ] Create branch with granted non-owner capability.
- [ ] Create warehouse with granted non-owner capability.
- [ ] Edit warehouse/branch.
- [ ] Confirm denied user cannot perform same mutation.
- [ ] Configure required quality destinations.

## 14.2 Product readiness journey

- [ ] Assign product to warehouse.
- [ ] Validate operational inbound/outbound flags.
- [ ] Validate lot/expiry modes from Catalog reach Inbound unchanged.

## 14.3 Inbound journey

- [ ] Receive non-lot product without fake supplier batch.
- [ ] Receive optional-lot product with and without lot.
- [ ] Receive required-lot product.
- [ ] Exercise expiry NONE/OPTIONAL/REQUIRED.
- [ ] Verify costing and Ledger evidence.

## 14.4 Batch/quality journey

- [ ] Batch appears in Batches view.
- [ ] Sellability explanation is correct.
- [ ] Change company-wide disposition where permitted.
- [ ] Change a location-specific quantity stock status where permitted.
- [ ] Execute quarantine/return/disposal flow where configured.
- [ ] Verify Live Stock and Ledger update consistently.

## 14.5 Transfer journey

- [ ] Warehouse → warehouse transfer.
- [ ] Warehouse ↔ vehicle path where V1 supports it.
- [ ] Receive/reject/cancel paths.
- [ ] FEFO/override behavior and permissions.

## 14.6 Stocktake journey

- [ ] Start/count/review/approve.
- [ ] Variance/recount.
- [ ] Cancel.
- [ ] Vehicle recon.
- [ ] Verify resulting movements and Ledger evidence.

## 14.7 Lifecycle blocker journey

- [ ] Attempt warehouse deactivation with stock.
- [ ] With open transfer.
- [ ] With open stocktake.
- [ ] With published destination policy reference.
- [ ] With open Dispatch route source dependency.
- [ ] After clearing blockers, deactivate and verify Live Stock projection behavior.

## 14.8 Device/UX acceptance

- [ ] Arabic RTL desktop.
- [ ] English LTR desktop.
- [ ] Keyboard navigation.
- [ ] Narrow phone width.
- [ ] Refresh/direct navigation state.
- [ ] Offline/error recovery where the workflow already supports local pending/draft behavior.

**Checkpoint 14 gate:** Owner Acceptance PASS with no V1 blocker.

---

# CHECKPOINT 15 — Final production and documentation closure

- [ ] All prior checkpoints have evidence and no unresolved `[!]` V1 blocker.
- [ ] Focused backend tests PASS.
- [ ] Relevant real-PostgreSQL tests PASS where DB behavior matters.
- [ ] Focused frontend tests PASS.
- [ ] `npx tsc --noEmit` PASS.
- [ ] Dashboard build PASS.
- [ ] `git diff --check` PASS.
- [ ] Relevant Alembic head verified if migrations were introduced.
- [ ] No unexplained TODO/FIXME/HACK in touched production paths.
- [ ] Performance/security regressions reviewed.
- [ ] Update `V1_SCOPE_FREEZE.md` only for owner-approved final truth, not progress chatter.
- [ ] Update `RUN.txt` notes only to remove stale contradictions and reflect the completed state; do not turn it into the primary plan.
- [ ] Reconcile or retire narrower Inventory plans only after their open items are demonstrably absorbed/closed here.
- [ ] Do not delete useful historical evidence until the lead confirms it is superseded.
- [ ] Merge final stable PRs.
- [ ] Local `main` fast-forwards to `origin/main` and is clean.
- [ ] Remove temporary worktrees/branches only after verification; no destructive cleanup shortcuts.
- [ ] Declare **Inventory / Warehouses V1 COMPLETE** only after Owner Acceptance.

---

# 16. Known audited blockers at plan creation

These are not speculative and should drive the first implementation waves:

1. [ ] **Inbound lot-control mismatch** — `lot_control_mode` supports NONE/OPTIONAL/REQUIRED but current `InboundBatchItem.batch_number` is unconditional and current inbound rules only apply expiry mode.
2. [ ] **Missing stock-status UI** — backend `/warehouse/inventory/status-change` exists with `inventory.status_change` but no direct Dashboard runtime path was found.
3. [ ] **Branch capability/UI mismatch** — backend has `branch.read/create/update/state`; current Branch Management entry is gated by CompanyOwner in UI.
4. [ ] **Minimum Stock capability/UI mismatch** — backend uses `inventory.minimum_stock.manage`; current Warehouse page exposes the manager only to CompanyOwner.
5. [ ] **Batches primary-read architecture** — current Batches experience still depends on product-first Live Stock-style discovery; final V1 target is a batch-centric warehouse index with explicit sellability reasons.
6. [ ] **Inventory UI i18n debt** — active Warehouse/Branch and other Inventory paths still contain user-facing hardcoded strings.
7. [ ] **Permissions information-architecture debt** — current Inventory permissions surface is really a Backoffice role/grant seam; keep functionality now, decide final placement only after operational Inventory closure.

---

# 17. Old Inbound/Batches plan absorption map

`INBOUND_BATCHES_EXPIRY_PRODUCTION_PLAN.md` remains useful detailed evidence, but execution is now governed by this master plan.

- [ ] Parts A/B → Checkpoint 1 and architecture invariants.
- [ ] Parts C/D → Checkpoint 2 + Checkpoint 13.
- [ ] Part E → Checkpoint 3.
- [ ] Part F → Checkpoint 6 + Checkpoint 13.
- [ ] Parts G/I → Checkpoint 12 + Checkpoint 13.
- [ ] Part H → Checkpoint 12.
- [ ] Part J → Checkpoints 14–15.
- [ ] Original observations 1–33 must be checked during corresponding checkpoints before the old plan is archived/removed.
- [ ] Do not mark this absorption complete merely because the mapping exists; verify each open observation against implementation evidence.

---

# 18. Immediate execution order

1. **Checkpoint 1 — Inbound contract closure.**
2. **Checkpoint 2 — Batch-centric read foundation.**
3. **Checkpoint 3 — Batch actions including missing `inventory.status_change` UI.**
4. **Checkpoint 4 — Warehouses/Branches capability parity.**
5. **Checkpoint 5 — ProductLocation closure.**
6. **Checkpoint 6 — Minimum stock / shelf-life / cost-visibility decisions.**
7. **Checkpoint 7 — Live Stock acceptance.**
8. **Checkpoint 8 — Transfers + quality policy acceptance.**
9. **Checkpoint 9 — Stocktake acceptance.**
10. **Checkpoint 10 — Ledger acceptance.**
11. **Checkpoint 11 — Permissions/Backoffice seam acceptance.**
12. **Checkpoint 12 — Cross-cutting final gate.**
13. **Checkpoint 13 — Full Inventory UI/IA redesign and polish.**
14. **Checkpoint 14 — End-to-end Owner Acceptance.**
15. **Checkpoint 15 — Production/documentation closure and stability point.**

No later checkpoint blocks a safe earlier correction, but dependency order must not be inverted where business truth depends on upstream contracts.