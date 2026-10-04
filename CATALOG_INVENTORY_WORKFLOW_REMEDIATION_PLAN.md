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
- [ ] Produce a dependency map of current cross-page imports and navigation bridges involving `pages/products`, `pages/inventory`, lifecycle, batch issue navigation, and blockers.
- [ ] Record each current violation as either architectural debt or acceptable read-only cross-domain projection.

**Exit gate:** no ambiguous ownership remains for the workflows in this plan.

---

# Phase 1 — Fix frontend ownership without changing business behavior

Purpose: remove the accidental coupling before changing UX behavior.

## 1.1 Product lifecycle ownership

- [ ] Move Product/Catalog lifecycle UI out of `pages/inventory/catalog` into Product/Catalog-owned frontend structure.
- [ ] `ProductsPage` must not import Inventory page business-action components.
- [ ] Keep backend catalog endpoints/contracts unchanged unless a proven gap requires a separately approved change.
- [ ] Preserve current permissions, durable request IDs, and mutation semantics during the move.

## 1.2 Shared code rules

- [ ] Extract only generic UI primitives or pure navigation contracts when genuinely shared.
- [ ] Do not create a generic `shared business logic` folder.
- [ ] Keep Product-specific DTO parsing with Products when the API response belongs to Products.
- [ ] Keep Inventory batch/quantity DTO parsing with Inventory.

## 1.3 Navigation contract

- [ ] Replace cross-module localStorage workflow signaling with an explicit typed navigation intent.
- [ ] Navigation may carry `variant_id`, `batch_id`, `location_id`, and target surface as hints only.
- [ ] Inventory must independently resolve and authorize every target.
- [ ] Preserve localStorage only for harmless UI preferences such as last selected tab/location when appropriate.

**Exit gate:** no Products business component imports Inventory internal business UI, and vice versa.

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