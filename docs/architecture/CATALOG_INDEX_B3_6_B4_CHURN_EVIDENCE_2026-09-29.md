# Catalog Phase B3.6 + B4 — per-row SQL isolation and physical churn on disposable PostgreSQL

**Timestamp:** 2026-09-29. **Branch:** `hardening/catalog-index-worker-fairness`. **Status:** scoped tracking-default deduplication and physical storage experiments **PASS**; production-scale root-cause attribution, exact 50k XLSX SLA, index strategy and Gate B **OPEN**.

Read together with `CATALOG_INDEX_PHASE_B3_1000_AND_IMPORT_CAUSAL_DIAGNOSTICS_2026-09-29.md` and `CATALOG_INDEX_PHASE_B_T0_BASELINE_2026-09-29.md`. The existing historical 49,999-row job with 34,999 imported records took **45.76 minutes** according to `product_import_jobs`; no phase-by-phase timings exist for that job. **Never extrapolate** 1k-row clone time linearly into an actual 35k/50k job SLA.

## B3.6 — actual source of many surviving SELECTs

Inspection of `create_product_structures` and `domains/product_tracking.py` identified a precise, separate per-row N+1: `resolve_product_tracking_modes` had loaded company `SystemSetting` defaults for **each** new SKU, even when the spreadsheet specified explicit values. The authoritative loader normalizes both settings and fails closed on corrupt configuration; it cannot be skipped for all rows or silently replaced with hard-coded defaults.

Implemented a pure `resolve_product_tracking_modes_from_defaults` inside the Product Tracking domain; the original public per-request resolver still loads fresh settings and delegates to the **same** pure validation. The simple product creation path lazily reads the authorized company's defaults **once in each bounded product batch/transaction**, then validates every SKU's explicit or missing lot/expiry override. No global, process-level or cross-tenant cache. The parent family resolution, SQL uniqueness, pricing authority, stock projection, audit events, DRAFT→ACTIVE transition, event outbox, posted cost history and per-product tracking interpretation remain unchanged.

**Measured with real 10×100 synthetic product and published-price batches in standalone disposable PG16:**

| Metric | B3.5 with batch-local UOM only | B3.6 with UOM + tracking-default reuse |
|---|---:|---:|
| Total SQL statements / 1k new SKU | 9,345 | **8,355** |
| SELECT statements | 3,253 | **2,263** |
| INSERT / UPDATE / WITH | 5,023 / 1,049 / 20 | **5,023 / 1,049 / 20** |
| Wall clock | 23.673 s | **18.935 s** |

The **exact 990 fewer SELECTs per 1k** (one lookup per 100-SKU batch vs one per SKU) is deterministically explained by the source/SQL bucket counts. Wall-clock runs were **not randomized paired under equal host load**; no guarantee of a constant time percentage for 50k rows. The subsequent independent shadow/churn run reproduced **8,355 SQL / 1,000 products**, wall **17.404 s** under its own host conditions. No product/index/price data were committed into the real source DB.

**Top actual SQL families per 1k after tracking fix:**

| Classified operation | SQL calls | Why it exists |
|---|---:|---|
| `SELECT pg_advisory_xact_lock` | **1,010** | ~1,000 per-name family serialization, plus other publication locking; preserve concurrency authority |
| `SELECT … FROM products` | **1,000** | family identity/name resolution (current per-SKU lookup) |
| `INSERT INTO products` | **1,000** | independent master on these unique synthetic names |
| `INSERT INTO product_variants` | **1,000** | one physical sellable SKU each |
| `INSERT INTO product_uom_conversions` | **1,000** | EACH↔CARTON commercial/stock conversion |
| `INSERT INTO domain_audit_events` | **1,000** | append-only SKU publication audit provenance |
| `INSERT INTO transactional_outbox` | **1,000** | durable publication event delivery |
| `UPDATE product_variants` | **1,000** | authorized DRAFT→ACTIVE lifecycle update; indexed non-HOT change |
| `SELECT … FROM price_book_entries` | 21 | publication and existing price validation |

The **5,023 INSERTs** are not 5,023 pointless `SELECT` N+1 statements; they reflect five independent domain entities/evidence types plus batched price entries and publications. Reducing each must respect referential integrity, immutable audit/outbox, published pricing, transaction semantics and source identity. The remaining per-name family lock/lookup is a candidate for an **ordered, tenant-scoped batch resolution with negative concurrency tests**, not for removing locks or implicit family reuse rules.

Functional proof: `tests/test_catalog_tracking_batch_b3.py` **4/4 PASS** (original API equals cached override resolution; invalid override and company configuration fail closed; next request reloads settings), plus original import, C1/C2 accountancy, priced sale/return, bulk pricing and source-cost regressions **213/213 PASS, 0 skipped/failures/errors**. Stage74 costing contract **48/48 PASS**.

## B4 — live-like index definitions, independent shadow data, immutable prices respected

The first attempt to DELETE published pricing rows **inside a throwaway clone** failed with the correct existing business protection: **published price entries are immutable and cannot be deleted**. This is not an index bug. We did **not** disable/delete triggers or rewrite an immutable price record; we changed the physical experiment.

The revised disposable test `scripts/b4_catalog_index_churn_disposable.py` creates two NEW clone-only `LIKE ... INCLUDING ALL` shadow tables for `products` and `product_variants`, including exactly the original **18 index definitions (6 + 12)**, then copies **only 1,000 synthetic company-2 product/variant rows** (no customer real data, no price rows). Direct DELETE, VACUUM and REINDEX apply **only to these shadow relations** inside the temporary PG16 cluster; all 1,000 originally posted test SKUs and 2,000 immutable prices remain intact. The shadow rows do not invoke normal product-delete lifecycle, financial or audit API rules. This is **physical index reuse evidence**, not proof of correct commercial deletion.

In successful first shadow run:

| Phase on same two shadow tables | Total index allocated bytes |
|---|---:|
| Insert/copy 1,000 source-identical SKU/master rows | **2,383,872** |
| Ordinary manual VACUUM after first copy | **2,662,400** |
| Physically delete all 1,000 rows (before VACUUM) | **2,662,400** |
| Ordinary VACUUM after delete | **2,662,400** |
| Reinsert same 1,000 rows, then ordinary VACUUM | **3,063,808** |
| Compare `REINDEX TABLE` on **shadow tables only** | **991,232** |

**2,072,576 bytes of allocated index space were recovered by reindexing these destroyed-clone shadow tables** despite the **same final 1,000 live rows**. The second independent shadow run reproduced the mechanism: **3,096,576 → 991,232 bytes**, **2,105,344 bytes** recovered. **Neither difference is a measured bloat percentage of the owner's 217k-row live catalog.** Index size can grow during ordinary VACUUM as buffered GIN entries consolidate into the main index tree; non-shrinking files are not automatically unusable space. B-tree pages can remain allocated for later reuse. In the first run, **49 B-tree deleted pages** remained after delete+VACUUM and after refill+VACUUM; second run recorded **51**. GIN pending pages went from **198** immediately after first copy to **0** after manual VACUUM. This directly isolates physical retention and GIN-pending consolidation in the copied index topology.

**Why we do not replace production indexes:** the real T0 source database still had global **2,395,689 variant inserts / 1,786,141 deletes** and **87,048 variant updates, only 44 HOT**. Repeated historical testing, indexed DRAFT→ACTIVE updates, page split patterns and GIN pending-list growth are plausible contributors; exact global counters do not identify which delete/import/worker generated the active 217k-row table's retained pages. No active `pgstattuple` physical scan has been performed (app role cannot CREATE extension), so this shadow proof is NOT a per-index live bloat ratio or a reason to remove a UNIQUE/PK/active-search index.

## B4 — autovacuum threshold comparison: execution confirmed, causal comparison INCONCLUSIVE

On the throwaway PG16 cluster only, the test set `autovacuum_naptime='1s'` (never active PostgreSQL), compared shadow tables containing 1,000 rows and 100 deletions each, with one default-like trigger **50 + 0.20×1,000 ≈250** and one stricter **50 + 0.02×1,000 ≈70**. **PostgreSQL autovacuum was observed on BOTH shadow relations**, and both estimated post-vacuum dead-tuple counts returned to zero within about **1.03 s**. Thus this run **proves the test cluster's autovacuum worked**, but **does not distinguish that the smaller scale factor caused the difference**: insert-trigger criteria, statistics lag and background scheduling are confounders. The initial runner printed `B4_AUTO_POLICY_THRESHOLD=PASS` when it saw the tuned table; this was overly broad because the default table also vacuumed. We immediately corrected the test verdict logic: future runs print **`BOTH_TRIGGERED_NON_DISCRIMINATIVE`** if both tables vacuum. Do not promote this condition to a passed selective-tuning recommendation.

For the active tenant-38 development database, the baseline `product_variants` default threshold was estimated near **43,461 dead tuples** from ~217,055 estimated live rows and global default 0.20 scale, with current estimated 15,802 dead tuples. The threshold is a **test candidate**, not proof of missed autovacuum or endorsement of a `0.02` live tuning value. Benchmark maintenance I/O, GIN consolidation, RLS read p95 and real import throughput on representative volume before ALTER TABLE reloptions.

## B3.7/B5 — open engineering gates, no false release

- [ ] **Family-name batch work:** gather consistent normalized names, obtain the SAME per-company advisory locks in a deterministic order, preserve `family_mode` none/existing/new/implicit/ambiguous case behavior, multiple same-name masters and cross-tenant identity. Bounded multi-name lookup under RLS must have real interleaved transaction tests to reject duplicate parents; do not just delete `_family_name_lock`. Only after those tests should we count fewer than 1,010 name locks / 1,000 SKU.
- [ ] **Real 50k file/queue pipeline:** measure XLSX parse/validation/staging, worker queue wait, per-100-row execution/retries, family and pricing stage SQL, DB WAL/autovacuum and UI progress timestamps on identical data mix. A previous 45.76 min job cannot be explained by a 19 s small-clone core profile alone.
- [ ] **Full-size physical root cause:** representative multi-tenant 217k-row clone with controlled 1k→5k→10k/50k write and real lifecycle/retire cycles; `pgstatindex/pgstatginindex` before/after B-tree + GIN density, dead tuples, pending-list flush and actual catalog query EXPLAIN (ANALYZE, BUFFERS). Bench real `autovacuum` load/I/O and alternative per-table thresholds without touching active.
- [ ] **Maintenance strategy / index review:** never drop search/constraint indexes or run routine `REINDEX` solely from this result. Protect original company stock/accounting, data audit and publication restrictions, and plan post-deployment regression and rollback. Final Gate B and merge to `main` remain OPEN until the agreed stabilization point.

**Proven isolation:** runner schema-copied only approved dev metadata and one synthetic company fixture; `pgstattuple` was enabled only in disposable database; **real source `velotrack_db` contains no `pgstattuple` extension**. The temporary PostgreSQL port 55441 and `wanasah_b3_index_gate_*` folder were destroyed after successful tests. No production/live schema DDL, autovacuum change, direct DELETE, actual REINDEX, trigger disable, main-branch merge or original-folder edit was performed.
