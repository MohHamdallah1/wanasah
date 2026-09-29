# Supplier invoice price correction after stock has moved

**Status:** REVIEWED DESIGN / **NOT IMPLEMENTED** — separate release gate.
**Related authority:** `INVENTORY_COSTING_FINANCIAL_TRUTH_DECISION.md` (single authoritative cost method).
**Business example:** 10 units purchased at JOD 2, 6 units sold, supplier confirms actual purchase price was JOD 2.50. Gross acquisition delta = **JOD 5**. With one isolated acquisition and no other purchases/reversals, JOD 2 belongs to the 4 remaining units and JOD 3 to the 6 units sold. **Never apply that physical 4:6 split mechanically once mixed purchases, FIFO allocations, moving average changes, adjustments, returns or period boundaries exist.**

## 1. Critical invariants

- **No UPDATE/DELETE on a posted `InventoryCostEvent`, sale evidence or original purchase movement.** The original unit cost, actor, supplier reference and posting timestamp are historical facts, even when the originally recorded supplier price later proves inaccurate. A later correction has its own effective date, posting date, actor and source-document identity.
- Manufacturer's `ProductBatch` is **not** an accounting purchase layer. Distinct receipt events can share a lot number and have different prices. Correct a **specific original purchase/cost event**, never every row in the batch.
- One financial COGS and inventory valuation authority: adjustments must reconcile to the same elected company costing policy and source event chain; no parallel "real batch profit" ledger.
- Every correction is tenant- and actor-authorized, permission checked, concurrency guarded, versioned/idempotent, append-only and auditable. Duplicated supplier invoice/credit note or duplicate request ID must not double-post.
- A supplier's **new rebate/credit note** is not automatically the same as discovery of an error that was knowable at the original reporting date. Determine accounting treatment from source documents and financial-period state rather than guessing.
- A **closed financial reporting period** may require an IAS 8 comparative restatement or other accountant-approved presentation if the original period contains a material error; never silently post a material prior-period adjustment into current profit or rewrite a published prior period. Financial-period close/reopen and amendment authority must be versioned and explicit.

## 2. Exact calculation authority by selected method

- **Moving average:** An earlier purchase-price correction can affect moving average cost at the purchase date, subsequent averages whenever more receipts arrive, COGS of later outward movements, return/reversal amounts and ending inventory. It is **not generally** safe to multiply the new unit-price delta by today's physical units in the manufacturer lot. Re-evaluate the authoritative financial event sequence at its original chronology, calculate the accounting-period inventory and COGS delta, and post a signed, uniquely identified adjustment with a balanced bridge.
- **Financial FIFO:** The source purchase creates a financial acquisition layer. Use its **actual financial FIFO consumption allocations** to determine the consumed portion and the remaining portion of that **source layer**, independently of FEFO batch selection. Apply controlled signed adjustments to its remaining financial value and prior/current COGS through explicit adjustment records, without editing the original receipt or pretending physical batch numbers identify FIFO layers. Later reversals, disposals and returns must reconcile.
- For either method, **acquisition delta = eligible correction to remaining inventory value + applicable COGS/expenses adjustments + other explicitly classified differences** with defined period, currency and rounding policy. Preserve a zero-variance gate or stop.
- Handle multiple purchase UOMs, conversions, currency and exchange rate authority, late freight/landed costs, discounts, supplier credits, taxes, damaged stock, stock transfers, replacement, gifts/samples, expiry write-down, retroactive negative deltas, consumed-to-zero inventory and partial quantities. A return must reference the authoritative original financial cost evidence.
- Never retrospectively revise the actual historical sale price/discount/tax, or the originally recorded sale cost event, simply because a supplier invoice was corrected. Show a linked adjustment and an **as-restated** period presentation only where an approved accounting-close workflow explicitly authorizes it.

## 3. Required append-only contract before exposing an edit button

Proposed dedicated **Inventory Cost Correction** command/ledger (not an authorized migration yet):

`(company_id, request_id, original_purchase_cost_event_id, supplier_document_id, supplier_correction_reference, original_purchase_UOM, new_confirmed_unit_cost, original_recorded_unit_cost, delta, selected_method_snapshot, affected_financial_period, posting_period, approval_status, approved_by, posted_by, posted_at, source_sha256, revision, idempotency_hash)`.

A separate append-only **valuation/COGS allocation** links each correction to the original acquisition event and the current financial cost state (and FIFO cost layer/allocations where applicable). Show the original + new supplier evidence + adjustment to the accountant, and provide a narrow audit report: original cost; changed supplier amount; remaining-inventory adjustment; cost-of-sales/expense adjustment; period treatment; rounding/FX; status. Nothing is booked until the accounting period and purchase-cost model can actually support the command. Define amount/rate precision and reverse/compensate paths rather than allowing edits to posted corrections.

**Fail closed:** if the source receipt, cost layer history, stock/COGS coverage, authority, currency exchange basis, financial-period state or rollback support is missing or inconsistent, reject with an actionable error and leave previous journal/cost events unchanged.

## 4. Test gates / operational scope

- [ ] **RC1** Source invoice correction type, original receipt identifier, cost adjustments, permissions and supplier-tax/document rules are signed off by owner/accountant.
- [ ] **RC2** Append-only schema, authorized API, idempotency (same request replay/different payload conflict), tenant-safe FK/RLS, audit, optimistic concurrency and selective approvals.
- [ ] **RC3** Moving-average replay-to-adjustment parity at every intermediate purchase/sale/return in mixed cost scenarios.
- [ ] **RC4** FIFO layer-by-layer consumed/remaining reconciliation, including FEFO-vs-FIFO divergence.
- [ ] **RC5** Current/open vs closed/prior period accounting classification, material error/restate vs credit note, foreign currency and financial rounding.
- [ ] **RC6** Actual UI approval/reconciliation/rollback, historical report versions, failed/timeout/retry behavior, Flutter offline and bounded performance with 50k+ rows.
- [ ] **RC7** Controlled DB/HTTP negative gates prove original immutable events unchanged, exactly one financial truth, zero double-posting and no inventory-quantity mutation.

**Existing V1 behavior verified at source:** `wa_backend/api/warehouse/inbound.py` prohibits reposting the same supplier reference; `InventoryCostEvent` is append-only, and existing FIFO reversal can fail when its layer was consumed. This **does not** constitute an approved, correct supplier price correction workflow after a sale. The current UI must not provide a destructive "edit posted price" shortcut.

## 5. Standards reference

[IAS 2](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/) addresses inventory cost formulas and cost recognition. [IAS 8](https://www.ifrs.org/issued-standards/list-of-standards/ias-8-basis-of-preparation-of-financial-statements/) distinguishes current-period estimates, errors and material prior-period restatements. Jurisdiction-specific reporting and tax amendments require separately verified company accountant approval.

**No code/schema for retroactive correction is claimed or authorized by this design note.** Explicit method selection (C1/C2) is a separate, presently implemented and tested workstream.
