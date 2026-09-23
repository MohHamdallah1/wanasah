# Wanasah — Inventory Inbound → Batches & Expiry Production Plan

> **Status legend**
> - `[ ]` Not started
> - `[~]` In progress
> - `[x]` Completed
> - `[!]` Blocked / requires decision
>
> **Execution rule:** We do not mark any item `[x]` until its implementation, tests/gates, and regression review are complete.
>
> **Architecture rule:** Tenant/company isolation and warehouse isolation are non-negotiable. Every read/filter/candidate stage must remain explicitly scoped before pagination or aggregation.
>
> **UX rule:** Reduce user effort without hiding important inventory facts or weakening safety.
>
> **i18n rule:** Every new UI element must be translation-ready from day one. No user-facing hardcoded Arabic/English strings in React.

---

## 0. Engineering decision and dependency order

- [x] Confirm that the **Inbound / Goods Receipt** workflow is an upstream dependency of Batches & Expiry.
- [x] Confirm that actual batch metadata is stored in `ProductBatch`.
- [x] Confirm that actual warehouse quantities are stored/aggregated from `InventoryBalance`.
- [x] Confirm that batch sellability is centrally governed by `domains/inventory_rules.py`.
- [x] Identify an important current gap: `ProductVariant.lot_control_mode` exists (`NONE / OPTIONAL / REQUIRED`) but the current inbound contract still requires `batch_number` for every inbound line.
- [ ] Finish a production audit and hardening pass for **Inbound / Goods Receipt** before finalizing the new Batches & Expiry UI.
- [ ] Freeze the inbound batch/expiry contract after that audit.
- [ ] Only then build the final Batches & Expiry page on top of the frozen contract.

---

# PART A — Where Batches & Expiry data comes from

## A1. Product tracking configuration (catalog / product definition)

Source of truth: `ProductVariant`

- [ ] Verify and expose `lot_control_mode` consistently:
  - `NONE`
  - `OPTIONAL`
  - `REQUIRED`
- [ ] Verify and expose `expiry_control_mode` consistently:
  - `NONE`
  - `OPTIONAL`
  - `REQUIRED`
- [ ] Ensure product setup UI clearly explains the difference between lot tracking and expiry tracking.
- [ ] Ensure these values cannot drift between catalog API, inbound API, and dashboard contracts.

## A2. Goods receipt / inbound metadata

Source of truth entered during inbound and persisted to `ProductBatch`:

- [ ] `batch_number`
- [ ] `production_date`
- [ ] `expiry_date`
- [ ] Product + company identity
- [ ] Initial batch disposition rules
- [ ] Existing-batch metadata conflict behavior

Required validation:

- [ ] Production date cannot be after expiry date.
- [ ] Production date cannot be in the future when business rules forbid it.
- [ ] Expired inventory cannot be received as AVAILABLE inventory.
- [ ] `expiry_control_mode=REQUIRED` requires expiry date.
- [ ] `expiry_control_mode=NONE` rejects expiry date.
- [ ] `lot_control_mode=REQUIRED` requires batch number.
- [ ] `lot_control_mode=NONE` must not force the user to invent a batch number.
- [ ] Define and implement the exact safe identity strategy for non-lot-tracked inventory without weakening the `ProductBatch` / `InventoryBalance` model.
- [ ] Existing batch with conflicting production/expiry metadata must fail closed.
- [ ] Duplicate product+batch+UOM lines must remain rejected.

## A3. Warehouse quantity source

Source of truth: `InventoryBalance`

- [ ] Keep quantities scoped by `company_id + location_id + product_variant_id + batch_id`.
- [ ] Preserve separation between:
  - AVAILABLE
  - QUARANTINED
  - BLOCKED
  - RECALLED
  - DAMAGED
  - DISPOSAL_PENDING
- [ ] Preserve reservation invariant: non-AVAILABLE balances cannot hold reservations.
- [ ] Keep `on_hand`, `reserved`, `available_for_sale`, and unavailable quantities exact and decimal-safe.

## A4. Expiry and sellability policy

Source of truth:
- `ProductVariant.expiry_control_mode`
- `InventoryStockPolicy.minimum_remaining_shelf_life_days`
- `ProductBatch.production_date`
- `ProductBatch.expiry_date`
- `ProductBatch.disposition`
- company-local date

- [ ] Keep `batch_sellability_predicate` the single SQL authority.
- [ ] Never duplicate expiry/sellability business logic independently in React.
- [ ] Return enough reason metadata to explain **why** a batch is not sellable.
- [ ] Distinguish:
  - actually expired
  - not yet expired but below minimum remaining shelf life
  - globally blocked/quarantined/recalled by batch disposition
  - quantity unavailable because of warehouse stock status
  - future production date
  - inactive batch

## A5. Purchase/cost evidence

- [ ] Keep latest batch purchase cost/date derived from authoritative purchase/cost evidence.
- [ ] Decide whether cost visibility needs a dedicated permission instead of inheriting `inventory.read`.
- [ ] If cost permission is introduced, hide cost both server-side and UI-side when unauthorized.

---

# PART B — Finish Inbound / Goods Receipt first

## B1. Contract correctness

- [ ] Audit `InboundBatchItem` against `lot_control_mode`.
- [ ] Add `lot_control_mode` to backend inbound variant rules.
- [ ] Ensure frontend has the same tracking metadata available without guessing.
- [ ] Make batch-number requirement dynamic based on product tracking mode.
- [ ] Make expiry fields required/optional/hidden based on `expiry_control_mode`.
- [ ] Ensure production date behavior is explicit and consistent.
- [ ] Preserve exact UOM conversion and quantity validation.
- [ ] Preserve costing/idempotency/concurrency behavior.

## B2. Inbound UX

- [ ] Do not show irrelevant batch/expiry fields for products that do not use them.
- [ ] Required fields must be visually clear before submit.
- [ ] Existing-batch conflicts must explain what metadata differs.
- [ ] Repeated receipt lines for the same batch must be easy to understand.
- [ ] Keep document-level defaults only where logically valid.
- [ ] Avoid forcing users to repeatedly enter identical metadata.
- [ ] Make validation errors focus/scroll to the exact failing row.
- [ ] Preserve draft recovery without cross-company/user/warehouse leakage.
- [ ] Keep audit-lock behavior obvious.
- [ ] Review keyboard flow for high-volume receiving.

## B3. Inbound i18n baseline

- [ ] No new hardcoded visible Arabic/English strings in React.
- [ ] All labels, placeholders, tooltips, empty states, confirmations, and errors use i18n keys.
- [ ] Backend error **codes** remain stable and language-independent.
- [ ] UI translates known backend error codes.
- [ ] Do not make frontend logic depend on translated message text.
- [ ] Date controls and displayed dates remain locale-safe.
- [ ] Number and currency formatting use locale-aware formatters.
- [ ] Layout must work in RTL and LTR.
- [ ] Avoid fixed widths that only work for Arabic/English text length.

## B4. Inbound production gates

- [ ] Backend validation tests for all lot-control modes.
- [ ] Backend validation tests for all expiry-control modes.
- [ ] Existing batch metadata conflict test.
- [ ] Cross-tenant batch identity test.
- [ ] Concurrent receipt/idempotency tests.
- [ ] Frontend contract parser tests.
- [ ] Frontend draft recovery tests.
- [ ] Frontend build.
- [ ] Production gate PASS before moving back to Batches & Expiry.

---

# PART C — Batches & Expiry backend foundation

## C1. Keep existing product detail endpoint

Current endpoint remains useful for drill-down:

`GET /warehouse/inventory/{product_variant_id}/batches`

- [ ] Preserve current tenant/location/product isolation.
- [ ] Preserve bounded keyset pagination.
- [ ] Preserve `(expiry_date ASC NULLS LAST, id ASC)` ordering.
- [ ] Preserve existing seek index.
- [ ] Preserve company-local date calculation.
- [ ] Extend response only where required for safe management.

## C2. Add a dedicated warehouse batch-index endpoint

Goal: the page should not use Live Stock product pagination as its primary data source.

- [ ] Create a dedicated batch-centric read endpoint scoped to one warehouse.
- [ ] Only return batches with relevant current warehouse presence by default.
- [ ] Support bounded keyset pagination.
- [ ] No unbounded `.all()`.
- [ ] No N+1.
- [ ] All filters applied in SQL before pagination.
- [ ] Explicit `company_id` + `location_id` predicates at every relevant stage.
- [ ] Search across:
  - product name
  - SKU
  - batch/lot number
- [ ] Multi-token search semantics documented and tested.
- [ ] Search escaping for `%`, `_`, and `\`.
- [ ] Add indexes only from measured query plans, never speculative query golfing.

## C3. Required batch-index filters

- [ ] All batches
- [ ] Expired
- [ ] Expires today
- [ ] Expiring soon
- [ ] Sellable
- [ ] Not sellable
- [ ] RELEASED
- [ ] QUARANTINED
- [ ] BLOCKED
- [ ] RECALLED
- [ ] Has unavailable quantity
- [ ] Has damaged quantity
- [ ] Has disposal-pending quantity
- [ ] No expiry date
- [ ] Product family
- [ ] Optional product filter

## C4. Sorting

- [ ] Expiry soonest first
- [ ] Expiry latest first
- [ ] Product name A→Z
- [ ] Product name Z→A
- [ ] Batch number
- [ ] Largest unavailable quantity
- [ ] Default sort chosen for operational usefulness, not aesthetics.

## C5. Batch-index response fields

- [ ] `batch_id`
- [ ] `batch_number`
- [ ] product id / variant id
- [ ] product name
- [ ] SKU
- [ ] family
- [ ] production date
- [ ] expiry date
- [ ] `days_to_expiry`
- [ ] `expiry_control_mode`
- [ ] `minimum_remaining_shelf_life_days`
- [ ] explicit sellability state
- [ ] explicit sellability reason code
- [ ] batch `disposition`
- [ ] `disposition_reason`
- [ ] `disposition_revision`
- [ ] on-hand quantity
- [ ] reserved quantity
- [ ] available-for-sale quantity
- [ ] unavailable quantity
- [ ] per-status quantities
- [ ] display UOM information
- [ ] currency/cost fields only when authorized
- [ ] latest purchase evidence
- [ ] no presentation-language strings embedded in the contract

## C6. Warehouse summary endpoint / counters

- [ ] Total active batches in warehouse
- [ ] Expired batch count
- [ ] Expiring-soon count
- [ ] Non-sellable count
- [ ] Quarantined count
- [ ] Blocked count
- [ ] Recalled count
- [ ] Damaged/disposal attention count
- [ ] Summary must be measured for cost before deciding projection vs direct aggregation.

---

# PART D — Batches & Expiry page UX redesign

## D1. Default information architecture

- [ ] Default page becomes **batch-centric**, not product-list-first.
- [ ] Product becomes a filter/drill-down, not a mandatory first click.
- [ ] Keep optional "Group by product" view for companies/users who prefer it.
- [ ] Eliminate the large useless empty panel visible when auto-selected product has no batches.
- [ ] Do not auto-select an arbitrary product unless the selected view specifically requires it.

## D2. Toolbar

- [ ] One main search box: product / SKU / batch number.
- [ ] Filter button with active-filter count.
- [ ] Sort control.
- [ ] Product-family filter.
- [ ] Optional product filter.
- [ ] Clear filters action.
- [ ] Warehouse context visible and consistent with Live Stock.
- [ ] Refresh button refreshes **Batches & Expiry data**, not Live Stock only.
- [ ] Last-updated timestamp belongs to this tab's own data.

## D3. Summary/attention area

- [ ] Compact counters above the table.
- [ ] Expired count visually highest priority.
- [ ] Expiring-soon count.
- [ ] Restricted/non-sellable count.
- [ ] Recalled/blocked count.
- [ ] Clicking a counter applies the corresponding filter.

## D4. Table hierarchy

Primary/default columns:

- [ ] Product
- [ ] Batch/Lot
- [ ] Expiry
- [ ] Sellability / attention state
- [ ] Batch-wide disposition
- [ ] On hand
- [ ] Available for sale

Secondary/optional columns:

- [ ] Production date
- [ ] Reserved
- [ ] Unavailable
- [ ] Restriction breakdown
- [ ] Latest purchase cost/date
- [ ] Family
- [ ] SKU

- [ ] Allow configurable column visibility as a UI preference.
- [ ] Do not hide data permanently; secondary detail can live in row expansion/drawer.
- [ ] Sticky header.
- [ ] Responsive behavior for narrower screens.
- [ ] Avoid a mandatory 78rem-wide table for ordinary use.

## D5. Expiry visual hierarchy

- [ ] Expired
- [ ] Expires today
- [ ] Critical window
- [ ] Warning window
- [ ] Healthy
- [ ] No expiry / not applicable
- [ ] Do not hardcode warning windows inside React.
- [ ] Warning thresholds come from company/user display preferences.
- [ ] Sellability cutoff remains a business policy, separate from visual warning thresholds.

## D6. Explainability

For every non-sellable batch, user can understand the cause:

- [ ] Expired.
- [ ] Below required remaining shelf-life.
- [ ] Batch disposition is not RELEASED.
- [ ] Inventory portion is restricted.
- [ ] Future production date.
- [ ] Batch inactive.
- [ ] Multiple reasons can be represented without misleading simplification.

## D7. Loading / errors / pagination

- [ ] Separate loading state from empty state.
- [ ] Separate first-load failure from "no batches".
- [ ] Failed continuation must preserve already-loaded rows.
- [ ] Inline retry for failed next page.
- [ ] Never clear successful pages because page N+1 failed.
- [ ] Prefer infinite/automatic continuation consistent with Live Stock where suitable.
- [ ] Prevent stale responses/race conditions after filter/search/location changes.
- [ ] Abort old requests.
- [ ] Deduplicate rows defensively.
- [ ] Preserve active selection/drawer across harmless refreshes when safe.

---

# PART E — Batch management actions

## E1. Explicitly separate two concepts

**Batch-wide disposition (company-wide batch fact):**
- RELEASED
- QUARANTINED
- BLOCKED
- RECALLED

**Warehouse quantity stock status (location-specific quantity):**
- AVAILABLE
- QUARANTINED
- BLOCKED
- RECALLED
- DAMAGED
- DISPOSAL_PENDING

- [ ] UI terminology makes the difference impossible to miss.
- [ ] Never label both simply as "Status".
- [ ] Confirmation for batch-wide disposition explicitly says it affects the batch across the company, not only the selected warehouse.

## E2. Batch-wide disposition action

Existing backend capability must be surfaced safely:

- [ ] Show only with `batch.disposition` permission.
- [ ] Use `expected_revision`.
- [ ] Require reason.
- [ ] Preserve idempotency.
- [ ] Preserve transition matrix.
- [ ] Preserve audit/domain event.
- [ ] Handle revision conflict with refresh/retry UX.
- [ ] Display last disposition reason where useful.

## E3. Warehouse stock-status action

Existing backend capability:

`/warehouse/inventory/status-change`

- [ ] Show only with `inventory.status_change`.
- [ ] Operates only on selected warehouse/location quantity.
- [ ] Quantity and UOM exactness preserved.
- [ ] Require reason.
- [ ] Explain source and destination status.
- [ ] Refresh current batch row, summary, Live Stock, and ledger after success.

## E4. Drawer / detail panel

- [ ] Batch identity and product.
- [ ] Dates.
- [ ] Sellability explanation.
- [ ] Batch-wide disposition and reason.
- [ ] Warehouse quantity breakdown.
- [ ] Purchase evidence.
- [ ] Allowed actions based on permission.
- [ ] Clear warning before company-wide actions.
- [ ] Link/reference to relevant ledger movements where useful.

---

# PART F — Shelf-life policy management and company customization

## F1. Business policy

`InventoryStockPolicy.minimum_remaining_shelf_life_days`

- [ ] Provide UI to view the effective value.
- [ ] Provide safe management UI with proper permission.
- [ ] Decide company default + warehouse/product override hierarchy.
- [ ] Explicitly show inherited vs overridden values.
- [ ] Preview impact before bulk changes when practical.
- [ ] Do not mix this rule with purely visual alert thresholds.

## F2. Display preferences

Company/user preferences may include:

- [ ] Default Batches view: flat batch list / group by product.
- [ ] Default sort.
- [ ] Visible columns.
- [ ] Expiry warning thresholds.
- [ ] Compact vs comfortable density.
- [ ] Whether cost columns are shown when authorized.
- [ ] Persist preferences per company/user without affecting inventory truth.

---

# PART G — Internationalization (mandatory for every step)

## G1. UI string discipline

- [ ] No user-facing hardcoded strings in new React code.
- [ ] Translation keys grouped under a stable `inventoryBatches` namespace.
- [ ] Enum labels translated by stable codes, never database text.
- [ ] Error UI translates backend error codes.
- [ ] Confirmation dialogs fully translated.
- [ ] Tooltips and aria-labels translated.
- [ ] Empty/loading/retry states translated.
- [ ] Dynamic counts use interpolation/plural-aware patterns.

## G2. Locale-safe rendering

- [ ] Dates rendered through `Intl.DateTimeFormat`.
- [ ] Numbers through `Intl.NumberFormat`.
- [ ] Currency through the existing exact-money formatter.
- [ ] Never parse localized formatted numbers back into business values.
- [ ] UTC/date-only handling remains correct and timezone-safe.
- [ ] RTL and LTR layouts tested.
- [ ] Long German/French-like labels do not break layout.
- [ ] Non-Latin product/batch text works in search/display.

## G3. Backend language independence

- [ ] Stable error codes are the primary machine contract.
- [ ] Frontend does not branch on Arabic/English backend messages.
- [ ] API enums remain language-neutral.
- [ ] Audit data stores facts/codes/reasons, not translated UI labels.

---

# PART H — Performance, security, correctness

## H1. Security / tenant isolation

- [ ] Every batch index query explicitly scopes `company_id`.
- [ ] Every warehouse fact explicitly scopes `location_id`.
- [ ] Permission checks happen before data exposure.
- [ ] RLS remains defense-in-depth.
- [ ] No global candidate list followed by post-tenant filtering.
- [ ] Company-wide batch disposition never leaks cross-company batch existence.

## H2. Performance

- [ ] Keyset pagination only.
- [ ] Hard page bounds.
- [ ] Query count stable.
- [ ] No N+1.
- [ ] No unbounded aggregation on the page path.
- [ ] Measure p50/p95/p99.
- [ ] Inspect EXPLAIN for search/filter/sort combinations.
- [ ] Add indexes only from measured evidence.
- [ ] Permanent performance regression gate.

## H3. Correctness

- [ ] FEFO behavior remains authoritative and unchanged unless explicitly approved.
- [ ] Sellability read path matches movement/allocation authority.
- [ ] Product with `expiry_control_mode=NONE` behaves correctly.
- [ ] OPTIONAL expiry behavior tested.
- [ ] REQUIRED expiry behavior tested.
- [ ] Minimum shelf-life boundary day tested.
- [ ] Expiry-today boundary tested.
- [ ] Company timezone day-boundary tested.
- [ ] Disposition transitions tested.
- [ ] Status-change quantities tested.
- [ ] Concurrent mutation conflicts tested.

---

# PART I — Accessibility and high-volume operator UX

- [ ] Full keyboard navigation for search/filter/table/actions.
- [ ] Visible focus states.
- [ ] Screen-reader labels for icons/buttons.
- [ ] Status is not communicated by color alone.
- [ ] Sufficient contrast for expiry severity.
- [ ] Confirmations state scope and impact in text.
- [ ] Dense workflows minimize mouse travel.
- [ ] Search focuses quickly and supports warehouse operator usage.
- [ ] Optional barcode/GS1 batch lookup considered after core flow is stable.

---

# PART J — Tests and release gate

Backend:
- [ ] Contract tests.
- [ ] Isolation tests.
- [ ] Permission tests.
- [ ] Cursor tamper tests.
- [ ] Filter-before-pagination tests.
- [ ] Search escaping tests.
- [ ] Sellability reason tests.
- [ ] Mutation concurrency/idempotency tests.
- [ ] Performance benchmark/gate.

Frontend:
- [ ] Contract parser tests.
- [ ] Search debounce/race tests.
- [ ] Filter/reset tests.
- [ ] First-load failure state.
- [ ] Continuation failure preserves rows.
- [ ] Drawer state.
- [ ] Permission-based action visibility.
- [ ] i18n key coverage.
- [ ] RTL smoke test.
- [ ] LTR smoke test.
- [ ] Build succeeds.

Final:
- [ ] Production checklist review.
- [ ] No TODO/FIXME/HACK in touched production path unless documented.
- [ ] Clean Git diff.
- [ ] PR review.
- [ ] Merge.
- [ ] Local `main` matches `origin/main`.
- [ ] Relevant Alembic head verified if migrations were added.
- [ ] Batches & Expiry declared **Production Ready** only after all blockers above are `[x]`.

---

# Original 25 observations — coverage map

- [ ] 1. Replace Live Stock product endpoint as primary Batches page source.
- [ ] 2. Make default view batch-centric, product as filter/drill-down.
- [ ] 3. Make shared context/refresh tab-aware.
- [ ] 4. Fix product continuation failure clearing previous results.
- [ ] 5. Add distinct first-load error state.
- [ ] 6. Surface existing batch disposition backend capability.
- [ ] 7. Return `disposition_revision` / reason needed for safe mutation.
- [ ] 8. Separate batch disposition from warehouse stock status terminology.
- [ ] 9. Warn that batch disposition is company-wide.
- [ ] 10. Surface location-specific inventory status-change workflow separately.
- [ ] 11. Add meaningful expiry severity hierarchy.
- [ ] 12. Explain minimum remaining shelf-life impact on sellability.
- [ ] 13. Add UI for managing minimum remaining shelf-life policy.
- [ ] 14. Separate visual alert thresholds from sellability policy.
- [ ] 15. Rework table information hierarchy / optional columns.
- [ ] 16. Eliminate large unused empty-state space; use operational summary.
- [ ] 17. Remove arbitrary auto-selection behavior unless view requires it.
- [ ] 18. Search by batch/lot number.
- [ ] 19. Add operational filters.
- [ ] 20. Preserve proven expiry/id keyset pagination and seek index.
- [ ] 21. Preserve centralized company-timezone sellability authority.
- [ ] 22. Keep existing product-batch endpoint as drill-down; add batch-index above it.
- [ ] 23. Add inline continuation retry and consistent progressive loading.
- [ ] 24. Add configurable view/columns/sort/warning preferences.
- [ ] 25. Revisit cost visibility as a separate permission/policy.

---

# Additional findings added after the original 25

- [ ] 26. Fix the `lot_control_mode` mismatch: model supports NONE/OPTIONAL/REQUIRED but inbound currently requires `batch_number` unconditionally.
- [ ] 27. Freeze the inbound batch identity strategy before redesigning the batch page.
- [ ] 28. Make the entire new flow i18n-first, not Arabic/English-specific.
- [ ] 29. Add explicit sellability reason codes to API contracts instead of reconstructing reasons in React.
- [ ] 30. Add accessibility and keyboard-operation requirements to the production gate.
- [ ] 31. Ensure company/user display preferences remain separate from inventory business truth.
- [ ] 32. Ensure tab refresh timestamps and controls always refer to the active tab's data.
- [ ] 33. Consider barcode/GS1 lot lookup only after the core batch flow is production-stable.

---

## Next concrete step

**Next page to audit and finish: `Tab2Inbound` / Goods Receipt.**

The first audit focus is:

1. `lot_control_mode` end-to-end behavior.
2. `expiry_control_mode` end-to-end behavior.
3. batch identity/metadata creation.
4. inbound UI field visibility/requiredness.
5. i18n readiness.
6. errors, recovery, idempotency, and concurrency.
7. only after that: UX refinement and production gate.

After Inbound is frozen and production-ready, return to this plan at **PART C** and build the final Batches & Expiry experience.
