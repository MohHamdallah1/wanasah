# Inventory Quality Workflow Completion Plan

**Status:** ACTIVE — execution plan  
**Created:** 2026-10-04  
**Scope:** Complete the inventory quality workflows end-to-end after the Catalog/Inventory boundary remediation.  
**Canonical architecture:** `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `docs/architecture/CATALOG_INVENTORY_WORKFLOW_BOUNDARIES.md`.

## 1. Goal

Finish the operational foundation before adding more inventory features.

The required product quality is:

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

These are confirmed from the current implementation and manual acceptance:

- Product batch-warning navigation carries `variantId + batchId`, but the Batches page still visually depends on the currently selected warehouse. A valid affected batch can therefore open while the background page says “no matching products”.
- The same company-level `ProductBatch` may physically exist in multiple warehouse/vehicle locations. The workflow must therefore be **batch-centric**, not silently bound to one arbitrary warehouse.
- Whole-product confirmed-quality flow is currently hosted under the Batches tab even though it can span multiple batches, warehouses, vehicles, reservations, and owner operations.
- `allowed_purposes` currently tells the UI what actions are allowed, but an empty list does not explain why no action is available.
- The generic “open transfers” button can appear without a concrete transfer/action context and confuses the workflow.
- `DISPOSAL` currently means transfer to the configured disposal location; on receive, stock becomes `DISPOSAL_PENDING`. **This is not final destruction.**
- `RETURN_TO_VENDOR` currently represents a controlled transfer/staging path. Reaching the staging destination is **not proof of vendor handover**.
- Final terminal evidence for destruction and vendor handover is not yet a complete user workflow.

---

# Phase 1 — Batch-centric multi-location navigation

**Owner:** Inventory UI + read contracts.  
**Goal:** Opening an affected batch must work correctly regardless of the warehouse currently selected in Inventory.

- [ ] **1.1 Batch focus contract:** Treat `batchId` as the primary focus identity. Inventory must resolve the batch from authoritative `stock-sources` before relying on the selected warehouse.
- [ ] **1.2 One-source behavior:** If the user can read exactly one physical source for the batch, the Inventory shell may select that source automatically for context, without changing batch authority.
- [ ] **1.3 Multi-source behavior:** If the batch exists in multiple readable warehouses/vehicles, do not silently choose one. Open the batch workspace and list every readable source with its quantity/status/actions.
- [ ] **1.4 Permission-safe hidden sources:** Do not expose identities, counts, names, or quantities of unauthorized locations. If company-level backend safety still blocks completion because of hidden work, return only a safe non-leaking blocker signal.
- [ ] **1.5 Background UX cleanup:** A focused batch must never display a contradictory “no matching products in this warehouse” primary state behind the active batch workflow.
- [ ] **1.6 Automated acceptance:** Cover one warehouse, two warehouses, warehouse + vehicle, vehicle-only, and no-access-to-second-location cases.

**Phase 1 done when:** A warning from Products opens the exact batch correctly even if the user was last viewing another warehouse, and multi-location stock is presented without implicit cross-location authority.

---

# Phase 2 — Dedicated whole-product quality workspace

**Owner:** Inventory.  
**Goal:** A confirmed problem affecting the entire product must have a clear Inventory-owned workspace instead of behaving like a hidden Batches-tab modal.

- [ ] **2.1 Dedicated navigation intent/workspace:** `quality-issue` must open a distinct Inventory workspace/state, not pretend to be a normal warehouse Batches view.
- [ ] **2.2 Clear hierarchy:** Show `Product → affected batches → physical sources → reserved/movable quantities → available actions`.
- [ ] **2.3 Company-wide hold remains visible:** Clearly state that sale of the product remains stopped company-wide while physical work is incomplete; the workspace itself does not silently change Catalog lifecycle state.
- [ ] **2.4 Explain action availability:** Replace plain `allowed_purposes=[]` UX with an authoritative backend action-availability contract that can return safe reason codes such as: no configured destination, insufficient permission, fully reserved quantity, source cannot send, already at destination, lifecycle/state restriction, or no movable quantity. Frontend only translates these reason codes.
- [ ] **2.5 Remove generic dead-end controls:** Do not show “open transfers” unless there is an actual transfer to follow or a concrete owner workflow to open.
- [ ] **2.6 Fix duplicated/ambiguous entry points:** `عرض الرصيد` must remain read-only context if retained. `المشكلة مؤكدة — التعامل مع الكميات الحالية` must open the executable Inventory workspace. Two labels must not open the same workflow while implying different meanings.
- [ ] **2.7 Readiness truth:** Backend remains the only authority for `ready_to_resume_sales`. UI must never infer completion from visible rows alone.
- [ ] **2.8 Automated acceptance:** Cover multiple batches, multiple warehouses, vehicle source, partial permissions, reservations, no available action with explicit reason, and readiness remaining false while hidden/company blockers exist.

**Phase 2 done when:** A manager can understand exactly what remains for a whole-product issue without knowing backend terminology, and every visible action/reason is server-derived.

---

# Phase 3 — Real terminal physical workflows

**Owner:** Backend Inventory authority first; thin UI second.  
**Goal:** Complete the missing final step after staging stock for disposal or vendor return.

## 3A. Final disposal

- [ ] **3.1 Domain design:** Define the terminal disposal command and evidence contract. Reuse existing movement/ledger authority; do not simulate destruction by moving to another fake location.
- [ ] **3.2 Preconditions:** Final disposal is allowed only for the exact company/location/product/batch/status/quantity that is eligible (normally at the approved disposal destination with `DISPOSAL_PENDING` stock), with reservations and in-flight operations handled safely.
- [ ] **3.3 Permission and concurrency:** Add/reuse the narrowest explicit disposal-confirm permission; lock/revalidate authoritative rows; require idempotent request identity and safe retries.
- [ ] **3.4 Inventory effect:** Successful final disposal must reduce company-owned on-hand quantity by the disposed amount through approved inventory authority and must never make the quantity silently sellable again.
- [ ] **3.5 Evidence:** Persist auditable terminal evidence: company, operator, timestamp, product variant, batch, source location, quantity/UOM, reason/method/reference as appropriate, request identity, and links to originating transfer/evidence when available.
- [ ] **3.6 Ledger/audit/outbox:** Produce the canonical inventory ledger/movement evidence and required audit/outbox events. No direct balance mutation without ledger truth.
- [ ] **3.7 UI:** In the disposal location/workspace show a simple human action such as `تأكيد إتلاف الكمية`, confirmation summary, and final success evidence. Do not expose `DISPOSAL_PENDING` as the primary business language.
- [ ] **3.8 Automated acceptance:** Full path: source stock → disposal staging transfer → receive at disposal location → final disposal → company total decreases → ledger/audit evidence exists → repeated request is idempotent.

## 3B. Final return to vendor

- [ ] **3.9 Counterparty/evidence authority:** Determine and reuse the authoritative supplier/vendor reference already available to the inventory/purchasing data. If no authoritative supplier identity exists for this flow, define the smallest explicit V1 evidence contract instead of burying the counterparty in free text.
- [ ] **3.10 Terminal handover command:** Add/reuse a command representing actual vendor handover, distinct from moving stock to a return-staging location.
- [ ] **3.11 Preconditions, permissions, concurrency:** Exact-location authorization, eligible status/quantity, no unsafe reservations, revision/lock checks, idempotent retries, and immutable original transfer evidence.
- [ ] **3.12 Inventory effect:** Confirmed vendor handover removes the handed-over quantity from company-owned on-hand inventory through canonical movement/ledger authority.
- [ ] **3.13 Evidence:** Persist supplier/vendor, product, batch, quantity/UOM, operator, timestamp, reason/reference, originating receipt/transfer references when available, request identity, audit/outbox evidence.
- [ ] **3.14 UI:** Show a simple action such as `تأكيد تسليم الكمية للمورد` only when backend says the stock is ready for terminal handover.
- [ ] **3.15 Automated acceptance:** Full path: source stock → return staging → vendor handover → company total decreases → ledger/audit evidence exists → duplicate request is harmless/idempotent.

**Phase 3 done when:** “Disposal” and “return to vendor” have real terminal business outcomes, not only staging transfers.

---

# Phase 4 — End-to-end acceptance and closure

**Goal:** Prove that the workflow is operationally complete, scalable, and understandable.

- [ ] **4.1 Backend contract matrix:** Automated tests cover state transitions, permissions, tenant/location isolation, multi-warehouse stock, vehicle stock, reservation owners, policy destinations, hidden sources, terminal disposal, terminal vendor return, readiness, retry/idempotency, and audit/ledger evidence.
- [ ] **4.2 Frontend/E2E workflow:** Automate the main journey from Products warning/quality decision through Inventory actions to terminal completion, including failure/retry paths. Prefer browser-level tests for cross-page navigation and focus behavior.
- [ ] **4.3 UX/accessibility:** Arabic RTL, English LTR, Western digits, keyboard navigation, Enter/Escape where safe, focus entry/return, no dead links, no ambiguous backend language.
- [ ] **4.4 Architecture audit:** Products has no Inventory mutation authority; Inventory does not redefine Catalog identity/lifecycle; no sibling-page business imports; no localStorage business-command bus; no new mega-files/god hooks.
- [ ] **4.5 Performance:** No N+1 source/action discovery. Batch and whole-product read contracts remain bounded/paginated and query counts are verified for multi-location cases.
- [ ] **4.6 Manual product acceptance:** One final human walkthrough validates that the UI is obvious without backend knowledge. Any “what am I supposed to do here?” moment reopens the responsible item.
- [ ] **4.7 Stable merge/cleanup:** Merge completed branches to `main`, delete temporary branches/worktrees, confirm local `main == origin/main`, and preserve local `RUN.txt` changes.

---

## 4. Parallel execution lanes

To avoid branch/file collisions:

### Lane A — Core terminal workflows

Owns:
- Phase 2 whole-product workspace integration where it touches the current quality manager.
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

This plan is complete only when all of the following are true:

1. A product/batch issue can be started from Products without Products becoming an Inventory mutation surface.
2. The same batch can exist in many warehouses/vehicles and the UI handles that explicitly and permission-safely.
3. A whole-product confirmed issue has a dedicated, understandable Inventory workflow.
4. If an action is unavailable, the user receives a concrete server-derived explanation, not a generic dead end.
5. Disposal has a real final destruction step that removes quantity from company-owned inventory and leaves ledger/audit evidence.
6. Vendor return has a real final handover step that removes quantity from company-owned inventory and leaves counterparty/audit evidence.
7. Reservations and owner operations remain owned by their authoritative modules.
8. Readiness to resume sales is backend-derived and cannot be bypassed by UI navigation.
9. Automated tests prove the full cross-module flow, multi-location isolation, retries, and terminal inventory effects.
10. A final manual walkthrough is simple enough that the user does not need to understand `RECALL`, `RECALL_RETURN`, `DISPOSAL_PENDING`, transfer internals, or backend blocker codes.
