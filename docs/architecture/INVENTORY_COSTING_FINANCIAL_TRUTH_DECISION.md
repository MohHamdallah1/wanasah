# ADR — One financial inventory truth, receipt-cost evidence, and optional batch analytics

**Recorded:** 2026-09-29  
**Decision status:** **V1 direction accepted; explicit costing choice C1 IMPLEMENTED and developer-tested; further C2-C5/reconciliation gates OPEN**.
**Scope:** Wanasah inventory costing, supplier receipts, physical inventory, sales/returns, valuation, future reporting and Flutter contracts.  
**Owner:** Inventory Costing / Financial Valuation domain. Catalog and warehouse own their existing data; Reporting may read approved projections but may not independently determine accounting COGS.

## 1. Business answer, in plain Arabic

**طريقة واحدة معتمدة لحساب تكلفة المبيعات وقيمة المخزون وأرباح الشركة المحاسبية. الشركة تختار FIFO أو المتوسط المتحرك قبل أول توريد بتكلفة؛ لا يختار النظام بصمت نيابة عنها. نحتفظ بالتكلفة الحقيقية لكل عملية توريد لأغراض التتبع والمراجعة. لا نبني محرك أرباح محاسبي ثانٍ لكل دفعة ولا نعرض رقمًا ثانيًا كأنه صافي/إجمالي ربح الشركة.**

**Physical batch/expiry tracking is NOT a second accounting valuation ledger.** A manufacturer's lot may be received more than once, at different purchase costs. A batch code alone must never be interpreted as one immutable financial acquisition cost.

## 2. Accepted V1 architecture: one authoritative valuation stream

1. **Exactly one company-selected accounting cost formula** for a given class of interchangeable goods: `MOVING_AVERAGE` or `FIFO` as permitted by the governing accounting policy. Respect the same-formula-for-similar-nature/use constraint. This is not a per-sales-line toggle.
2. The Inventory Costing domain alone records authoritative **financial inventory value and accounting COGS** in historical immutable cost events, and FIFO layers/allocations only for companies using FIFO. Sales/financial reports must obtain COGS from those events, never recalculate it from a manufacturer batch's purchase price or the current average.
3. **Actual supplier receipt cost evidence is always recorded and immutable** at the receipt/movement level: purchase UOM, quantity, unit cost, extended cost, relevant allocated landed costs when supported, currency/rate authority where applicable and subsequent documented adjustments/reversals. Reusing one manufacturer batch in multiple receipts does not erase individual acquisition costs.
4. Physical quantities and deterministic **FEFO** allocation are a distinct warehouse authority. A physical sale may consume manufacturer batch B while financial FIFO consumes cost layer A, or moving-average COGS differs from B's acquisition cost. That is expected, not a lost cent. Without carton-level traceability or segregation we must not claim to know the exact carton physically handed to a customer.
5. **One accounting profit figure** for any fixed period and scope: authoritative eligible net sales/revenue minus authoritative COGS (with returns/reversals, discounts, rewards, samples, taxes, net realizable value write-downs, period and currency rules classified consistently). Distinguish gross profit from net profit; overheads are not magically included.
6. Do **not** write two balances, two cost-ledger posting streams, two accounting profit columns, or alternative automatic accounting methods merely to offer a different management view. Do not silently rewrite earlier sale costs when new receipts arrive.
7. If no authorized explicit selection exists before the first **costed supplier receipt**, **fail closed** with a clear actionable error and provide the authorized cost-policy selection UI/API. The selection is auditable/versioned, and the first costed receipt locks it. A displayed default or an auto-provisioned inactive policy does NOT constitute an explicit user choice. Existing active legacy policies need migration/compatibility review, never silent re-selection.

## 3. What V1 may display, without duplicate profit

- On a receipt: **actual recorded acquisition cost** and base-UOM normalized acquisition cost for that receipt (subject to landed-cost adjustment policy). This is historical source evidence, not accounting COGS for an arbitrary later sale.
- On a manufacturer lot: physical on-hand quantity, expiry status and **its constituent receipts and their costs**. Do not flatten heterogeneous receipts into an invented single universal lot cost.
- On product/company financial screens: the **selected method**, current accounted inventory value, recognized COGS and gross profit from the one costing authority, with timestamps/periods and transaction-currency consistency.
- A batch/receipt procurement-cost comparison, expiry-loss/at-risk dashboard or supplier comparison is descriptive operational analysis only. It must not be titled **"profit"**, summed into company P&L, booked as cost, or presented as reconciliation-ready financial income.
- Normal current V1 workflow must not depend on expensive per-sale batch-margin joins, a second valuation pipeline or a second write-time profit calculation.

## 4. Future, optional batch contribution analysis — NOT authorized for V1

Only propose a **separately labeled managerial estimate** if a verified and testable allocation exists between: each sale/discount/tax basis/reward/return -> exact sale items -> deterministic physical batch movement segment -> actual acquisition receipt cost (if multiple receipts share a batch, this further receipt allocation needs evidence). Validate timing, multi-warehouse/vehicle transfers, FEFO vs FIFO divergence, mixed pack/UOM, landed-cost corrections, expiry/write-down, samples, rewards, reversals, currency and rounding.

Any such presentation must:
- Explain it is **non-accounting managerial analysis** and show the canonical accounting profit separately, NOT call both figures "official profit".
- Supply a defined bridge/variance, e.g. `accounting_COGS - allocated_physical_acquisition_cost`, with identical quantity, period, revenue, returns, discounts, and rounding scopes; fail closed if evidence is missing.
- Avoid cost-flow mutations and never treat manufacturer's batch ID alone as an unambiguous receipt ID.
- Be optional, read-side/projection-based, bounded and benchmarked; no unbounded per-line joins on the transactional sales hot path.
- Remain CLOSED until the owner approves a separately reviewed business requirement and negative/performance/reconciliation tests.

**Worked example** (after buying A: 10 units at JOD 1; B: 10 units at JOD 2): one unit of physical batch B is sold at JOD 3. Its receipt-cost *illustration* is JOD 2 and an **illustrative physical-margin estimate** would be JOD 1; moving-average accounting COGS may be JOD 1.5 and accounting gross profit JOD 1.5; financial FIFO may charge JOD 1 and accounting gross profit JOD 2. These are *different concepts*. V1 displays only the one selected accounting result as profit and can display the original receipt costs separately. The example ignores taxes, discounts, freight and rounding for clarity.

## 5. Actual Wanasah source evidence — review conducted 2026-09-29

- `wa_backend/domains/inventory_costing/service.py`: module docstring declares separate physical FEFO vs financial costing authority. `_new_event` copies concrete movement SKU and batch; `PURCHASE_IN` records `PURCHASE_ACTUAL`, source purchase UOM, quantity and cost. Outbound uses `MOVING_AVERAGE` or product-wide acquisition-layer `FIFO`; physical FEFO is intentionally not the financial layer order.
- `wa_backend/models.py`: `InventoryCostEvent` retains receipt and outbound cost events, `InventoryCostLayer` carries provenance batch and per-receipt cost layers for FIFO, `InventoryCostAllocation` records layer consumption. A batch provenance field does NOT mean financial FIFO follows that physical batch.
- `wa_backend/api/warehouse/inbound.py`: existing `ProductBatch` found/created by (`company_id`, `product_variant_id`, `batch_number`), with `on_conflict_do_nothing`. Receipt lines independently supply their purchase costs. **Different receipts may share one manufacturer batch identity**, so a batch is not one purchase-price record.
- `wa_backend/api/driver.py`: driver sale physically allocates by FEFO segments; `domains.sales_evidence` persists financial sale items and price-component evidence. A robust receipt-cost per-batch sales-profit bridge has **NOT** been proven, especially for rewards/returns/samples and repeated receipt batches.
- **Historical issue fixed by V1-C1**: `activate_costing_for_first_receipt` previously created/locked implicit MOVING_AVERAGE on missing/unselected policy. It now requires `selected_at/selected_by` and returns `INVENTORY_COST_POLICY_SELECTION_REQUIRED` before evaluating stock; `cost_policy_payload` exposes `method=null` when unselected. Legacy already-active methods remain locked and unmodified. This line describes historical evidence, NOT current behavior.
- **Important scope:** the earlier A3.2 database gate had only 2 company-38 cost events and 0 frozen price components. That is NOT evidence that all possible financial/reporting/reconciliation cases are already correct.

## 5A. Correcting a supplier price AFTER some units have been sold

See [SUPPLIER_INVOICE_RETROACTIVE_COST_CORRECTION.md](SUPPLIER_INVOICE_RETROACTIVE_COST_CORRECTION.md) for the reviewed future command design, method-specific FIFO/average attribution, audit evidence, and period-close handling. **No posted invoice edit or retroactive adjustment API exists in this checkpoint.** A manufacturer batch is not a receipt/acquisition event. Original purchase and sales cost events remain immutable; any future accepted correction must be a separate append-only financial adjustment, with an exact valuation/COGS reconciliation and the accounting period classified before posting. No claim of a 4/6 physical-lot split without full cost-flow evidence. Never implement a silent history UPDATE or automatically recalculate past issued profit figures.

## 6. Implementation order and acceptance gates (each remains OPEN until proven)

- [x] **V1-C1 — explicit costing choice in backend and Dashboard:** `InventoryCostPolicy.selected_at/selected_by` with tenant-safe FK, atomic advisory guard, immutable active legacy policy, idempotent authorized policy PUT, nullable unselected UI DTO, visible accessible user choice, and deny-first-receipt guard. Migration `ce41f0a92b68` applied to development DB without modifying active tenant-38 FIFO. Implemented and covered by tests; see urgent plan checkpoint. Downgrade fails closed if provenance would be lost.
- [ ] **V1-C2 — complete end-to-end/transaction gate:** core explicit selection unit 14/14, selection developer DB 3/3 and negative warehouse handler 1/1, Dashboard selected-state 15/15, immutable source event 1/1 verified. **Scoped real successful supplier receipt under FIFO and MOVING_AVERAGE**: `wa_backend/tests/test_warehouse_costed_inbound_c2_db.py` **8/8 PASS** with outer transaction rollback, idempotent replay, changed payload/duplicate invoice rejection; real physical outbound financial FIFO-versus-average differences, method-correct exact cost reversal, source-cost fidelity for separate receipts sharing one manufacturer lot. Advisory lock contention negative gate `wa_backend/tests/test_cost_policy_lock_contention_c2_db.py` **1/1 PASS**. **C2 remains OPEN** for real authenticated full HTTP sale/return, two concurrently posting invoice requests/recovery, network interruption, opening stock, Flutter and financial period/accounting/report reconciliation. No retroactive price correction is implemented.
- [ ] **V1-C3 — source cost fidelity:** **completed limited case**: repeated manufacturer lot received at 10 × 2 and 5 × 3 has TWO preserved original cost events, one physical lot and a single reconciled inventory value 35 under both FIFO and MA (C2.2, 8/8 database tests). **Still required:** alternate purchase UOM, multiple cost adjustments/late landed cost, FX authority, return-based reversal and controlled historical reconciliation. Do NOT assume those features already exist.
- [ ] **V1-C4 — one-profit/report contract:** audit every P&L/gross-profit UI, report and export to prove authoritative cost-event source, stable historic period and currency semantics. No per-batch official-profit feature. Verify method switching is blocked after financial activation.
- [ ] **V1-C5 — cross-domain gates:** **completed limited inventory cost boundary tests** for physical lot expiry-vs-FIFO disagreement and exact sale-like movement reversal (C2.3, no real VisitItem or customer refund created). **Remaining:** authenticated sale/return, replacement, sample/reward, expiry/write-down, actual FEFO allocator, full tenant/RLS, Flutter/offline and performance. Do not close Gate A/G until independently measured.
- [ ] **V2 option, not a task in V1:** if requested, separately scope managerial batch-contribution with provable allocation and variance reconciliation; otherwise stop after informative receipt-cost and physical-lot display.

## 7. Accounting source and limitations

The official IFRS Foundation [IAS 2 Inventories](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/) explains specific identification for non-interchangeable goods and FIFO/weighted average for ordinarily interchangeable goods. IAS 2 paragraphs 23–27 explicitly distinguish those methods and permit calculating average periodically or after each receipt: https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-2-inventories.pdf . This is the accounting framework reference, not a blanket legal/tax compliance determination for every tenant or country; jurisdiction-specific statutory/tax reporting still needs the company's accountant to confirm.

**Implementation checkpoint:** C1 is now implemented in source, typed API, Dashboard and Alembic migration; unit, developer DB, UI, frontend and import gates are recorded in the urgent plan. The document alone does not authorize or implement supplier invoice retrospective corrections, historical COGS restatements, new period-close logic or a second profit ledger. These remain OPEN and separate.
