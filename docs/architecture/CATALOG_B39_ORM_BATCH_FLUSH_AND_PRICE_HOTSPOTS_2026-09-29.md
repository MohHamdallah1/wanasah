# B3.9 — real Excel product-write consolidation and remaining pricing bottlenecks

**Date:** 2026-09-29. **Branch:** `hardening/catalog-index-worker-fairness`. **Result:** scoped bounded creation writer **IMPLEMENTED + TESTED**. Product Import 1k/5k committed tenant/RLS integrity gates passed; complete 50k file/HTTP/Procrastinate queue and representative 217k company-size load remain OPEN. **Do not represent this as a verified faster 50k release.**

## The precise N+1 discovered with live application-stage SQL fingerprints

A normal `create_product_structures` pass did `db.add(variant); await db.flush()` for **every new SKU** to obtain its PK, then created UOM/barcode relationships, applied `DRAFT→ACTIVE`, and recorded the required immutable `domain_audit_events` + durable `transactional_outbox`. Because SQLAlchemy autoflushes all pending objects before the *next* individual flush, each per-SKU flush also caused independent INSERT/UPDATE statements for the *previous* SKU's conversion, barcode, audit/outbox and publication lifecycle. This was the dominant write-roundtrip amplification missed by earlier reader-side N+1 fixes. The **5k full real XLSX** profiler before the writer change recorded the following actual SQL shapes and cursor totals:

| SQL shape | Executions | Accumulated database cursor time |
|---|---:|---:|
| Per-SKU ProductVariant INSERT | 4,950 | 4.205 s |
| Per-SKU ProductVariant DRAFT→ACTIVE UPDATE | 4,950 | 4.205 s |
| Active barcode INSERT, all shape variants | 4,950 | ~7.673 s |
| Outer UOM conversion INSERT | 4,133 | 4.214 s |
| Immutable audit INSERT | 4,950 | 3.354 s |
| Transactional outbox INSERT | 4,950 | 3.075 s |
| Per-publication current-SKU/UOM predecessor evidence `WITH fresh_pairs` | 50 | **8.416 s** |
| Published price range GiST/constraints, other publication operations | 50 batches | additional substantial work |

**This is a quantified concrete ORM flush amplification**, not merely an unsubstantiated claim that all 31,629 statements are N+1 reads. The catalog creates real, required different records; each record must remain durable and attributed, but each one does **not** need its own SQL roundtrip.

## Scoped implementation

In `wa_backend/domains/simple_products/service.py`, the entire existing per-SKU spec/family/barcode validation and per-batch tracking/UOM/name prefetch remains unchanged. The worker builds bounded ORM `ProductVariant` objects for all valid specs, each still initially `DRAFT`, without adding them to the session until **all product-family IDs are resolved**, so intervening family flushes cannot break grouping. Calls `db.add_all(staged_variants)` and **one ORM `db.flush()`** for the batch and reads the REAL IDs from the original ORM instance objects (no ordering assumption about RETURNING, no guessed IDs or unsafe bulk_save_objects).

Only AFTER the actual SKU IDs are assigned does the same loop attach original UOM conversions and barcodes, call the existing official publish transition, advance variant version/revision, create the same immutable audit plus transactional outbox records with each exact SKU id, then flushes them together. The same `apply_live_stock_active_variant_delta`, allowed operation idempotency, price-publication authority, tenant RLS/FKs, barcode uniqueness, SAVEPOINT and commit/rollback remain in place. **No physical cost events, financial sale accounting, active indexes, Alembic/schema migrations, trigger disable or worker concurrency knobs are changed.** The caller still controls a bounded ~100-SKU application transaction.

## Controlled real XLSX application-stage results

The original 1k/5k datasets and the new datasets have the same **generated row mix** with 1% intended invalidity, but separate random unique SKU/barcode values and independently restarted/small disposable PG16 instances. The **SQL reduction and lifecycle identity correctness are deterministic; wall-clock timing is NOT an interleaved A/B and must be treated as variable.**

| Real XLSX pipeline stage | Before ORM SKU batch | After ORM SKU batch |
|---|---:|---:|
| Input rows | 1,000 | 1,000 |
| Imported / invalid | 990 / 10 | 990 / 10 |
| Published price entries | 1,817 | 1,817 |
| Execution SQL calls | 6,463 | **726** |
| Execution SQL INSERT | 4,940 | **203** |
| Execution SQL UPDATE | 1,070 | **90** |
| Execution seconds | 8.539 | **3.245** (fresh instance #1) |
| Recheck with full audit/outbox linkage assertion | n/a | **729 SQL / 4.484 s** (another instance) |

| Real XLSX pipeline stage | Before ORM SKU batch | After ORM SKU batch |
|---|---:|---:|
| Input rows | 5,000 | 5,000 |
| Imported / invalid | 4,950 / 50 | 4,950 / 50 |
| Published price entries | 9,083 | 9,083 |
| Execution SQL calls | 31,629 | **3,046** |
| Execution SQL INSERT | 24,206 | **523** |
| Execution SQL UPDATE | 5,350 | **450** |
| Execution seconds | **52.402** | **58.037** |

**Do not claim a verified 5k wall-time speedup**: the single latest 5k sample actually took **5.635s longer** than its independent predecessor despite **~90.4% fewer SQL statements**. The host load, pricing book growth, GIN/GiST index maintenance, WAL and PostgreSQL cache and statistics remain confounding factors. The **1k** benchmark twice showed substantially lower SQL and favorable wall time, but neither licenses an extrapolation to a production 50k SLA.

The new 5k trace is informative because batching made the actual remaining expensive work impossible to hide:

| Shape after the ORM batch | Call count | PostgreSQL cursor time, independent 5k sample |
|---|---:|---:|
| Current-publication prior-price `WITH fresh_pairs` | 50 | **11.011s** |
| Published price-entry UPDATE/constraint validation | 50 | **6.227s** |
| PriceBookEntry INSERT/constraint validation | 50 | **6.095s** |
| All active barcode INSERT | 50 | **5.823s** |
| Imported source rows UPDATE with linked SKU | 50 | **3.510s** |
| Product UOM conversions INSERT | 50 | **2.632s** |
| SKU lifecycle DRAFT→ACTIVE UPDATE | 50 | **2.602s** |
| ProductVariant INSERT | 50 | **0.835s** |
| Immutable audits/outbox INSERT | 50+50 | 0.665s + 0.638s |

This is the **next measured database scaling bottleneck**: pricing publication book grows with each 100-SKU batch, and GiST published-overlap, former-price proof, RLS and range-write amplification continue even after batched ORM inserts. Do not disable history or remove GiST exclusion constraints. Optimize against real `EXPLAIN (ANALYZE,BUFFERS)` under representative published history, company isolation and mutation-heavy concurrent workloads, preserve maker/checker and route commercial locks. An after-import query-plan comparison on the same 5k throwaway database found the present SQL's historical-pair proof used existing `ix_price_book_entry_resolver` index-only scans for **91 pairs** and ran in ~2.5–3.4ms; a forced nested `LATERAL LIMIT 1` alternative was **not faster** (3.4ms twice). It was therefore **NOT deployed**. The in-import ~0.2–0.8s calls need an in-flight plan/lock/I/O investigation; do not assume the after-import query plan proves in-flight wait cause.

## Protection and release gates

- [x] 1k XLSX source staging/validation, SQL production code/real RLS, 990 linked SKU rows, 1,817 exact published prices, and normal post-import state PASS.
- [x] 5k XLSX source staging/validation, actual commit, 4,950 linked SKU rows, 50 invalid, 9,083 exact published prices PASS.
- [x] Strengthened fixture explicitly requires **one ProductPublished audit and one ProductPublished outbox for EACH of the 990 committed variant IDs, all ACTIVE, zero missing links**. PASS in isolated 1k rerun, despite only 10 batched INSERT statements per table. No claim of an already-run audit join at the 5k size: its imported price/SKU counts passed; auditing on 1k proves the batch contract.
- [x] Broad covered backend: **225/225 tests PASS, 0 errors/failures/skips** after the ORM writer refactor, including product-import, UOM, family race, Pricing real DB published-price revision, FIFO/moving-average costed inbound/sale/returns and transaction races. Inventory costing Stage74 **48/48 PASS**. Tests run in original dev Postgres with outer rollback; no real dev transactional records committed.
- [x] `pgstattuple` installed ONLY in temporary test DB; original dev `velotrack_db` and tenant financial cost records remain untouched; no source/prod index dropped or REINDEX/autovacuum reloptions changed.
- [ ] Pair identical 5k/10k workloads on representative populated tenant catalogs, with instrumented WAL/CPU/GIN/GiST write costs, background autovacuum and true queue wait/HTTP ingress. Test 50k throughput with memory/slot headroom, imported/invalid distribution, DB size and actual Live Stock/search p95.
- [ ] Full HTTP SourceStore, isolated Procrastinate worker and retry/cancellation/queue fairness, staged file recovery, file upload/download front-end state. The direct synthetic-job application pipeline explicitly **does not** exercise them.
- [ ] B4 real-catalog index physical-density and a reversible production migration/maintenance strategy, preserving all PK/UNIQUE/FK/functional search indexes. **Gate B OPEN; not a merge/release authorization.**

The branch worktree is isolated from the user's original `main` checkout, which contains seven preexisting dirty/untracked owner files. No original edits, branch merge, reset/stash, or customer import job were performed in B3.9.
