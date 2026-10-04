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

- [ ] **1.1 Batch-first focus and source resolution**  
  Treat `batchId` as the primary focus identity. Resolve the batch from authoritative `stock-sources` before relying on the selected warehouse. If exactly one readable source exists, Inventory may select it for context; if multiple sources exist, do not silently choose one.

- [ ] **1.2 Multi-source batch workspace**  
  Show every readable warehouse/vehicle source with quantity, stock status, reservation, and allowed actions. Do not leak unauthorized source identities/counts/quantities. Remove contradictory background states such as “no matching products” while the focused batch is open.

- [ ] **1.3 Permission-safe navigation contract**  
  Route state remains a hint only. Destination must re-fetch the batch and exact-location permissions. Hidden company blockers may be reported only through non-leaking signals.

- [ ] **1.4 Automated Phase 1 acceptance**  
  Cover one warehouse, two warehouses, warehouse + vehicle, vehicle-only, wrong-last-selected-warehouse, and no-access-to-second-location cases.

**Phase 1 done when:** A Products warning opens the exact batch correctly from any prior warehouse context and multi-location stock is explicit without implicit authority.

---

# Phase 2 — Dedicated whole-product quality workspace

**Goal:** A confirmed problem affecting the entire product must have a clear Inventory-owned workspace instead of behaving like a hidden Batches-tab modal.

- [ ] **2.1 Dedicated workspace and clear hierarchy**  
  `quality-issue` opens a distinct Inventory workspace/state. Present `Product → affected batches → physical sources → reserved/movable quantities → available actions`. Keep the company-wide product hold visible without letting Inventory silently redefine Catalog lifecycle.

- [ ] **2.2 Backend action-availability reasons**  
  Replace “empty allowed list” UX with a backend availability contract that returns safe reason codes such as: no configured destination, insufficient permission, fully reserved, source cannot send, already at destination, lifecycle/state restriction, or no movable quantity. Frontend only translates these reasons.

- [ ] **2.3 Remove dead-end and duplicate controls**  
  Do not show generic “open transfers” unless there is an actual transfer or owner workflow to follow. `عرض الرصيد` remains read-only context if retained; `المشكلة مؤكدة — التعامل مع الكميات الحالية` opens the executable workspace. Different labels must not open the same workflow while implying different meanings.

- [ ] **2.4 Readiness and automated Phase 2 acceptance**  
  Backend remains the only authority for `ready_to_resume_sales`. Cover multiple batches, multiple warehouses, vehicle source, partial permissions, reservations, no-action reasons, hidden blockers, and readiness remaining false until company-level requirements are truly complete.

**Phase 2 done when:** A manager can understand exactly what remains for a whole-product issue without knowing backend terminology, and every visible action/reason is server-derived.

---

# Phase 3 — Real terminal physical workflows

**Goal:** Complete the missing final step after staging stock for disposal or vendor return.

- [ ] **3.1 Terminal disposal backend contract**  
  Define the final disposal command and evidence contract. Final disposal must be allowed only for the exact eligible company/location/product/batch/status/quantity, normally at the approved disposal destination with `DISPOSAL_PENDING` stock. Reuse the unified inventory movement/ledger authority; never simulate destruction by moving to another fake location. Revalidate locks/revisions, reservations, permissions, idempotency, and current policy/state.

- [ ] **3.2 Final disposal inventory effect and evidence**  
  Successful disposal removes the disposed quantity from company-owned on-hand inventory through canonical inventory authority and leaves immutable evidence: operator, timestamp, product, batch, source location, quantity/UOM, reason/method/reference as appropriate, request identity, originating transfer/evidence links, ledger, audit, and required outbox events.

- [ ] **3.3 Terminal vendor-return backend contract**  
  Determine and reuse the authoritative supplier/vendor reference. Add/reuse a terminal handover command distinct from staging. Enforce exact-location authorization, eligible status/quantity, safe reservation state, revision/lock checks, idempotent retries, and immutable original transfer evidence.

- [ ] **3.4 Terminal UI + end-to-end acceptance**  
  UI exposes simple human actions such as `تأكيد إتلاف الكمية` and `تأكيد تسليم الكمية للمورد` only when backend says they are eligible. Full automated paths must prove: source stock → staging transfer → staging receipt → terminal action → company total decreases → ledger/audit evidence exists → duplicate request remains harmless/idempotent.

**Phase 3 done when:** “Disposal” and “return to vendor” have real terminal business outcomes, not only staging transfers.

---

# Phase 4 — End-to-end acceptance and closure

- [ ] **4.1 Backend + E2E contract matrix**  
  Cover state transitions, permissions, tenant/location isolation, multi-warehouse stock, vehicle stock, reservation owners, policy destinations, hidden sources, terminal disposal, terminal vendor return, readiness, retries/idempotency, ledger/audit evidence, and browser-level cross-page navigation.

- [ ] **4.2 UX/accessibility acceptance**  
  Arabic RTL, English LTR, Western digits, keyboard navigation, Enter/Escape where safe, focus entry/return, no dead links, and no ambiguous backend language. A final manual walkthrough must be understandable without knowing `RECALL`, `RECALL_RETURN`, `DISPOSAL_PENDING`, transfer internals, or blocker codes.

- [ ] **4.3 Architecture + performance audit**  
  Products has no Inventory mutation authority; Inventory does not redefine Catalog identity/lifecycle; no sibling-page business imports; no localStorage business-command bus; no new mega-files/god hooks; no N+1 source/action discovery; read contracts remain bounded/paginated.

- [ ] **4.4 Stable merge/cleanup**  
  Merge completed branches to `main`, delete temporary branches/worktrees, confirm local `main == origin/main`, preserve local `RUN.txt`, and remove this plan only after every item is `[x]`.

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
