# Dispatch V1 — Current Audit Notes / Scale Risks

> Status: **working audit note, not a closure plan and not acceptance evidence.**
>
> Purpose: preserve the issues discovered while Inventory V1 is still the active workstream.
> Dispatch / Zones / Shops remains a required V1 surface and will receive a deeper end-to-end audit after Inventory closure.
>
> Current stress evidence: the developer dataset contains about **45,000 imported products**. Opening `/dispatch` exposed severe latency and browser freezing.

## 1. What the user should experience

Dispatch must remain fast regardless of total catalog size.

Opening the page should load only the data needed for the visible dispatch workspace. A company with 500, 50,000, or more products must not make the whole page freeze merely because product names and IDs exist in the catalog.

Product selection for route load / shortages / route adjustments must be **search-driven, bounded, lazy, and backend-authoritative**. The browser must never need the entire company product catalog in the DOM.

## 2. Confirmed current scale problems

### 2.1 `GET /dispatch/init` loads the full route-load product catalog

Current backend: `wa_backend/api/dispatch.py::dispatch_init`.

The endpoint loads:

- zones;
- drivers;
- vehicles;
- warehouses;
- **every ProductVariant allowed by `ROUTE_LOAD_NEW`**.

The product query has no product pagination or limit.

It currently selects full `ProductVariant` ORM rows even though the response only uses product ID and name.

Impact with ~45,000 products:

- large database result materialization;
- large Python object allocation;
- large JSON serialization;
- large HTTP response;
- large JSON parse cost in the browser;
- large React state allocation.

This is **not primarily an N+1 query problem**. It is an unbounded bulk-read / over-fetch problem.

### 2.2 Dispatch bootstrap is fetched even when the visible tab does not need products

`dashboard/src/pages/DispatchBoard.tsx` calls `/dispatch/init` when the page mounts.

Therefore the product catalog is loaded before the operator actually needs to search/select any product.

The bootstrap should not own the company catalog.

### 2.3 Full bootstrap can be fetched repeatedly

`fetchInitialData()` re-fetches `/dispatch/init` together with other Dispatch reads.

It can run:

- on initial page entry;
- after multiple mutations;
- after coalesced realtime WebSocket events;
- on a 30-second polling loop for non-owner readers while visible.

With the current contract, each refresh can re-transfer the whole product catalog.

### 2.4 The Launch tab renders the full product list into the DOM

Current Launch UI performs:

`products.filter(...).map(...)`

and renders a table row plus `QuantityInput` for every matching product.

With an empty search, every product matches.

A fixed CSS container height such as `h-[400px]` does **not** virtualize rows. It only hides overflow; all React elements and DOM nodes are still created.

At ~45,000 products this creates a huge DOM/component tree and is a direct cause of the observed page freeze.

### 2.5 The browser currently remembers the expensive Launch tab

Dispatch stores the selected tab under the generic Local Storage key:

`activeTab`

The current developer browser had:

`activeTab = launch`

So opening `/dispatch` immediately enters the most expensive product-rendering path.

The key is also not company/user scoped. This persistence contract should be audited when Dispatch is polished.

### 2.6 Closed modals still construct massive product children

`RouteManagementModal` receives the full `products` array and performs `products.map(...)` for quantity rows.

`ShortageModal` performs `products.map(...)` to create native `<option>` elements.

Both components are rendered by `DispatchBoard` even when their modal is closed. The generic `Modal` component decides whether to portal/display the dialog, but the child JSX has already been constructed by the parent component call.

Result: tens of thousands of product elements can be created even for a hidden dialog.

### 2.7 Native shortage product select is not viable at catalog scale

A native select containing tens of thousands of product options is not an acceptable scalable picker.

It must become bounded search / autocomplete backed by server-side search.

### 2.8 Product search is client-side O(N) for every keystroke

The Launch search lowercases, tokenizes, and scans the full product list on each render / search change.

With 45,000 products this produces repeated O(N) work while typing.

The correct contract is debounced server-side search with a bounded result page.

### 2.9 Quantity changes trigger broad page rerenders

Product quantities live in `DispatchBoard` state.

Changing one quantity updates `preloadQuantities`, causing the large `DispatchBoard` component to rerender.

When the product catalog is present in multiple child surfaces this multiplies the cost.

Dispatch should be split into focused state/read-model owners when the page is audited.

### 2.10 QuantityInput performs document-wide input scans

`dashboard/src/components/ui/quantity-input.tsx` uses:

`document.querySelectorAll('input[inputmode="numeric"]')`

for Enter / Arrow navigation.

With a very large rendered product table this becomes another document-wide scan on keyboard interaction.

This is acceptable only when the rendered row count is bounded; it must not be combined with tens of thousands of mounted quantity inputs.

### 2.11 Product list is not scoped to the selected source warehouse

`/dispatch/init` filters products by the product-level `ROUTE_LOAD_NEW` capability, but the list is not narrowed by:

- selected source warehouse;
- ProductLocation operational flags for that warehouse;
- current sellable / available stock.

The launch backend correctly remains authoritative and can reject a product later, but the current picker can advertise products that cannot actually be loaded from the selected warehouse.

The final Dispatch product-search read model should consider the source warehouse and operational availability contract.

### 2.12 Zero-quantity product keys can remain in route payload state

The route request schema allows up to 5,000 inventory keys.

The frontend stores quantity entries by product ID. A product that was touched and later returned to zero can remain as a key depending on the workflow.

The backend currently builds `target_product_ids` from all keys in `payload.inventory`, not only positive targets.

This can cause unnecessary lifecycle guards / assignment reads / load-plan work for zero targets.

Before final Dispatch acceptance, frontend and backend should normalize route load targets so only intentional product targets are processed, while preserving explicit unload semantics for existing vehicle stock.

### 2.13 Route launch contains per-product database work

Route creation does not show the same unbounded bootstrap issue, but its load mutation loop performs product-specific work including:

- load-plan target updates;
- inventory lock checks;
- source assignment/capability handling;
- batch allocation;
- movement specification creation.

This is linear in the number of loaded product variants and includes awaited database/domain operations inside the product loop.

For a realistic route load this may be fine, but it must be profiled and batched where appropriate. Do not confuse this with the `/dispatch/init` issue: bootstrap is an unbounded bulk-read/render problem; route launch has a separate per-selected-product mutation cost.

### 2.14 DispatchBoard is a very large stateful page

`dashboard/src/pages/DispatchBoard.tsx` owns a large number of unrelated concerns:

- route monitoring;
- route launch;
- zones;
- shops;
- scheduling;
- shortages;
- route adjustments;
- transfer/radar interactions;
- archive/recycle flows;
- realtime refresh;
- product load planning.

This increases rerender blast radius and makes performance regressions easy.

Do **not** rewrite Dispatch from zero. During the full Dispatch V1 pass, split by existing business surfaces/read models while preserving the accepted backend authority.

### 2.15 Route-launch errors are currently masked by a generic frontend message

`useAuthFetch` preserves the backend business reason in `serverMessage` / normalized error data, but `DispatchBoard` historically called its local `getErrorMessage(error)` helper for route launch.

For every non-2xx HTTP response, the visible `Error.message` created by `useAuthFetch` is the generic localized network text (Arabic: `تعذر إكمال الطلب.`). Therefore a precise 409/422 business rejection can be reduced to:

`خطأ في إطلاق خط السير: تعذر إكمال الطلب.`

This is a confirmed UX/debuggability defect. Route launch must use the canonical `apiErrorMessage(...)` path so safe 4xx business messages remain actionable while unknown 5xx errors stay redacted.

### 2.16 Route launch depends on commercial setup that is not yet initialized in the current V1 test tenant

The current tenant has valid pricing publication/assignment data, but the audit found:

- no published Tax rule-set/version;
- no published `COMMERCIAL_ROUNDING` tenant operational policy.

`lock_route_commercial_context()` requires a complete commercial snapshot at route launch. It checks Tax before rounding, so the current first blocker is:

`TAX_CONFIGURATION_REQUIRED`

with the backend rule that even a genuinely non-taxed business must publish an explicit 0% tax component rather than having no Tax configuration.

After Tax is configured, the same tenant would next fail with `COMMERCIAL_ROUNDING_NOT_CONFIGURED` until a rounding policy is published.

This commercial fail-closed behavior is intentional and must not be bypassed just to make Dispatch launch succeed. The UI/setup flow, however, must make the prerequisite obvious before the operator reaches the Launch button.

## 3. Confirmed items that are NOT the main cause

- Product data is mostly text/IDs, not images or video. Individual records are light, but **45,000 records multiplied across DB objects, JSON, React elements, DOM nodes and input components is not light**.
- The current `/dispatch/init` problem is not a classic one-query-per-product N+1.
- The 400px scroll container is not pagination and not virtualization.

## 4. Immediate containment applied before the full Dispatch pass

The temporary containment applied during the Inventory workstream is intentionally smaller than the final architecture:

1. `/dispatch/init` still preserves its existing response contract, but its product query now projects only `ProductVariant.id` and `ProductVariant.name` instead of materializing full ORM product objects.
2. Launch renders at most **80 search results** at once.
3. Search is deferred and the bounded selector stops collecting after the display window is full.
4. Products with a positive entered load quantity remain visible even when the search text changes.
5. A quantity returned to zero is removed from the new-route client payload state.
6. `RouteManagementModal` and `ShortageModal` are not constructed while closed, removing hidden 45k-product render work.
7. Route creation / inventory / costing / custody backend authority is unchanged.
8. A 50,000-product unit test proves that the visible Launch result window remains bounded.

### Still intentionally NOT closed by this containment

The following remain open for the real Dispatch V1 pass:

- the full product catalog is **still transported by `/dispatch/init`**;
- product search is still client-side over the received catalog;
- realtime/full-bootstrap refresh can still re-transfer the catalog;
- Route Management and Shortage product pickers still need scalable search when they are actually opened;
- source-warehouse-aware server-side product search is not implemented yet;
- the generic `activeTab` Local Storage contract is not fixed yet.

The final architecture should remove the catalog from the Dispatch bootstrap and replace it with a bounded Dispatch-specific server-side search/read model. The current containment exists only to make the immediate route-launch acceptance test usable without opening the full Dispatch workstream.

## 5. Full Dispatch V1 audit checklist for later

When Inventory closure is complete and Dispatch becomes the active workstream, audit at least:

- [ ] `/dispatch/init` contract and bootstrap size.
- [ ] Dispatch product search/read model.
- [ ] Source-warehouse-aware product eligibility.
- [ ] Available/sellable stock visibility.
- [ ] Product picker UX for Launch.
- [ ] Shortage product picker.
- [ ] Route-management load editor.
- [ ] Virtualization vs search-only UX decisions.
- [ ] Sparse route load state and zero-target normalization.
- [ ] Route launch SQL/domain query count and batch behavior.
- [ ] Vehicle inventory read size.
- [ ] Realtime event-specific refresh instead of whole-page bootstrap refresh.
- [ ] Non-owner polling behavior.
- [ ] Zones/shops data volume and pagination.
- [ ] Shop table rendering / drag reorder scale.
- [ ] Active routes rendering scale.
- [ ] Modal lazy mounting.
- [ ] `QuantityInput` keyboard navigation scope.
- [ ] Local Storage keys scoped by company/user where required.
- [ ] Route-launch commercial prerequisites (Pricing Assignment/Publication, Tax, rounding policy) are visible and actionable before submit.
- [ ] Dispatch business errors use canonical `apiErrorMessage` and focus/identify the affected setup or product where possible.
- [ ] Permissions/capabilities and organizational scope.
- [ ] Source warehouse / vehicle custody invariants.
- [ ] Route load / unload / adjustment semantics.
- [ ] Audit-lock behavior.
- [ ] Offline/retry/idempotency seams where applicable.
- [ ] Arabic/English i18n consistency and remaining hard-coded operational messages.
- [ ] Accessibility/focus/error-location behavior.
- [ ] Performance acceptance with a large catalog (at least the current ~45k-product dataset).
- [ ] Browser responsiveness while typing, scrolling and changing quantities.
- [ ] Network payload sizes and p50/p95 timings for Dispatch reads.
- [ ] Database EXPLAIN/query-count evidence for bootstrap, product search and route launch.

## 6. Acceptance principle for the later page closure

A large company catalog must not determine the cost of opening Dispatch.

The normal page-open cost should depend on the small operational working set (zones, active routes, vehicles, warehouses, visible shops), while product catalog access is bounded and requested only when the operator searches/selects a product.

No final `[x]` should be placed on Dispatch performance until that behavior is proven with a large catalog.
