# B3.8 — measured real Excel pipeline and isolated barcode query repair

**Date:** 2026-09-29. **Branch:** `hardening/catalog-index-worker-fairness`. **Checkpoint:** XLSX → staging → barcode validation → committed product/price execution on a disposable PostgreSQL 16 clone **PASS at 1,000 and 5,000 rows**. **Full HTTP authorization / durable SourceStore admission / Procrastinate queue scheduling / real production-sized ~217k SKU index baseline / official Wanasah 50k workbook not run.** Phase B overall, index-bloat maintenance and 50k SLA remain OPEN.

## Measured scope and evidence

`scripts/b38_profile_real_import_disposable.py` generates a real, self-contained XLSX workbook with varied packages, prices, tracking, uniquely derived synthetic barcodes and **1% deliberately invalid source rows** using the existing Phase19 data generator. It enters the existing `open_source` XLSX parser, `stage_source`, `validate_rows` and `execute_import` application services **without replacing business logic**. `run_b3_index_growth_gate.py` creates a fresh PostgreSQL 16 cluster at `127.0.0.1:55441`, copies only schema and approved empty synthetic tenant-2 UOM/actor/one SKU fixtures from the local developer database, enables `pgstattuple` **only in the disposable DB**, and destroys the cluster after every benchmark. Each import stage uses the real SQLAlchemy + PostgreSQL RLS, tracked source physical row numbers, per-row validation and barcode staging, idempotent execution batches, lifecycle events, append-only audit/outbox, actual draft/published price entries, and committed transactions. No real tenant customer data or active production source data is written.

Timings measured from Python `perf_counter`, rounded to 3 decimal places; individual isolated runs, not randomized A/B on a full catalog:

| XLSX source | 1,000 rows | 5,000 rows |
|---|---:|---:|
| Generate XLSX fixture outside worker stages | 0.173 s | 0.618 s |
| Open XLSX + stage source rows transactionally | **0.547 s** | **3.821 s** |
| Inside staging: active parser iterator time (subset, not additive) | 0.200 s | 2.058 s |
| Validate source row values, build staging barcodes, resolve duplicate/existing barcode conflicts | **0.224 s** | **3.141 s** |
| Create products, SKU UOM links, commercial prices, audit/outbox and commit batches | **11.429 s** | **77.600 s** |
| Final evidence read after execution (not included in execution) | 0.016 s | 0.015 s |
| Committed new SKUs | **990** | **4,950** |
| Invalid as designed | **10** | **50** |
| Published price entries | **1,817** | **9,083** |
| Execution-stage SQL statements | **6,463** | **31,729** |
| Execution-stage `INSERT` / `UPDATE` / `SELECT` / `WITH` | 4,940 / 1,070 / 393 / 30 | 24,206 / 5,350 / 1,873 / 150 |
| SQL cursor-time inside execution (subset of wall time) | 7.536 s | 55.646 s |
| Whole staging + validation + execution (excluding fixture setup/queue/HTTP) | **12.200 s** | **84.562 s** |
| Fixture job end state | COMPLETED_WITH_ERRORS | COMPLETED_WITH_ERRORS |

**Evidence reconciled:** all `product_import_rows` from valid sources ended as `IMPORTED`; all invalid test rows remained `INVALID`; imported-to-SKU identity mapping and final variant counts matched exactly. The test harness was subsequently hardened to **assert exact expected EACH/package published price counts**, not merely print them. There is no promise that file uploads over network, real HTTP authorisation, queue wait, real 217k-row index size or customer activity are included.

The 5k **validation-only** rerun on a separate disposable cluster after fixing barcode queries recorded **4.178 s staging, 2.646 s validation, 4,950 valid / 50 invalid**; the Phase6 disposable 50k query-plan fixture passed **15/15**, using the original active-barcode UNIQUE index `uq_active_product_barcode` and a temporary staging index. Timing differences versus the 3.821/3.141 full run are host variance and different execution context, not regressions.

## Confirmed query-level cause of a validation-phase stall

The original external existing-barcode conflict path used per-staged-barcode correlated `LATERAL` constraints and then attempted an UPDATE of source rows. On larger temporary staging data, PostgreSQL could choose a planner path that rescanned candidates for every outer row rather than computing the conflict set once. Earlier B3.8 diagnostics isolated this class of expensive validation statement; the revised code is in `domains/simple_products/imports/infrastructure/repository.py`.

- Uses a tenant/job-scoped `EXISTS` semi-join on `product_barcodes` with `existing.is_active IS TRUE`, still relying on the existing `uq_active_product_barcode` authority (no `DROP INDEX`).
- A `MATERIALIZED` `bad_rows` CTE computes external conflicts once, then updates only valid rows from the same tenant/job; no cross-tenant collision or deactivation semantics change.
- An independent disposable fixture verified that a staged barcode colliding with an **active** existing barcode is rejected, while collision with an **inactive** barcode remains allowed; a 50k synthetic index-plan gate passed 15/15 on a disposable clone. Exact historical pre-fix 5k duration was **not** recorded as a comparable completed baseline; do NOT advertise a specific X-times speedup.

In the latest 5k run the stage timing makes the remaining bottleneck clear: **~77.6 s of 84.56 s are creation/pricing/commit**, not XLSX parse/validation. Even after B3.1–B3.7 SQL deduplication, the real import execution loop still executed **31,729 commands** for 4,950 successful rows. Reducing remaining writes without breaking immutable lineage is the next major performance area.

## Additional execution hot path requiring follow-up

SQL tracing (SQL structure preview and hash only; **no bind parameters or customer contents logged**) identified multiple `WITH new_starts AS ...` statements in `domains/pricing/publishing.py::_close_predecessor_ranges` taking **0.36–0.57 seconds EACH** in the 5k run. This domain routine checks historical published-effective range overlap and locked commercial contexts; current publication inserts are bounded but the price book accumulates many previous published rows. The B3.8 change at HEAD `09959d5` already materializes the new current price set before its final historical overlap probe, and its correctness gate protects GiST effective-range exclusion. **Do not bypass publication/route-history constraints or delete a covering index** just to make this faster. The other two `new_starts` queries (locked commercial route-context detection and real predecessor range closure) should be EXPLAINed on a representative scoped 5k/50k test book before further optimization. Variants are newly created in this fixture, so the expected predecessor match set is empty; the correctness-sensitive general pricing API must still handle legitimate price revisions with shared SKU/UOM identities.

For a credible enterprise SLA and safe merge:

- [x] Real XLSX parser, staging, validation, and committed execution baseline on one synthetic tenant: 1k and 5k, with integrity and price count gates.
- [x] Existing/active external barcode lookup made set-based and validated on 5k and 50k synthetic **query-plan** fixture.
- [x] Verified no active DB schema, extension, index, worker, financial cost, or customer data changed by these experiments.
- [ ] Implement phase-specific **full HTTP/SourceStore/Procrastinate queue** end-to-end on an explicitly isolated environment; no real customer DB import runs to measure timing. Include queue wait and durable retry/cancellation.
- [ ] Analyze/optimize priced product writing without losing domain audit/outbox, tenant FKs, pricing/range historical authority, product identity, maker/checker, and version evidence. Target SQL and WAL byte write amplification **not just statement counts**.
- [ ] Repeat on a representative company-sized catalog (~217k SKUs), realistic row mix and existing barcode density, 5k→10k→50k XLSX sources, memory/CPU/WAL/IO and read-latency p95. Do not extrapolate this tiny clone linearly to 35k products.
- [ ] Review each existing active index against real SELECT/UPDATE/INSERT query plans and physical density; no index deletion, routine REINDEX or active `autovacuum_scale_factor` change without independent proof.
- [ ] Run the required final backend/Finance/costing/UI gating after any further implementation; B3.8 scoped metrics alone do not close Phase B or approve a merge.
