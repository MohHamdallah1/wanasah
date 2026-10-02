# Product Import — Final V1 Engineering Acceptance

**Closed:** 2026-10-02  
**Scope:** Product Import development/engineering acceptance.  
**Runtime authority:** current source + `ARCHITECTURE.md`.  
**Release-time authority:** `docs/operations/PRODUCT_IMPORT_V1_RELEASE_RUNBOOK_2026-09-30.md`.

## Final owner Dashboard evidence

The owner completed the final real Dashboard XLSX acceptance on the intended developer database.

- 500-row mixed acceptance: **350 IMPORTED / 150 expected INVALID / 0 IMPORT_FAILED**. Worker execution: **4.378 s**.
- 50,000-row mixed acceptance: **35,000 IMPORTED / 15,000 expected INVALID / 0 IMPORT_FAILED**. Full worker time: **243.302 s (~4m03s)**.
- 50,000-row all-valid acceptance: **50,000 IMPORTED / 0 INVALID / 0 IMPORT_FAILED**. Full worker time: **241.798 s (~4m02s)**.
- The all-valid run executed **250 data batches x 200 products**. Mean batch wall time **629.49 ms**, median **600.96 ms**, min **396.55 ms**, max **1299.33 ms**. First 25 batches averaged **575.62 ms**; last 25 averaged **831.28 ms**.
- Final all-valid measured phases: source-row buffer **36.140 s**, staging session **27.893 s**, barcode rebuild **4.952 s**, internal barcode validation **0.370 s**, external barcode validation **1.176 s**, execution service **157.814 s**.
- Profiling integrity: **251 profiles (250 data + terminal)**, **0 dropped SQL timings**, **0 incomplete profiles**, **0 unfinished SQL calls**.
- Final execution SQL: **11,762 calls / 61.155 s cursor wall**. Major measured phase SQL: activation flush **18.461 s**, price publish **14.745 s**, draft flush **8.224 s**, savepoint attempts **7.865 s**, product structures **6.517 s**.
- Historical comparable 50k execution was ~**726.390 s (~12m06s)**; the final ~4-minute runs establish the V1 development performance point. Further deep optimization is V2/evidence-driven work unless a real deployment regression appears.

Raw owner-machine evidence remains local and Git-ignored under `IMPORT_PERFORMANCE_EVIDENCE_2026-10-02/`.

## D3 database/table/index health closure

Post-run read-only PostgreSQL checks showed no destructive bloat signal.

- `uq_product_variants_company_id(company_id,id)`: **idx_scan 33,088,620**, idx_tup_read 35,274,421, idx_tup_fetch 33,803,319, size ~10 MB.
- Dead tuple ratios: `product_variants 0.0000%`, `price_book_entries 0.0000%`, `product_barcodes 0.0434%`, `product_uom_conversions 0.0512%`, `products 0.0122%`, `product_import_rows 0.5524%`, `operation_idempotency 1.7133%`.
- Autovacuum/autoanalyze ran during or immediately after the large imports on the heavy tables.
- Health-check row counts: products **32,801**, product_variants **394,884**, product_barcodes **490,799**, price_book_entries **489,821**, product_import_rows **374,431**.
- Company 38 owned **274,607 variants (69.54%)** at the check. Tenant-prefixed indexes preserve logical access locality, while CPU/cache/WAL/I/O/autovacuum remain shared PostgreSQL resources. Sustained multi-million-row single-tenant pressure is a V2 scale concern unless a measured V1 regression appears.

**D3 decision:** closed. No V1 REINDEX/VACUUM FULL/index removal or deeper ORM rewrite is justified by current evidence.

## D4 recovery closure

The recovery design is already implemented: separate control queue, global recovery advisory mutex, stalled-worker recovery, orphan business-job reconciliation, job-scoped queue dedupe, company-scoped execution serialization, same-job retry, cancellation at durable transaction boundaries, lost-COMMIT-ack reconciliation, permission recheck, and retention locking.

The six historical synthetic developer jobs for companies 2393–2398 were read back on 2026-10-02:

- D4 produced exactly one `wanasah.process_product_import` delivery per job.
- Each queue delivery ended `succeeded` on attempt 1.
- Each business job correctly ended terminal `FAILED / PRODUCT_IMPORT_JOB_INVALID` because its retained `tracking.csv` source is intentionally only one byte.
- Current developer DB readback: **0 active Product Import jobs**, **0 active business jobs without live delivery**, **0 live Product Import execution deliveries**.
- Their retained SourceStore rows are not an orphan defect. The 7-day source-retention window is based on terminal `finished_at`; normal cleanup becomes due around 2026-10-08 11:49 UTC. Do not manually mutate/delete those records.

**D4 decision:** closed for current development engineering.

## Preserved V1 contracts

Performance work did not weaken tenant/RLS isolation, Product/Variant identity, Product/Pricing/UOM authority, price history, Maker/Checker, audit/outbox, idempotent request/job identity, durable correction/retry, cancellation boundaries, SourceStore semantics, row fidelity, or company-scoped execution serialization.

## What remains open

These are **not reasons to keep Product Import engineering open**:

- first-company D7-P/D8-P deployment rehearsal and release sign-off;
- real target backup + disposable full restore;
- target-host p50/p95/p99/resource/connection/alert envelope;
- real ingress/proxy log checks if such infrastructure exists;
- final physical keyboard/screen-reader/touch owner walkthrough where required.

Those items remain in the release runbook.

Pure scale work—1,000 genuinely open external connections, sustained multi-company fairness, multi-million-row tenant pressure, production-scale SQL/ORM/index profiling, and deeper bulk-write optimization—belongs to `VERSION_2_FUTURE_FEATURES.md`.

## Repository cleanup note

The former Product Import hardening/performance plans and detailed Phase 19 evidence files were intentionally removed after this acceptance was consolidated here. Git history remains available if forensic detail is ever required.
