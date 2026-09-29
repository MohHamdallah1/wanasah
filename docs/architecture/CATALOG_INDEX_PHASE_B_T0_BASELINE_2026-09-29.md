# Phase B — Catalog index baseline T0 (read-only developer snapshot)

**Measured at:** 2026-09-29 08:46:39.986137 UTC (11:46:39 +03:00). **Branch:** `hardening/catalog-index-worker-fairness`. **Role:** `wanasah_app`. **Database:** `velotrack_db`. **PostgreSQL:** 16.9. **RLS:** `row_security=on`; the exact company-level row counts are scoped to tenant **38**. **Mutation:** NONE; all evidence queries were SELECT under an existing tenant-bound SQLAlchemy transaction, followed by ROLLBACK. No extension, ALTER, REINDEX, VACUUM, DELETE, index removal or connection termination was issued.

**Critical distinction:** PostgreSQL catalog/storage metrics, `pg_stat_all_tables` and `pg_stat_user_indexes` are **database-global across tenants**; the `WHERE company_id=38` `COUNT(*)` results are company-scoped (under RLS). Do not compare their populations as though equivalent. This snapshot is **after** the owner's earlier REINDEX, not an instantaneous before/after REINDEX experiment.

## B1 — Table baseline (bytes, estimates, operations and maintenance)

| Physical table | Estimated live tuples `reltuples` | Exact company-38 count, RLS | Heap bytes | TOAST incl. indexes bytes | Table bytes | All index bytes | Total bytes | Est. dead tuples |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `products` | 19,296 | 8,035 | 2,662,400 | 8,192 | 2,703,360 | **4,964,352** | 7,667,712 | 2 |
| `product_variants` | 217,055 | 96,778 | 49,045,504 | 0 | 49,086,464 | **72,187,904** | 121,274,368 | 15,802 |
| `product_batches` | 124,297 | not measured | 14,753,792 | 8,192 | 14,794,752 | 48,226,304 | 63,021,056 | 11,947 |
| `product_import_rows` | 150,932 | not measured | 198,918,144 | 8,192 | 199,000,064 | 53,272,576 | 252,272,640 | 2,909 |
| `product_import_jobs` | 24 | not measured | 73,728 | 8,192 | 114,688 | 98,304 | 212,992 | 0 |

`pg_table_size` includes heap+other table overhead and need not equal `pg_relation_size(heap)` plus the single TOAST field. Estimates (`reltuples`, `n_dead_tup`) are **not exact cardinalities**.

| Table | Cumulative inserts | Cumulative updates | Cumulative deletes | HOT updates | Autovacuum count | Last autovacuum UTC | last autoanalyze UTC |
|---|---:|---:|---:|---:|---:|---|
| `products` | 996,750 | 40 | 476,879 | 1 | 76 | 2026-09-28 14:31:48 | 2026-09-28 14:48:39 |
| `product_variants` | 2,395,689 | 87,048 | 1,786,141 | 44 | 33 | 2026-09-28 14:36:59 | 2026-09-28 14:53:41 |
| `product_batches` | 338,502 | 1 | 300,649 | 0 | 6 | 2026-09-21 10:25:38 | 2026-09-21 10:23:43 |
| `product_import_rows` | 971,018 | 360,019 | 511,584 | 83 | 39 | 2026-09-28 14:57:49 | 2026-09-28 14:57:54 |
| `product_import_jobs` | 1,176 | 1,591 | 1,141 | 1,375 | 29 | 2026-09-29 08:40:01 | 2026-09-29 08:40:01 |

These are **cumulative PostgreSQL statistics**, not per-import, per-day, per-tenant or per-REINDEX counts. `pg_stat_database.stats_reset` returned `NULL`, so the exact start of these table/index counters was **not established**. `pg_stat_wal` independently showed global `wal_bytes=16,505,126,571`, reset at 2026-08-01 21:03:45 UTC; **do not attribute this WAL total to the catalog or to a single import**.

## B1 — All current catalog indexes (18 complete records)

Physical index table: `product_variants`: **12 indexes / 72,187,904 bytes**; `products`: **6 indexes / 4,964,352 bytes**. **16 B-tree and 2 GIN**. `idx_scan` is cumulative and may include older work; zero does **not** authorize dropping a UNIQUE index or imply an index is permanently unused.

| Table | Index | Method | Bytes | Unique | Owning constraint | `idx_scan` |
|---|---|---|---:|---|---|---:|
| `product_variants` | `ix_product_variants_company_search_trgm` | GIN | 15,163,392 | no | — | 294 |
| `product_variants` | `ix_product_variant_company_name_id` | BTREE | 14,761,984 | no | — | 15,393 |
| `product_variants` | `ix_product_variant_live_active_seek` | BTREE | 14,712,832 | no | — | 4,268 |
| `product_variants` | `uq_company_sku` | BTREE | 10,633,216 | YES | `uq_company_sku` | 0 |
| `product_variants` | `pk_product_variants` | BTREE | 4,907,008 | YES/PK | `pk_product_variants` | 2,935,059 |
| `product_variants` | `uq_product_variants_company_id` | BTREE | 4,907,008 | YES | `uq_product_variants_company_id` | 31,665,998 |
| `product_variants` | `ix_product_variants_product_id` | BTREE | 1,794,048 | no | — | 869,320 |
| `product_variants` | `ix_product_variants_company_id` | BTREE | 1,515,520 | no | — | 55,493 |
| `product_variants` | `ix_product_variants_lifecycle_status` | BTREE | 1,515,520 | no | — | 1,295 |
| `product_variants` | `ix_product_variants_operational_hold` | BTREE | 1,515,520 | no | — | 79 |
| `product_variants` | `ix_product_variant_simple_common_filters_seek` | BTREE | 753,664 | no | — | 180 |
| `product_variants` | `uq_product_variant_company_gtin` | BTREE | 8,192 | YES | — | 0 |
| `products` | `ix_products_company_name_trgm` | GIN | 1,523,712 | no | — | 0 |
| `products` | `ix_product_company_name_id` | BTREE | 1,400,832 | no | — | 5 |
| `products` | `uq_company_product_code` | BTREE | 966,656 | YES | `uq_company_product_code` | 1,070 |
| `products` | `pk_products` | BTREE | 450,560 | YES/PK | `pk_products` | 55,570 |
| `products` | `uq_products_company_id` | BTREE | 450,560 | YES | `uq_products_company_id` | 653,910 |
| `products` | `ix_products_company_id` | BTREE | 172,032 | no | — | 1,136,831 |

Full definitions read from `pg_get_indexdef(index_oid)`; these are **evidence only**, not a migration to execute:

```sql
CREATE INDEX ix_product_variants_company_search_trgm ON public.product_variants USING gin (company_id, lower((((name)::text || ' '::text) || (sku)::text)) gin_trgm_ops);
CREATE INDEX ix_product_variant_company_name_id ON public.product_variants USING btree (company_id, name, id);
CREATE INDEX ix_product_variant_live_active_seek ON public.product_variants USING btree (company_id, name, id) WHERE ((lifecycle_status)::text = 'ACTIVE'::text);
CREATE UNIQUE INDEX uq_company_sku ON public.product_variants USING btree (company_id, sku);
CREATE UNIQUE INDEX pk_product_variants ON public.product_variants USING btree (id);
CREATE UNIQUE INDEX uq_product_variants_company_id ON public.product_variants USING btree (company_id, id);
CREATE INDEX ix_product_variants_product_id ON public.product_variants USING btree (product_id);
CREATE INDEX ix_product_variants_company_id ON public.product_variants USING btree (company_id);
CREATE INDEX ix_product_variants_lifecycle_status ON public.product_variants USING btree (lifecycle_status);
CREATE INDEX ix_product_variants_operational_hold ON public.product_variants USING btree (operational_hold);
CREATE INDEX ix_product_variant_simple_common_filters_seek ON public.product_variants USING btree (company_id, base_uom_id, lower((name)::text), id) WHERE (((lifecycle_status)::text = 'ACTIVE'::text) AND ((lot_control_mode)::text <> 'NONE'::text) AND ((expiry_control_mode)::text = 'NONE'::text) AND (packs_per_carton > 0));
CREATE UNIQUE INDEX uq_product_variant_company_gtin ON public.product_variants USING btree (company_id, gtin) WHERE (gtin IS NOT NULL);
CREATE INDEX ix_products_company_name_trgm ON public.products USING gin (company_id, lower((name)::text) gin_trgm_ops);
CREATE INDEX ix_product_company_name_id ON public.products USING btree (company_id, name, id);
CREATE UNIQUE INDEX uq_company_product_code ON public.products USING btree (company_id, code);
CREATE UNIQUE INDEX pk_products ON public.products USING btree (id);
CREATE UNIQUE INDEX uq_products_company_id ON public.products USING btree (company_id, id);
CREATE INDEX ix_products_company_id ON public.products USING btree (company_id);
```

For full selectivity analysis, a later snapshot should also capture `idx_tup_read` and `idx_tup_fetch`. Selected current values: `uq_product_variants_company_id` = **33,246,541 read / 32,380,732 fetched** (31,665,998 scans); `ix_product_variants_company_id` = **628,124,500 read / 176,450,917 fetched** (55,493 scans); `ix_products_company_id` = **7,653,392,030 read / 1,030,613,052 fetched** (1,136,831 scans). These large lifetime figures demand **query-plan and time-window correlation**; they are not a latency or cost measurement by themselves.

### B1 interpretation — supported hypotheses, not a demonstrated root cause

- The owner had measured approximately **93.18 MB of indexes on `products` and 213.98 MB on `product_variants` before a manual REINDEX**, falling to 4,956,160 / 72,179,712 bytes afterward. This T0 remeasurement (4,964,352 / 72,187,904 bytes) is close to the post-REINDEX sizes. **A large amount of size was recoverable at that earlier point; the cause and rate of regrowth are still unproven.**
- Historical inserts/deletes indicate **high catalog churn**. With only **44 HOT updates out of 87,048 updates** on `product_variants`, non-HOT updates are worth profiling. They may incur index maintenance, but these counters alone do not show which columns were updated or how many pages became fragmented.
- Three leading `product_variants` indexes (`ix_product_variants_company_search_trgm`, `ix_product_variant_company_name_id`, `ix_product_variant_live_active_seek`) account for **44,638,208 bytes**, about **61.8%** of its total index bytes. The two `(company_id,name,id)` B-trees overlap textually; the second has `WHERE lifecycle_status='ACTIVE'`. **No index was declared redundant or removed.** Explain actual list/search/Live Stock plans before deciding.
- The `uq_company_sku` UNIQUE constraint had `idx_scan=0`, yet it is business/consistency authority. **Never remove it based on a zero read count.** The small partial GTIN unique index likewise requires functional and data-integrity review.

## B2 — Vacuum and index-density measurement plan (DESIGNED; physical density NOT yet measured)

- Defaults at T0: `autovacuum=on`; `autovacuum_vacuum_threshold=50`, `autovacuum_vacuum_scale_factor=0.2` for `products`, `product_variants`, `product_batches`. Based on estimated table size, variants' dead-tuple vacuum trigger is roughly **43,461** (50 + 0.2 × 217,055), versus the current estimated **15,802** dead tuples; this alone **does not prove** missing or delayed vacuum. `product_import_rows` has a deliberate stronger per-table setting (threshold **2,500**, scale **0.05**); do not blindly copy it to catalog tables.
- `track_io_timing=off` and `track_wal_io_timing=off`. `maintenance_work_mem=65536 kB`; `max_wal_size=1024 MB`. Hardware I/O latency, saturation and per-import WAL deltas **were not captured**; collect only when the owner approves controlled observability.
- Two `idle in transaction` client sessions observed at 2026-09-29 approximately 08:47 UTC (ages ~**63,076** and **15,380** seconds). **Both had `backend_xmin=NULL` AND `backend_xid=NULL` at the follow-up check**; no evidence that either held the oldest snapshot or blocked vacuum *at this time*. No session was killed. Check again during actual bloat or vacuum symptoms.
- **No `pgstattuple`, `pageinspect`, or `pg_stat_statements` extension is installed.** Therefore **we did not measure** B-tree leaf density, deleted/empty pages, true live/dead index tuples or GIN pending pages; index-size reduction after REINDEX is suggestive, not physical-proof of the current bloat ratio.
- **Proposed bounded physical analysis (NOT EXECUTED):** first run in a disposable/non-customer PostgreSQL clone with matching schema/data volume or a review-approved `pgstattuple` extension. Capture `pgstatindex(index_oid)` leaf density, `avg_leaf_density`, deleted/empty pages on representative B-trees; use `pgstatginindex(index_oid)` for GIN pending pages/tuples. Review runtime, privilege, lock behavior and disk headroom; set read-only transaction, explicit tenant RLS context and bounded `lock_timeout` / `statement_timeout`. Do **not** CREATE EXTENSION on the active database without explicit approval; do not execute `REINDEX` or `VACUUM FULL` as a diagnostic.
- Collect a **T1 snapshot after a controlled 1k-row same-semantic import**, then 5k/10k/50k if previous stage passed. Compare index-by-index byte deltas, `idx_scan` deltas, insert/update/delete/HOT/dead deltas, autovacuum timestamps and physical density only where explicitly available. Repeat after normal autovacuum; correlate to actual query `EXPLAIN (ANALYZE, BUFFERS)` and importer-stage timings. **No import load test has been performed in B yet.**
- Root cause and remediation stay **OPEN** until controlled causal tests distinguish delete churn, HOT failures, index split/fillfactor and GIN pending-list growth. No index removal, vacuum reloptions, schema migration, worker change or data mutation is authorized by this baseline.

## Reproduction authority and safety

Measured via existing `open_tenant_session(38)` under `row_security=on` and PostgreSQL catalog views: `pg_class`, `pg_namespace`, `pg_index`, `pg_am`, `pg_constraint`, `pg_stat_user_indexes`, `pg_stat_all_tables`, `pg_stat_database`, `pg_stat_wal`, `pg_settings`, `pg_stat_activity`, `pg_extension` and `pg_relation_size/pg_table_size/pg_indexes_size/pg_total_relation_size`. Set local statement timeouts (5–15s), run scoped `COUNT(*)`, roll back and close. Never show or copy a database password or expose another company's row data. Snapshot timestamps and stats-reset limitations must accompany all reported deltas.

**Checkpoint outcome:** B1 catalog index/tables baseline **PASS**; B2 safe test design **PASS**. **Physical bloat measurement, controlled growth, index redundancy and root-cause diagnosis NOT YET EXECUTED.** See the urgent plan Phase B remaining checkboxes.
