# INVENTORY_RECEIPT_LOT_TERMINOLOGY_CLOSURE_PLAN

**Status:** V1 focused cleanup — no inventory-engine rewrite.
**Decision authority:** `ARCHITECTURE.md` canonical receipt/lot separation decision dated 2026-10-29.

## Goal

Make the existing Design-1 architecture obvious and safe in user-facing workflows: receipt/invoice identity stays separate from physical Lot tracking, while backend-only no-Lot identities remain hidden from operators.

## Scope

- [x] **1. Canonical architecture decision**
  - Supplier receipt/invoice = inbound business event.
  - Supplier invoice/reference != Lot.
  - Genuine Lot may repeat across multiple receipts.
  - Cost evidence/layers remain receipt-based and separate from physical Lot identity.
  - Arabic UI terminology: `توريد` for receipt, `تشغيلة` for Lot; avoid ambiguous unqualified `دفعة`.

- [ ] **2. Transfer UX cleanup**
  - Keep automatic FEFO as the default when a real Lot exists.
  - Rename manual physical choice to `تغيير التشغيلة`.
  - Show manual Lot choice only when the operator can distinguish a genuine human-readable Lot.
  - Never show backend synthetic/no-Lot identities as repeated `بدون رقم دفعة` options.
  - Keep internal allocation authoritative for products with no user-facing Lot.

- [ ] **3. Inbound terminology and evidence audit**
  - Verify receipt/invoice fields remain separate from `batch_number`/Lot fields.
  - Verify `NONE / OPTIONAL / REQUIRED` lot policy behavior matches `ARCHITECTURE.md`.
  - Verify repeated genuine Lot across separate receipts remains supported without merging receipt/cost evidence.

- [ ] **4. Cross-workflow terminology audit**
  - Inventory details, recall, quarantine, stocktake, returns, transfers and reports must use `تشغيلة` only for physical Lot identity.
  - Remove or relabel ambiguous user-facing `دفعة` wording where it means receipt or internal identity.

- [ ] **5. Acceptance tests**
  - Same genuine Lot received in two separate invoices remains one physical Lot identity with two independent receipt/cost histories.
  - No-Lot products never expose synthetic identities to the operator.
  - REQUIRED Lot products fail closed when genuine Lot evidence is missing.
  - Transfer/recall/stocktake preserve genuine Lot provenance.
  - Costing behavior remains unchanged.

- [ ] **6. Closeout**
  - Mark completed items `[x]`.
  - Merge only after focused backend + Dashboard gates pass.
  - Delete the task branch after merge and sync local `main` once.

## Explicit non-goals

- No conversion of supplier invoice/reference into ProductBatch/Lot identity.
- No redesign of accounting costing authority.
- No destructive migration or rewrite of historical inventory.
- No requirement that every product have a manufacturer Lot.
- No exposure of internal `batch_id` or synthetic no-Lot identifiers to users.

## Expected size

**Small-to-medium focused closure.** The core backend architecture already follows Design 1. Most remaining work is UI terminology, hiding internal identities, transfer behavior cleanup, and regression tests. A database migration is not expected unless the audit discovers data that violates the existing architecture contract.
