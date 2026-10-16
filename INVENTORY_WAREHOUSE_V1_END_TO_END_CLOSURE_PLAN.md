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

- [x] Do not build a generalized WMS beyond frozen V1.
- [x] Do not build generalized IAM inside Inventory.
- [x] Do not reintroduce generic `.is_admin` / manager shortcuts.
- [x] Do not merge FieldRepresentative identity with Backoffice identity.
- [x] Do not expose every backend endpoint merely because it exists.
- [x] Do not replace authoritative inventory movement rules with React-side business logic.
- [x] Do not expand into advanced forecasting, replenishment, procurement planning, barcode automation, GS1 lot ingestion, warehouse robotics, or generalized multi-warehouse optimization unless separately promoted.
- [x] Do not redesign Dispatch or Vehicles inside this plan; only preserve Inventory seams they depend on.

---

# 1. Frozen architecture invariants

## 1.1 Inventory truth

- [x] `InventoryBalance` remains the current-stock SSOT.
- [x] Every quantity/status mutation continues through the Unified Inventory Movement authority.
- [x] No UI convenience may directly mutate balances or bypass movement invariants.
- [x] Quantities remain exact decimal-safe values; no float business math.
- [x] Reservation invariants remain enforced, including no reservations in non-AVAILABLE buckets.

## 1.2 Tenant and location isolation

- [x] Every read/write is explicitly scoped by canonical `company_id`.
- [x] Location-sensitive operations use canonical location-capability semantics.
- [x] Filtering/scoping occurs before pagination and aggregation.
- [x] RLS remains defense-in-depth, not the only isolation mechanism.
- [x] Cross-company existence must not leak through 404/403 differences beyond frozen contracts.

## 1.3 Canonical identity and authorization

- [x] Request authority comes from `BackofficeCapabilityAccess` / canonical Backoffice subject.
- [x] `access.company_id` is tenant authority.
- [x] Company Owner authority comes only from canonical owner state.
- [x] Legacy `Driver` may remain only where existing audit/provenance/idempotency storage genuinely requires a legacy actor id.
- [x] No authority decision may depend on principal/profile/Driver numeric ID equality assumptions.
- [x] Read-only endpoints must not load legacy Driver unnecessarily.

## 1.4 Product and lifecycle rules

- [x] Catalog remains authority for product/variant identity, lifecycle and tracking modes.
- [x] Product-location operational flags remain respected for inbound/outbound behavior.
- [x] Product lifecycle guards remain authoritative.
- [x] `lot_control_mode` and `expiry_control_mode` must not drift between Catalog, Inbound, Live Stock and Batches UI.

## 1.5 Time and sellability

- [x] Company-local date remains authoritative for date-only inventory rules.
- [x] `batch_sellability_predicate` remains central SQL authority for sellability.
- [x] React does not independently reconstruct sellability truth.
- [x] Visual warning thresholds are not allowed to change business sellability.

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

- [x] Primary ChatGPT lead assigns exact branch + exact write ownership before each parallel wave.
- [x] Workers do not broaden scope or make architecture decisions independently.
- [x] Every worker starts from an explicitly named main SHA.
- [x] No worker merges to `main`.
- [x] Main integration happens only after independent acceptance at a stability point.

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

- [x] Never have two workers own the same runtime file simultaneously.
- [x] Never mix broad UI redesign with business-rule changes in the same PR unless unavoidable.
- [x] Every wave ends in a clean checkpoint before the next dependency wave.

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
- [x] Record the exact starting SHA for each implementation wave when work begins.

**Checkpoint 0 gate:** no runtime changes; plan becomes the master Inventory/Warehouse V1 closure tracker.

---

# CHECKPOINT 1 — Inbound / Goods Receipt contract closure

This is the first runtime wave. Do not finalize Batches UX before this checkpoint closes.

## 1.1 Lot-control semantics

- [x] Audit `InboundBatchItem.batch_number` against `ProductVariant.lot_control_mode`.
- [x] Add `lot_control_mode` to the authoritative inbound variant rules/contract where required.
- [x] Freeze exact semantics for `NONE / OPTIONAL / REQUIRED`.
- [x] `REQUIRED`: real supplier/internal lot identity is required.
- [x] `OPTIONAL`: real lot may be supplied; absence is accepted safely.
- [x] `NONE`: user must not be forced to invent a lot/batch number.
- [x] Define a safe internal identity strategy for non-lot-tracked receipts while preserving `ProductBatch` / `InventoryBalance` referential integrity and uniqueness.
- [x] Internal identity for `NONE` must not be presented as fake supplier lot data.
- [x] Same product + same real batch must preserve metadata consistency.
- [x] Duplicate product + batch identity + UOM lines remain fail-closed.

## 1.2 Expiry semantics

- [x] Preserve `expiry_control_mode=REQUIRED` → expiry required.
- [x] Preserve `expiry_control_mode=NONE` → expiry rejected/hidden.
- [x] Preserve `OPTIONAL` → missing or valid expiry accepted.
- [x] Production date cannot be after expiry date.
- [x] Production date future rule remains company-local-date aware.
- [x] Expired stock cannot enter AVAILABLE inventory.
- [x] Existing batch metadata conflict remains fail-closed.
- [x] Production-date semantics are explicit for all tracking modes.

## 1.3 Cross-path parity

- [x] Interactive Dashboard receipt and any bulk/integration receipt path enforce the same lot/expiry semantics.
- [x] Product Import tracking defaults/modes cannot create data that Inbound later interprets differently.
- [x] Catalog API, Dashboard Catalog contract, Inbound API and Dashboard Inbound contract use the same stable mode values.

## 1.4 UOM / costing / supplier / lifecycle preservation

- [x] Preserve exact direct UOM conversion requirements.
- [x] Preserve `quantity_scale` / `quantity_step` validation.
- [x] Preserve Supplier requirement and supplier permission checks.
- [x] Preserve ProductLocation inbound flags and product lifecycle guards.
- [x] Preserve MOVING_AVERAGE / FIFO policy behavior.
- [x] Preserve first-receipt costing activation/locking.
- [x] Preserve idempotency and advisory/row lock behavior.
- [x] Preserve audit/domain-event/provenance behavior.

## 1.5 Inbound UI reflection — same checkpoint

- [x] UI receives `lot_control_mode` and `expiry_control_mode` without guessing.
- [x] Batch/Lot field is hidden/optional/required according to product mode.
- [x] Expiry field is hidden/optional/required according to product mode.
- [x] Production date visibility/requirement follows frozen contract.
- [x] Requiredness is visually explicit before submit.
- [x] Irrelevant fields do not consume operator time.
- [x] Existing-batch conflict explains exactly which metadata conflicts.
- [x] Document defaults are offered only where logically valid.
- [x] Repeated metadata entry is minimized without changing truth.
- [x] Validation focuses/scrolls to the exact invalid row.
- [x] Enter/keyboard workflow remains high-volume friendly.
- [x] Draft recovery remains scoped by company + actor + warehouse.

## 1.6 Inbound tests / gate

- [x] Backend tests: lot NONE/OPTIONAL/REQUIRED.
- [x] Backend tests: expiry NONE/OPTIONAL/REQUIRED.
- [x] Existing-batch metadata conflict.
- [x] Cross-tenant identity isolation.
- [x] Concurrent receipt/idempotency.
- [x] UOM exactness regression.
- [x] Supplier permission regression.
- [x] Frontend contract parser tests.
- [x] Frontend draft-recovery tests.
- [x] UI field visibility/requiredness tests.
- [x] RTL/LTR focused acceptance.
- [x] Typecheck/build/diff-check.
- [x] Real runtime receipt acceptance with representative mode combinations.

**Checkpoint 1 gate:** Inbound contract frozen and production-safe before Checkpoint 2.

---

# CHECKPOINT 2 — Batches & Expiry read model and page foundation

## 2.1 Preserve existing drill-down endpoint

- [x] Keep `GET /warehouse/inventory/{product_variant_id}/batches` as product drill-down.
- [x] Preserve company/location/product isolation.
- [x] Preserve bounded keyset pagination.
- [x] Preserve `(expiry_date ASC NULLS LAST, id ASC)` ordering unless a measured contract change is explicitly approved.
- [x] Preserve company-local date calculation.

## 2.2 Batch-centric warehouse index

- [x] Implement/freeze a dedicated warehouse batch-index read path for the main Batches page.
- [x] Do not use Live Stock product pagination as the primary Batches page source.
- [x] Default scope returns batches with relevant current presence in selected warehouse.
- [x] Explicit `company_id` + `location_id` at every candidate stage.
- [x] Keyset pagination only; hard page bounds.
- [x] No unbounded `.all()`.
- [x] No N+1.
- [x] Filters applied in SQL before pagination.
- [x] Search by product name, SKU and real batch/lot identity.
- [x] Search escaping covers `%`, `_`, `\`.
- [x] Multi-token behavior documented/tested.

## 2.3 Required filters and sorting

- [x] All.
- [x] Expired.
- [x] Expires today.
- [x] Expiring soon.
- [x] Sellable.
- [x] Not sellable.
- [x] RELEASED / QUARANTINED / BLOCKED / RECALLED.
- [x] Has unavailable quantity.
- [x] Has DAMAGED quantity.
- [x] Has DISPOSAL_PENDING quantity.
- [x] No expiry/not applicable.
- [x] Product family.
- [x] Optional product filter.
- [x] Sort expiry soonest/latest.
- [x] Sort product A→Z / Z→A.
- [x] Sort batch identity.
- [x] Sort largest unavailable quantity if operationally useful and performant.
- [x] Default sort chosen for operational usefulness.

## 2.4 Response contract / explainability

- [x] Batch identity + product/variant identity.
- [x] Product name, SKU, family.
- [x] Production/expiry dates.
- [x] `days_to_expiry`.
- [x] `lot_control_mode` / `expiry_control_mode` where needed for display.
- [x] Effective `minimum_remaining_shelf_life_days`.
- [x] Explicit sellability boolean/state.
- [x] Stable sellability reason code(s).
- [x] `disposition`, reason and revision.
- [x] On-hand / reserved / available-for-sale / unavailable quantities.
- [x] Per-stock-status quantities.
- [x] Display UOM metadata.
- [x] Cost/latest purchase evidence only according to approved visibility policy.
- [x] No translated presentation strings in API contract.

## 2.5 Summary/attention counters

- [x] Total relevant batches.
- [x] Expired.
- [x] Expiring soon.
- [x] Non-sellable.
- [x] Quarantined.
- [x] Blocked.
- [x] Recalled.
- [x] Damaged/disposal attention.
- [x] Measure aggregation cost before choosing direct query vs projection.

## 2.6 Page data behavior

- [x] Batches page defaults to batch-centric list.
- [x] Product is a filter/drill-down, not mandatory first selection.
- [x] Do not auto-select arbitrary product in default batch-centric mode.
- [x] First-load error is distinct from empty state.
- [x] Continuation failure preserves loaded rows.
- [x] Inline retry for failed continuation.
- [x] Abort stale requests on filter/search/location changes.
- [x] Defensive row de-duplication.
- [x] Automatic continuation/infinite loading where suitable.
- [x] Tab refresh timestamp refers to Batches data, not Live Stock.

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

- [x] UI never labels both concepts with one ambiguous "Status".
- [x] Company-wide scope is explicit before batch disposition mutation.
- [x] Location scope is explicit before stock-status quantity mutation.

## 3.2 Batch-wide disposition

- [x] Surface only when `batch.disposition` allows it.
- [x] Preserve expected revision / optimistic concurrency.
- [x] Require reason.
- [x] Preserve transition matrix.
- [x] Preserve audit/domain event/idempotency.
- [x] Revision conflict offers refresh/retry UX.
- [x] Current/last reason visible where useful.

## 3.3 Warehouse stock-status change — audited missing UI

- [x] Add a direct Dashboard flow for `POST /warehouse/inventory/status-change`.
- [x] Show only with `inventory.status_change` at the selected location.
- [x] Operate on a specific batch/product/location quantity.
- [x] Preserve base-UOM/exact-quantity contract.
- [x] Require reason.
- [x] Clearly show source bucket → destination bucket.
- [x] Do not allow impossible transitions in UI; Backend remains final authority.
- [x] After success refresh affected batch row, Batches summary, Live Stock snapshot and Ledger evidence as appropriate.

## 3.4 Quality / special-transfer actions

- [x] Preserve batch stock-source read contract.
- [x] Preserve reservation evidence and owner linking.
- [x] Preserve `transfer.special.quarantine`.
- [x] Preserve `transfer.special.recall_return`.
- [x] Preserve `transfer.special.return_to_vendor`.
- [x] Preserve `transfer.special.disposal`.
- [x] Preserve terminal disposal confirmation.
- [x] Preserve vendor-return handover confirmation.
- [x] Preserve whole-product quality preview/resolve paths.
- [x] Keep `/warehouse/quality/stage` internal unless a proven operator need requires a direct UI path.
- [x] Never duplicate the same quality command in Catalog and Inventory in conflicting ways.

## 3.5 Detail surface

- [x] Batch identity/product.
- [x] Dates and expiry explanation.
- [x] Sellability reason(s).
- [x] Company-wide disposition/reason.
- [x] Warehouse quantity breakdown.
- [x] Reservations/source evidence.
- [x] Purchase/cost evidence if authorized.
- [x] Allowed actions derived from capabilities.
- [x] Relevant Ledger/Transfer references where useful.

**Checkpoint 3 gate:** every V1 batch mutation has one clear, permission-correct UI route.

---

# CHECKPOINT 4 — Warehouse locations and branches closure

## 4.1 Warehouse lifecycle

- [x] Validate create/update/activate/deactivate contracts against current UI.
- [x] Preserve version checks/idempotency.
- [x] Preserve system-location protection.
- [x] Preserve duplicate/reserved code rules.
- [x] Preserve Live Stock projection rebuild/removal on lifecycle changes.
- [x] Preserve branch-active constraint on warehouse assignment.

## 4.2 Deactivation blockers

UI must present useful operator-facing explanations for backend blockers without weakening them:

- [x] Inventory balance/reservations.
- [x] Open transfer.
- [x] Active inventory lock.
- [x] Open stocktake.
- [x] Published transfer-destination operational policy.
- [x] Open/non-final Dispatch route using the warehouse as source.
- [x] Any additional authoritative blocker found during implementation audit.

## 4.3 Branch capability mismatch — audited blocker

Backend authority:
- `branch.read`
- `branch.create`
- `branch.update`
- `branch.state`

- [x] Remove generic CompanyOwner-only UI gating where capability grants should allow the action.
- [x] Branch manager visibility derives from relevant `branch.*` capability.
- [x] Create/edit/state buttons derive from exact capability.
- [x] Backend remains authoritative even if UI state is stale.
- [x] Non-owner Backoffice acceptance proves granted capabilities work.
- [x] Denied user acceptance proves controls are hidden/disabled safely and API rejects direct calls.

## 4.4 Warehouse list UX functional baseline

- [x] Search remains server-backed and scoped before pagination.
- [x] Cursor behavior remains correct.
- [x] Branch label/state stays consistent after branch mutation.
- [x] Location capability checks are batched where appropriate.
- [x] Do not redesign visual hierarchy yet beyond what is needed for clear functionality.

**Checkpoint 4 gate:** warehouse + branch management is capability-correct for Backoffice, not Owner-only by UI accident.

---

# CHECKPOINT 5 — Product ↔ Location assignment closure

- [x] Validate `product_location.read` and `product_location.manage` UI parity.
- [x] Preserve company/location/product isolation.
- [x] Preserve product lifecycle restrictions.
- [x] Preserve operational flags such as inbound/outbound enablement.
- [x] Preserve reference/deletion blockers and locks.
- [x] Product assignment changes refresh affected Inventory views safely.
- [x] Product page remains the natural product-centric management surface; Inventory may link/focus it but does not duplicate a second conflicting editor.
- [x] Non-owner capability acceptance.

**Checkpoint 5 gate:** ProductLocation truth is consistent between Products and Inventory.

---

# CHECKPOINT 6 — Stock policy, minimum stock and shelf-life policy

## 6.1 Minimum stock capability mismatch — audited blocker

- [x] Use `inventory.minimum_stock.manage`, not CompanyOwner-only UI gating.
- [x] Preserve required `inventory.read` at target location where backend requires it.
- [x] Bulk preview and apply remain the primary high-volume UI path.
- [x] Single-product backend endpoint stays available; add a standalone UI only if it improves an existing workflow rather than duplicating bulk UI.
- [x] Preserve exact UOM conversion.
- [x] Preserve expected/current minimum conflict handling.
- [x] Preserve ProductLocation requirement.
- [x] Preserve target-quantity constraint.
- [x] Preserve projection refresh after policy change.

## 6.2 Shelf-life sellability policy

- [x] Audit current creation/update paths for `minimum_remaining_shelf_life_days`.
- [x] Show effective value where it materially explains non-sellability.
- [x] Decide whether V1 needs operator-editable shelf-life policy for the first company.
- [x] If editable in V1, use a dedicated explicit capability/policy path and audit trail.
- [x] If not required in V1, do not invent a generalized company-default/override center; keep read-only explainability and track richer management for later.
- [x] Never mix business sellability cutoff with visual expiry-warning preference.

## 6.3 Cost visibility decision

- [x] Audit where purchase/cost fields are currently exposed under `inventory.read`.
- [x] Decide whether V1 requires a dedicated cost-visibility capability.
- [x] If introduced, enforce server-side omission/redaction and UI hiding together.
- [x] If not introduced, document the frozen V1 visibility rule explicitly.

**Checkpoint 6 gate:** policy controls are capability-correct and explainable without scope creep.

---

# CHECKPOINT 7 — Live Stock closure

Live Stock is primarily an operational read surface; avoid turning it into a second management center.

- [x] Validate warehouse selection/setup-status behavior.
- [x] Validate `inventory.read` location scoping.
- [x] Validate company-wide vs restricted vehicle-presence semantics.
- [x] Preserve summary, families and cursor read paths.
- [x] Preserve server-side search/filter/order semantics.
- [x] Preserve low-stock indicators from authoritative policy/projection.
- [x] Preserve batch drill-down links.
- [x] Preserve cost display according to Checkpoint 6 decision.
- [x] Preserve warm-session cache scoping by tenant/location/user context.
- [x] No stale cache may leak after company/location/auth change.
- [x] Keep alert-summary endpoint auxiliary unless a proven UI need justifies dedicated rendering.
- [x] First-load / refresh / continuation errors remain distinct and recoverable.
- [x] Performance evidence for normal and large product counts.

**Checkpoint 7 gate:** Live Stock is trusted operational visibility, not a source of mutation truth.

---

# CHECKPOINT 8 — Transfers and quality-destination policy closure

## 8.1 Unified transfers

- [x] Validate source/destination location discovery and capability filtering.
- [x] Validate source inventory cursor/search.
- [x] Validate FEFO authority.
- [x] Validate override options and exact override capabilities.
- [x] Validate dispatch/send.
- [x] Validate receive.
- [x] Validate cancel.
- [x] Validate reject.
- [x] Validate transfer list/detail.
- [x] Preserve warehouse ↔ vehicle behavior where supported.
- [x] Preserve reservations and release semantics.
- [x] Preserve idempotency and lock ordering.
- [x] Preserve product lifecycle and ProductLocation outbound/inbound constraints.

## 8.2 Quality handling destinations

- [x] Validate read/draft/publish of transfer-destination operational policy.
- [x] Use `inventory.transfer_policy.manage` exactly.
- [x] Validate quarantine/disposal/vendor-return destination semantics.
- [x] Warehouse deactivation must remain blocked while referenced by published policy.
- [x] Quality action UI provides configuration path only when destination setup is actually the blocker.

## 8.3 UX acceptance

- [x] Clear source/destination/purpose terminology.
- [x] Clear transfer lifecycle statuses.
- [x] No duplicate action surfaces.
- [x] Partial/failed continuation does not clear good data.
- [x] RTL/LTR + keyboard + phone-width acceptance.

**Checkpoint 8 gate:** Transfers are complete enough for real V1 distribution operations.

---

# CHECKPOINT 9 — Stocktake / reconciliation closure

- [x] Validate active sessions list.
- [x] Validate session context.
- [x] Validate start flow.
- [x] Validate count sheet.
- [x] Validate count submission.
- [x] Validate review.
- [x] Validate approve.
- [x] Validate recount.
- [x] Validate cancel.
- [x] Validate cycle-count batch candidates.
- [x] Validate Vehicle Recon candidates and strict vehicle/location eligibility.
- [x] Preserve independent capabilities: `stocktake.read/start/count/review/approve/recount/cancel`.
- [x] Preserve inventory locks and release semantics.
- [x] Preserve adjustment posting through authoritative movement path.
- [x] Preserve tenant/location isolation before candidate selection.
- [x] Warehouse deactivation remains blocked by non-final stocktake.
- [x] Runtime acceptance covers normal count, variance, recount and cancellation.

**Checkpoint 9 gate:** stock correction is never an ad-hoc balance edit.

---

# CHECKPOINT 10 — Ledger and authoritative adjustment closure

- [x] Validate cursor-based Ledger read.
- [x] Preserve company/location capability scope.
- [x] Preserve filters/search/reference semantics.
- [x] Preserve movement identity, source/destination, status and evidence.
- [x] Preserve costing/supplier evidence where exposed.
- [x] Validate Ledger adjustment command and its exact permission.
- [x] Adjustment must create authoritative movement/evidence; never edit historical movement rows silently.
- [x] Conflict/idempotency behavior is understandable in UI.
- [x] Cross-links from Batches/Transfers/Stocktake resolve to relevant evidence where practical.
- [x] Export is not introduced unless already frozen in V1 scope.

**Checkpoint 10 gate:** Ledger is reliable audit/history, not a mutation shortcut.

---

# CHECKPOINT 11 — Inventory permissions / Backoffice seam

Current Inventory access APIs already manage canonical Backoffice role/grant data while some storage still bridges legacy Driver ids.

- [x] Keep `/inventory/access/me` and location-capability reads as canonical Inventory UI inputs.
- [x] Keep owner-only role/grant administration behavior where backend intentionally requires CompanyOwner.
- [x] Do not broaden owner-only grants without an explicit authorization design decision.
- [x] Validate roles and permission catalog.
- [x] Validate company grants.
- [x] Validate location grants.
- [x] Validate Warehouse and Vehicle location scope.
- [x] Validate canonical Backoffice target identity → legacy grant-storage bridge without ID-equality assumptions.
- [x] Do not add user creation/password/deactivation to this Inventory tab; that belongs to future/next Backoffice Users Administration work.
- [ ] At final Inventory UI redesign, decide whether `Permissions` remains a tab, becomes a link, or moves into Backoffice Administration; do not duplicate the permission system.

**Checkpoint 11 gate:** Inventory consumes canonical permissions correctly and leaves generalized staff lifecycle to the proper module. Runtime/capability implementation is accepted; final product placement remains an Owner decision.

---

# CHECKPOINT 12 — Cross-cutting i18n, accessibility, security and performance

This checkpoint is cumulative. Individual waves must improve their touched paths immediately; final gate verifies the whole module.

## 12.1 i18n

- [x] No new hardcoded user-facing Arabic/English in touched React code.
- [x] Existing hardcoded strings in active Inventory paths are migrated in bounded batches.
- [x] Stable namespaces for Inventory shell, Live Stock, Inbound, Batches, Transfers, Stocktake, Ledger, Warehouses and access UI.
- [x] Backend machine contracts use stable codes/enums, not translated text.
- [x] UI translates known business error codes.
- [x] Frontend logic never branches on translated backend message text.
- [x] Dates use locale-safe formatters.
- [x] Numbers/currency use existing exact locale-safe formatters.
- [x] Western digits remain consistent where owner-approved UI convention requires them.

## 12.2 RTL/LTR and accessibility

- [x] Full RTL and LTR smoke coverage.
- [x] Keyboard-first navigation for dense workflows.
- [x] Visible focus.
- [x] Escape closes modal/sheet where appropriate.
- [x] Focus enters opened dialogs and returns safely.
- [x] No status is communicated by color alone.
- [x] Icon buttons have translated accessible labels/tooltips.
- [x] Long labels do not break layout.
- [x] Phone-width layout remains usable; horizontal table scrolling is deliberate, not accidental.

## 12.3 Security

- [x] Cross-tenant negative tests for major reads/writes.
- [x] Location-scope negative tests.
- [x] Capability-denied direct API tests even when UI hides the action.
- [x] No generic Owner/admin bypass outside canonical subject rules.
- [x] No sensitive cost/identity data leaks through over-broad responses.
- [x] Cursor/tamper validation where cursors encode scope.

## 12.4 Performance

- [x] Hard page bounds everywhere.
- [x] No N+1 on primary list paths.
- [x] Search/filter conditions execute before pagination.
- [x] Query count is stable for page size.
- [x] Measure p50/p95/p99 on important read paths.
- [x] EXPLAIN representative search/filter/sort combinations.
- [x] Add indexes only from measured evidence.
- [x] Large-company paths do not depend on unbounded in-memory lists.
- [x] No regression to accepted Product Import performance or shared DB health from Inventory changes.

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

- [ ] Validate final IA/navigation with owner before any owner-approved large structural refactor.
- [ ] Final Owner UI/UX acceptance.
- [x] Preserve deep links/navigation state during IA change.
- [x] Preserve capability-driven visibility.

## 13.2 Shell/top-level UX

- [x] Match accepted Products/Representatives page-level quality: compact, edge-aligned, no unnecessary nested cards.
- [x] Clear primary action for the active workflow.
- [x] Avoid 8 equal-weight tabs if grouping/navigation can reduce cognitive load.
- [x] Selected warehouse/context always obvious.
- [x] Active-tab refresh only refreshes that workflow's authoritative data.
- [x] No duplicate toolbars/action lists.
- [x] Search belongs visually with the list it controls.
- [x] Infinite scroll used where it improves operator flow; do not replace keyset backend semantics with unbounded client loading.

## 13.3 Batches final presentation

- [x] Batch-centric default list.
- [x] Compact attention counters.
- [x] Clear expiry severity.
- [x] Clear sellability explanation.
- [x] Separate batch disposition vs quantity status.
- [x] Optional secondary columns/detail drawer or expansion.
- [x] Cost columns only according to frozen visibility rule.
- [x] User/company display preferences never change business truth.

## 13.4 Warehouse setup final presentation

- [x] Warehouse CRUD/lifecycle is understandable without reading backend terminology.
- [x] Branch management is discoverable but not visually dominant.
- [x] Quality destinations and policy controls appear as setup, not daily stock actions.
- [x] Deactivation blockers display actionable references.

## 13.5 Density and consistency

- [x] Consistent row height, button hierarchy, dropdown behavior and empty states.
- [x] Western digits.
- [x] Arabic alignment and English LTR parity.
- [x] Compact desktop-first operator density without sacrificing phone usability.
- [x] No mega-component regression; keep page-level feature folders and bounded components.

**Checkpoint 13 technical gate:** implementation and presentation are complete. Final Owner UI/UX and IA/navigation acceptance remains open.

---

# CHECKPOINT 14 — End-to-end operational acceptance

Run from a realistic company setup, not isolated component demos.

## 14.1 Warehouse setup journey

- [x] Create branch with granted non-owner capability.
- [x] Create warehouse with granted non-owner capability.
- [x] Edit warehouse/branch.
- [x] Confirm denied user cannot perform same mutation.
- [x] Configure required quality destinations.

## 14.2 Product readiness journey

- [x] Assign product to warehouse.
- [x] Validate operational inbound/outbound flags.
- [x] Validate lot/expiry modes from Catalog reach Inbound unchanged.

## 14.3 Inbound journey

- [x] Receive non-lot product without fake supplier batch.
- [x] Receive optional-lot product with and without lot.
- [x] Receive required-lot product.
- [x] Exercise expiry NONE/OPTIONAL/REQUIRED.
- [x] Verify costing and Ledger evidence.

## 14.4 Batch/quality journey

- [x] Batch appears in Batches view.
- [x] Sellability explanation is correct.
- [x] Change company-wide disposition where permitted.
- [x] Change a location-specific quantity stock status where permitted.
- [x] Execute quarantine/return/disposal flow where configured.
- [x] Verify Live Stock and Ledger update consistently.

## 14.5 Transfer journey

- [x] Warehouse → warehouse transfer.
- [x] Warehouse ↔ vehicle path where V1 supports it.
- [x] Receive/reject/cancel paths.
- [x] FEFO/override behavior and permissions.

## 14.6 Stocktake journey

- [x] Start/count/review/approve.
- [x] Variance/recount.
- [x] Cancel.
- [x] Vehicle recon.
- [x] Verify resulting movements and Ledger evidence.

## 14.7 Lifecycle blocker journey

- [x] Attempt warehouse deactivation with stock.
- [x] With open transfer.
- [x] With open stocktake.
- [x] With published destination policy reference.
- [x] With open Dispatch route source dependency.
- [x] After clearing blockers, deactivate and verify Live Stock projection behavior.

## 14.8 Device/UX acceptance

- [x] Arabic RTL desktop.
- [x] English LTR desktop.
- [x] Keyboard navigation.
- [x] Narrow phone width.
- [x] Refresh/direct navigation state.
- [x] Offline/error recovery where the workflow already supports local pending/draft behavior.

**Checkpoint 14 technical gate:** 40/40 operational acceptance items PASS with no technical V1 blocker. Final Owner UI/UX and IA/navigation acceptance remains separate and open.

---

# CHECKPOINT 15 — Final production and documentation closure

- [x] All prior technical checkpoint requirements have evidence and no unresolved `[!]` V1 blocker.
- [x] Focused backend tests PASS.
- [x] Relevant real-PostgreSQL tests PASS where DB behavior matters.
- [x] Focused frontend tests PASS.
- [x] `npx tsc --noEmit` PASS.
- [x] Dashboard build PASS.
- [x] `git diff --check` PASS.
- [x] Relevant Alembic head verified if migrations were introduced.
- [x] No unexplained TODO/FIXME/HACK in touched production paths.
- [x] Performance/security regressions reviewed.
- [ ] Update `V1_SCOPE_FREEZE.md` only for owner-approved final truth, not progress chatter.
- [ ] Update `RUN.txt` notes only to remove stale contradictions and reflect the completed state; do not turn it into the primary plan.
- [x] Reconcile or retire narrower Inventory plans only after their open items are demonstrably absorbed/closed here.
- [x] Do not delete useful historical evidence until the lead confirms it is superseded.
- [x] Merge final stable PRs.
- [ ] Local `main` fast-forwards to `origin/main` and is clean.
- [ ] Remove temporary worktrees/branches only after verification; no destructive cleanup shortcuts.
- [ ] Declare **Inventory / Warehouses V1 COMPLETE** only after Owner Acceptance.

**Final CP15 technical evidence:** GitHub Actions run `38974770361` — backend, PostgreSQL 16 + clean Alembic head, Dashboard regression acceptance, `npx tsc --noEmit`, production build, scope/marker audit, `git diff --check`, and the aggregate final technical gate all PASS.

---

# 16. Known audited blockers at plan creation

These are not speculative and should drive the first implementation waves:

1. [x] **Inbound lot-control mismatch** — `lot_control_mode` supports NONE/OPTIONAL/REQUIRED but current `InboundBatchItem.batch_number` is unconditional and current inbound rules only apply expiry mode.
2. [x] **Missing stock-status UI** — backend `/warehouse/inventory/status-change` exists with `inventory.status_change` but no direct Dashboard runtime path was found.
3. [x] **Branch capability/UI mismatch** — backend has `branch.read/create/update/state`; current Branch Management entry is gated by CompanyOwner in UI.
4. [x] **Minimum Stock capability/UI mismatch** — backend uses `inventory.minimum_stock.manage`; current Warehouse page exposes the manager only to CompanyOwner.
5. [x] **Batches primary-read architecture** — current Batches experience still depends on product-first Live Stock-style discovery; final V1 target is a batch-centric warehouse index with explicit sellability reasons.
6. [x] **Inventory UI i18n debt** — active Warehouse/Branch and other Inventory paths still contain user-facing hardcoded strings.
7. [ ] **Permissions information-architecture debt** — current Inventory permissions surface is really a Backoffice role/grant seam; keep functionality now, decide final placement only after operational Inventory closure.

---

# 17. Old Inbound/Batches plan absorption map

`INBOUND_BATCHES_EXPIRY_PRODUCTION_PLAN.md` remains useful detailed evidence, but execution is now governed by this master plan.

- [x] Parts A/B → Checkpoint 1 and architecture invariants.
- [x] Parts C/D → Checkpoint 2 + Checkpoint 13.
- [x] Part E → Checkpoint 3.
- [x] Part F → Checkpoint 6 + Checkpoint 13.
- [x] Parts G/I → Checkpoint 12 + Checkpoint 13.
- [x] Part H → Checkpoint 12.
- [x] Part J → Checkpoints 14–15.
- [x] Original observations 1–33 must be checked during corresponding checkpoints before the old plan is archived/removed.
- [x] Do not mark this absorption complete merely because the mapping exists; verify each open observation against implementation evidence.

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
14. **Checkpoint 14 — End-to-end operational acceptance.**
15. **Checkpoint 15 — Production/documentation technical closure and stability point.**

Final Owner UI/UX and IA/navigation review follows technical/documentation closure before the V1 COMPLETE declaration. Permissions product placement remains part of that Owner decision.

No later checkpoint blocks a safe earlier correction, but dependency order must not be inverted where business truth depends on upstream contracts.