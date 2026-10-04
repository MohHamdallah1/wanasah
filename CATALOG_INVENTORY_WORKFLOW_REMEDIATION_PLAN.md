# Catalog / Inventory Workflow Remediation Plan

**Status:** ACTIVE — current execution plan  
**Created:** 2026-10-04  
**Architecture reference:** `docs/architecture/CATALOG_INVENTORY_WORKFLOW_BOUNDARIES.md`  
**Repository baseline before this plan:** `main` at `e780538743c134d0d5a0931b70d4ba7d63b51a30`

## Goal

Restore strict ownership and a simple user flow across Products, Live Stock, Batches & Expiry, Inbound, Transfers, Stocktake, Warehouses, and future Driver/Vehicle capabilities.

The backend strength must remain. The dashboard must expose that strength through clear business decisions without leaking state-machine terminology or forcing users to understand backend mechanics.

## Execution rules

- Every completed item is marked `[x]`.
- Code analysis comes before tests; tests prove the demonstrated fix.
- Do not weaken company isolation, exact-location authorization, RLS, idempotency, audit/outbox, inventory movement authority, pricing authority, or lifecycle invariants.
- One owner per business truth.
- Products may display Inventory warnings but must not mutate Inventory.
- Inventory must not mutate Catalog identity/lifecycle.
- No page-to-page internal UI imports as target architecture.
- No generic `معالجة` instruction without a concrete user action.
- No blocker button may open a page that cannot actually resolve the blocker.
- Do not use Live Stock as an action page; it remains read-only stock truth.
- Preserve Arabic-first + i18n, RTL/LTR, keyboard accessibility, durable commands, and Western digits.
- Use focused branches and merge only at stable checkpoints.

---

# Phase 0 — Freeze, architecture map, and current-state audit

Purpose: stop adding new cross-page behavior until ownership is explicit.

- [x] Confirm Catalog owns product identity and company-wide lifecycle/business availability.
- [x] Confirm Inventory owns physical quantity, batch disposition, reservations, movement, inbound, transfers, stocktake, and custody stock.
- [x] Confirm Products is company-wide and must not require warehouse selection.
- [x] Confirm Inventory mutations are exact-location authorized.
- [x] Define permanent page boundaries in `docs/architecture/CATALOG_INVENTORY_WORKFLOW_BOUNDARIES.md`.
- [x] Decide that user-facing `RECALL / close-recall / RECALL_RETURN` terminology must disappear from the dashboard.
- [x] Decide batch user language: `عزل الدفعة للفحص`, `منع بيع الدفعة`, `استبعاد الدفعة من البيع نهائيًا`, and `السماح ببيع الدفعة من جديد` where allowed.
- [x] Add the architecture companion reference to `ARCHITECTURE.md` so future work cannot miss it.
- [x] Produce a dependency map of current cross-page imports and navigation bridges involving `pages/products`, `pages/inventory`, lifecycle, batch issue navigation, and blockers. Evidence: Phase 0 audit below.
- [x] Record each current violation as either architectural debt or acceptable read-only cross-domain projection. Evidence: classified dependencies, destination matrix, and storage inventory below; shared technical primitives are classified separately.

**Exit gate:** no ambiguous ownership remains for the workflows in this plan.

## Phase 0 audit — evidence frozen at latest main on 2026-10-04

**Audited commit:** `706c5788ae2fa595ba75b3743c4d49f51516f00b` (`origin/main` after fetch). All paths and line numbers below refer to this immutable commit, not subsequent working-tree edits. Paths are repository-relative; `P/` means `dashboard/src/pages/products/`, `I/` means `dashboard/src/pages/inventory/`, and `S/` means `dashboard/src/`.

**Method and limits:** read the constitution, `.rules`, `AGENTS.md`, workflow-protection rule, boundary companion, and this plan before editing. Enumerated all 208 tracked `.ts`/`.tsx` files under Products and Inventory; parsed import/export declarations and literal dynamic imports, resolving aliases and relative paths. There are 194 dependency edges outside each owning page folder, grouped exhaustively below. Same-owner imports are not cross-module edges. Followed lifecycle callbacks, route composition, storage producers/consumers, and actual destination commands. Read backend blocker/stock-source contracts solely to verify authority and record identity; executed no backend code, SQL, tests, workers, or browser workflows. This is source evidence, not runtime/permission acceptance or proof that every existing backend workflow is correct. Only this plan is changed by this audit.

Classification: **1 = correct read-only projection**, **2 = acceptable shared technical primitive**, **3 = boundary/ownership debt**. A correct API projection can coexist with an incorrect import location; those are listed as separate dependencies. None of the findings authorizes changing backend rules.

### A. Direct page-to-page dependency map

| Source -> target (exact source line) | Class | Finding / ownership |
| --- | --- | --- |
| `P/lifecycle/ProductLifecycleManager.tsx:18` -> `I/catalog/CatalogLifecycleActions.tsx` | 3 | Products renders Inventory-internal UI that owns Catalog lifecycle commands, version/preflight checks, durable operations and callbacks. This is the active coupling, not just type reuse. Actions call `/catalog/variants/{id}/{command}` at `I/catalog/CatalogLifecycleActions.tsx:520,552`. Its child import is `CatalogLifecycleSimplePanel` at line 36. Both belong to Catalog. |
| `P/lifecycle/ProductLifecycleManager.tsx:22` -> `I/catalog/contracts.ts` | 3 | Catalog variant parsing/type is owned under Inventory internals. The actual `/catalog/variants/resolve` read at manager line 128 is legitimate Catalog authority; the import boundary is wrong. |
| `P/advanced-uom/AdvancedUomDashboard.tsx:51` -> `I/catalog/contracts.ts` | 3 | Catalog UOM/conversion DTOs, parsing and command builders depend on Inventory's mixed internal contract. Catalog owns this workflow; do not move its mutations to Inventory or a neutral helper. |
| `P/lifecycle/ProductLifecycleManager.tsx:17` -> `I/batches/batchIssueNavigation.ts` | 3 | Products imports an Inventory-internal storage writer to select the batches workflow. The helper currently carries only product/variant identity and a display name, not a batch or location. |
| `I/catalog/CatalogLifecycleSimplePanel.tsx:19` -> `P/status/productCommercialStatus.ts` | 3 | Reverse sibling-page import. The function is presentation-only, not authorization; the root cause is Catalog lifecycle UI living under Inventory. Moving that UI to Products removes the reverse edge without making Product status a neutral business authority. |

These are all **5 direct Products/Inventory import edges** at the audited commit. No other Inventory production file imports Products internals, and no Products file imports Inventory quantity/batch mutation UI directly. Do not describe the reverse mapper import as evidence that active Batches/Live Stock currently mutate Catalog.

**Transitive/misplaced ownership:**

- `I/catalog/contracts.ts:5` imports `I/quantity.ts` for exact decimal parsing/scale-step checks: class **2** for the arithmetic itself, but a Catalog-owned contract must eventually consume it through a small neutral technical module, not an Inventory page path. Do not promote batch sellability, inventory permissions or lifecycle rules with it.
- `I/catalog/contracts.ts:125,134,159,169,177,184,207,260,295,334,338,350,421` mixes Catalog product/variant/UOM/barcode/lifecycle DTOs and builders with `ProductLocationAssignment` / `parseProductLocations` at `311,405,420`. Class **3** for mixed owner placement. A navigation layer must not absorb either owner's DTOs or commands.
- `I/catalog/CatalogLifecyclePanel.tsx:874` composes Catalog lifecycle actions alongside Inventory product-location mutations (`/warehouse/product-locations` at `391,564,595,623`). Class **3** for the mixed business component; assignment reads/mutations themselves remain Inventory-owned. It omits `onOpenBlocker` / `onManageBatchIssue` when rendering the actions. This wrapper uses advanced mode; it is not an additional active simple-mode blocker bridge.
- `I/TabProductCatalog.tsx:12,165,172,182,190,224` contains Catalog create/variant/UOM/barcode mutations and the mixed panel: class **3**, **latent**, not a currently mounted Inventory workflow. `I/MainInventory.tsx:9-16,38-47` imports/renders only Live Stock, Batches, Inbound, Transfers, Ledger, Stocktake, Warehouses and Permissions. `S/App.tsx:195-197` routes Products/Advanced UOM separately; no production consumer mounts `TabProductCatalog`. Preserve this distinction and do not silently re-enable/delete the legacy surface during Phase 1.
- `I/catalogParsers.ts:1-2` is an internal compatibility re-export of Catalog parsing/types: class **3** for owner placement, not a second API or authority. Production Inbound uses `I/catalog/contracts.ts` directly; this shim also has test consumers.

### B. All remaining external import targets (189 edges)

All consumers of each target below receive the stated classification. Counts include repeated imports from different files, not only distinct target modules. Representative source anchors allow inspection; the table is the complete target set outside the two page folders after the 5 sibling edges above. React/router/query/i18next/icon/toast packages are technical dependencies (class 2), not sibling business-module imports.

| Target under `S/` | Edges | Class / representative source |
| --- | ---: | --- |
| `components/dashboard/WorkspaceTopBar` | 2 | 2; `I/InventoryTopDock.tsx:8`, `P/ProductsPageHeader.tsx:8`; workspace presentation. |
| `hooks/useInventoryAccess` | 20 | 2; `I/MainInventory.tsx:1`, `P/ProductsPage.tsx:9`, `P/advanced-uom/AdvancedUomDashboard.tsx:27`; adapter to existing backend permission contract, not Inventory page business UI. Name alone is not a boundary violation. |
| `hooks/useAuthFetch` | 27 | 2; `P/ProductsPage.tsx:8`, `I/MainInventory.tsx:35`; authenticated transport/error/recovery. |
| `hooks/useNetworkStatus` | 10 | 2; `P/ProductsPage.tsx:10`, `I/batches/useBatchDispositionCommand.ts:7`; connectivity only. |
| `hooks/useMediaQuery` | 1 | 2; `P/ProductsPage.tsx:11`. |
| `hooks/useDialogFocusTrap` | 1 | 2; `P/detail/ProductDetailDrawer.tsx:9`. |
| `lib/apiErrors` | 35 | 2; `P/lifecycle/ProductLifecycleManager.tsx:16`, `I/MainInventory.tsx:7`; coded transport errors. |
| `lib/durableOperations` | 22 | 2; `P/productDurableScope.ts:3`, `I/batches/useBatchDispositionCommand.ts:20`; stable request identity/replay, no domain policy. |
| `lib/locale` | 12 | 2; `P/list/ProductTableRow.tsx:5`, `I/MainInventory.tsx:8`. |
| `lib/localeNumbers` | 4 | 2; `P/list/ProductTableRow.tsx:9`. |
| `lib/money` | 2 | 2; `I/Tab1LiveStock.tsx:25`, `I/TabBatches.tsx:17`; formatting, not Pricing authority. |
| `lib/exactMoney` | 2 | 2; `P/create/deriveCreateProductViewState.ts:3`, `P/pricing/usePriceEditState.ts:8`; numeric parsing, not price calculation. |
| `lib/productDisplayPreferences` | 13 | 2; `P/detail/ProductDetailDrawer.tsx:13`, `P/useProductsIdentityScopeReset.ts:10`; harmless display preferences, no cross-page business command. All production consumers are Products-local; prefer owner-local placement if moved, not a new shared domain service. |
| `i18n` | 2 | 2; `I/Tab2Inbound.tsx:15`, `I/transfers/utils.ts:2`. |
| `components/forms/ReasonPresetField` | 2 | 2; `I/batches/BatchDispositionManager.tsx:12`, `I/catalog/CatalogLifecycleSimplePanel.tsx:12`; generic field. Domain preset choices stay owner-local. |
| `components/ui/modal` | 24 | 2; `P/lifecycle/ProductLifecycleManager.tsx:12`, `I/Tab2Inbound.tsx:14`. |
| `components/ui/dialog` | 1 | 2; `I/StockMinimumManager.tsx:14`. |
| `components/ui/popover` | 3 | 2; `P/list/ProductsListToolbar.tsx:14`, `P/shared/ProductPackagingHelp.tsx:12`, `I/Tab1LiveStock.tsx:22`. |
| `components/ui/select` | 1 | 2; `P/create/CreateProductCommerceSection.tsx:12`. |
| `components/ui/command` | 1 | 2; `P/family/ProductFamilyReassignDialog.tsx:24`. |
| `components/ui/dropdown-menu` | 3 | 2; `P/header/ProductsAddMenu.tsx:14`, `P/header/ProductsCatalogToolsMenu.tsx:22`, `P/list/ProductRowActions.tsx:23`. |
| `components/ui/tooltip` | 1 | 2; `P/import/ImportInlineCorrectionRow.tsx:6`. |

### C. Public read projections vs business authority

| Cross-domain contract / workflow | Class | Evidence / boundary |
| --- | --- | --- |
| Products list `batch_restrictions` summary from Inventory | 1 | `P/contracts.ts:146,383,712`; `P/list/ProductStatusBadges.tsx:40-45,83-105`. Counts/disposition/reason are displayed without changing Product lifecycle or batch state. Warning is currently text (`div`/`p`), not a link/button; correct projection, unresolved navigation debt. Do not mark Phase 3 complete. |
| Inbound reads/resolves Catalog variants | 1 for API, 3 for internal DTO placement | `I/Tab2Inbound.tsx:25,139,320`; `I/inbound/contracts.ts:1`. Catalog lookups feed receipt validation, not identity creation. Import owner-public Catalog read DTOs in Phase 1; keep receipt/cost-policy commands Inventory/Costing-owned. POST `/catalog/variants/resolve` is a read, not a Catalog mutation. |
| Inventory Live Stock and Batches use names/UOM/lifecycle/pricing in warehouse read DTOs | 1 | `I/liveStock/contracts.ts`; queries in `I/MainInventory.tsx:678,784`, `I/TabBatches.tsx:174,245`. Data is a documented stock projection; don't move stock quantities or sellability to Products. |
| Batch quantity view reads Product operational hold and authorized warehouse/vehicle sources | 1 | `I/batches/useBatchStockSources.ts:11-42`; `wa_backend/api/warehouse/live_stock.py:2410-2430,2447-2449,2485-2493`: tenant/batch predicates, readable-location filter, `can_send` hint. Company-wide readability is distinct from exact source send permission. |
| Batch disposition and physical special transfers | Inventory owner-local, not a cross-module mutation | `I/batches/BatchDispositionManager.tsx:253-258` renders `BatchQuantityActions`; `useBatchSpecialTransfer.ts:91-118` carries source, batch, purpose and durable request ID. Existing `QUARANTINE`, `RECALL_RETURN`, `RETURN_TO_VENDOR`, `DISPOSAL` actions already exist (`BatchQuantityActions.tsx:49-52,70-119`); backend remains final authority. Do not claim the entire Inventory quality action capability is absent. |

### D. Navigation / blocker resolution matrix

Shared defect for **all 10 archive blocker codes**: `ArchiveBlocker` retains `{code, count, sample_id}` (`I/catalog/contracts.ts:295,326-331`), but both archive and recall-completion buttons forward **only `item.code`** (`CatalogLifecycleSimplePanel.tsx:666,763`). `P/lifecycle/ProductLifecycleManager.tsx:68-105` then opens a broad route/tab, losing variant, sample operation, batch and location identity. There is no owner-action capability/permission check in this callback; destination/backend permission checks still apply. This is class **3** navigation debt, not evidence of a tenant or permission bypass.

Backend archive evidence: `wa_backend/product_lifecycle.py:421-479`. Recall close uses only `INVENTORY_BALANCE`, `OPEN_TRANSFER`, `ACTIVE_ROUTE_LOAD`, `OPEN_CUSTODY`, `OPEN_SHORTAGE` (`wa_backend/api/catalog.py:1556-1573`). Do not conflate these with draft-delete/history blockers or imply a universal archive-cleanup command.

| Blocker / trigger | Current destination | Actual capability and precise debt | Recommended owning surface (proposal only) |
| --- | --- | --- | --- |
| `INVENTORY_BALANCE` | `/inventory`, `live` | **Confirmed read-only dead end.** Includes nonzero on-hand OR reserved quantity; `Tab1LiveStock` exposes stock read/filter/refresh, not reservation release/return/disposal. Hints actually tell user to return quantities/release reservations (`S/i18n/resources.ts:1107,1129`); minimum-stock management cannot resolve physical stock. | Inventory batch/quantity workflow for authorized sources; reservation owner operation must be identified, not inferred from balance alone. |
| `PRODUCT_LOCATION` | `/inventory`, `warehouses` | **Confirmed wrong entity.** `TabWarehouseLocations.tsx:338-343,383-386` creates/updates/activates warehouse masters, not product-location links. Link removal exists in legacy mixed `CatalogLifecyclePanel.tsx:623-626`, but that surface is unmounted. A link can also be non-removable because of stock policy or immutable movement/transfer/stocktake references (`product_lifecycle.py:483-519`); zero stock is not proof it can be deleted. | Inventory-owned Product Location manager; expose guarded action/capability gap and permanent references explicitly. |
| `STOCK_POLICY` | `/inventory`, default `live` | **Confirmed misleading destination.** Label says stock settings (`resources.ts:1119,1131`), callback has no mapping. `StockMinimumManager.tsx:209,252` edits minimums via bulk API, not an explicit active-policy retirement/removal workflow. No demonstrated UI resolution for the counted active policy. | Inventory policy owner; verify a policy disable/removal contract and exact permission before proposing a button. |
| `OPEN_TRANSFER` | `/inventory`, `transfers` | Correct action owner, incomplete context. Transfer list/actions exist, but link loses header `sample_id` and source/destination; selected remembered warehouse may not show the operation. Not a read-only destination. | Inventory Transfers focused on the resolved header and authorized location. |
| `OPEN_STOCKTAKE` | `/inventory`, `stocktake` | Correct action owner, incomplete context. Selected warehouse/session must correspond to blocker `sample_id`; open session completion depends on its current backend state. | Inventory Stocktake focused on the session/location; never fabricate an unlock. |
| `ACTIVE_INVENTORY_LOCK` | `/inventory`, `stocktake` | Conditional destination, **not proven sufficient** for every lock. Evidence counts `inventory_locks` with `released_at IS NULL`, not a guaranteed stocktake session (`product_lifecycle.py:456-458`). Lock ID is not a session ID. | Resolve the lock's creating owner/operation first; link Stocktake only when evidence identifies it. |
| `ACTIVE_ROUTE_LOAD` | `/dispatch` | Correct Dispatch/Fleet owner, incomplete context. Route status commands exist (`DispatchBoard.tsx:825,1428,1450,1477`), but no route/variant focus is passed; do not promise returning/closing a session-bound load through any generic route-status command. | Dispatch load/route workflow resolved from route ID and actual state. |
| `OPEN_CUSTODY` | `/dispatch` | **Wrong demonstrated action destination.** Blocker is a snapshot/work-session reconciliation/settlement condition (`product_lifecycle.py:460-464`). Dispatch route/load management is not the session inventory reconciliation/settlement workflow. Such UI exists in Operations (`S/pages/OperationsDashboard.tsx`, `S/components/operations/CommandCenter.tsx:59-71`), routed at `/` (`S/App.tsx:193`). | Operations custody/session owner, after resolving snapshot ID to session/representative and validating supported action. Vehicle quantity collection remains Inventory-owned; don't treat it as settlement. |
| `OPEN_SHORTAGE` | `/dispatch` | Real owner action exists: shortage listing, group update and deletion (`DispatchBoard.tsx:396,1104,1135,1723`). Link still loses shortage ID/variant and does not open shortages; availability depends on user permissions/current record. | Dispatch shortage workflow, focused record/group; verify decision removes the actual pending blocker. |
| `ACTIVE_OFFER` | `/commercial-rules` | **Confirmed contract mismatch, not merely missing focus.** Blocker counts legacy `offer_rules.is_active` (`product_lifecycle.py:470-472`); destination operates `/offers/definitions` and version DTOs (`S/features/commercialRules/api.ts:129,142,299-304`). It does not expose a legacy `OfferRule.is_active` action. Cancel buttons concern draft/pending versions (`OfferManagement.tsx:31,43`). No proven action clears this particular blocker. | Commercial owner must resolve legacy rule identity/capability; no ID interchange or backend change authorized by this audit. |
| Quality scope: `specific batch` | `/inventory`, `batches`, storage focus | Correct owner **intent**, class 3 bridge implementation. Manager `269-282` sends variant/name only; `TabBatches.tsx:73-77,125-138` searches by name and focuses ID only if present in paginated products for the selected location (`174`). No exact batch/location is carried. A company-wide product may have its affected stock elsewhere. | Explicit typed Inventory navigation hint; owner resolves batch and authorized source(s), including missing/inaccessible targets. |
| Whole-product confirmed issue / recall completion | Catalog `close-recall` attempt, then blocker destinations above | `CatalogLifecycleSimplePanel.tsx:377-390` chooses `close-recall`; it does not directly open a complete company-wide quantity action flow. API guard remains authoritative. On completion error, quantity blocker sends user to Live Stock. Existing batch quantity actions do not fix this missing entry/context. | Catalog decision stays company-wide; Inventory owns accessible quantity handling. Separate later UX/capability phase, not a behavior-changing Phase 1 move. |
| Product batch warning | No navigation | Correct summary projection but no keyboard-actionable owner link (`ProductStatusBadges.tsx:83-105`). `representative_reason.batch_id` is representative reason evidence, not necessarily the only affected batch. | Inventory restricted-batch list/focus using authoritative identity; don't silently choose that representative as the entire incident. |
| Batch quantity `open transfers` | Inventory internal `setActiveTab("transfers")` | Class **2** local navigation, not cross-domain authority (`MainInventory.tsx:1241`). Real transfer owner exists, but this fallback carries no particular transfer ID. | Keep Inventory-local; optional focused intent if a specific transfer exists. |

### E. Storage bridges vs legitimate durable/UI state

| Storage / producers -> consumers | Class | Findings |
| --- | --- | --- |
| `localStorage["inventory_active_tab:<company>"]`: Products blocker callback (`ProductLifecycleManager.tsx:98-101`) and batch helper (`batchIssueNavigation.ts:13-17`) -> Inventory mount (`MainInventory.tsx:245-252`) | 3 when written cross-page; 2 for Inventory's own last-tab preference | Navigation piggybacks on persistent UI preference. It carries no operation/location identity, TTL or consume/acknowledge contract. Inventory reads initial tab on mount; no route-intent/storage-event synchronization guarantees refocus for an already mounted surface. Do not call it an executed backend command: mutations still require explicit user actions and server checks. |
| `sessionStorage["inventory_batch_issue_focus:<company>"]`: batch helper (`18-22`) -> `takeBatchIssueFocus` (`25-53`) -> `TabBatches.tsx:73-77` | 3 | Cross-page workflow hint is a second storage channel (not localStorage). Company-keyed, validates positive safe-integer variant and nonblank name, deletes before parsing. Contains no actor, batch, location or expiry; consumed once, lost on remount/location change or invalid data, cannot be bookmarked/replayed as a route. Preserve current guards while replacing the bridge; do not weaken tenant resolution. |
| Inventory selected location/tab preference (`MainInventory.tsx:203-218,523-552,620-622`) | 2 | Remembered location is a hint validated against fetched locations and location access; retain backend exact-location authority (`267-290`). Company-wide Products decisions must not acquire this location dependency. |
| Products display preferences (`lib/productDisplayPreferences.ts:248-298`), create draft persistence (`P/create/useCreateProductDraftPersistence.ts`), import resume/inline drafts (`P/import/useImportSessionResume.ts`, `useImportInlineCorrection.ts`) | 2 | Owner-local preference/draft/resume persistence; not Products-to-Inventory signaling. Do not remove safe user draft recovery or durable operation evidence to eliminate the navigation bridge. |
| Inventory inbound drafts/reference/notes/request fingerprint (`Tab2Inbound.tsx:71-114,345-349`); stocktake draft/session/phase keys (`stocktake/hooks/useStocktakeLifecycle.ts:180,317-321`, `useStocktakeCounting.ts:115-175`) | 2 | Inventory-owned continuity/retry state, not Catalog commands. Durable request identity is intentionally preserved across lost responses; never replace it with a fresh ID during an ownership refactor. |
| `company_id` / `driver_id` / auth storage used by transport, permission-query keys and pages; Inventory in-memory warm snapshots | 2 for existing technical scoping hints | Not workflow bridges and not permission authority. `useInventoryAccess.ts:89-116` fetches backend permissions with tenant/actor/location query scope. Do not equate an arbitrary storage value with authorization or label all localStorage as forbidden. This audit does not certify broader auth-storage security. |

### F. Recommended Phase 1 file moves / ownership splits (not implemented)

1. Move `I/catalog/CatalogLifecycleActions.tsx` and `CatalogLifecycleSimplePanel.tsx` to `P/lifecycle/`, with their lifecycle command/recovery/preset types and focused tests. Keep `ProductLifecycleManager`, `productCommercialStatus`, lifecycle/hold presentation Catalog-owned. Preserve all endpoint paths, `expected_version`, preflight freshness, durable scopes/request IDs, response ordering/AbortController guards, invalidation and permissions. Do not extract a shared lifecycle business service.
2. Split `I/catalog/contracts.ts`: Catalog DTOs/parsers/builders (`CatalogVariant`, Catalog/UOM/barcode/conversion, lifecycle/preflight) belong in a **Catalog-owned public contract**, e.g. `S/features/catalog/contracts.ts`, so Inbound can import a stable read contract without importing Products page internals. Prefer separate read DTO and owner-local command/preflight files over exposing every mutation builder publicly. Products list/import/tracking/simple-pricing contracts remain Products-owned, not navigation contracts.
3. Extract `ProductLocationAssignment` / `parseProductLocations` and Inventory assignment workflow from mixed `CatalogLifecyclePanel.tsx` into `I/product-locations/` contracts/component/workflow. Keep flags, deletion blockers, exact-location permission and durable recovery with Inventory. Move only Catalog portions of the legacy wrapper to Products; do not move the whole panel into Products, as that would move physical operational configuration across the boundary.
4. Treat `TabProductCatalog.tsx` and `catalogParsers.ts` as legacy ownership migration candidates: relocate Catalog-specific pieces to a Products-owned advanced-catalog slice / explicit Catalog contract compatibility facade after all consumers are verified. They are unmounted legacy code, not permission to create another catalog screen, delete files or reactivate old commands. Adapt source-reading/mock tests along with future moves; many explicitly name `pages/inventory/catalog` (e.g. `S/test/products-enter-recall-ux.test.ts:34`, `products-functional-acceptance-p9.test.ts:223`, `inventory-access.test.ts:4-5`). No tests are changed in Phase 0.
5. Replace `I/batches/batchIssueNavigation.ts` cross-page writer with a **small neutral route-intent contract**, e.g. `S/lib/navigation/inventoryIntent.ts`: surface + positive IDs (`variant_id`, optional `batch_id`/`location_id`/owner operation ID) as hints only. No disposition change, lifecycle transition, permissions, command payload, durable operation ID or business policy belongs in this layer. Inventory owns parsing/resolution/authorization and missing/inaccessible-target behavior; Catalog owns mapping its blocker DTO to an owner-navigation request. Keep harmless Inventory preferences separate. Removing the storage bridge changes navigation behavior and requires its own focused parity gate, not a silent file move.
6. If Catalog parsing needs exact quantities after separation, extract only reusable arithmetic from `I/quantity.ts` to `S/lib/exactQuantity.ts` (retain compatibility until all consumers are migrated). Keep batch transition mapping, physical action selection, stock statuses, policy and backend validation Inventory-local. Generic reason field/modal/transport/durable/i18n primitives already have acceptable homes; no broad shared-business folder is needed.

**Completion interpretation:** only the two Phase 0 evidence tasks above are newly checked. Phase 1-8 and all defect-fix boxes remain open. Ownership is assigned; resolution capabilities for stock policy, legacy offers, permanent product-location references, lock provenance and reservation/custody operations must be verified in their owning modules before actionable links can be promised. Runtime, multi-warehouse, permission-limited, RTL/keyboard and durable retry acceptance remain future gates, not completed audit evidence.

---

# Phase 1 — Fix frontend ownership without changing business behavior

Purpose: remove the accidental coupling before changing UX behavior.

## 1.1 Product lifecycle ownership

- [x] Move Product/Catalog lifecycle UI out of `pages/inventory/catalog` into Product/Catalog-owned frontend structure. Canonical implementation now lives under `dashboard/src/features/catalog/`; old paths are compatibility re-exports only.
- [x] `ProductsPage` / Products-owned code no longer imports Inventory page business-action components; an architecture gate prevents direct `pages/products` ? `pages/inventory` imports.
- [x] Keep backend catalog endpoints and mutation semantics unchanged; this phase is frontend ownership/navigation only.
- [x] Preserve current permissions, durable request IDs, and mutation semantics during the move; focused lifecycle/catalog/inventory regressions remain green.

## 1.2 Shared code rules

- [x] Extract only genuine technical primitives: exact quantity arithmetic to `lib/quantity.ts` and typed Inventory route intent to `features/inventory/navigation.ts`.
- [x] No generic shared-business folder was introduced; Catalog and Inventory retain explicit owners.
- [x] Product-specific Products-page contracts remain Products-owned; Catalog public contracts are isolated under `features/catalog`.
- [x] Inventory batch/quantity DTOs remain Inventory-owned; `ProductLocation` parsing/mutation validation was split into `features/inventory/productLocations`.

## 1.3 Navigation contract

- [x] Replace cross-module localStorage/sessionStorage workflow signaling with a versioned typed React Router navigation intent.
- [x] Navigation contract carries only typed surface/identity/location hints; no permission, mutation payload, business transition, or durable command is transported.
- [x] Inventory consumes the hint and still resolves data through its existing location-scoped APIs/access checks; navigation state is never authorization.
- [x] Inventory localStorage remains only for harmless last-tab/last-location UI preferences; the batch workflow bridge no longer uses storage.

**Exit gate:** no Products business component imports Inventory internal business UI, and vice versa.

**Phase 1 implementation evidence (2026-10-04):**
- Canonical Catalog lifecycle/contracts/status live under `dashboard/src/features/catalog/`; `pages/inventory/catalog/*` compatibility files no longer own those implementations.
- `ProductLocationAssignment` and its mutation/parser contract are Inventory-owned under `dashboard/src/features/inventory/productLocations/`; the legacy mixed lifecycle panel is now composition-only.
- Direct Products <-> Inventory page-internal imports are blocked by `catalog-inventory-boundary.test.ts`.
- Product -> Inventory workflow navigation uses typed route state; `inventory_batch_issue_focus` storage signaling was removed.
- Focused gate at this checkpoint: TypeScript PASS, ESLint PASS, 6 test files / 73 tests PASS, production build PASS (2786 modules).

**Residual legacy debt - quarantined, not mounted:**
- [x] Verify `pages/inventory/TabProductCatalog.tsx` is not mounted by the active Inventory shell and preserve it as legacy/test-only code during this behavior-preserving phase.
- Legacy cleanup for `TabProductCatalog.tsx` is tracked only in **Phase 8** together with duplicate/dead UI cleanup; it is not a separate open task here.


---

# Phase 2 — Replace backend terminology with business language

Purpose: user decisions must be understandable without knowing backend state machines.

## 2.1 Whole-product issue

- [x] Keep entry action `مشكلة جودة أو سلامة`.
- [x] Keep scope question `أين توجد المشكلة؟` → `دفعة محددة` / `المنتج بالكامل`.
- [x] Replace user-facing recall/withdrawal terminology in the active Product, Batch, quantity-action, and Live Stock surfaces while preserving canonical backend codes and command names.
- [x] False alarm action remains `تبين أن المنتج سليم`.
- [x] Confirmed issue action becomes `المشكلة مؤكدة — التعامل مع الكميات الحالية`.
- [x] After blockers are resolved, `close-recall` is presented as `السماح ببيع المنتج من جديد`; once the hold is cleared, the existing `التوقف عن استخدام المنتج` lifecycle choice remains available according to the backend state.

## 2.2 Batch issue

- [x] `QUARANTINED` user action/label: `عزل الدفعة للفحص`.
- [x] `BLOCKED` user action/label: `منع بيع الدفعة`, with explicit consequence text.
- [x] `RECALLED` user action/label: `استبعاد الدفعة من البيع نهائيًا`.
- [x] Explain that final batch exclusion concerns whether it can ever be sold again; physical quantities are handled separately by Inventory actions.
- [x] Keep canonical backend codes unchanged (`RECALL`, `RECALLED`, `RECALL_RETURN` remain internal contracts only).

## 2.3 Reason UX

- [x] Keep preset reason lists + `سبب آخر` for Product lifecycle actions where useful.
- [x] Keep preset reason lists + `سبب آخر` for batch disposition actions.
- [x] Use the actual saved human reason in warnings/details (`disposition_reason` and Products `representative_reason`).
- [x] Avoid vague fallback text when authoritative reason/status exists; active batch/product warnings prefer saved reason + business-language disposition labels.

**Exit gate:** a normal warehouse/product manager can understand every action without knowledge of backend terms.

**Phase 2 implementation evidence (2026-10-04):**
- Product quality/safety entry and scope remain business-first; the technical `recall` command is not exposed as user language.
- Whole-product recovery now says `تبين أن المنتج سليم` / `السماح ببيع المنتج من جديد`; batch actions say `عزل الدفعة للفحص`, `منع بيع الدفعة`, and `استبعاد الدفعة من البيع نهائيًا`.
- `RECALL_RETURN` remains the backend purpose while the UI says `إرجاع الكمية للتعامل معها`. Live Stock uses the same exclusion language.
- Product and batch reason presets still support `سبب آخر`, and saved disposition reasons are shown in Batch details and Products restriction warnings.
- Focused language/lifecycle gate: 4 test files / 37 tests PASS; TypeScript PASS; ESLint PASS; production build PASS (2786 modules).


---

# Phase 3 — Products page: catalog decisions and read-only operational warnings

Purpose: Products controls the catalog and only points to Inventory when physical action is needed.

- [x] Product lifecycle actions stay company-wide and warehouse-independent.
- [x] Products shows batch warning summaries without changing batch state.
- [x] Warning such as `المنتج نشط، لكن 1 دفعة غير متاحة للبيع` is clickable/keyboard accessible.
- [x] Clicking the warning deep-links directly to the affected batch workflow, not generic Inventory home and not Live Stock.
- [x] Preserve product status as `متاح للبيع` when the product is active even if one batch is restricted.
- [x] Never infer product stoppage from zero stock or one restricted batch.
- [x] `دفعة محددة` from quality issue scope navigates to Batches & Expiry only.
- [x] `المنتج بالكامل` applies only the Product/Catalog company-wide hold.
- [x] Product blockers are displayed as summaries from the owning domain; Products does not perform inventory mutations.

**Phase 3 evidence:** Products warnings now use a typed route-state contract carrying the authoritative variant and representative batch id. Inventory revalidates the batch through the read-only `stock-sources` endpoint, selects a readable warehouse when required, paginates until the exact batch is found, opens its Inventory-owned manager, and consumes the navigation intent after use. Products performs no physical-stock or batch mutation. Focused gate: 44 tests PASS; TypeScript PASS; ESLint PASS; production build PASS; post-consumption regression gate 35 tests PASS.

**Exit gate:** Products can add/edit/stop/resume/archive product identity and show operational warnings, but cannot mutate physical stock or batch state.

---

# Phase 4 — Inventory-owned quality action flow

Purpose: when physical quantities require action, Inventory provides the complete action in the correct place.

## 4.1 Batch-specific issue

- [x] Batches & Expiry opens directly on the affected product/batch from a navigation intent.
- [x] Show batch state, saved reason, expiry evidence, and affected quantities.
- [x] Show quantity by exact warehouse/location and vehicle/custody source when supported.
- [x] Offer only backend-valid actions for the current quantity/state/permission. `stock-sources` now returns backend-derived `allowed_purposes` using current lifecycle/hold/batch/source/expiry-policy state, exact source send permission, published server-derived destination policy, purpose permission and destination permission; mutation endpoints still re-check under locks before writing.
- [x] Supported physical actions include quarantine, affected-quantity transfer, supplier-return staging, disposal staging, and warehouse/vehicle source collection through Inventory-owned special transfers. Terminal supplier handoff/destruction are not falsely claimed; those remain separate capability boundaries.
- [x] Reserved quantity must show the exact blocker and the owning operation when available; do not say only `عالج الحجز`.

**4.1 checkpoint evidence:** exact-batch navigation now opens from the permission-filtered known-batch `stock-sources` contract itself rather than requiring the batch to exist in the currently selected warehouse. The contract carries authoritative batch number, disposition/revision/reason, production/expiry dates, company-local days-to-expiry and base UOM code, so vehicle-only batches can open the same Inventory-owned manager without fabricating warehouse state. The manager shows current batch decision context and company-readable source quantities; supplier-return/disposal actions are explicitly described as staging, not terminal handoff/destruction. A newly created special-transfer operation now retains its authoritative `header_id`/reference; Inventory checks `transfer.read` on only the operation's related readable warehouse endpoints, then opens that exact transfer detail and filters the list to its reference instead of dropping the user into a generic list. No workflow state is persisted through browser storage. Reservation evidence now comes from the authoritative balance snapshot: proven readable Dispatch HANDSHAKE owners are shown with exact reserved quantity/reference and any unexplained remainder stays explicit as PARTIAL/UNRESOLVED rather than guessed. Inventory never cancels these reservations itself; typed navigation opens the exact Dispatch route/transfer, highlights it, and opens Dispatch's existing force-cancel flow only when the backend action hint permits it. Focused gates: batch-source checkpoint 15 frontend tests + 2 backend contract tests PASS; exact-transfer follow-up checkpoint 39 frontend tests PASS; reservation-owner integration 52 frontend tests PASS + 28 backend tests PASS; TypeScript, ESLint, Python compile, diff check and production Vite build PASS. Unsupported/unreadable reservation evidence, complete custody-person identity and terminal vendor-handoff/destruction remain explicit limits.

## 4.2 Whole-product confirmed issue

- [x] `المشكلة مؤكدة — التعامل مع الكميات الحالية` opens an Inventory-owned workflow.
- [x] Inventory lists affected accessible locations separately.
- [x] Never silently combine independent warehouses into one unauthorized mutation.
- [x] For each location/source show quantity, reservation, status, and concrete allowed next actions.
- [x] Company-wide product restriction remains active while physical operations are open.
- [x] Completion/readiness is computed by backend evidence, not UI guessing.

**4.2 implementation evidence (2026-10-04):** the confirmed whole-product path now applies only the company-wide Catalog hold, then opens a typed `quality-issue` navigation intent into an Inventory-owned workflow. Inventory reads a bounded variant-first page of affected batches and permission-filtered WAREHOUSE/VEHICLE sources, including RELEASED batches affected only by the product hold. Each source remains a separate action; the UI never batches independent warehouses into one mutation and all special-transfer commands continue to re-check source permission, destination policy, quantity and state in the backend. Existing reservation-owner evidence is reused without N+1 reads. A shared `recall_completion_blockers` backend authority now drives both the close command and read-only readiness, so `السماح ببيع المنتج من جديد` is offered only when backend evidence is clear; Inventory never clears the product hold. Hidden/inaccessible company evidence can keep readiness blocked without leaking its details. Focused gates recorded with this checkpoint cover the variant-first endpoint, permission filtering, pagination, typed navigation and frontend contract; final gate is recorded below before merge.

## 4.3 Read-only Live Stock boundary

- [ ] Remove blocker actions that send the user to Live Stock expecting them to fix stock there.
- [ ] Live Stock may show a `فتح الإجراء` link to Batches/Transfers/etc., but remains read-only.

**Exit gate:** any message that says stock action is required provides an actual executable action or an exact link to the action owner.

---

## Phase 4 audit evidence — 2026-10-04

> Historical pre-implementation audit. Completed checklist items and checkpoint evidence above supersede PARTIAL/GAP rows below where a newer implementation checkpoint is recorded.

Source baseline: latest fetched `main`, `fc77123783eab0cbec1742a36dbf3440e0c0d317`. Source-only audit/design; no tests, SQL, migrations or workflow commands executed. `READY` means the cited capability exists; `PARTIAL` means it has the stated coverage/connection gap; `GAP` means the required connection/contract is absent from the inspected path. These are not runtime acceptance results; existing checklist boxes remain unchanged.

### Checklist coverage

Rows correspond, in order, to every checkbox in 4.1–4.3.

| Item | Status | Evidence and remaining scope |
| --- | --- | --- |
| 4.1.1 Exact product/batch navigation | PARTIAL | `dashboard/src/pages/inventory/TabBatches.tsx:111–144,351–379` revalidates batch/variant, selects a readable warehouse, traverses batch pages and opens the manager. Discovery selects WAREHOUSE sources only; vehicle-only stock cannot be opened through this warehouse-dependent path. Preserve the completed Phase 3 typed route contract. |
| 4.1.2 State, saved reason, expiry, quantities | READY | `wa_backend/api/warehouse/live_stock.py:2315–2385` returns disposition/revision/reason, expiry date/days and on-hand/reserved/restricted/status quantities; `dashboard/src/pages/inventory/TabBatches.tsx:625–675` renders expiry and the restricted batch's saved reason. This is selected-warehouse coverage, not all company stock. |
| 4.1.3 Warehouse/vehicle/custody sources | PARTIAL | `wa_backend/api/warehouse/live_stock.py:2409–2559` groups stock sources by location/status, including VEHICLE, but excludes inactive locations, transit/scrap types and non-positive on-hand. No custody-session/person identity. UI consumes this in `dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx:208–266`. |
| 4.1.4 Only valid state/permission actions | PARTIAL | `dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx:49–121,208–275` filters purposes but uses the selected warehouse's aggregate restricted quantity as a metadata hint for other sources. `can_send` is not complete destination/policy/lock eligibility. Backend remains decisive (`wa_backend/api/warehouse/transfers.py:1459–1515`; `wa_backend/services.py:1842–2011`). |
| 4.1.5 Supported physical actions | PARTIAL | Special dispatch supports QUARANTINE, RECALL_RETURN, RETURN_TO_VENDOR and DISPOSAL; receipt/cancel/reject exist (`wa_backend/api/warehouse/transfers.py:1436–1643,2517,2642,2759`). Vehicle sources work, but this is not complete custody collection or final vendor handoff/destruction. Receipt leaves disposal pending (`wa_backend/services.py:2506–2531`). |
| 4.1.6 Exact reservation owner | GAP | Stock sources return reserved/movable amounts, not owner references (`wa_backend/api/warehouse/live_stock.py:2526–2540`; `dashboard/src/pages/inventory/batches/BatchQuantityActions.tsx:249–264`). HANDSHAKE evidence and cancellation already exist in Dispatch; missing reverse lookup/navigation does not justify another release command. |
| 4.2.1 Confirmed whole-product issue opens Inventory | GAP | Recall action still chooses `close-recall`, not an Inventory quantity workflow (`dashboard/src/features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx:377–390`). Batch issue callback separately creates Inventory focus (`dashboard/src/pages/products/lifecycle/ProductLifecycleManager.tsx:267–276`). |
| 4.2.2 Affected accessible locations separately | PARTIAL | Known-batch sources separate locations, but lack comprehensive variant-first discovery. Batch listing requires one active WAREHOUSE (`wa_backend/api/warehouse/live_stock.py:1775–1845`); source exclusions at `2485–2493` prevent treating that read as recall-completion coverage. |
| 4.2.3 No combined unauthorized warehouse mutation | READY | Special dispatch takes one source, checks source `transfer.send`, resolves published destination policy and checks destination permission before creating one transfer (`wa_backend/api/warehouse/transfers.py:1459–1532`). Preserve separate commands/operation IDs per source. |
| 4.2.4 Source quantity/reservation/status/actions | PARTIAL | Known-batch read/action path exists, but lacks reservation-owner links, complete source-specific eligibility and whole-product discovery (4.1.3–4.1.6, 4.2.2). Quantity alone proves neither permission nor readiness. |
| 4.2.5 Restriction survives physical operations | READY | Catalog sets the hold; `close-recall` checks inventory/transfer/route-load/custody/shortage blockers (`wa_backend/api/catalog.py:1537–1575`). Physical transfer commands do not clear it. Distinct guarded `cancel-recall` remains unchanged (`1394–1427,1542–1555`); this audit does not redefine it. |
| 4.2.6 Backend completion/readiness | PARTIAL | Authoritative close guard exists; no matching read-only recall-readiness contract in this path. Archive preflight requires `catalog.archive`; `can_archive` requires RETIRING + NONE (`wa_backend/api/catalog.py:1814–1826`). It is not recall readiness or a permission substitute. Never issue mutations to probe readiness. |
| 4.3.1 Remove Live Stock action dead ends | GAP | `dashboard/src/pages/products/lifecycle/ProductLifecycleManager.tsx:71–102` defaults otherwise-unhandled blockers to live, without operation identity. Blocker UI passes only `item.code` (`dashboard/src/features/catalog/lifecycle/CatalogLifecycleSimplePanel.tsx:666,763`). |
| 4.3.2 Live Stock remains read projection/link | PARTIAL | Quality actions live under Batches/Transfers, but Live Stock lacks exact quality-owner handoff and embeds `StockMinimumManager` (`dashboard/src/pages/inventory/Tab1LiveStock.tsx:37,450`). Keep settings separate from quality resolution; do not add batch/recall mutations or claim the whole tab is strictly read-only today. |

### Reusable authorities and proven gaps

**Batch decision/reason:** `wa_backend/models.py:2469–2520` stores `ProductBatch.disposition_reason` directly. `wa_backend/services.py:660–758` checks revision/transitions/product guards, saves reason, increments revision and emits `BatchDispositionChanged` with before/after evidence and Outbox. This is the current saved decision reason, not a fabricated movement description or proof of a reason-history UI. `POST /warehouse/batches/{batch_id}/disposition` requires company-level `batch.disposition`, idempotency input and expected revision (`wa_backend/api/warehouse/transfers.py:215–279`). It does not rewrite InventoryBalance buckets. Existing durable UI command preserves request/revision/reason (`dashboard/src/pages/inventory/batches/useBatchDispositionCommand.ts:149–201`). Reuse it; no new decision endpoint/state machine is needed. Frontend transition hints must also respect backend refusal to release a batch while the product hold is non-NONE (`wa_backend/services.py:700–722`).

**Known-batch inspection:** reuse `GET /warehouse/inventory/{product_variant_id}/batches` for paged warehouse-specific batch/expiry evidence, and `GET /warehouse/batches/{batch_id}/stock-sources` for permission-filtered positive quantities/source send permission (`wa_backend/api/warehouse/live_stock.py:1768–1845,2315–2385,2409–2559`). Quantities use the variant base UOM and canonical decimal strings. Disposition, balance status, expiry and product hold remain separate authorities. Stock sources currently reads matching rows before enforcing its 500-location response cap (`2502,2543–2549`); do not fan this out once per batch for a company-wide browser.

**Whole-product discovery:** RECALL sets `ProductVariant.operational_hold`, not every batch's disposition (`wa_backend/api/catalog.py:1537–1541`). Discovery must include RELEASED batches affected by that hold; restricted-batch summaries alone are insufficient. Existing endpoints cover a known warehouse or known batch, not bounded variant-first discovery across all relevant accessible sources. Transfer location lookup has different permissions/purpose and a limit without cursor (`wa_backend/api/warehouse/transfers.py:456–532`); source-inventory requires `transfer.send` and sellable-batch predicates (`545–594,681`). Neither replaces issue discovery. Prefer extending the existing Inventory read service/contract narrowly for this proven gap, including vehicle-only stock, rather than inventing parallel actions or browser-wide scans. Explicitly distinguish accessible physical sources from backend completion evidence in hidden/inactive/transit sources.

**Physical actions:** reuse `POST /warehouse/unified/transfer/special/dispatch` and existing receipt/cancel/reject. Backend selects destination from published policy and checks source/destination permissions, quantity net of reservations, product capability, expiry/shelf-life and purpose/status (`wa_backend/api/warehouse/transfers.py:1459–1515`; `wa_backend/services.py:1389–1416,1842–2011`). UI already uses durable request IDs and preserves ambiguous failures (`dashboard/src/pages/inventory/batches/useBatchSpecialTransfer.ts:70–123`). `BatchQuantityActions.tsx:341–368` submits one source/status's movable quantity, then opens generic Transfers; follow-up should focus the returned transfer. Vehicle support alone does not prove a custody blocker is resolved. No automatic reservation release or company-wide combined mutation is authorized.

**Reservation ownership:** Dispatch persists PENDING HANDSHAKE headers and RESERVE movements linked by batch allocation, `transfer_header_id`, `work_session_id` and reference (`wa_backend/api/dispatch.py:2225–2260`; `wa_backend/models.py:3032–3043`). `GET /dispatch/route/{route_id}/transfers` requires `dispatch.read`, returning transfer identity/status and source-scoped `can_force_cancel` (`wa_backend/api/dispatch.py:2742–2793,2876–2892`). Its response `batch_id` is a notes/reference identifier, **not a ProductBatch ID** (`2886–2890`); do not use it as reverse batch lookup. Existing owner UI `dashboard/src/components/dispatch/TransfersRadarModal.tsx:167,184–229,433` calls `POST /dispatch/transfers/{transfer_id}/force_cancel`, whose authority checks tenant, source permission, HANDSHAKE/PENDING, locks and idempotency before RELEASE (`wa_backend/api/dispatch.py:2624–2711`). Unified Inventory list/detail restrict workflow to TRANSIT (`wa_backend/api/warehouse/transfers.py:1229,1345`), so their generic cancel page cannot resolve these reservations.

Smallest reservation gap fix: a bounded, permission-filtered live owner-reference projection within an existing Inventory read contract, resolved through authoritative header/line/movement relations with exact batch/source/status and route/work-session context. Verify all reservation producers before claiming exhaustive coverage; historical RESERVE alone is not live ownership. Link authorized users to Dispatch's existing owner; otherwise report the inaccessible owner without leaking identity/granting permission. `/warehouse/ledger/cursor` is historical, reference-filtered and separately permissioned (`wa_backend/api/warehouse/live_stock.py:295–354,752–822`); do not sum ledger history in the browser or scan every route.

**Staging versus completion:** receipt maps DISPOSAL to DISPOSAL_PENDING, RECALL_RETURN to RECALLED and vendor return to restricted staging (`wa_backend/services.py:2506–2531`). No terminal destruction/vendor-handoff command was identified in the inspected warehouse API path. Resolve that business-workflow ownership with the project owner before designing any new command; do not silently use stocktake adjustments to erase quantities. Close guards count company evidence beyond visible active warehouse/vehicle sources, including nonzero on-hand/reserved balances (`wa_backend/product_lifecycle.py:421–479`). Empty visible sources or completed transport cannot prove recall completion. Future read-only readiness must reuse existing blocker authority, hide unauthorized details and leave close-recall execution validation authoritative.

### Smallest safe implementation order

1. Connect existing owners: Inventory confirmed-issue entry and exact batch/transfer/Dispatch navigation; remove Live Stock dead ends. Preserve typed navigation and unchanged hold/close/cancel/archive permissions and semantics. Explain unavailable or unauthorized destinations.
2. Fill only proven reads: bounded variant-first affected-stock discovery, then live reservation-owner references. Reuse batch details/source contracts without N+1 fan-out or permission broadening. Include vehicle-only and RELEASED batches under RECALL; distinguish accessible stock from hidden completion blockers.
3. Compose source-specific actions using existing disposition/special-transfer commands, actual source eligibility, published destination policy and permissions. Focus the returned transfer for follow-up. Preserve separate commands and durable IDs; concurrent changes still require backend revalidation.
4. Expose progress/readiness from existing blocker authority, never archive eligibility or browser totals. Keep pending physical states until resolved; terminal disposal/vendor handoff requires explicit owner-approved workflow design, not a UI workaround.
5. Before implementation acceptance, verify tenant/RLS/per-location denial, hidden/transit/vehicle-only stock, mixed buckets/expiry, reservation races, stale revision, policy/destination denial, lost-response replay, partial source success and close-recall blockers. These are future verification requirements, not executed tests or checked-off acceptance.

Preservation gate: retain tenant context (`wa_backend/database.py:48–55`), explicit company predicates, permissions/locks, idempotency payload matching, audit/Outbox transactions, lifecycle authority and existing state codes. Navigation carries identity, never authority. This audit changes no frontend/backend behavior or business rule.

---

# Phase 5 — Archive blockers become owner-specific actions

Purpose: archiving must not show backend nouns and leave the user stranded.

- [x] Implement owner-specific handling for the current blocker set, using the authoritative owner module and exact identity/context when an executable V1 action exists; unsupported/partial contexts remain explicit capability gaps documented below.
- [x] Where no executable V1 owner action exists, expose an explicit capability gap; do not invent a fake mutation or send the user to a dead-end/read-only screen.
- [x] Product modal presents a plain-language explanation plus the exact owner action/capability gap; never generic `??????`.


**Exit gate:** every displayed blocker either has a real resolution action or clearly states that the required capability is not yet available; no dead-end links.

## Phase 5 owner-action checkpoint evidence — 2026-10-04

**Base and scope:** started from merged Phase 4.1 main `6b2a34470d7a5c9816c70512ac28e957c777a24c`, branch `codex/archive-blocker-owner-actions-20261004`. This checkpoint changes archive read/navigation presentation only. The raw blocker authority and archive eligibility still come from `wa_backend/product_lifecycle.py:421–479` and `wa_backend/api/catalog.py:1818–1833`. No lifecycle, recall/close/cancel-recall command, reservation/quantity mutation, permission grant, RLS, idempotency, Audit/Outbox, or transaction boundary is changed. Whole-product confirmed-issue callbacks remain outside this diff. `RUN.txt` is excluded.

**Contract:** the existing `GET /catalog/variants/{variant_id}/archive-preflight` adds optional `blockers[].owner_target`; existing `{code,count,sample_id}` and `can_archive` retain their authority. The target is a representative operation, not a promise to resolve all `count` blockers. Inventory, Dispatch and Operations provide public read projections (`wa_backend/domains/inventory_archive_navigation.py:18,133`; `wa_backend/domains/dispatch_archive_navigation.py:13,53`; `wa_backend/domains/operations_archive_navigation.py:11,25`). Tenant and owner permission predicates precede projection. At most one bounded query per owner is added (Inventory/Dispatch use UNION), plus the existing product-location deletion guard for one authorized assignment. There are no queries per list row, locks, writes, commits or mutation probes. Missing/inaccessible/stale representatives produce no target; count/eligibility is never inferred from target availability.

Targets contain identities only: `batch` carries batch/anchor-location IDs; `transfer` carries header/location/reference; `stocktake` carries actual session/anchor-location IDs (a lock ID is never treated as a session ID); `product-location` carries assignment/location IDs; `handshake` carries header/route IDs; `route-load` carries route ID; `shortage` carries shortage ID; `settlement` carries the work-session ID resolved from the custody snapshot. Authorized unsupported contexts return `kind: capability-gap` with `INVENTORY_SOURCE`, `TRANSIT_STATE`, `STOCKTAKE_STATE` or `PRODUCT_LOCATION_REFERENCES`. These are navigation capability reasons, not new business states. Unknown/malformed hints fail closed.

| Blocker | Checkpoint result and real action owner | Explicit remaining gap / limit |
|---|---|---|
| `INVENTORY_BALANCE` | **PARTIAL.** Exact batch entry in Inventory opens the existing batch quantities/reservation workflow, including authorized vehicle sources using a readable warehouse anchor. Read projection: `inventory_archive_navigation.py:35–56`; receiver: `dashboard/src/pages/inventory/archive/ArchiveOwnerWorkspace.tsx:19`. Source/batch/variant are read again by the owning screens. | Transit/scrap/inactive sources and missing warehouse context are explicit capability gaps. Transfer to another company location or disposal/vendor-return staging does not prove the company-wide quantity blocker is gone. No terminal destruction/vendor-handoff workflow is invented. |
| `OPEN_TRANSFER` | **PARTIAL.** `TRANSIT / IN_TRANSIT` opens exact Inventory transfer detail and pins its freshly read row with the existing receipt/reject/cancel actions; an executable source/destination is selected using current permissions. `HANDSHAKE / PENDING` opens the exact Dispatch route radar/header with the existing guarded cancellation. Evidence: `inventory_archive_navigation.py:58–84`, `dispatch_archive_navigation.py:31–43`, `dashboard/src/pages/inventory/TabTransfers.tsx:30–87`, `dashboard/src/features/dispatch/useOwnerNavigation.ts:14`. | V1 Transfers has no executable action for TRANSIT DRAFT/PENDING/ACCEPTED. Non-pending handshake or a route outside the active/waiting/postponed read surface has no proven direct V1 resolution entry. No generic transfer tab or Live Stock fallback is offered. |
| `OPEN_STOCKTAKE` / `ACTIVE_INVENTORY_LOCK` | **PARTIAL.** Inventory resolves the session and correct warehouse anchor, including VEHICLE_RECON's stored session/vehicle/route relationship; COUNTING/RECOUNT_REQUIRED use existing count-sheet, PENDING_REVIEW uses existing review. Exact context is fetched again; the session owns any cancellation/completion/unlock. Evidence: `inventory_archive_navigation.py:86–118`, existing `wa_backend/api/warehouse/stocktake.py:1178–1370`, `dashboard/src/pages/inventory/stocktake/hooks/useStocktakeLifecycle.ts:182–295`. | DRAFT/APPROVED are explicit V1 capability gaps. Independent-recount/Maker-Checker, current state and permissions can still deny opening. No standalone unlock is added. Focus is consumed once; failed navigation preserves another session's resume pointer/phase and saved draft, and never borrows its independent-wait state. |
| `PRODUCT_LOCATION` | **PARTIAL.** Mount the existing Inventory-owned assignment manager through exact variant/location/assignment focus; re-read variant and location-filtered assignment, then use its existing durable reason/version-guarded delete. Evidence: `ArchiveOwnerWorkspace.tsx:42–63`, `dashboard/src/features/inventory/productLocations/ProductLocationManager.tsx:289–329`. | Reuse `product_location_delete_blockers` (`wa_backend/product_lifecycle.py:483–527`) before offering the link. Any policy/balance/movement/transfer/stocktake references produce an explicit historical/reference capability gap without a delete button in Catalog. Zero quantity does not remove history; no historical detachment command exists or is added. |
| `STOCK_POLICY` | **GAP, explicitly displayed.** Inventory is the owner. The existing minimum-stock preview/apply/update APIs (`wa_backend/api/inventory_stock_policy.py:497,528,658`) do not deactivate `InventoryStockPolicy.is_active`. | Do not route to minimum-stock editing or Live Stock as a fix. A policy-owner deactivation/resolution workflow needs a separate approved contract and business discussion. |
| `ACTIVE_ROUTE_LOAD` | **READY for existing owner navigation.** Fresh exact route read opens its action card (active/waiting) or exact postponed-route restoration screen. Existing load changes/close/restore remain explicit owner actions with server checks. Evidence: `dispatch_archive_navigation.py:22–30`, `dashboard/src/pages/DispatchBoard.tsx:337–357,1403–1406,1458,1861`. | No automatic close/load adjustment. Existing shops/session/custody/permission guards can require other work first. Zero planned quantity alone is not used to override archive's load-line predicate. |
| `OPEN_CUSTODY` | **PARTIAL.** For an admin, a closed, inventory-reconciled, financially unsettled custody snapshot resolves to its exact work session and opens Operations' existing financial settlement. Historical unsettled sessions are already included by `/admin/sessions/today` (`wa_backend/api/dispatch.py:614–642`); the new optional `session_id` only narrows that authority. Projection: `operations_archive_navigation.py:11–31`; fresh readiness check: `dashboard/src/features/operations/useSettlementOwnerNavigation.ts:10–32`; existing report/modal: `dashboard/src/pages/OperationsDashboard.tsx:145–182,244–255`. | Open work, unreconciled inventory, non-admin access or a session whose debrief is not financially ready have no direct settlement action. Physical reconciliation and financial settlement remain separate owners. Exact custody-reference navigation for the other stages is not proven in V1; no combined custody command or Phase 4.2/4.3 change is added. |
| `OPEN_SHORTAGE` | **READY for existing owner navigation.** Fresh exact pending shortage read opens Dispatch's existing modal/group and highlights the exact row. Server `get_current_admin` + tenant scope and existing edit/delete semantics remain unchanged. Evidence: `wa_backend/api/dispatch.py:4846–4866`, `DispatchBoard.tsx:352–357,1753`, `dashboard/src/components/dispatch/ShortageModal.tsx:177–193,285–289,531–537`. | Non-admin, disappeared or fulfilled targets do not open an actionable record. No Inventory proxy cancellation is added. |
| `ACTIVE_OFFER` | **GAP, explicitly displayed.** Archive counts legacy `offer_rules.is_active` (`product_lifecycle.py:470–472`). Current Commercial Rules works on OfferDefinition/OfferVersion (`dashboard/src/features/commercialRules/api.ts:129,142,299–304`). | No legacy rule ID is mapped to a new offer/version ID. There is no proven current V1 legacy deactivation surface; generic Commercial Rules navigation is removed for archive. |

**Destination revalidation:** typed public navigation carries IDs/context, never permissions, command payloads, a lifecycle decision, an idempotency request ID or a localStorage workflow signal. Inventory's focused entry uses current exact-location capabilities and existing owner reads; operation identity is validated again. Existing owner read endpoints now accept optional positive `route_id` / `shortage_id` / `session_id` filters (`wa_backend/api/dispatch.py:3393–3426,4846–4866,614–642`). Navigation uses these bounded lookups instead of another unbounded list fetch; default list behavior, response shape and permissions are unchanged. Operations checks the existing settlement readiness status and reloads the exact settlement report before its existing command. The owning radar, transfer detail, stocktake context, assignment manager and shortage/route actions retain their current server checks.

**Catalog presentation:** `dashboard/src/features/catalog/archive/ArchiveBlockerList.tsx:7` and `navigation.ts:13,39` are archive-only; both simple/advanced archive sections reuse them. No Inventory internal UI is imported into Products. Arabic/English explanations, locale direction, Western digits and keyboard-reachable buttons are covered. No archive blocker action points to Live Stock. Policy, legacy offers, unsupported custody stages, historical assignment references and unsupported contexts are explained without fake buttons. The unchecked Phase 5 items above remain open because full resolution coverage is not proven; this checkpoint does not manufacture missing owner mutations.

**Verification:** 21 focused backend projection/preflight/owner-filter tests pass using synthetic SQLite fixtures or capture/compile read statements only; no production database, SQL console, workers, imports or migrations. All 46 new frontend mapping/RTL/LTR/action and receiver tests pass, covering stale state, revoked authority, saved stocktake drafts, one-time focus and exact custody readiness. Existing Dispatch navigation (6) and Catalog/Inventory boundary (8) regressions pass; the boundary's source assertion is updated for the extracted receiver and its handshake behavior is covered by a focused test. ESLint on all changed frontend files and production build pass. TypeScript remains FAIL: latest-main has 27 diagnostics, verified with HEAD sources in memory without a checkout/copy; this checkpoint has 26, after adapting the existing transfer-detail callback return mismatch at the touched boundary, with no new diagnostics. Unrelated batch contracts/Product action/test fixture errors remain outside Phase 5. The existing `products-enter-recall-ux.test.ts` has 3 passing tests and 1 baseline failure because its expected `إرجاع الكمية للتعامل معها` string is already absent from HEAD resources; neither the test nor whole-product wording is changed. PostgreSQL RLS, live permission races and actual owner-command acceptance remain runtime verification requirements; no broad suite or workflow execution is claimed.

**Smallest next steps requiring separate approval:** define Inventory policy deactivation; decide a history-preserving assignment/archive contract; provide a legacy-offer owner surface; supply exact custody/work-session navigation for open-work and inventory-reconciliation stages; address unsupported transit/stocktake states and terminal physical quantity completion. Financially ready custody already uses the existing Operations settlement. These are genuine ownership/capability gaps, not reasons to bypass archive guards or add a generic cleanup action.

---

# Phase 6 — Multi-warehouse, vehicle, and representative scalability

Purpose: validate the architecture for future operational growth before adding those modules.

- [x] Validate multi-warehouse authorization/isolation for product-wide and batch workflows:
  - Product-level decisions remain company-wide.
  - Quantity actions remain per location.
  - A user authorized for Warehouse A cannot view or mutate Warehouse B detail.
  - Company-wide summaries expose only detail/counts allowed by the approved permission contract.
  Evidence: whole-product source tests permission-filter Warehouse B from Warehouse-A-only users; exact-location InventoryAccess tests deny `transfer.send`/`transfer.destination` on B, and the special-transfer contract rechecks both the requested source and server-derived destination before mutation.
- [x] Validate vehicle/custody extensibility using current Inventory truth: vehicle-only stock remains discoverable/actionable where supported without redefining Catalog ownership. Evidence: whole-product source contract/test returns VEHICLE sources separately, and exact-batch stock-sources supports vehicle-only opening without fabricating warehouse state.
- [x] Preserve module boundaries for future scale: vehicle identity remains Fleet-owned, representative/driver identity stays outside Catalog, transfers use Inventory authority with exact source/destination permissions, and Products never imports driver/vehicle internals. Evidence: Catalog/Inventory boundary gate rejects dispatch components and vehicle/driver identity fields under Products; physical actions remain Inventory-owned source-scoped commands.

**Exit gate:** the same flow works for one warehouse or many warehouses and is ready for later fleet/custody expansion without redesigning Catalog.

---

# Phase 7 — Focused acceptance matrix

Use one consolidated acceptance gate after source analysis and implementation.

- [ ] Run and record one consolidated acceptance gate covering all scenarios below:
  - Active product + all normal batches.
  - Active product + one quarantined batch → product remains available + warning shown.
  - Quarantined batch passes inspection → allowed return-to-sale path.
  - Batch is blocked → UI explains stronger consequence.
  - Batch permanently excluded from sale → physical actions are offered by Inventory.
  - Whole-product false alarm → `تبين أن المنتج سليم` restores product hold; independent batch restrictions remain.
  - Whole-product confirmed issue with stock in one warehouse.
  - Whole-product confirmed issue with stock in multiple warehouses.
  - Whole-product issue with vehicle/custody quantity where supported.
  - Reserved stock shows exact owning blocker/action.
  - Archive with each supported blocker routes to a real owner action/capability gap.
  - Permission-limited user cannot see or mutate unauthorized warehouse detail.
  - Network lost after mutation preserves durable operation identity.
  - Arabic RTL + English LTR.
  - Keyboard-only completion of every critical workflow.
  - TypeScript, ESLint, focused frontend tests, backend tests, production build, and diff audit.

---

# Phase 8 — Cleanup and stable merge

- [x] Remove obsolete cross-page navigation hacks after replacement is proven.
- [x] Remove obsolete user-facing recall/sweep terminology.
- [ ] Remove/retire dead legacy UI together: `TabProductCatalog.tsx` test-only legacy surface plus duplicate lifecycle/batch action UI after consumers are migrated safely.
- [ ] Perform final architecture/code-size review: page folders remain responsibility-driven, no mega-file/god hook, and update the architecture companion only if implementation revealed a missing permanent rule.
- [ ] Finalize this plan from actual evidence and close only proven items; Phase 7 owns the consolidated technical/UX acceptance gate.
- [ ] Stable merge/cleanup: merge completed branches to `main`, delete merged temporary branches/worktrees, confirm local `main == origin/main`, and preserve local `RUN.txt` user changes.

---

# Safe parallelization with Codex

Parallel work is allowed only with non-overlapping file ownership.

Recommended lanes:

### Lane A — Main implementation owner

Owns:
- Product lifecycle refactor.
- Product/Inventory navigation contract.
- User-facing terminology.
- Whole-product quality flow.
- Final integration and architecture review.

### Lane B — Codex independent audit / Inventory lane

May own, on a separate branch:
- Inventory-only audit of actionable destinations for batch quantities and archive blockers.
- Multi-warehouse permission/read contract analysis.
- Focused Inventory tests.
- Inventory-owned components that do not touch Product lifecycle files.

Codex must not independently redefine lifecycle semantics, Catalog authority, or backend state transitions.

Before merging parallel work:
- inspect diff;
- verify no overlapping authorities;
- run one consolidated acceptance gate.

---

# Current known defects status summary

This section is **non-authoritative** and must not create duplicate open checklist items. Open work is tracked only in the numbered phases above.

- [x] Products lifecycle UI ownership was separated from Inventory page internals in Phase 1.
- [x] Product/batch workflow navigation no longer uses localStorage/sessionStorage as a business-command bridge.
- [x] User-facing product-wide issue language no longer exposes recall/sweep terminology.
- [x] Confirmed whole-product issues now enter an Inventory-owned quantity workflow with backend readiness evidence.
- [x] Product batch warnings deep-link to the exact owning batch workflow.
- [x] Batch actions use the approved business language and server-derived allowed actions.
- [x] Archive blockers now expose an exact owner action where V1 has one, or an explicit capability gap where it does not.
- [x] Multi-warehouse/vehicle authority and module boundaries are covered by Phase 6 gates.
- Open ? Live Stock/action-owner cleanup is tracked only in **Phase 4.3**.

This file stays ACTIVE until the authoritative numbered-phase items are closed or explicitly deferred with owner approval.

