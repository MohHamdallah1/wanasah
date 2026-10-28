# Dispatch V1 — Current Audit Notes / Scale Risks

> Status: **Dispatch V1 scale/UOM repair closure accepted; broader whole-page visual polish remains a later Dispatch pass.**
>
> Purpose: preserve the issues discovered while Inventory V1 is still the active workstream.
> Dispatch / Zones / Shops remains a required V1 surface and will receive a deeper end-to-end audit after Inventory closure.
>
> Current stress evidence: the developer dataset contains about **45,000 imported products**. Opening `/dispatch` exposed severe latency and browser freezing.

## 1. What the user should experience

Dispatch must remain fast regardless of total catalog size.

Opening the page should load only the data needed for the visible dispatch workspace. A company with 500, 50,000, or more products must not make the whole page freeze merely because product names and IDs exist in the catalog.

Product selection for route load / shortages / route adjustments must be **search-driven, bounded, lazy, and backend-authoritative**. The browser must never need the entire company product catalog in the DOM.

## 2. Historical findings before permanent discovery closure (superseded below)

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

**Local development acceptance note (2026-10-24):** after taking a verified database backup, the local `wanasah_local` tenant received a development-only scaffold through the real domain services: published 0% Tax revision 1 plus `COMMERCIAL_ROUNDING` revision 1 for JOD with precision 3 / `HALF_UP`. This exists only to unblock the immediate route-launch test before the Tax/Settings UI is built; it is not a production default and must not be inferred as the company's real tax policy.

### 2.17 Vehicle inventory endpoint could silently create a 45k-key launch payload and fail at schema validation

`GET /dispatch/inventory/{vehicle_id}` first reads the vehicle's positive AVAILABLE balances, but historically it then queried every product allowed by `ROUTE_LOAD_NEW` and returned zero quantities for products not actually loaded on the vehicle.

With the current ~45k-product catalog, selecting an empty vehicle therefore populated `preloadQuantities` with tens of thousands of zero-valued keys. `POST /dispatch/route` accepts at most 5,000 inventory keys, so a route containing one real selected product could still fail before business logic with FastAPI/Pydantic **422 Unprocessable Entity**.

This is a confirmed contract bug, not operator input error. Vehicle inventory reads must be sparse and return only products physically present on the vehicle. Route-launch payloads must also prune zero/non-integer quantities before submit.

The generic `VALIDATION_ERROR` translation currently hides FastAPI field locations; the later Dispatch UX audit must make validation errors identify the exact field rather than saying only “review the entered fields.”

### 2.18 A Dispatch render/chunk failure could destroy the whole dashboard session

The global `DashboardErrorBoundary` previously offered only “return to login”. Clicking it did all of the following even when the failure was only a frontend component/chunk problem:

- called the backend logout endpoint;
- cleared all `localStorage`;
- cleared all `sessionStorage`;
- navigated to `/login`.

That turns a local page-render failure into loss of authentication state and unrelated local drafts/preferences.

The recovery screen must preserve session/local draft state and offer reload/home recovery first. Explicit logout belongs to the normal account/logout flow, not to a generic React error boundary.

## 3. Confirmed items that are NOT the main cause

- Product data is mostly text/IDs, not images or video. Individual records are light, but **45,000 records multiplied across DB objects, JSON, React elements, DOM nodes and input components is not light**.
- The current `/dispatch/init` problem is not a classic one-query-per-product N+1.
- The 400px scroll container is not pagination and not virtualization.

## 4. Historical immediate containment (superseded on 2026-10-28)

The temporary containment applied during the Inventory workstream is intentionally smaller than the final architecture:

1. `/dispatch/init` still preserves its existing response contract, but its product query now projects only `ProductVariant.id` and `ProductVariant.name` instead of materializing full ORM product objects.
2. Launch renders at most **80 search results** at once.
3. Search is deferred and the bounded selector stops collecting after the display window is full.
4. Products with a positive entered load quantity remain visible even when the search text changes.
5. A quantity returned to zero is removed from the new-route client payload state.
6. `RouteManagementModal` and `ShortageModal` are not constructed while closed, removing hidden 45k-product render work.
7. Route creation / inventory / costing / custody backend authority is unchanged.
8. A 50,000-product unit test proves that the visible Launch result window remains bounded.

### Items left open by that historical containment

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

- [x] `/dispatch/init` contract and bootstrap size. Focused discovery closure evidence: section 7.
- [x] Dispatch product search/read model. Focused discovery closure evidence: section 7.
- [x] Source-warehouse-aware product eligibility. Focused discovery closure evidence: section 7.
- [ ] Available/sellable stock visibility. Search eligibility filtering is covered by section 7; wider page acceptance remains open.
- [x] Product picker UX for Launch. Focused discovery closure evidence: section 7.
- [x] Shortage product picker. Focused discovery closure evidence: section 7.
- [x] Route-management product discovery. Focused discovery closure evidence: section 7; existing mutation semantics are preserved.
- [x] Virtualization vs search-only UX decisions. Focused discovery closure evidence: section 7.
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

The normal page-open cost should depend on the small operational working set (zones, active routes, vehicles, warehouses, visible shops), while source-stock product access is bounded and begins with the first page once the Vehicle/Warehouse context exists.

No final `[x]` should be placed on Dispatch performance until that behavior is proven with a large catalog.

## 7. Permanent product discovery and recovery closure — 2026-10-28

The owner revoked the V2 Dispatch transport deferral. This section supersedes the
catalog transport/client search descriptions in sections 2–4; those sections
remain as historical defect evidence. `V1_SCOPE_FREEZE.md` and
`VERSION_2_FUTURE_FEATURES.md` now agree. the former final-repair item 6 is CLOSED after lead review, focused automated gates, owner live `-5/+5` acceptance, and live database verification that Vehicle/Warehouse/load-plan quantities returned exactly to the expected canonical-base state. This does not claim whole-page visual polish acceptance.

Implemented boundary:

- `/dispatch/init` returns zones, canonical representatives, authorized Vehicles
  and Warehouses only. Its schema, query and Dashboard bootstrap own no Products.
- Route Launch, Adjust Load and Route Management discover source Warehouse stock
  through the existing shared `inventory_source_stock.py` authority, preserving
  ProductLocation, ROUTE_LOAD_NEW, batch sellability, free stock and inventory locks.
- Shortages use REPLENISHMENT_NEW, matching the existing mutation, without needing
  Warehouse stock. Discovery never changes stock or creates a business operation.
- `items` / `next_cursor` / `has_more` pages have at most 80 items. HMAC cursors bind
  tenant, purpose/eligibility, actual route/source/vehicle/session and normalized
  search. Immutable ID seeks allow every result to be reached with no deep OFFSET;
  the shared query's OFFSET 0 remains its pre-existing PostgreSQL execution fence.
- Owner-final stock-first UX: a valid Vehicle/source Warehouse context immediately
  reads the first eligible positive-usable-stock page without typing. Blank and
  one-character load searches filter that same shared stock population; Shortages
  retain their separate two-character demand search. Each picker retains one page
  plus explicit current/pending/selected/drafted pins, with Load
  more and Previous results; traversed pages do not accumulate catalog rows.
  Current custody remains visible even at zero source stock. Unselected products
  without usable source stock are absent. Returning to blank search starts at page 1.
- Vehicle/source changes clear stale search, cursor, display and draft state, reload
  custody and ignore aborted/late responses. Active-route read metadata now exposes
  the authoritative source Warehouse so refreshed route context invalidates open
  editors; it never grants authority or changes command payloads. Route Management
  keeps physical custody pins even when target quantities are cleared.
- Normal Adjust Load execution displays progress only. Persisted or ambiguous
  commands require explicit recovery using their original UUID/body. Deterministic
  4xx and successful responses clear the command. Mutation/UOM/legacy FIELD/radar
  contracts and inventory/cost/FEFO authorities were not changed.

Automated evidence (disposable PostgreSQL 16 only, no live DB access):

- `tests.test_dispatch_adjust_load_search`: a fresh **50,000 eligible stocked SKU**
  fixture leaves the entire serialized `/dispatch/init` payload byte-for-byte
  identical to its pre-catalog value. Captured init SQL never reads ProductVariant.
  Initial live inventory projects only the loaded 25 BASE product and its PACK=8
  metadata; search projects at most the page size before UOM work.
- **200 matches → 80 + 80 + 40**, all unique and ordered by immutable ID. The last
  result is adjusted successfully and replay preserves custody. Cursor tampering,
  changed query/source/route/tenant/purpose, denied location and shortage capability,
  ineligible products, held loaded/pending products and HTTP page bounds are covered.
- DIRECT +5 and -5 each create exactly one movement; replay creates none. Existing
  canonical/legacy, decimal, FEFO, handshake terminal plan synchronization and
  Vehicle Load gates remain green (42 PostgreSQL + 24 contract tests total).
- Dashboard: **144 tests / 13 files** pass, including all four cursor pickers,
  blank and filtered 200-result navigation, previous-page/search/zero-stock pinning,
  actual DispatchBoard Warehouse/Vehicle switching with late-response rejection,
  bounded DOM, normal DIRECT
  no-warning behavior, ambiguous same-wire retry and persisted recovery, PACK/PALLET
  formatting and Vehicle Load regressions.
- Focused TypeScript has zero diagnostics; full-app diagnostics remain the existing
  59, with zero additions. Changed-scope lint, production build, Python compile and
  diff whitespace checks pass. The Vehicle Load acceptance workflow includes the
  fresh Dispatch 50k and cursor regressions on every relevant change.

Additional existing authorization/custody source checks: 69/70 pass. The one
failure is the old `test_request_transaction_calls_remain_at_the_existing_boundaries`
guard expecting five `dispatch_route` rollbacks. The exact base already has six;
that function's AST is identical on this branch. No transaction behavior or that
unrelated guard was changed to hide the baseline failure.

Remaining acceptance is lead review plus owner testing of the actual Dispatch
workflow. The supplied route 11 evidence (product 521: Vehicle 25 BASE, Warehouse
5 BASE, target 25 BASE, completed unload/load requests) was not modified or queried.
Unrelated audit items, full-page p50/p95 profiling and remaining Vehicle Load V2
benchmark scope are not declared complete by this focused closure.
