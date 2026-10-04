# Inventory Quality Workflow Completion Plan

**Status:** ACTIVE — execution plan
**Created:** 2026-10-04
**Scope:** Complete the inventory quality workflows end-to-end after the Catalog/Inventory boundary remediation.
**Canonical architecture:** `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/architecture/CATALOG_INVENTORY_WORKFLOW_BOUNDARIES.md`.

## 1. Goal

Finish the operational foundation before adding more inventory features.

> **The backend carries the complexity and authority. The frontend stays intentionally simple, obvious, and hard to misuse.**

A workflow is not complete because a button or endpoint exists. It is complete only when the user can start the business decision, execute every required physical step, reach a terminal state, and the backend can prove the final result through inventory truth, ledger/audit evidence, permissions, and idempotent commands.

## 2. Non-negotiable engineering rules

1. **Backend is authoritative.** React must never duplicate lifecycle, sellability, transfer, expiry, reservation, destination-policy, terminal-disposition, or permission rules.
2. **Exact-location isolation remains mandatory.** Company-wide incidents may summarize many locations, but every physical mutation is re-authorized for the exact source/destination.
3. **Navigation is not authorization.** Route state may identify product/batch/location, but the destination re-fetches and re-checks access and current state.
4. **No hidden cross-domain mutation.** Products may show inventory warnings and launch Inventory workflows; Products never moves, reserves, disposes, returns, or reconciles stock.
5. **No fake completion.** Moving stock to a disposal area is not destruction. Moving stock to a vendor-return staging area is not proof that the vendor received it.
6. **No dead-end instructions.** Never tell the user to “process/handle stock” without a concrete executable action or an explicit capability gap.
7. **No fake actions.** If V1 has no executable resolution surface, say so explicitly instead of linking to an unrelated/read-only page.
8. **Durability.** New mutations must preserve request idempotency, revision/locking strategy, retry safety, audit/outbox requirements, and tenant/RLS invariants.
9. **Unified inventory truth.** Terminal quantity changes must go through the approved Inventory movement/ledger authority; no direct balance deletion or ad-hoc stock decrement.
10. **Small modules.** Do not create a new mega-component, god hook, or generic shared-business-logic dumping ground.
11. **Human language only in UI.** Backend codes such as `RECALL`, `RECALL_RETURN`, `DISPOSAL_PENDING`, etc. may remain canonical internally; the UI translates them into simple business decisions.
12. **Definition of done is end-to-end.** A checklist item becomes `[x]` only after focused automated evidence proves the intended contract and the user flow has no known missing required step.

## 3. Current confirmed gaps

- Product batch-warning navigation carries `variantId + batchId`, but the Batches page still visually depends on the currently selected warehouse.
- The same company-level `ProductBatch` may physically exist in multiple warehouse/vehicle locations; the workflow must therefore be batch-centric.
- Whole-product confirmed-quality flow is currently hosted under the Batches tab even though it can span multiple batches, warehouses, vehicles, reservations, and owner operations.
- `allowed_purposes` can return an empty list without explaining why no action is available.
- The generic “open transfers” button can appear without a concrete transfer/action context.
- `DISPOSAL` currently means transfer to the configured disposal location; on receive, stock becomes `DISPOSAL_PENDING`. This is not final destruction.
- `RETURN_TO_VENDOR` currently represents a controlled transfer/staging path; reaching staging is not proof of vendor handover.
- Final terminal evidence for destruction and vendor handover is not yet a complete user workflow.

---

# Phase 1 — Batch-centric multi-location navigation

**Goal:** Opening an affected batch must work correctly regardless of the warehouse currently selected in Inventory.

- [x] **1.1 Batch-first focus and source resolution**
  Treat `batchId` as the primary focus identity. Resolve the batch from authoritative `stock-sources` before relying on the selected warehouse. If exactly one readable source exists, Inventory may select it for context; if multiple sources exist, do not silently choose one.

- [x] **1.2 Multi-source batch workspace**
  Show every readable warehouse/vehicle source with quantity, stock status, reservation, and allowed actions. Do not leak unauthorized source identities/counts/quantities. Remove contradictory background states such as “no matching products” while the focused batch is open.

- [x] **1.3 Permission-safe navigation contract**
  Route state remains a hint only. Destination must re-fetch the batch and exact-location permissions. Hidden company blockers may be reported only through non-leaking signals.

- [x] **1.4 Automated Phase 1 acceptance**
  Cover one warehouse, two warehouses, warehouse + vehicle, vehicle-only, wrong-last-selected-warehouse, and no-access-to-second-location cases.

**Phase 1 done when:** A Products warning opens the exact batch correctly from any prior warehouse context and multi-location stock is explicit without implicit authority.

### Phase 1 implementation and acceptance evidence — Lane B, 2026-10-04

- Starting point: latest `origin/main` at `b2bb6c1fcb3176921aca1f7d0110a27139fb9bd6`; isolated temporary worktree, branch `feat/batch-multilocation-quality-workflow-20261004`. The desktop checkout and `RUN.txt` were not edited or switched.
- Root cause: the previous Inventory entry mounted the warehouse shell before its Batches focus resolver. Warehouse setup/access and the saved warehouse could therefore prevent the batch resolver from mounting or leave a contradictory warehouse table behind it. The existing Products warning already passes typed `batchId + variantId`; it needs no Products change.
- `dashboard/src/pages/inventory/InventoryPage.tsx` intercepts only exact batch focus (including the existing batch owner-focus intent). `dashboard/src/features/inventory/batchFocusNavigation.ts` retains identity only, discarding warehouse/name hints. Other valid Inventory intents still enter the existing shell. Whole-product workspace internals are unchanged.
- `dashboard/src/pages/inventory/batches/BatchFocusWorkspace.tsx` waits for fresh destination capabilities **and** fresh batch stock-sources. Warm cached evidence is not shown as authorization. Mismatched batch/variant fails closed; structured read failures preserve the request id. The route hint is consumed once on resolution/failure; closing while loading aborts the read. No localStorage workflow signaling is added.
- **One readable source:** show that source as context without changing the saved warehouse preference. **Multiple readable sources:** show all of them together, including vehicles, without choosing an implicit warehouse. The warehouse shell/table is not mounted while exact batch focus is active. Counts refer only to the returned readable sources, never to company-wide hidden sources.
- Reuse the existing `BatchQuantityActions` and batch disposition manager: current batch state/reason/expiry, source status/on-hand/reserved/movable quantities, reservation owners, and server-derived actions. No duplicated sellability, disposition, lifecycle, destination or permission rules. Quantity actions receive the same snapshot rather than starting another stock-sources request. A presentation-only option hides duplicate quantity controls in the disposition dialog; all existing callers retain their defaults.
- Existing backend authority is sufficient: `wa_backend/api/warehouse/live_stock.py:2756` owns `/warehouse/batches/{batch_id}/stock-sources`; company-scoped batch lookup at line 2806, set-based source query at line 2886, exact readable-location predicate at line 2893, server-derived purposes at line 2973. No backend runtime code/endpoint or schema change was needed. Hidden source identity/name/count/quantity stays absent from the response. Mutations still use the existing exact source/destination authority, durable request identity and audit/ledger semantics.
- Generic transfer-list navigation is hidden only in this new workspace. Following an actual created transfer reads both endpoint locations' capabilities in one bounded request, then sends typed operation/location identity to the existing owner workflow. Reservation links use existing typed Dispatch navigation; Inventory does not cancel owner operations.
- **Focused frontend acceptance:** `dashboard/src/test/batch-focus-workspace.test.tsx` has 14 passing cases exercising the real Products warning, Inventory entry, read/access hooks, parser and quantity panel. Includes one/two warehouses, warehouse + vehicle, vehicle-only, unrelated saved warehouse, hidden source, per-source action permissions, consumed/malformed/mismatched intent, delayed fresh capabilities, stale-cache revocation, pending-read abort, reservation owner navigation, Arabic RTL/English LTR and keyboard entry. With existing boundary/disposition/source-parser suites: **29 passed**.
- **Focused backend read acceptance:** `wa_backend/tests/test_batch_multilocation_read_acceptance.py` uses the actual existing endpoint and synthetic fixture. Proves all source combinations, constant four statement calls independent of source count, hidden-source redaction and existing inaccessible/foreign-company 404s. With existing stock-sources/reservation-owner suites: **34 passed**. Synthetic SQLite tests do not claim PostgreSQL RLS runtime verification.
- **Browser scaffolding and acceptance:** `dashboard/e2e/batch-focus.config.ts`, `batch-focus.spec.ts`, `README.md`, and shared read fixtures. Installed Edge against the production build: **10 passed**, covering five source configurations in both locales, wrong saved warehouse, one batch read, consumed typed history state and keyboard entry. All API requests are intercepted; unexpected reads and all mutations fail. The React suite proves the actual Products-warning click; browser coverage here proves the destination, not terminal disposal/vendor handover or live-backend E2E.
- **Gates:** ESLint passes for every changed frontend/test/scaffold file; production build passes; `tsc --project tsconfig.app.json --noEmit` remains blocked by **27 pre-existing diagnostics**, reproduced from the unchanged starting `main` via a read-only compiler-source overlay, with no new diagnostic in this branch's files. These baseline errors are not silently repaired in another lane's files.
- **Remaining verification boundary:** no known missing Phase 1 functional step in the tested contract. Live authenticated PostgreSQL/RLS browser acceptance and the repository-wide TypeScript baseline remain integration gates; neither is claimed complete. Phase 2/3 internals and all other phase checkboxes remain untouched.

---

# Phase 2 — Dedicated whole-product quality workspace

**Goal:** A confirmed problem affecting the entire product must have a clear Inventory-owned workspace instead of behaving like a hidden Batches-tab modal.

- [x] **2.1 Dedicated workspace and clear hierarchy**
  `quality-issue` opens a distinct Inventory workspace/state. Present `Product → affected batches → physical sources → reserved/movable quantities → available actions`. Keep the company-wide product hold visible without letting Inventory silently redefine Catalog lifecycle.

- [x] **2.2 Backend action-availability reasons**
  Replace “empty allowed list” UX with a backend availability contract that returns safe reason codes such as: no configured destination, insufficient permission, fully reserved, source cannot send, already at destination, lifecycle/state restriction, or no movable quantity. Frontend only translates these reasons.

- [x] **2.3 Remove dead-end and duplicate controls**
  Do not show generic “open transfers” unless there is an actual transfer or owner workflow to follow. `عرض الرصيد` remains read-only context if retained; `المشكلة مؤكدة — التعامل مع الكميات الحالية` opens the executable workspace. Different labels must not open the same workflow while implying different meanings.

- [x] **2.4 Readiness and automated Phase 2 acceptance**
  Backend remains the only authority for `ready_to_resume_sales`. Cover multiple batches, multiple warehouses, vehicle source, partial permissions, reservations, no-action reasons, hidden blockers, and readiness remaining false until company-level requirements are truly complete.

**Phase 2 done when:** A manager can understand exactly what remains for a whole-product issue without knowing backend terminology, and every visible action/reason is server-derived.

### Phase 2.4 readiness and acceptance evidence — 2026-10-04

- Exact starting point: `origin/integrate/inventory-quality-workflow-20261004` at `839c29fb2231defb6b6590ab9c906ba256dd7cdb`; branch `feat/quality-phase2-readiness-acceptance-20261004`, isolated temporary worktree. The desktop worktree and `RUN.txt` were not edited or switched.
- Confirmed presentation gap: the dedicated `quality/WholeProductIssueWorkspace.tsx` fetched both readiness fields but did not display them. The older modal's presentation did not cover this destination. The production correction is one small `ProductQualityReadiness.tsx` component plus its composition in the dedicated workspace; existing translation keys are reused. No backend contract, lifecycle decision, permission rule or command changes.
- **Authority:** `/warehouse/variants/{product_variant_id}/quality-issue-sources` already calls `recall_completion_blockers(db, company_id, product_variant_id)` and returns only `not blockers` / `bool(blockers)` (`wa_backend/api/warehouse/live_stock.py:2731–2748`). That reader uses the canonical company/variant predicates and close-recall blocker set (`wa_backend/product_lifecycle.py:421–506`), independently of the permission-filtered visible batches. React presents `ready_to_resume_sales` and `company_requirements_remaining`; it never counts stock, reservations, allowed actions, hidden sources or pages to decide completion. Catalog hold stays visible and read-only even when readiness is true; no resume-sales action is added.
- Each bounded page includes a fresh company-wide readiness check. The workspace uses the latest returned page's flags, without AND/OR across pages. Positive and negative readiness presentations are withheld during source/capability fetching; initial warm cache remains hidden until both fresh destination reads complete. Errors and revocation hide readiness/source content and preserve the request id. Retry uses a new authoritative read. Batch action panels remain mounted during successful refresh, preserving existing drafts and concrete created-operation follow-up state.
- **Focused React/read-contract acceptance: 41 passed** across `whole-product-quality-readiness.test.tsx` (11), `whole-product-quality-workspace.test.tsx` (9), `whole-product-quality-issue-contract.test.ts` (3), `inventory-batch-stock-sources.test.ts` (4) and unchanged `batch-focus-workspace.test.tsx` (14). Covers false/true readiness with no readable batches; a deliberately counterfactual populated projection proving no React readiness inference; multiple batches/warehouses/vehicle; reserved versus movable quantities; exact server no-action reasons; non-identifying company requirements; fresh cache/capabilities; read/capability revocation; redacted retry; bounded pagination and changed readiness between pages; typed reservation-owner navigation; and concrete created-transfer follow-up after fresh endpoint capabilities. The two older parser fixtures lacked required current action fields; only fixtures were brought up to the existing contract, without relaxing a parser.
- **No generic transfers:** tests prove no generic transfer-list button before or after a created operation. Reservation navigation carries the exact Dispatch route/transfer identity. Only a successful existing quarantine-transfer result exposes an exact follow-up action, with source/destination capability re-read; no Inventory cancellation proxy or terminal workflow is added. The command acceptance uses an intercepted response and the existing durable hook, not a real mutation or transfer-endpoint change.
- **Production-browser acceptance: 4 passed** using `dashboard/e2e/quality-readiness.config.ts` and `quality-readiness.spec.ts` against the production build in installed Edge. Both readiness states in Arabic RTL/English LTR, Western digits, heading focus, actual Tab/Enter back navigation, consumed history intent, unchanged saved warehouse and no generic transfer/resume-sales button. Every API call is intercepted; all mutations/unexpected reads are rejected. The returning warehouse shell is outside this quality harness. Run with an isolated preview and `QUALITY_READINESS_BASE_URL`, then the available Playwright CLI `test --config e2e/quality-readiness.config.ts`; no dependency manifest/browser installation change.
- **Gates:** ESLint passes for all seven changed/new frontend/test/browser files; production build passes. TypeScript `tsconfig.app.json` with `noEmit` has **21 baseline diagnostics and the same 21 final diagnostics**, compared by file/position/code/message against the unchanged starting commit before edits; **zero new diagnostics**. These existing errors are not repaired in this lane.
- **Verification boundary:** no known remaining Phase 2.4 UI/read-contract gap in the focused automated matrix. Intercepted acceptance and source review do not claim live PostgreSQL/RLS or terminal business-outcome verification; those remain Phase 3.4/4 integration work. No SQL, migration, live backend test, terminal implementation, broad suite or merge was performed. All other phase checkboxes remain unchanged.

### Phase 2.2–2.3 evidence — integrated lane, 2026-10-04

- `stock-sources` returns bounded `special_actions` with server-derived `reason_code` and `eligible_quantity`; React validates the contract and only translates the reason.
- Empty action sets now explain the denied operations instead of showing a generic no-action sentence.
- Generic transfer-list navigation is hidden by default; only a concrete newly created transfer exposes a follow-up link.
- Recall completion `INVENTORY_BALANCE` opens the executable whole-product workflow and uses the same human action label rather than the misleading read-only `View stock` wording.
- Focused frontend gate: 34/34 passed. ESLint and production build passed. Repository TypeScript remains at 21 pre-existing diagnostics, with none in the changed files.

### Phase 2.1 implementation evidence — bounded checkpoint, 2026-10-04

- The existing Products lifecycle action already sends the typed `quality-issue` intent (`dashboard/src/pages/products/lifecycle/ProductLifecycleManager.tsx:265`). Its old destination was a warehouse-shell Batches modal (`dashboard/src/pages/inventory/MainInventory.tsx:279`, `:1425`). The Phase 1 Inventory entry now recognizes whole-product focus separately and mounts `quality/WholeProductIssueWorkspace.tsx` before the warehouse shell. Products, Catalog lifecycle components and the legacy modal are not modified.
- `dashboard/src/features/inventory/workspaceFocusNavigation.ts` preserves the existing typed navigation contract and retains only the variant identity plus the contextual product label. The warehouse hint and any injected permission/state fields are not authority. The product label is navigation context, not a new authoritative Catalog name read. Hold/state/access are confirmed by fresh owning reads before product/source content appears.
- Reuse `/warehouse/variants/{product_variant_id}/quality-issue-sources` unchanged: `wa_backend/api/warehouse/live_stock.py:2426`; `inventory.read` authorization at `:2444`; tenant-scoped variant lookup at `:2464`; exact readable-location filtering in both page selection (`:2503`) and source projection (`:2607`). The existing page includes batch/source/reservation evidence and server-derived purposes; default page size remains 25. No new endpoint, per-batch source request, backend authority or query change.
- The dedicated hierarchy is **Product → displayed affected batches → warehouse/vehicle sources → reserved/movable quantities → existing server-derived actions**. `WholeProductIssueBatchSection.tsx` owns compact batch headers, saved disposition reason and locale-formatted expiry. It composes the existing `BatchQuantityActions` with a presentation-only header slot; mutation payloads, durable scopes, permissions, destination selection and reservation navigation stay unchanged. The existing Phase 1 exact-transfer follow path is reused; default presentation of other callers is unchanged.
- The company-wide hold is visible read-only context after the active-RECALL read succeeds. There is no Catalog mutation or readiness calculation/display. Empty readable stock does not imply issue completion. Loaded-batch counts explicitly count displayed, permission-filtered rows; hidden identities/counts/quantities are never reconstructed. Both fresh capabilities and fresh paginated source evidence are required; mismatches/revocation fail closed and preserve structured error/request-id presentation. Route focus is consumed safely; closing during loading aborts the read. Phase 1 batch focus remains separate and unchanged in behavior.
- **Acceptance:** `dashboard/src/test/whole-product-quality-workspace.test.tsx` has **9 passing cases** for typed workspace entry without warehouse shell/modal, multiple batches, warehouse + vehicle sources, reserved versus movable quantities and allowed purposes, redacted/read-only sources, released batch versus company-wide hold context, Arabic RTL/English LTR/Western digits, keyboard focus and back/close, bounded pagination without per-batch reads, warm-cache revocation, mismatched identity and pending-read abort. Together with affected Phase 1, existing quality-contract and boundary tests: **36 focused cases passed** (9 workspace cases plus 27 unchanged affected regression/contract cases). ESLint passes on all nine changed/new frontend files; production build passes. Only the requested focused frontend tests/lint/build were run in this checkpoint; no backend tests, broad suite or new TypeScript run.
- **Scope/remaining gaps:** 2.1 has no known missing functional step in the tested contract. The accepted read endpoint requires an active product RECALL; unrelated/inactive product intents retain the backend's rejection. This checkpoint does not complete 2.2 availability reasons, 2.3 global control/navigation cleanup, 2.4 readiness/full-workflow acceptance, or any Phase 3 terminal command. Live authenticated PostgreSQL/RLS browser acceptance and the previously documented TypeScript baseline remain separate integration limitations.

---

# Phase 3 — Real terminal physical workflows

**Goal:** Complete the missing final step after staging stock for disposal or vendor return.

- [x] **3.1 Terminal disposal backend contract**
  Define the final disposal command and evidence contract. Final disposal must be allowed only for the exact eligible company/location/product/batch/status/quantity, normally at the approved disposal destination with `DISPOSAL_PENDING` stock. Reuse the unified inventory movement/ledger authority; never simulate destruction by moving to another fake location. Revalidate locks/revisions, reservations, permissions, idempotency, and current policy/state.

- [x] **3.2 Final disposal inventory effect and evidence**
  Successful disposal removes the disposed quantity from company-owned on-hand inventory through canonical inventory authority and leaves immutable evidence: operator, timestamp, product, batch, source location, quantity/UOM, reason/method/reference as appropriate, request identity, originating transfer/evidence links, ledger, audit, and required outbox events.

- [x] **3.3 Terminal vendor-return backend contract**
  Determine and reuse the authoritative supplier/vendor reference. Add/reuse a terminal handover command distinct from staging. Enforce exact-location authorization, eligible status/quantity, safe reservation state, revision/lock checks, idempotent retries, and immutable original transfer evidence.

- [x] **3.4 Terminal UI + end-to-end acceptance**
  UI exposes simple human actions such as `تأكيد إتلاف الكمية` and `تأكيد تسليم الكمية للمورد` only when backend says they are eligible. Full automated paths must prove: source stock → staging transfer → staging receipt → terminal action → company total decreases → ledger/audit evidence exists → duplicate request remains harmless/idempotent.

**Phase 3 done when:** “Disposal” and “return to vendor” have real terminal business outcomes, not only staging transfers.

---

# Phase 4 — End-to-end acceptance and closure

- [x] **4.1 Backend + E2E contract matrix**
  Cover state transitions, permissions, tenant/location isolation, multi-warehouse stock, vehicle stock, reservation owners, policy destinations, hidden sources, terminal disposal, terminal vendor return, readiness, retries/idempotency, ledger/audit evidence, and browser-level cross-page navigation.
  - **Closure evidence — 2026-10-04:** the focused backend closure gate is **77/77 PASS**, covering multi-location/vehicle visibility, hidden-source and tenant/location isolation, reservation ownership, server-derived action reasons, whole-product readiness, terminal disposal/vendor handover, provenance, replay/idempotency, and canonical movement/event/evidence contracts. The production frontend build passes. Browser acceptance is **12/12 PASS**, including true Products → Inventory navigation in Arabic and English plus one/two warehouses, warehouse + vehicle, vehicle-only, hidden-source, wrong-saved-warehouse, consumed route-state, and keyboard-focus cases.

- [x] **4.2 UX/accessibility acceptance**
  Arabic RTL, English LTR, Western digits, keyboard navigation, Enter/Escape where safe, focus entry/return, no dead links, and no ambiguous backend language. A final manual walkthrough must be understandable without knowing `RECALL`, `RECALL_RETURN`, `DISPOSAL_PENDING`, transfer internals, or blocker codes.
  - **Closure evidence — 2026-10-04:** restored the corrupt Arabic terminal-action copy, removed backend-oriented terminal wording, made final confirmation safely form-submit capable for Enter, and fixed opener focus restoration by letting the shared modal own initial focus. The focused UX matrix is **45/45 PASS** across six workflow suites; terminal-action UX is **5/5 PASS** for Arabic RTL, Western digits, Enter, Escape, focus entry/return, required human evidence, and raw-backend-code suppression. Production build and the **12/12** browser matrix pass; the final browser/user-visible walkthrough review has no known dead link or required backend-code interpretation in this workflow.

- [x] **4.3 Architecture + performance audit**
  Products has no Inventory mutation authority; Inventory does not redefine Catalog identity/lifecycle; no sibling-page business imports; no localStorage business-command bus; no new mega-files/god hooks; no N+1 source/action discovery; read contracts remain bounded/paginated.
  - **Closure evidence — 2026-10-04:** the audit confirmed Catalog/Inventory authority separation and typed navigation, then closed every demonstrated performance/authority gap: terminal provenance reads are SQL-bounded before materialization, quality-source limits are checked set-wise before source/owner detail loading, terminal read-capacity errors remain explicit business `409`s, Live Stock warehouse-summary deltas use one set-based update, the TRANSIT company guard is restricted to singleton provisioning/recheck rather than the normal path, and batch-disposition targets now come from the backend authority instead of a React transition matrix. Focused closure gates are **90/90 backend PASS**, **41/41 frontend PASS**, production build PASS, and **12/12 browser PASS**.

- [x] **4.4 Stable merge/cleanup**
  Merge completed branches to `main`, delete temporary branches/worktrees, confirm local `main == origin/main`, preserve local `RUN.txt`, and remove this plan only after every item is `[x]`.
  - **Closure evidence — 2026-10-04:** the completed gate fast-forwarded into `main`; `RUN.txt` and the local handoff file were hash-verified unchanged across the merge; all workflow worktrees and temporary local/remote branches were removed; only the `main` worktree remains; and local `main == origin/main`. One non-Git leftover temp directory may remain because Windows denied filesystem deletion, but it is no longer a Git worktree and holds no branch authority.

---

## 4. Parallel execution lanes

### Lane A — Core terminal workflows

Owns:
- Phase 2 whole-product workspace integration where it touches current quality-manager code.
- Phase 3 terminal disposal.
- Phase 3 terminal vendor handover.
- Backend domain authority, ledger/audit/idempotency, and terminal evidence.

### Lane B — Batch navigation + automated workflow scaffolding

Owns:
- Phase 1 batch-centric multi-location navigation.
- Focused navigation/read-contract tests.
- Browser/E2E scaffolding that does not modify terminal command implementation files.

### Integration rule

- Each lane uses a separate branch/worktree.
- Do not edit the same plan section concurrently unless coordinated.
- Integrate only at small stable checkpoints.
- Root-cause/code analysis precedes tests; tests prove the fix rather than discover the design.

---

## 5. Definition of complete

The plan is complete only when:

1. A product/batch issue can start from Products without Products becoming an Inventory mutation surface.
2. The same batch can exist in many warehouses/vehicles and the UI handles that explicitly and permission-safely.
3. A whole-product confirmed issue has a dedicated, understandable Inventory workflow.
4. If an action is unavailable, the user receives a concrete server-derived explanation.
5. Disposal has a real final destruction step that removes quantity from company-owned inventory and leaves ledger/audit evidence.
6. Vendor return has a real final handover step that removes quantity from company-owned inventory and leaves counterparty/audit evidence.
7. Reservations and owner operations remain owned by their authoritative modules.
8. Readiness to resume sales is backend-derived and cannot be bypassed by UI navigation.
9. Automated tests prove the full cross-module flow, multi-location isolation, retries, and terminal inventory effects.
10. Final manual acceptance is simple enough that the user never has to decode backend concepts.
