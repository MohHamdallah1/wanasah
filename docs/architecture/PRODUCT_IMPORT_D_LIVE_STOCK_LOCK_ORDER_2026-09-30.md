# Audit D — Live Stock company/summary lock inversion, controlled correction

**Scope:** Wanasah V1 / catalog activation and Product Import vs Live Stock rebuild. **2026-09-30**. **Result:** a specific ABBA locking risk was reproduced with real PostgreSQL 16 on a guarded disposable clone; corrected with one production-function change and independently re-tested. **Full Audit D operational and staging contention sign-off remains OPEN** (no production sized, arbitrary stock-movement-vs-rebuild matrix or deployed ingress measured).

## Root cause — demonstrated before modifying the service

The pre-fix `apply_live_stock_active_variant_delta` acquired advisory
`live-stock-company-summary:{company_id}` and the company summary row before the caller
proceeded to `refresh_live_stock_variants`, which acquires
`live-stock-company:{company_id}` shared. A whole-company rebuild calls
`_acquire_company_projection_guard(exclusive=True)` **before**
`_ensure_company_summary_exact`, which takes that very same summary
advisory lock and `FOR UPDATE` row.

Therefore the previous order permitted this ABBA arrangement:
- Lifecycle/Product Import owns **summary**, waits for **company shared**.
- Rebuild owns **company exclusive**, waits for **summary**.

A brand-new regression using the **real** Live Stock functions and the
private PostgreSQL listener 127.0.0.1:55445/d1_mix held the catalog
summary transaction open, and then observed the rebuild obtain the
company-exclusive guard while the summary was still owned by catalog.
The child **failed before permitting a server-side deadlock** with:
`DEADLOCK_RISK: rebuild grabbed company EXCLUSIVE while catalog owned company-summary; inversion is reproducible`.
This is proven **lock-order inversion**, not a claim that a production
deadlock was recorded. The pre-fix private cluster was stopped/deleted.

## Precise fix, unchanged business semantics

Only the ordering in
`wa_backend/domains/live_stock_projection/service.py` changed:
`apply_live_stock_active_variant_delta` now takes the **shared**
`live-stock-company:{id}` transaction advisory guard *before* the
existing exclusive company-summary advisory guard and
`InventoryLiveStockCompanySummary ... FOR UPDATE`. The shared
guard is held to the transaction end. Ordinary independent company
updates continue independently; full rebuilds correctly require
company exclusivity. Existing delta math, active count, RLS, product
lifecycle transitions, projection key locks, pricing, ledger, audit,
outbox, retries, workers and migration schema did not change.

This order is shared → summary for ordinary updates and exclusive →
summary for full rebuilds. **Do not delete the Company guard, change it
to exclusive for every small update, or "fix" the test by suppressing
lock failures.** Changing lock acquisition is purposeful contention
rather than extra database CPU work.

## After-fix bounded disposable-PostgreSQL evidence

`WANASAH_D_PROJECTION_LOCK_GATE=1` uses the existing opt-in D1
disposable PostgreSQL 16 fixture, copies only the approved synthetic
tenant 2 and creates tenant 3 **inside the private clone**. It starts
the real application SQLAlchemy/RLS tenant sessions and the real
`apply_live_stock_active_variant_delta`,
`refresh_live_stock_variants` and `rebuild_live_stock_company`
functions (not a string-only lock mock).

- Catalog shared company guard held: rebuild exclusive company guard
  **waited 298.90ms**, then rebuilt successfully after catalog commit.
- Rebuild exclusive company guard held: catalog variant-summary delta
  **waited 230.89ms**, then continued after the rebuild transaction
  released.
- The independent company-3 exclusive guard succeeded during
  company-2 contention.
- No deadlock/timeouts; company 2's persisted active variant count
  equalled the actual active variant count (**1 = 1**) after rebuild.
- Candidate projection rebuild keys were **0** in this narrow synthetic
  fixture; this tests the **summary/company guard ordering**, not
  heavyweight projection-key rebuilding under a populated warehouse.
- The runner verified `D1_DEVELOPER_SOURCE_UNMODIFIED=PASS` and
  `D1_PRIVATE_POSTGRES_REMOVED=PASS`.

The affected **real business** gate was also executed once after the
service change: 3,000-row committed Product Import with 2,970
imported/30 intentionally invalid, **2,970 prices, 2,970 audit
records, 2,970 outbox entries**, a real Sale+COGS, Supplier Inbound,
Route Launch commercial context and zero negative stock, all PASS.
Source developer tenant unchanged; private DB removed.

An unrelated **pre-existing static gate expectation** was found during
the bundled check: `gate_stage822_live_stock_rebuild_core.py` required
`COMPANY_SCAN_PAGE = 1000` and `Company.id > after_company_id`
to appear in the temporal *worker file*. Those exact bounded
keyset-pagination statements already live in the shared
`workers/scheduling.py` helper called by the worker. Only that static
gate was updated to verify the real delegation **and** the bounded
shared scheduling helper; production worker, queue topology and
pagination were not changed. The repaired source gate passed
**CHECKS=37, FAILURES=0**.

## Reproduce only after relevant code changes

From `wa_backend` with its existing Python virtualenv, approved local
`.env`, and the specifically guarded 127.0.0.1 private-port fixture:

```powershell
$env:WANASAH_D1_LOCAL_GATE = "1"
$env:WANASAH_D_PROJECTION_LOCK_GATE = "1"
$env:WANASAH_D1_SOURCE_ENV_FILE = (Resolve-Path ".\.env").Path
.\venv\Scripts\python.exe -m scripts.run_product_import_d1_isolated_gate
```

**Release boundary:** this isolated demonstration does not establish
production-scale rebuild duration, stock-transfer/vehicle-lock order
under a populated project, TLS ingress admission fairness, or the full
1,000-client D7-S acceptance. These remain separate staging gates.
Never execute this test on the developer business DB, customer data or
a shared production port.
