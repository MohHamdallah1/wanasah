# Inventory Costing Opening Valuation — Production Plan

**Status:** ACTIVE — V1 financial/inventory correctness blocker
**Created:** 2026-10-23
**Authority:** `.rules`, `V1_SCOPE_FREEZE.md`, `ARCHITECTURE.md`, `docs/architecture/INVENTORY_COSTING_FINANCIAL_TRUTH_DECISION.md`

## 1. Why this exists

Wanasah correctly refuses to activate inventory costing when physical stock already exists but no financial opening valuation exists. The current blocker `COST_OPENING_BALANCE_REQUIRED` is therefore correct, but the product is incomplete because there is no operator workflow to establish that one-time opening valuation.

Opening valuation is part of the already-open V1 costing gate. It is not a second costing ledger and must not alter physical quantities.

Current local acceptance evidence (development company only, not a product assumption):
- 500 product variants currently have positive stock.
- Current positive on-hand total: 620,291 base units.
- Current cost states/events/FIFO layers: 0.
- Current selected method: FIFO, selected but not active.
- Current purchase-cost-reference coverage for those 500 variants: 0/500.

## 2. Non-negotiable invariants

1. Backend is the only authority for quantities, company, currency, costing method, activation eligibility, snapshot consistency, posting, audit and idempotency.
2. The operator never types physical opening quantities or database IDs. Quantities come from authoritative current inventory balances.
3. The operator supplies only the minimum missing financial fact: opening unit cost in the product base UOM.
4. No automatic inference from sale price, current Purchase Cost Reference, batch identity, retail price, product import price or arbitrary history.
5. A Purchase Cost Reference may only be shown as an optional suggestion if one exists; it is never silently accepted as opening valuation.
6. Opening valuation is a one-time company-wide command before costing activation. It cannot run after the policy is active or cost history already exists.
7. Finalization is idempotent/durable. Reusing one request id with changed input fails closed.
8. The command does not create or modify physical inventory movements/balances.
9. The command records append-only financial evidence and an auditable opening-valuation header/lines.
10. Company currency is authoritative; V1 has no FX opening-valuation path.
11. Unknown/missing/duplicate products, invalid money, cross-company data, partial coverage, stale stock snapshots and concurrent activation fail closed.
12. Finalization and physical inventory mutations must be concurrency-safe; no movement may commit through an uncosted activation race.
13. FIFO remains financial product-wide FIFO, separate from physical FEFO. Opening layers are bootstrap financial evidence only.
14. UI must explain the business meaning in plain language and never expose internal IDs.
15. The existing `COST_OPENING_BALANCE_REQUIRED` error must become actionable: explain that old stock predates costing and direct the user to the one-time opening-valuation workflow.

## 3. Accepted V1 operator workflow

1. In Inbound, the first costed receipt detects existing unvalued stock.
2. Wanasah opens a one-time **Opening inventory valuation / تقييم المخزون الافتتاحي** workflow.
3. User downloads an XLSX template generated from current positive inventory. It contains human-readable product/SKU/base UOM/current quantity as read-only context plus one editable field: **Opening unit cost / تكلفة الوحدة الافتتاحية**.
4. User fills costs and uploads the file.
5. Backend parses/validates the file and returns a bounded preview: covered products, missing/invalid rows, total quantity and total opening inventory value. Backend re-resolves product identity and quantities; uploaded quantities are never authority.
6. If stock changed since the template/preview, finalization rejects as stale and requires a refreshed template/preview.
7. User explicitly confirms the preview.
8. Backend finalizes opening financial evidence and activates/locks the already-selected FIFO or MOVING_AVERAGE policy in the same authoritative transaction.
9. User returns to Inbound and posts the supplier receipt normally.

For small companies the UI may also support direct per-product edits, but XLSX is the primary V1 path for hundreds of products.

## 4. Financial bootstrap representation

### Moving average
For each positive-stock variant:
- authoritative opening quantity = company-wide physical on-hand at finalization;
- operator-provided base-unit opening cost;
- initialize one `InventoryCostState`: quantity, inventory value, average unit cost;
- create immutable opening financial evidence.

### FIFO
For each positive-stock variant:
- one operator-provided base-unit opening cost for the opening inventory position;
- authoritative quantity is split by existing product batch provenance from current physical balances;
- create immutable `OPENING_BALANCE / OPENING_VALUATION` cost events and corresponding FIFO opening layers;
- all opening layers for the same variant carry the explicit opening unit cost; deterministic batch ordering is provenance only and does not claim historical acquisition chronology that Wanasah does not know;
- initialize the variant cost state to the exact total opening quantity/value.

No synthetic physical inventory movement is created.

## 5. Implementation checkpoints

### P0 — false uncertain-result banner
- [x] Separate durable-command existence from actual recovery-required state.
- [x] Normal in-flight Supplier Inbound request does not show “نتيجة العملية غير مؤكدة”.
- [x] Ambiguous network outcome does set recovery-required and preserves the same request identity.
- [x] Focused Supplier/Inbound tests pass.

### P1 — opening valuation financial model
- [x] Add one-time opening-valuation header + lines with tenant-safe FKs, actor, company currency, request identity, snapshot fingerprint, totals and timestamps.
- [x] Extend authoritative cost-event model for `OPENING_BALANCE` / `OPENING_VALUATION` without inventing a physical inventory movement.
- [x] Preserve existing movement-backed event invariants with explicit XOR/source constraints.
- [x] Migration upgrade/downgrade and clean-bootstrap tests.

### P2 — backend preview/template/finalize
- [x] Company-wide authorized template/preview contracts with bounded file and row limits.
- [x] XLSX template download generated from authoritative positive inventory.
- [x] XLSX upload/preview validates exact SKU coverage and money scale, rejects duplicates, and re-resolves current product/base-UOM identity server-side instead of trusting spreadsheet text.
- [x] Store/compare deterministic inventory snapshot fingerprint.
- [x] Finalize command is idempotent and atomic.
- [x] Concurrency contract prevents stock mutations/cost activation race.
- [x] Initialize Moving Average or FIFO exactly once and activate/lock the selected policy in the same transaction.
- [x] Append audit evidence and return stable localized error codes/context.

### P3 — Dashboard workflow
- [x] Replace dead-end `COST_OPENING_BALANCE_REQUIRED` copy with plain business explanation.
- [x] One-time opening valuation modal/workspace from Inbound costing setup.
- [x] Download template, upload, preview missing/invalid items, show total opening value, explicit confirmation.
- [x] Keyboard-first, AR/EN, Western digits, accessible progress/errors.
- [x] No internal IDs or editable physical quantities.

### P4 — acceptance
- [x] Unit/contract tests for invalid/partial/stale/cross-company/permission/idempotency cases.
- [x] Real PostgreSQL FIFO acceptance: opening state + layers + first receipt + outbound COGS + replay/rollback.
- [x] Real PostgreSQL Moving Average opening-valuation acceptance.
- [x] Concurrent movement/finalization race proves no uncosted gap.
- [x] XLSX 500-row reference acceptance.
- [x] Production build + TypeScript + relevant Inventory regression suites.
- [x] Local development acceptance completed only after a verified DB backup; no guessed costs were written to the user's current data. Evidence: backup `wanasah-local-pre-opening-valuation-20261023-053559.dump` (SHA256 `0b13f12d576645ee51da28949d7ada815e3b65d9d3fee81cf6525722bab9807c`); local DB upgraded to Alembic `9c4f8a2d7e31`; real company snapshot produced a protected 500-row XLSX for 620,291 base units; empty-cost workbook was rejected with `OPENING_VALUATION_COST_REQUIRED`; opening valuation/cost state/event/layer tables remained empty and FIFO remained selected but inactive.

## 6. Stop / completion rule

Do not remove this plan until P1–P4 are all checked and the current `COST_OPENING_BALANCE_REQUIRED` path is replaced by a complete, usable one-time opening valuation workflow. Do not bypass the guard with zero cost, current sale price, or silent Purchase Cost Reference fallback.
