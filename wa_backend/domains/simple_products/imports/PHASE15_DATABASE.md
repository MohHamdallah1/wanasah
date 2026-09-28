# Product Import Phase 15 — database/index strategy

## Index authority

The hot batch read path is already covered by:

- `ix_product_import_row_job_status (company_id, job_id, status, row_number)`
  for validation keyset batches, execution selection and ordered existence probes.
- `ix_product_import_row_barcode_job_barcode (company_id, job_id, barcode, row_number)`
  for the normalized barcode staging joins introduced in Phase 6/7.
- `uq_product_import_row_job_number (company_id, job_id, row_number)`
  for stable row identity/FK lookup.

No duplicate barcode/status index is added in Phase 15: the existing index order
exactly matches the tenant-scoped query shapes and an additional equivalent
index would increase insert/update/vacuum cost without adding a new access path.
Surrogate primary keys on `id` are the only non-tenant-prefixed indexes on jobs/
rows; all tenant query/constraint indexes begin with `company_id`.

## 50k benchmark evidence

`scripts/audit_product_import_phase15_scale.py` uses the real staging tables,
FORCE RLS runtime role and `EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON)`.
Representative development run after Phase 15 changes:

- 50,000-row seed: `1510.216 ms`.
- validation batch (`STAGED`, 500 rows): `0.596 ms`,
  `ix_product_import_row_job_status`, no sequential scan.
- mixed execution selection (`VALID`, 100 rows, `FOR UPDATE SKIP LOCKED`):
  `0.136 ms`, same index, no sequential scan.
- execution finalization existence probe: `0.058 ms`, same index, no
  sequential scan.
- two concurrent SKIP LOCKED consumers: `100 + 100` disjoint rows in
  `5.614 ms`; no deadlock/blocking overlap.
- owner plan `0.123 ms` vs FORCE-RLS runtime plan `0.216 ms`
  (`1.76x` on sub-millisecond work); the RLS plan retained the same index.
- 20k-row churn update: `407.875 ms`.
- manual `VACUUM (ANALYZE)` after churn: `146.304 ms` while concurrent
  indexed foreground reads peaked at `4.563 ms`.

The benchmark also records live/dead tuples, table/index/total bytes, last
autovacuum/autoanalyze timestamps and transaction age. The development database
had deliberate synthetic churn from repeated audits, demonstrating why physical
index bytes must be monitored even after dead tuples are vacuumed.

Phase 6 remains the 50k barcode-join plan gate and is run together with this
audit; it verifies the real staging index definition plus the set-based duplicate
join plan without loading a large FK-backed barcode fixture into durable tables.

## Full-scan policy

Phase 15 removed `count_job_progress()` from the execution batch loop. Batch
progress now advances by the committed imported-row delta under the locked job
row. When SKIP LOCKED returns no rows, execution uses an ordered indexed
existence probe for remaining VALID rows and derives terminal counts from durable
job counters.

Validation performs one grouped status reconciliation when a validation lifecycle
starts (needed for restart/correction recovery). It does not perform an aggregate
scan after every batch. Final checkpointing uses indexed STAGED existence and
barcode invalidation row-count deltas.

## Autovacuum/analyze tuning

The pre-Phase-15 50k churn run produced 20,000 dead row versions after one
bounded status-change workload; PostgreSQL defaults would wait for about
`10,050` dead tuples at 50k live rows before vacuum. The measured manual
vacuum/analyze completed in roughly `125–247 ms` during these development runs.

Phase 15 therefore sets the high-churn row/barcode tables to:

- vacuum: threshold `2500`, scale factor `0.05` => `5000` tuples at 50k.
- analyze: threshold `1000`, scale factor `0.02` => `2000` tuples at 50k.
- insert vacuum: threshold `5000`, scale factor `0.05` => `7500` inserts at 50k.

This is materially earlier than PostgreSQL defaults but not per-batch: a 500-row
validation batch needs ten full batches before the 50k vacuum threshold is
crossed. `product_import_jobs` uses lower absolute thresholds appropriate to its
small update-heavy footprint. The final retention/compaction implementation from
Phase 10 was already present when the Phase 15 churn/vacuum benchmark was run.

## Ongoing health monitoring

The existing five-minute Product Import capacity scheduler now also records:
live/dead tuples, dead-tuple percentage, table/index/total bytes, transaction
age, autovacuum/autoanalyze lag/counts, active vacuum duration and reloptions.
Repeated warnings provide sustained dead-tuple/bloat-growth visibility; separate
alerts cover autovacuum lag and transaction-age risk.
