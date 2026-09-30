# D6 — Product Import runtime attribution and pricing predecessor proof

**Scope:** Wanasah V1 / Product Import. This report contains **measured
disposable-local PostgreSQL 16 evidence**, not extrapolated production
throughput. Read it together with
`V1_MULTITENANT_ASYNC_AND_IMPORT_RELEASE_PLAN_2026-09-30.md`,
`ARCHITECTURE.md` and the original Astra audit archived under
`docs/architecture/ASTRA6_V1_IMPORT_SCALABILITY_AUDIT_2026-09-30.md`.

## What was tested

The guarded runner `wa_backend/scripts/run_product_import_d1_isolated_gate.py`
was activated with `WANASAH_D1_LOCAL_GATE=1`,
`WANASAH_D6_PROFILE=1`, and `WANASAH_D1_IMPORT_ROWS=3000`.
It creates a private PostgreSQL 16 cluster on `127.0.0.1:55445`,
copies only the approved empty synthetic fixture from development tenant 2
and the schema, applies migrations, and executes the **real** import worker
against a committed 3,000-row synthetic file. It stops and removes its
private cluster afterward; the original developer fixture is verified
unchanged.

The runtime observer measures:
- Worker process CPU time and resident memory (PSUtil, actual Python worker).
- SQLAlchemy before/after cursor round-trip wall time (SQL + driver +
  transport + possible waits, **not** server execution alone).
- PostgreSQL `pg_stat_statements` aggregated execution time, calls, block
  hits/reads, statement-attributed WAL, and block I/O time.
- Periodic `pg_stat_activity` wait/blocker samples, peak private-DB
  connections, and PostgreSQL cluster-global WAL deltas.
- Real Product/Price/Audit/Outbox counts and a bounded read-only
  `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)` query-plan comparison.
- The fixture includes a real preexisting priced synthetic sale setup; no
  domain handler, RLS, event, idempotency, pricing revision, or stock
  semantics is mocked by the worker profiler.

**Hard limits:** 1,000–5,000 rows, explicit developer source guard,
private loopback port, no writes to developer customer data, controlled
runtime; this is not a stress test of 1,000 simultaneous users.

## Three comparable independent private runs

| Measurement | Unchanged baseline (first) | Unchanged baseline (second) | After bounded SQL edit |
|---|---:|---:|---:|
| Source rows | 3,000 | 3,000 | 3,000 |
| Successfully imported | 2,970 | 2,970 | 2,970 |
| Intended invalid rows | 30 | 30 | 30 |
| Import wall time (s) | 28.278 | 28.970 | 24.465 |
| Worker CPU time (s) | 8.312 | 8.625 | 8.609 |
| SQLAlchemy cursor round-trip sum (s) | 19.948 | 20.244 | 15.918 |
| PostgreSQL statement execution aggregate (s) | 18.023 | 18.348 | 13.902 |
| First-ever-price/predecessor SQL, 30 calls (s) | 4.013 | 4.363 | below top SQL groups |
| Worker peak RSS (MiB) | 116.18 | 116.09 | 115.74 |
| Observed PG block samples | 0 | 0 | 0 |
| Peak connections inside private DB | 7 | 7 | 6 |
| Private-cluster global WAL (bytes) | 50,916,874 | 50,923,700 | 51,936,733 |
| Published price variants / audit / outbox | 2,970 each | 2,970 each | 2,970 each |
| Invalid successful-row writes / duplicate lineage | 0 | 0 | 0 |

For the directly comparable second baseline and edited run, wall time
changed from **28.970s to 24.465s** (approximately **15.6% lower**);
PostgreSQL aggregated statement time changed from **18.348s to 13.902s**.
These are observed outcomes of independent executions on local disposable
clusters, **not** a guaranteed production gain. The extra ~1 MB global WAL
is not attributed to one query and cannot be interpreted as a per-import
regression. The worker CPU was essentially unchanged, suggesting this
particular win did not arise from a Python CPU rewrite.

**Measurement caution:** SQLAlchemy round-trip time overlaps with server
execution; these times must not be added to worker CPU or subtracted from
wall time as if disjoint. `pg_stat_statements.track=all` can include
nested PL/pgSQL/trigger statements, so the server statement aggregate is
also not strictly identical to worker critical-path SQL time. WAL is
cluster-global and includes incidental private-cluster operations.
Zero detected blockers means zero within the observation windows, not
proof that lock contention can never arise.

## Reproduced SQL issue and the single production change

The prior `_close_predecessor_ranges` query at
`wa_backend/domains/pricing/publishing.py` used a materialized set of
fresh SKU/UOM pairs with a correlated `WHERE EXISTS(old price)`. PostgreSQL
flattened that form into a nested loop. For the last 129 fresh pairs in
the synthetic 3k run, the old-price index scan visited roughly 5,322
old rows **129 times**; a sampled plan had **37,255 shared buffer hits**
and **329.654ms** execution.

The equivalent **`CROSS JOIN LATERAL (SELECT 1 ... LIMIT 1)`** forces a
bounded point lookup per fresh SKU/UOM key while preserving all original
tenant, price-book, publication-ID, SKU, UOM, and published-status predicates.
The same private DB produced **490 shared buffer hits** and **1.225ms**
for the alternative. A repeat independently measured **37,255 hits and
345.508ms** for the original versus **490 hits and 1.317ms** for the
candidate. Both the *no predecessor* and *existing predecessor* boolean
cases agreed before changing the production query.

After this database-plan proof, **only the preceding-existence SQL
expression** inside `_close_predecessor_ranges` was changed. The
existing Company pricing mutex, ordered locks, version/revision controls,
old-window closure, route-context historical protection, GiST exclusion
constraints, fallback error codes, idempotency and inventory authority
were **not** touched. No index, migration, pricing storage or SKU lifecycle
was changed. `LIMIT 1` is correct here because the entire subquery asks
only whether any older published matching row exists, never which price
to use. Real rollback Pricing B3 acceptance (7 cases) proves that a new
SKU still takes the first-publication fast path and a real earlier
publication still closes the exact historical window correctly. The
permanent B3 gate now also asserts that the bounded LATERAL/LIMIT 1
lookup is retained, preventing accidental return to the costly plan.

**Do not remove or rebuild** `excl_price_book_entry_published_overlap`
or other pricing constraints on the basis of this profile. The winning
query may use that GiST index as a point-probe authority, and the
constraint is independently required for price-history correctness.

## Acceptance and remaining limits

The post-change disposable import finished with **2,970 real variants,
2,970 published priced variants, 2,970 unique ProductVariant audit events,
2,970 corresponding transactional-outbox events, 30 intentionally invalid
rows, and zero valid-row import failures**. The developer source tenant
remained unchanged. The independent post-edit gates PASSED: real
PostgreSQL price-history rollback tests **7/7**, Company lock
compatibility **1/1**, actual sale/correction rollback **2/2**,
Product Import unit regression **136/136**, permanent D6 profile
contracts **6/6**, plus the previously accepted **D1 real ASGI
72-business-operation baseline/import concurrency matrix** and the
**D2 real pricing/route/summary lock matrix** rerun successfully against
their own disposable PostgreSQL clusters. Both private clusters were
stopped and removed; developer source was verified unchanged. The
bounded predicate/plan parity probe (positive and negative predecessor
cases) also PASSED.

D6 does **not** certify production-sized 50,000-row performance, complex
multi-revision portfolios, arbitrary concurrent 1,000-user load, or
production connection/backpressure settings; those are D7/D8 or a
separately approved production-like measurement. Other observed SQL hot
groups (price UPDATE/INSERT, barcode INSERT, variant lifecycle UPDATE,
staging-row updates) have real costs but **no demonstrated incorrectness
or unacceptable V1 performance** in this local acceptance. Do not
preemptively replace the ORM, bypass domain services, batch across
idempotency boundaries, or drop GiST/TRGM/B-tree indexes. Further
optimizations require independent measured before/after and exact
product/price/audit/outbox/stock parity, not guesswork.

## Reproduction

From `wa_backend` using its virtual environment and the approved
local development `.env`:

```powershell
$env:WANASAH_D1_LOCAL_GATE = "1"
$env:WANASAH_D6_PROFILE = "1"
$env:WANASAH_D1_IMPORT_ROWS = "3000"
$env:WANASAH_D1_SOURCE_ENV_FILE = (Resolve-Path ".\.env").Path
python -m scripts.run_product_import_d1_isolated_gate
python -m unittest tests.test_product_import_d6_profile_contract
```

Run Pricing real-DB gates only on the separately approved rollback-only
test tenant (see `test_pricing_bulk_catalog_b3_db.py` and
`test_pricing_company_keyshare_d21_db.py`); never run those gates against
customer data. Do not assume a script's mere presence means the public
production deployment has been profiled.
