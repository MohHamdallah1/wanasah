# ADR — One financial inventory truth, receipt-cost evidence, and optional batch analytics

**Recorded:** 2026-09-29  
**Decision status:** **V1 direction accepted; specific implementation tasks remain gated and OPEN**.  
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
- `wa_backend/domains/inventory_costing/service.py:activate_costing_for_first_receipt`: **proven implementation gap** — when policy is missing, it creates and locks `MOVING_AVERAGE`; even if a policy was default-provisioned, it can be activated without proof the company explicitly chose it. `cost_policy_payload` also displays MOVING_AVERAGE as an unselected default. This violates `.rules` and `AGENTS.md` explicit-company-choice contract.
- **Important scope:** the earlier A3.2 database gate had only 2 company-38 cost events and 0 frozen price components. That is NOT evidence that all possible financial/reporting/reconciliation cases are already correct.

## 6. Implementation order and acceptance gates (each remains OPEN until proven)

- [ ] **V1-C1 — explicit costing choice only:** design an unambiguous stored provenance of company choice, check all registration/onboarding, policy create/update, authorized role, idempotency and first receipt concurrency paths; an inactive provisioned default is unselected. Preserve existing valid active histories. Owner-reviewed behavior and rollback plan BEFORE code migration.
- [ ] **V1-C2 — negative tests first:** with no explicit policy choice, a costed supplier receipt must fail with a localized actionable error and leave zero inventory/cost/idempotency partial writes; a company-chosen FIFO or MOVING_AVERAGE must lock exactly once at first costed receipt; retries cannot alter method or double-post; opening stock and costed returns remain guarded.
- [ ] **V1-C3 — source cost fidelity:** test different purchase costs on two inbound events sharing the SAME manufacturer batch, plus UOM conversions and landed-cost late adjustments. Verify both receipt cost records remain immutable and full-value reconciles with the elected financial method. Do NOT assume all landed-cost or FX allocation functionality already exists.
- [ ] **V1-C4 — one-profit/report contract:** audit every P&L/gross-profit UI, report and export to prove authoritative cost-event source, stable historic period and currency semantics. No per-batch official-profit feature. Verify method switching is blocked after financial activation.
- [ ] **V1-C5 — cross-domain gates:** negative cases for sale, return, replacement, sample/reward, expiry/write-down and FEFO-vs-FIFO divergence; full controlled tenant/RLS tests, Flutter/offline contract and performance. Do not close full Gate A/G until measured.
- [ ] **V2 option, not a task in V1:** if requested, separately scope managerial batch-contribution with provable allocation and variance reconciliation; otherwise stop after informative receipt-cost and physical-lot display.

## 7. Accounting source and limitations

The official IFRS Foundation [IAS 2 Inventories](https://www.ifrs.org/issued-standards/list-of-standards/ias-2-inventories/) explains specific identification for non-interchangeable goods and FIFO/weighted average for ordinarily interchangeable goods. IAS 2 paragraphs 23–27 explicitly distinguish those methods and permit calculating average periodically or after each receipt: https://www.ifrs.org/content/dam/ifrs/publications/pdf-standards/english/2021/issued/part-a/ias-2-inventories.pdf . This is the accounting framework reference, not a blanket legal/tax compliance determination for every tenant or country; jurisdiction-specific statutory/tax reporting still needs the company's accountant to confirm.

**No runtime or schema changes are authorized by merely writing this document.** In particular the known silent-policy-selection code is not fixed by this ADR; the separate implementation gate above stays open.
