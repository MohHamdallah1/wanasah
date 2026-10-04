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
- [ ] Relocate or retire the legacy `TabProductCatalog.tsx` file itself after its test-only consumers and old hardcoded UI are migrated safely. Do not re-enable it in Inventory and do not let it become an excuse for new cross-domain code.


---

# Phase 2 — Replace backend terminology with business language

Purpose: user decisions must be understandable without knowing backend state machines.

## 2.1 Whole-product issue

- [ ] Keep entry action `مشكلة جودة أو سلامة`.
- [ ] Keep scope question `أين توجد المشكلة؟` → `دفعة محددة` / `المنتج بالكامل`.
- [ ] Replace any user-facing `استدعاء المنتج`, `سحب`, `إغلاق السحب`, `إنهاء السحب`, `close recall`, or `إرجاع ضمن السحب` wording.
- [ ] False alarm action remains `تبين أن المنتج سليم`.
- [ ] Confirmed issue action becomes `المشكلة مؤكدة — التعامل مع الكميات الحالية`.
- [ ] After quantities/open operations are resolved, present a business choice such as `السماح ببيع المنتج من جديد` or `التوقف عن استخدام المنتج` according to actual backend state.

## 2.2 Batch issue

- [ ] `QUARANTINED` user action/label: `عزل الدفعة للفحص`.
- [ ] `BLOCKED` user action/label: `منع بيع الدفعة`, with explicit consequence text.
- [ ] `RECALLED` user action/label: `استبعاد الدفعة من البيع نهائيًا`.
- [ ] Explain that final batch exclusion concerns whether it can ever be sold again; physical quantities are handled separately by Inventory actions.
- [ ] Keep canonical backend codes unchanged.

## 2.3 Reason UX

- [ ] Keep preset reason lists + `سبب آخر` for Product lifecycle actions where useful.
- [ ] Keep preset reason lists + `سبب آخر` for batch disposition actions.
- [ ] Use the actual saved human reason in warnings/details.
- [ ] Avoid vague fallback text when authoritative reason/status exists.

**Exit gate:** a normal warehouse/product manager can understand every action without knowledge of backend terms.

---

# Phase 3 — Products page: catalog decisions and read-only operational warnings

Purpose: Products controls the catalog and only points to Inventory when physical action is needed.

- [ ] Product lifecycle actions stay company-wide and warehouse-independent.
- [ ] Products shows batch warning summaries without changing batch state.
- [ ] Warning such as `المنتج نشط، لكن 1 دفعة غير متاحة للبيع` is clickable/keyboard accessible.
- [ ] Clicking the warning deep-links directly to the affected batch workflow, not generic Inventory home and not Live Stock.
- [ ] Preserve product status as `متاح للبيع` when the product is active even if one batch is restricted.
- [ ] Never infer product stoppage from zero stock or one restricted batch.
- [ ] `دفعة محددة` from quality issue scope navigates to Batches & Expiry only.
- [ ] `المنتج بالكامل` applies only the Product/Catalog company-wide hold.
- [ ] Product blockers are displayed as summaries from the owning domain; Products does not perform inventory mutations.

**Exit gate:** Products can add/edit/stop/resume/archive product identity and show operational warnings, but cannot mutate physical stock or batch state.

---

# Phase 4 — Inventory-owned quality action flow

Purpose: when physical quantities require action, Inventory provides the complete action in the correct place.

## 4.1 Batch-specific issue

- [ ] Batches & Expiry opens directly on the affected product/batch from a navigation intent.
- [ ] Show batch state, saved reason, expiry evidence, and affected quantities.
- [ ] Show quantity by exact warehouse/location and vehicle/custody source when supported.
- [ ] Offer only backend-valid actions for the current quantity/state/permission.
- [ ] Supported physical actions may include quarantine, return to supplier, disposal, approved transfer, and custody/vehicle collection.
- [ ] Reserved quantity must show the exact blocker and the owning operation when available; do not say only `عالج الحجز`.

## 4.2 Whole-product confirmed issue

- [ ] `المشكلة مؤكدة — التعامل مع الكميات الحالية` opens an Inventory-owned workflow.
- [ ] Inventory lists affected accessible locations separately.
- [ ] Never silently combine independent warehouses into one unauthorized mutation.
- [ ] For each location/source show quantity, reservation, status, and concrete allowed next actions.
- [ ] Company-wide product restriction remains active while physical operations are open.
- [ ] Completion/readiness is computed by backend evidence, not UI guessing.

## 4.3 Read-only Live Stock boundary

- [ ] Remove blocker actions that send the user to Live Stock expecting them to fix stock there.
- [ ] Live Stock may show a `فتح الإجراء` link to Batches/Transfers/etc., but remains read-only.

**Exit gate:** any message that says stock action is required provides an actual executable action or an exact link to the action owner.

---

# Phase 5 — Archive blockers become owner-specific actions

Purpose: archiving must not show backend nouns and leave the user stranded.

Audit every current archive blocker before creating a link.

- [ ] `INVENTORY_BALANCE` → Inventory-owned quantity/reservation workflow.
- [ ] `OPEN_TRANSFER` → Transfers, focused on the affected product/operation.
- [ ] `OPEN_STOCKTAKE` / `ACTIVE_INVENTORY_LOCK` → Stocktake, focused on the affected warehouse/context.
- [ ] `PRODUCT_LOCATION` → Warehouse/Product-location management owner; verify an actual corrective action exists before linking.
- [ ] Inventory policy blocker → owning Inventory settings/policy action; verify actual UI capability first.
- [ ] `ACTIVE_ROUTE_LOAD` → Dispatch/Fleet owning workflow.
- [ ] `OPEN_CUSTODY` → custody/vehicle/representative owner.
- [ ] `OPEN_SHORTAGE` → owning shortage/reconciliation workflow.
- [ ] `ACTIVE_OFFER` → Commercial Rules/Offers owner.
- [ ] If a blocker has no V1 action surface, do not pretend it is actionable; mark the capability gap explicitly and implement the smallest correct owner-side action.
- [ ] Product modal presents human explanation + exact owner action, never generic `معالجة`.

**Exit gate:** every displayed blocker either has a real resolution action or clearly states that the required capability is not yet available; no dead-end links.

---

# Phase 6 — Multi-warehouse, vehicle, and representative scalability

Purpose: validate the architecture for future operational growth before adding those modules.

- [ ] Test a company with multiple warehouses where the same product/batch exists in several locations.
- [ ] Product-level decisions remain company-wide.
- [ ] Quantity actions remain per location.
- [ ] A user with access to Warehouse A cannot view/mutate Warehouse B details through a company-wide incident.
- [ ] Company-wide incident summaries may show only authorized detail; counts must follow the approved permission contract.
- [ ] Vehicle stock is modeled as Inventory/custody truth while vehicle identity remains Fleet-owned.
- [ ] Representative/driver identity remains outside Catalog/Inventory ownership.
- [ ] Future transfer to/from vehicle uses Inventory movement authority and exact source/destination permissions.
- [ ] Products never imports driver/vehicle internals.

**Exit gate:** the same flow works for one warehouse or many warehouses and is ready for later fleet/custody expansion without redesigning Catalog.

---

# Phase 7 — Focused acceptance matrix

Use one consolidated acceptance gate after source analysis and implementation.

- [ ] Active product + all normal batches.
- [ ] Active product + one quarantined batch → product remains available + warning shown.
- [ ] Quarantined batch passes inspection → allowed return-to-sale path.
- [ ] Batch is blocked → UI explains stronger consequence.
- [ ] Batch permanently excluded from sale → physical actions are offered by Inventory.
- [ ] Whole-product false alarm → `تبين أن المنتج سليم` restores product hold, independent batch restrictions remain.
- [ ] Whole-product confirmed issue with stock in one warehouse.
- [ ] Whole-product confirmed issue with stock in multiple warehouses.
- [ ] Whole-product issue with vehicle/custody quantity where supported.
- [ ] Reserved stock shows exact owning blocker/action.
- [ ] Archive with each supported blocker routes to a real owner action.
- [ ] Permission-limited user cannot see or mutate unauthorized warehouse detail.
- [ ] Network lost after mutation preserves durable operation identity.
- [ ] Arabic RTL + English LTR.
- [ ] Keyboard-only completion of every critical workflow.
- [ ] TypeScript, ESLint, focused frontend tests, backend tests, production build, diff audit.

---

# Phase 8 — Cleanup and stable merge

- [ ] Remove obsolete cross-page navigation hacks after replacement is proven.
- [ ] Remove obsolete user-facing recall/sweep terminology.
- [ ] Remove dead duplicate lifecycle/batch action UI.
- [ ] Confirm page folders remain small and responsibility-driven; no new mega-file or god hook.
- [ ] Update this plan with final `[x]` states.
- [ ] Update architecture companion if implementation revealed a missing permanent rule.
- [ ] Merge completed branches into `main` only at stable checkpoint.
- [ ] Delete merged temporary branches.
- [ ] Confirm local `main` == `origin/main`; preserve `RUN.txt` local user changes.

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

# Current known defects this plan must close

- [ ] Products lifecycle UI currently depends on Inventory/Catalog page internals; refactor ownership.
- [ ] Product/batch navigation currently relies partly on cross-page localStorage signaling; replace with explicit navigation intent.
- [ ] Product-wide issue UI exposes confusing recall/sweep language.
- [ ] Confirmed whole-product issue still sends users toward stock information instead of a complete Inventory action flow.
- [ ] Live Stock is read-only but has been used as a blocker destination.
- [ ] Product batch warning is informative but must deep-link directly to the exact owning batch workflow.
- [ ] Archive blocker links must be audited so every destination can actually resolve the blocker.
- [ ] Batch actions need final user-language cleanup and consequence explanations.
- [ ] Multi-warehouse and future vehicle/custody behavior needs explicit acceptance coverage.

This file stays ACTIVE until all items are closed or explicitly deferred with owner approval.