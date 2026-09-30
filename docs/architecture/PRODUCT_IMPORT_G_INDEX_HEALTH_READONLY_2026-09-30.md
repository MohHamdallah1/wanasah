# V1 Audit G — Index and Autovacuum Read-only Forensic Snapshot

**Date:** 2026-09-30. **Scope:** approved development
`velotrack_db`, PostgreSQL 16.9. **Mode:** SQL
`SET TRANSACTION READ ONLY`. No DDL, VACUUM, REINDEX, CREATE
EXTENSION, table deletion or business-record changes.

This is **G-local index/heap-stat census**, not a production-sized
index-bloat finding or overall G closure. Historical B3/B4 synthetic
index-churn experiments remain independently available; they were
**not rerun** for this read-only snapshot.

## Actual snapshot (database statistics are estimates)

| Object | AM | Size (MiB, approx.) | Observed index scans | Notes |
|---|---|---:|---:|---|
| `ix_product_variants_company_search_trgm` | GIN | 32.77 | 300 | Keep customer search support; size alone cannot prove bloat. |
| `uq_company_sku` | unique B-tree | 17.23 | 1 | **Must never drop because of low scan count:** unique constraints also enforce writes. |
| `excl_price_book_entry_published_overlap` | GiST | 30.49 | 991,018 | Published price-history exclusion authority; preserve. |
| `ix_price_book_entry_resolver` | B-tree | 34.88 | 903,496 | Large, actively used historical-price resolver. |
| `ix_product_import_row_job_status` | B-tree | 25.11 | 1,504,392 | Import staging/status access. |
| `ix_product_import_row_barcode_job_barcode` | B-tree | 22.40 | 22,615 | Elevated cumulative tuple reads merit *query-attributed* checking in staging. |
| `uq_product_import_row_job_identity` | unique B-tree | 21.30 | 43,474 | Preserve idempotent row identity. |
| `uq_active_product_barcode` | unique B-tree | 18.48 | 2,975,572 | Preserve barcode uniqueness. |
| `ix_product_barcodes_company_active_barcode_trgm` | GIN | 16.27 | 279 | Keep search functionality. |

Every index in the **35 largest returned** catalog/import indexes
had `indisvalid=true` and `indisready=true` in the snapshot;
this is not an audit of *every* index or proof every planner query
has optimal cost. `pg_trgm` and `btree_gist` exist;
`pgstattuple` was **not installed on the developer database**,
and was deliberately **not installed** for this analysis.

Approximate `pg_stat_user_tables` live/dead row estimates:

| Table | Estimated live | Estimated dead | Approx. dead fraction |
|---|---:|---:|---:|
| `product_variants` | 273,834 | 23,935 | 8.0% |
| `price_book_entries` | 261,709 | 16,363 | 5.9% |
| `product_import_rows` | 223,000 | 4,553 | 2.0% |
| `product_import_row_barcodes` | 263,377 | 390 | 0.15% |
| `product_barcodes` | 267,369 | 36 | 0.01% |
| `products` | 24,906 | 4 | 0.02% |

`product_import_rows`, `product_import_row_barcodes` and
`product_import_jobs` already have per-table autovacuum
scale-factor/threshold settings (the import jobs threshold is
substantially lower). Recorded autovacuum and autoanalyze counters
were nonzero for every listed table. The one-shot query found
**zero transactions aged over 60 seconds at inspection time**.
That does **not** disprove earlier idle-in-transaction incidents.

## Engineering interpretation and stop conditions

- PostgreSQL **does not report physical index bloat** from
  `pg_relation_size`, `idx_scan` or approximate `n_dead_tup` alone.
  Treat historical 14 → 32 MiB search-TRGM and 10 → 16 MiB SKU
  growth as *capacity observations*, not root-cause proof.
- Do **not** remove `uq_company_sku`, active barcode uniqueness,
  published-price GiST exclusion, or tenant/search B-tree/GIN/TRGM
  indexes. Even zero `idx_scan` over an unknown reset window does not
  make a uniqueness constraint disposable. Such changes can break
  customers, pricing or isolation, and are NOT authorized by this audit.
- Do **not** run `VACUUM FULL`, `REINDEX`,
  `CREATE EXTENSION pgstattuple` or ALTER autovacuum against
  the development/production database solely because of this report.
  These actions were intentionally **not performed**.
- PostgreSQL cumulative counters can reset. They do not identify
  which request, company, worker or SQL shape caused their reads.
  The high import-barcode tuple-read counter cannot independently
  explain a perceived long import. Compare its normalized SQL/
  `pg_stat_statements` delta, EXPLAIN buffers and *concurrent* latency
  only in a controlled representative fixture.

### What is needed for final Audit G

On an **isolated production-like staging database** with representative
company mix, SKUs, barcode cardinality, price revisions and import
retention, take two matched snapshots around real controlled import +
DRAFT→ACTIVE churn. Compare heap/index bytes, transaction age,
autovacuum progress, index scans, GIN pending lists, GiST/B-tree page
density and actual slow query plans. Use `pgstattuple` /
`pgstatindex` / `pgstatginindex` **only if permitted on that isolated
clone**, with bounded statement timeouts and storage overhead reviewed.
Restore and RLS/price-history correctness remain binding. Distinguish
growth from fragmentation, and benchmark any index/migration change
against the original plan and query. If no reproducible regression,
retain the existing indexes; do not invent a fix.

**G-local READ-ONLY CENSUS = COMPLETE.**
**Audit G production-scale index-growth sign-off = OPEN.**
