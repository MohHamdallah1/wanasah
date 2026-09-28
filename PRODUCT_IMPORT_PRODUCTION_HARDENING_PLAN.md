# Product Import — Production Hardening Plan

**Status:** ACTIVE IMPLEMENTATION PLAN  
**Scope:** Product/Catalog bulk import backend (CSV/XLSX)  
**Architecture authority:** `ARCHITECTURE.md`  
**Owning domain today:** `domains/simple_products`  
**Goal:** Enterprise-grade bulk Product ingestion that is modular, maintainable, bounded in memory, resumable, tenant-safe, observable, idempotent, and simple for the UI to consume.

> **🚨 RED-LINE REFACTORING RULE — DO NOT DELETE OR SILENTLY DROP EXISTING CODE DURING FILE MOVES / MODULE SPLITS.**
>
> **Architecture/refactor phases must preserve behavior first. Moving, renaming, splitting, or re-exporting code is not permission to “clean up” logic. No branch, helper, validation, security check, retry rule, tenant guard, idempotency behavior, or operational path may be removed merely because it looks redundant. Any later deletion must be a separate, explicit change backed by references/search evidence and tests proving the code is obsolete. When uncertain, preserve it.**
>
> This warning is intentionally repeated at the top because Phase 1–3 are structural and therefore have the highest accidental-deletion risk.

> This plan is implementation authority for the current Product Import hardening work.  
> Complete items one by one and mark them `[x]`. Do not skip forward when a previous phase defines contracts relied on by later phases.

## Execution priority and official stop point

The plan is intentionally split into two tracks:

### Track A — FOUNDATION FIRST (must be completed before any import-behavior redesign)

1. **Phase 1 — correct module ownership and file placement**
2. **Phase 2 — split the 1,500-line worker by responsibility without changing runtime behavior**
3. **Phase 3 — centralize and formalize the import state machine / contracts**

After Phase 3, the backend should have a clean, scalable structure and a single explicit state-machine authority. **This is an approved stopping point.** If Product Import feature hardening is postponed, stop here and leave the existing import semantics intact.

### Track B — IMPORT ENGINE HARDENING (may be postponed as one unit)

Everything after Phase 3 changes or strengthens the behavior of the import engine itself: streaming, bounded validation, database-backed duplicate detection, best-effort semantics, row-safe retry/idempotency, transaction isolation, audit retention, source fidelity, storage, queue scaling, error contracts, performance gates, and final cleanup.

**Do not start Track B accidentally while doing Track A. Structural refactoring must not silently change import semantics.**

---

## 0. Non-negotiable invariants

These rules apply to every phase below.

- [x] Current backend import flow audited end-to-end before refactoring.
- [ ] Preserve strict tenant/company isolation and PostgreSQL RLS.
- [ ] Preserve permission re-checks inside asynchronous execution.
- [ ] Preserve Catalog/Product, Pricing, Tracking and UOM domain authority; import code must orchestrate them, never duplicate them.
- [ ] Preserve durable queueing and network-request idempotency.
- [ ] Preserve fail-closed behavior for ambiguous tenant, permission, mapping and system-state conditions.
- [ ] Separate deterministic row/data errors from transient/system/runtime failures.
- [ ] No silent conflict handling and no `ON CONFLICT DO NOTHING` for business invariants.
- [ ] No unbounded in-memory collection proportional to file row count.
- [ ] No tenant/user can exhaust import storage or queue capacity by submitting many individually-valid uploads; admission control must happen before durable payload storage.
- [ ] Import progress delivery must not depend on high-frequency polling that scales request volume linearly with active users/jobs.
- [ ] No raw technical exception text in user-facing error contracts.
- [ ] Every structural move must have architecture/import-boundary tests before old paths are removed.
- [ ] Do not alter unrelated Product business behavior while hardening import infrastructure.

---

# Phase 1 — Put Product Import in the correct backend module

## Problem

The import capability is currently spread across root-level backend files, a large global API file, global models, queue code, worker code and migrations.

Current core files include:

- `product_import_localization.py`
- `product_import_queue.py`
- `product_import_template.py`
- `product_import_worker.py`
- Product-import endpoints inside `api/simple_products.py`
- `ProductImportJob` / `ProductImportRow` inside global `models.py`
- Product creation authority in `domains/simple_products/service.py`
- Tracking authority in `domains/product_tracking.py`
- Worker recovery in `workers/recovery.py`

The four `product_import_*.py` files are not the whole system. They are only the current import-specific core.

## Target ownership

Product Import is a capability of the existing Product/Simple Products domain. It should be co-located under that domain rather than becoming another top-level backend subsystem.

Target shape:

- `domains/simple_products/imports/api/`
  - Product-import router / transport adapter only.
- `domains/simple_products/imports/application/`
  - orchestration, commands, job state transitions and use cases.
- `domains/simple_products/imports/domain/`
  - import contracts, normalization rules, deterministic validation concepts and error taxonomy.
- `domains/simple_products/imports/infrastructure/`
  - CSV/XLSX parsing, staging repository, queue adapter, template generation and persistence adapters.

The existing `domains/simple_products/service.py` remains Product authority. Product Import calls that authority through an explicit application-facing contract; it must not copy Product creation rules.

`domains/product_tracking.py` remains Tracking authority.

A final modular design should expose the import router from its owning module. A permanent `api/simple_product_imports.py` at the global API root is **not** the preferred end-state; that would only move the mess sideways.

## Tasks

- [x] Create the module package and explicit public entry point.
- [x] Define allowed dependency directions for the import module.
- [x] Move localization into the import domain layer.
- [x] Move template generation into import infrastructure.
- [x] Move queue implementation into import infrastructure.
- [x] Split worker responsibilities into application orchestration + infrastructure/parser/repository components.
- [x] Move Product-import HTTP endpoints out of the large `api/simple_products.py` file into the module-local API layer.
- [x] Keep the application router registration thin and explicit.
- [x] Introduce an import repository so application code no longer reaches global ORM models everywhere.
- [x] Keep global model relocation as a controlled schema/model-ownership step; do not create circular imports just to move class declarations.
- [x] Add an architecture gate that forbids new root-level `product_import_*.py` business files.
- [x] Add an architecture gate that prevents import infrastructure from becoming Product/Pricing/Tracking business authority.
- [x] Update worker launcher/runbook imports after the move.
- [x] Update all tests/gates to use the module public path.
- [x] Remove obsolete root-level import files only after all imports and gates pass.

### Phase 1 exit criteria

- [x] No Product Import business/orchestration file remains loose in `wa_backend/` root.
- [x] No Product Import endpoint remains buried in the oversized general Product API file.
- [x] The import module has explicit domain/application/infrastructure/api boundaries.
- [x] Existing runtime behavior is unchanged at this phase.

---

# Phase 2 — Break up the 1,500-line worker into explicit responsibilities

## Problem

`product_import_worker.py` currently owns too many unrelated responsibilities:

- file parsing;
- XLSX archive security;
- header detection;
- row normalization;
- staging;
- validation;
- duplicate detection;
- Product creation orchestration;
- job status transitions;
- retry/failure recording;
- tenant session lifecycle.

This makes maintenance and safe testing harder and will become worse as import channels grow.

## Tasks

- [x] Define one explicit import job state machine.
- [x] Extract parser interfaces and format-specific parsers.
- [x] Extract row normalization from job orchestration.
- [x] Extract staging persistence into repository methods.
- [x] Extract validation orchestration into its own application service.
- [x] Extract import execution into its own application service.
- [x] Extract failure classification and error recording.
- [x] Extract job-state transition helpers and make illegal transitions fail closed.
- [x] Keep queue task code thin: load context, call application use case, classify retryability.
- [x] Add focused unit tests per responsibility.
- [x] Add a size/complexity architecture guard so a new worker god-file cannot return.

---

# Phase 3 — Centralize and lock the import state machine / contracts

> **FOUNDATION PHASE:** the canonical state vocabulary is now expanded for future best-effort execution, but best-effort/partial-import processing itself remains disabled. The current validation policy is still all-or-nothing until its dedicated later phase.

## Problems

The current job mixes validation-terminal states, runtime-terminal states and resumable states. Status strings are spread across API, queue, worker, ORM constraints and migrations.

Validation currently behaves all-or-nothing, while import execution commits in batches. Those semantics are inconsistent.

## Foundation target

Phase 3 first captures the **current** job/row lifecycle in one authoritative state-machine contract so status strings and transitions are no longer scattered across API, queue, worker, ORM constraints and migrations.

The desired Track B semantics are now represented in the state/error contracts, but the execution behavior is **not activated during this foundation refactor**:

- **best-effort across rows** — one bad Product must not block unrelated valid Products;
- **atomic within each successfully committed import unit** — a Product must never be half-created without its required Product/UOM/barcode/price effects;
- **idempotent on retries** — a committed successful row is never created twice;
- **fail-closed for infrastructure/system errors** — database outages, bugs and invariant failures are not mislabeled as bad Product rows.

That future design achieves atomicity and best-effort at different, compatible levels. The whole 50,000-row job is not one giant transaction.

## Tasks

- [x] Inventory every current job status, row status and transition before changing any of them.
- [x] Centralize current state constants/contracts rather than scattering raw strings.
- [x] Define canonical Job states and allowed transitions, including `COMPLETED_WITH_ERRORS` as a contract state without emitting it yet.
- [x] Define canonical Row states and allowed transitions with distinct `INVALID`, `IMPORT_FAILED`, and `IMPORTED` outcomes.
- [x] Add exhaustive state-transition tests for every allowed and forbidden Job/Row state pair.
- [x] Synchronize ORM/database constraints and preserve the public API shape/routes against the central state contract.
- [x] Preserve the current all-or-nothing validation/import execution policy; only the Phase 3 internal taxonomy/error classification changes are activated.
- [x] Add `COMPLETED_WITH_ERRORS` to the canonical/DB vocabulary without enabling partial-success execution yet.
- [x] Define deterministic validation/row-execution versus terminal/transient system error taxonomy; unexpected validation exceptions now fail closed as system errors rather than being mislabeled as bad rows.
- [x] Add owned Alembic migration `c4d9e7a1b623_stage7_import_states_taxonomy.py` with migration of legacy Row `FAILED` values to `INVALID`.
- [x] Validate migration in both directions (`downgrade -> upgrade`) and verify database constraints exactly match the canonical state machine.

### Foundation stop gate

- [x] Phase 1 module ownership/placement is complete.
- [x] Phase 2 worker decomposition is complete.
- [x] Phase 3 state-machine authority is centralized and tested.
- [x] Full Product Import regression gates pass with the intended Phase 3 taxonomy/error-classification change only.
- [x] Architecture/import-boundary gates pass.
- [x] No legacy code was deleted as part of Phase 3.
- [x] Track A can be stopped independently here before Phase 4/Track B import-engine redesign.

---

# Phase 4 — True bounded parsing and staging

## Problems

### CSV

The complete uploaded payload is decoded into one large string, then every parsed Product row is appended to a Python list before staging.

### XLSX

OpenPyXL was correctly opened in read-only mode, but every parsed row was still accumulated into a Python list before staging. Phase 4 also verified a deeper library-level issue: OpenPyXL 3.1.5 materializes the workbook shared-string table in memory even in read-only mode. The final Phase 4 implementation therefore keeps OpenPyXL's read-only cell semantics while replacing shared-string materialization with a bounded disk-backed SQLite sequence.

### Staging

`_stage_source` inserts in chunks, but only after the whole source has already been materialized in RAM.

## Target

Parsing and staging must be a bounded pipeline:

source → parse batch → stage batch → release batch → continue

Memory must be approximately proportional to batch size, not total Product count.

## Tasks

- [x] Introduce a parser contract that yields rows with their original source row numbers.
- [x] Stream CSV rows without building a complete `rows` list.
- [x] Stream XLSX rows from read-only workbook iteration without building a complete `rows` list, including disk-backed shared-string resolution so OpenPyXL cannot reintroduce row-count-scale RAM usage.
- [x] Stage fixed-size batches directly as they are parsed.
- [x] Preserve exact original row numbers, including when blank rows exist in the source.
- [x] Track total staged rows incrementally.
- [x] Enforce the 50,000-row limit incrementally without materializing the file.
- [x] Keep XLSX zip-bomb/archive safety checks before workbook traversal.
- [x] Guarantee workbook/file handles and disk-backed shared-string resources close on success and failure.
- [x] Add memory-bounded tests/benchmarks at 1k, 10k and 50k rows.
- [x] Prove that peak row-object accumulation is bounded by configured batch size.

---

# Phase 5 — Bounded validation instead of loading 50,000 ORM rows

## Problems

Validation currently loads every staged row into memory, then builds additional in-memory dictionaries for normalized rows, errors and barcode ownership.

This multiplies memory usage after parsing has already completed.

## Target

Validation must iterate staged rows with keyset/batch pagination and persist outcomes incrementally.

> Phase 5 deliberately keeps cross-row barcode duplicate detection bounded to the current validation batch. Whole-job duplicate/conflict detection remains owned by Phase 6 and is not implemented here.

## Tasks

- [x] Replace the full `.all()` staged-row load with ordered STAGED-only keyset/batch reads using bounded `fetchmany`.
- [x] Normalize each validation batch and persist normalized results/errors in bounded transactions.
- [x] Avoid keeping normalized data for the whole file in Python; validation dictionaries are hard-bounded to `VALIDATION_BATCH_SIZE = 500`.
- [x] Avoid keeping error dictionaries for the whole file in Python; only the current validation batch is retained.
- [x] Maintain aggregate valid/failed counters transactionally per batch and reconcile them with bounded SQL aggregates before finalization.
- [x] Make validation resumable from durable Row status checkpoints: committed `VALID`/`INVALID` rows are skipped and only `STAGED` rows are resumed.
- [x] Ensure retry never reclassifies already finalized rows; crash/resume tests verify prior Row `version` and normalization calls remain unchanged.
- [x] Add crash/restart tests during validation, including a simulated worker crash after the first committed batch.

---

# Phase 6 — Move cross-row duplicate checks to scalable database-backed logic

## Problem

Import-wide barcode detection can build tens of thousands of barcode values in Python and later issue a very large `IN (...)` query against active barcodes.

At 50,000 Products with unit/package barcodes, candidate count can approach 100,000 values.

## Target

Use staging/database operations for set-based validation rather than giant Python collections and giant parameter lists.

> Phase 6 uses dedicated barcode staging as a derived validation projection. Product/Pricing authority remains outside the import module, and the existing active-barcode unique index remains the final concurrency authority at Product creation time.

## Tasks

- [x] Persist normalized candidate barcodes in dedicated tenant-scoped `product_import_row_barcodes` staging.
- [x] Detect duplicate barcodes across the whole import with set-based SQL `GROUP BY barcode HAVING COUNT(*) > 1` and invalidate matching rows in SQL.
- [x] Detect conflicts with existing active company barcodes through a tenant-scoped indexed SQL join against `product_barcodes`.
- [x] Preserve the valid same-row shared unit/package barcode rule through the staging primary key `(company_id, job_id, row_number, barcode)`, which stores shared identity once per row.
- [x] Add owned Phase 6 staging index `ix_product_import_row_barcode_job_barcode (company_id, job_id, barcode, row_number)` plus ENABLE + FORCE RLS.
- [x] Remove Python-wide barcode sets and giant `IN (...)` parameter lists from validation; barcode checks are database set operations.
- [x] Prove 50k-row internal/external query plans use indexes and contain no protected Sequential Scans.
- [x] Add database integration/concurrent-conflict tests covering first/last-row duplicates, existing active conflicts, same-row shared identity, and a barcode becoming active after validation; `uq_active_product_barcode` remains the final race-closing authority.

---

# Phase 7 — Best-effort import with atomic successful units

## Problem

Current validation blocks the whole job if any row is invalid.

A business user with 49,999 valid Products and one bad row should not lose all useful work.

## Target

- validate all rows;
- mark invalid rows with deterministic errors;
- continue importing valid rows;
- finish as `COMPLETED` when all succeeded;
- finish as `COMPLETED_WITH_ERRORS` when some rows were invalid or import-failed;
- reserve `FAILED` for job/system failure that prevents safe continuation.

> Phase 7 keeps Phase 5 validation transaction boundaries intact. Execution remains batch-bounded; deterministic row failures are isolated through nested savepoints, while unknown/system exceptions are never reclassified as row failures. Imported row outcomes are retained for progress/audit and left for the dedicated retention phase.

## Tasks

- [x] Remove the old “any validation error blocks all valid rows” policy; validation continues whenever at least one row remains valid.
- [x] Continue from validation into `IMPORTING` when `valid_count > 0`, while zero-valid jobs stop at `VALIDATION_FAILED`.
- [x] Preserve every `INVALID` row and its deterministic error; execution selects only `VALID` rows.
- [x] Define zero-valid outcome explicitly as terminal `VALIDATION_FAILED`.
- [x] Define durable progress counters as total / imported / invalid / import-failed / pending using bounded SQL aggregation.
- [x] Extend the public job payload additively with `imported_rows`, `invalid_rows`, `import_failed_rows`, and `pending_rows`; frontend contracts/polling recognize `COMPLETED_WITH_ERRORS`.
- [x] Add a real 50,000-row CSV parser/normalization scenario proving 49,999 valid + 1 invalid continues and resolves to `COMPLETED_WITH_ERRORS`.
- [x] Add mixed tracking/package/price validation tests and retain Phase 6 database-backed barcode conflict/duplicate integration coverage.
- [x] Add tests proving invalid rows and deterministic execution failures never block unrelated valid rows; unexpected/system failures still propagate to the job failure path.

---

# Phase 8 — Row-safe idempotency and retry of failed rows

## Problem

Best-effort import is unsafe unless successful rows can never be duplicated during retries or correction flows.

Re-uploading the entire corrected file as a brand-new job can duplicate previously imported Products that have no naturally unique external identifier.

## Target

Retries of failed rows stay attached to the same durable import job and stable row identities.

Successful rows are immutable outcomes and are never replayed.

> Phase 8 uses the existing tenant-scoped `operation_idempotency` authority rather than inventing a second Product idempotency store. Correction upload, failed-row mutation, same-job transition, and queue defer are one PostgreSQL transaction. The generated correction format may add only its reserved metadata columns above the normal 100-column source limit.

## Tasks

- [x] Give every staged source row a durable UUID `row_identity`, unique within tenant + job and protected by a database immutability trigger.
- [x] Derive deterministic Product-creation request identity from `job_id` + ordered immutable row identities, with a canonical request hash over row identities + normalized payload.
- [x] Keep Product creation, durable operation-idempotency completion, and `IMPORTED` row outcome inside the same outer database transaction.
- [x] Keep execution/retry selection strictly `VALID`-only through the bounded repository path.
- [x] Keep `IMPORTED` as an immutable terminal row state; neither execution nor correction can move it back into the pipeline.
- [x] Add an idempotent correction contract that updates failed rows in-place and re-enters `VALIDATING` on the same durable job.
- [x] Generate CSV/XLSX correction artifacts containing only `INVALID` / `IMPORT_FAILED` rows plus explicit stable row identity metadata.
- [x] Validate correction identities tenant + job scoped and allow updates only for matching `INVALID` / `IMPORT_FAILED` rows.
- [x] Reject correction files that reference an `IMPORTED` row identity before any row mutation is applied.
- [x] Reset only corrected failed rows to `STAGED`; previous `IMPORTED` rows remain untouched while the same job is revalidated/re-executed.
- [x] Add crash/replay coverage proving a durable idempotency result restores the row outcome without a second Product create, while the normal path keeps Product + idempotency + row outcome atomic.
- [x] Add duplicate correction client-request tests proving the same `request_id` + payload replays without re-mutating rows.
- [x] Add duplicate queue-delivery tests proving the same job + row identity creates the Product once and replays the stored outcome.

---

# Phase 9 — Isolate one bad execution row without sacrificing batch performance

## Problem

Import currently sends up to 100 Products through one transactional batch. A deterministic constraint/business failure in one Product rolls back the whole batch and repeatedly blocks the other valid rows in that batch.

Blind `ON CONFLICT DO NOTHING` is forbidden because it can silently violate business expectations.

## Target algorithm

Use optimistic batch execution for performance, with savepoint-based deterministic isolation when a data-attributable batch fails.

Conceptually:

- try the full batch;
- if it succeeds, commit it;
- if it fails with a deterministic row-attributable business/data error, roll back to savepoint and split the batch;
- retry sub-batches until the bad row(s) are isolated;
- record those row failures;
- continue the other rows;
- if the failure is infrastructure/system-wide or non-attributable, fail/retry the job rather than blaming a Product row.

## Tasks

- [x] Define explicit deterministic row-attributable validation/execution exception classes and stable codes.
- [x] Classify unknown/database/infrastructure failures as transient job-scoped system failures rather than row failures.
- [x] Wrap optimistic execution attempts in nested database savepoints.
- [x] Bisect only deterministic row-attributable failed batches while preserving the fast full-batch path.
- [x] Stop bisection at one row and record that row as `IMPORT_FAILED` with its deterministic error.
- [x] Preserve Product/Pricing authority by continuing to execute through `create_products_and_prices`.
- [x] Keep each successful sub-batch on the same Product/Pricing creation authority and transaction path, preserving its pricing publication semantics.
- [x] Keep Product/UOM/barcode/pricing effects and the matching row outcome inside the successful transactional unit.
- [x] Add an explicit 100-row test where one active-barcode constraint failure is isolated and the other 99 rows import.
- [x] Add an explicit 100-row database-outage test proving the outage remains transient/job-scoped and no row is falsely marked failed.

---

# Phase 10 — Preserve audit lineage instead of deleting successful staging rows immediately

> **Retention contract:** source file bytes are normally removed as soon as durable staging succeeds and have a 7-day terminal-job hard ceiling; full row source/normalized detail is retained for 30 days; compact row lineage metadata is retained for 365 days. Cleanup is tenant-scoped, terminal-job-only, cutoff-bound, and batch-limited. Product Import job summaries and immutable source hashes are not deleted by this phase.

## Problem

Current completion deletes `IMPORTED` ProductImportRow records immediately.

That removes the useful lineage:

source file → source row → normalized row → created Product

This weakens audit, support, correction and forensic capability.

## Tasks

- [x] Keep imported row lineage after successful execution; execution no longer deletes `IMPORTED` rows.
- [x] Define retention as: upload bytes hard ceiling 7 days, full raw/normalized row detail 30 days, compact row lineage metadata 365 days.
- [x] Preserve durable `row_number` / `row_identity` → `product_variant_id` linkage through compaction.
- [x] Preserve immutable `source_sha256`, row number/token, status/outcome and error code across retention compaction.
- [x] After 30 days compact heavy `raw_data` / `normalized_data` and row error message while retaining compact audit metadata; prune derived barcode staging for compacted rows.
- [x] Separate source bytes from row lineage: source bytes are cleared immediately after successful staging when possible and forcibly cleared from terminal jobs by the 7-day ceiling; row lineage follows independent 30/365-day windows.
- [x] Add authorized keyset-paginated `/simple-products/imports/{job_id}/lineage` audit path backed by an explicit tenant session.
- [x] Add hourly Product Import retention scheduling with per-company locked cleanup jobs, 1,000-row bounded batches, a 10-batch/run ceiling, and explicit cleanup counters.
- [x] Add integration tests proving cleanup/compaction respects tenant RLS, never touches another company, preserves compact lineage fields, expires 365-day lineage, and honors bounded work.

---

# Phase 11 — Correct source-row fidelity and Excel semantics

> **Identity safety rule:** Wanasah never guesses a barcode that Excel may already have damaged. Numeric XLSX barcode cells are rejected because original leading zeros/digit fidelity cannot be reconstructed safely; scientific-notation text is rejected; literal text (including leading zeros) is preserved exactly. If an upstream CSV has already lost leading zeros and contains only plain digits, that lost information is not recoverable and must not be guessed.

## Problems

- Blank source rows can currently shift staged row numbering because numbering is reconstructed after filtering.
- Workbook `active` sheet is accepted silently.
- Formula/cached-cell behavior is not an explicit import contract.
- External Excel files can coerce barcode-like values to numbers and destroy leading zeros before Wanasah receives them.
- The current Product Catalog import does **not** ingest actual expiry dates; it only ingests expiry-tracking mode. However, any future date-valued spreadsheet field must not rely on naive Excel-number conversion because XLSX can use the 1900 or 1904 date system and includes the historic 1900 leap-year compatibility bug.

## Tasks

- [x] Preserve exact physical CSV/XLSX row numbers in `ParsedRow` and persist them unchanged through bounded staging; blank rows never renumber later source rows.
- [x] Define fail-closed XLSX worksheet selection: one visible external sheet is accepted; ambiguous multi-visible-sheet workbooks are rejected instead of using `active`.
- [x] Mark official Wanasah workbooks with hidden template metadata that names the canonical Products sheet; parser selection follows that marker deterministically.
- [x] Reject arbitrary XLSX files with multiple visible worksheets and require the user to provide/select one product worksheet; never choose one silently.
- [x] Traverse XLSX through paired bounded formula/cached-value readers: accept available cached values for non-identity fields, emit a row error when no cached value exists, and require barcode identities to remain literal.
- [x] Force official unit/package barcode columns to Excel Text format and apply text-only validation across all 50,000 template rows.
- [x] Reject numeric XLSX barcode cells as identity-unsafe, reject scientific-notation barcode text, and preserve literal leading-zero barcode text exactly.
- [x] Add one canonical `normalize_spreadsheet_date` authority for any future Product-import date-valued field; the current catalog import does not call it because it has no date-valued field.
- [x] Date normalization explicitly handles 1900/1904 epochs, rejects phantom serial 60 and fractional date-time serials, accepts native date/naive-midnight datetime and strict ISO `YYYY-MM-DD`, and rejects ambiguous locale text.
- [x] Keep future date-only values date-only: timezone-aware datetimes and non-midnight time components are rejected instead of silently converted.
- [x] Keep actual expiry/manufacture dates out of the current Product Catalog import; only the reusable date authority exists for the future owning inventory/inbound contract.
- [x] Add Phase 11 tests covering blank-row fidelity through staging, official/ambiguous worksheet selection, cached/uncached formulas, literal-only barcode formulas, numeric/scientific barcodes and preserved leading zeros.
- [x] Add canonical date-normalizer fixtures now for 1900/1904 epochs, serial 60, native date/datetime values, ISO text, ambiguous text, timezone values and fractional serials so future date-valued contracts inherit a tested authority.

---

# Phase 12 — Upload/source-payload memory and storage boundary

## Production boundary after hardening

The server upload ceiling remains **8 MiB**, but the HTTP path no longer materializes the whole source to calculate size or SHA-256. Upload bytes are read in fixed chunks into a disk-backed bounded spool while size and SHA-256 are calculated incrementally.

Application/queue logic now depends on the storage-neutral `SourceStore` contract. The current V1 production adapter stores immutable source metadata plus fixed **256 KiB PostgreSQL chunks**, because the current 8 MiB ceiling lets source persistence, durable capacity reservation, job creation and queue defer remain one database transaction. The application contract does not depend on PostgreSQL blobs; a future object-storage adapter can replace it without changing import orchestration.

Admission is enforced before source persistence with tenant/user rate limits, active-job limits, tenant live-source byte limits and a global source-storage ceiling. Concurrent requests are protected by tenant admission serialization plus durable atomic source-byte counters. Capacity denials return stable retryable codes with `Retry-After`.

## Tasks

- [x] Keep the current upload size bound enforced server-side — 8 MiB remains the authoritative Product Import HTTP ceiling.
- [x] Add import-specific admission control **before** persisting source bytes: per-user/per-tenant upload rate, maximum concurrent/queued jobs, maximum queued source bytes per tenant, and a global source-storage safety ceiling.
- [x] Make admission decisions from durable/atomic counters or database state so concurrent requests cannot race past quotas — tenant admissions use an advisory transaction lock and source bytes use durable tenant/global counters with conditional atomic reservation.
- [x] Return a stable retryable capacity/rate-limit error with Retry-After semantics when admission is denied; rejected admissions do not persist a new source.
- [x] Keep the existing global HTTP/IP rate limiter as defense-in-depth only; it is not a substitute for tenant-aware import quotas. This boundary is explicit in `domains/simple_products/imports/SOURCE_STORE.md`.
- [x] Add queue/source-storage metrics and alerts for queued/live source bytes, oldest retained source age, quota rejections and storage high-water marks.
- [x] Include PostgreSQL/WAL amplification in capacity tests while source payloads remain database-backed — the Phase 12 integration test measures `pg_wal_lsn_diff`; the current development run measured **1.073×** for the 1 MiB source fixture.
- [x] Compute size/hash in a bounded manner — HTTP uploads are read in 64 KiB chunks into a disk-backed spool while SHA-256 and exact byte count are calculated incrementally.
- [x] Introduce a `SourceStore` abstraction so queue/application logic references an immutable source rather than depending on one storage implementation.
- [x] Decide and document the production SourceStore implementation based on deployment needs — current V1 adapter is bounded PostgreSQL chunks under the 8 MiB ceiling.
- [x] If/when limits grow beyond the bounded DB-payload design, move source blobs to durable object storage without changing application contracts — the documented migration boundary is an immutable/checksummed S3-compatible adapter behind the same `SourceStore` port.
- [x] Guarantee source cleanup after staging according to retention policy — successful staging deletes retained SourceStore bytes immediately and Phase 10 remains the 7-day terminal-job hard ceiling; capacity counters are released atomically with source deletion.
- [x] Add hash verification before parsing/retry — the SourceStore streams every retained chunk in order, verifies exact size + SHA-256, and only then hands bytes to the parser; tampered/missing/reordered sources fail closed before parsing.

> Phase 12 migration `c9e5f2a7d310` backfills any still-live legacy inline source into the immutable SourceStore and initializes durable capacity counters. Its downgrade reconstructs still-live sources into the legacy inline payload before dropping the SourceStore schema, so migration rollback does not discard a queued source.

---

# Phase 13 — Queue concurrency, backpressure and worker availability

## Problems / decisions to make explicit

The queue currently serializes Product imports per company through a company-scoped lock. This is safe, but it is also a scalability policy.

The UI previously exposed the operational symptom of a worker not running as an endless queued spinner.

The current Product Import UI polls job status approximately every 1.5 seconds while active. That is acceptable for a small development workload but is not an enterprise-scale progress transport: request volume grows with every open import screen and can consume API/database connections unnecessarily.

Wanasah already has WebSocket infrastructure elsewhere in the backend. Product Import should reuse the platform realtime pattern through a **dedicated tenant-authenticated Product Import progress channel**, not reuse an admin/dispatch socket or create a second business authority.

## Tasks

- [x] Keep company-level serialization only if required by shared Product/Pricing invariants; document the reason.
- [x] Otherwise reduce lock scope safely after concurrency tests.
- [x] Add per-tenant active-import/backpressure limits.
- [x] Publish coarse-grained import progress/state-change events from the application/job-state authority after durable state changes.
- [x] Deliver progress push-first through a dedicated tenant-scoped realtime channel using the platform's existing WebSocket/realtime infrastructure pattern.
- [x] Authorize each subscription against the exact tenant/job; never trust a client-supplied company identifier as authority.
- [x] Coalesce/throttle progress notifications so row processing does not emit one network event per row.
- [x] Keep adaptive polling only as a fallback for reconnect/offline/realtime-unavailable cases, with exponential backoff, jitter and immediate stop on terminal states or hidden/closed workflow where appropriate.
- [x] Never poll every active import globally from the browser; subscribe only to jobs the user is actively observing.
- [x] Add connection/reconnect/backpressure tests for the progress channel.
- [x] Add global worker capacity metrics.
- [x] Add queue-age and oldest-job monitoring.
- [x] Add worker-health/readiness signal.
- [x] Add alerts for jobs stuck beyond expected stage duration.
- [x] Define cancellation semantics for jobs that have not committed all rows.
- [x] Ensure cancellation never leaves half-applied row effects.
- [x] Test duplicate queue delivery, stalled-worker recovery and worker restarts.


> **Phase 13 closure:** company serialization was retained because Product Import shares the company-default Pricing publication authority; see `domains/simple_products/imports/PHASE13_RUNTIME.md`. Queue-specific worker readiness, tenant backpressure, durable/coalesced realtime progress, adaptive polling fallback, safe cancellation and recovery/restart coverage are implemented and verified by `gate_product_import_phase13_runtime.py`.

---

# Phase 14 — Error contracts, security and user-safe diagnostics

## Problems

Some broad exception handlers currently store raw exception strings in row/job error fields. Those values may be too technical, unstable, or disclose implementation details.

Import error/report artifacts must also be safe when opened in spreadsheet software.

## Tasks

- [x] Create stable import error codes by phase and category.
- [x] Map deterministic domain errors to user-safe messages/context.
- [x] Keep technical exception detail only in structured server logs/observability with correlation IDs.
- [x] Never expose SQL/constraint/internal stack details to ordinary users.
- [x] Preserve actionable row number + field + safe code for business errors.
- [x] Sanitize generated CSV/error-report cells against spreadsheet formula injection.
- [x] Validate MIME/extension/content consistency where useful without trusting client MIME as authority.
- [x] Keep XLSX archive bomb, entry-count, compression-ratio and macro defenses.
- [x] Add malformed/corrupt/adversarial CSV/XLSX tests.

> **Phase 14 closure:** public Product Import diagnostics are code-driven and whitelist-based; technical exception/SQL/constraint detail is server-log-only with correlation IDs. Correction CSV/XLSX output is formula-injection sanitized, client MIME is not authoritative, source content signatures are verified, and XLSX archive/ratio/macro defenses remain fail-closed. Verified by `test_product_import_phase14_security.py` and `gate_product_import_phase14_security.py`.

---

# Phase 15 — Database/index, vacuum and table-health strategy for staged import scale

## Problem

`product_import_rows` is a high-churn staging table: rows are inserted in bulk, updated through validation/import states, and later compacted/deleted. `product_import_jobs` is smaller but update-heavy. Default PostgreSQL autovacuum thresholds are generic and may react too slowly for this workload as table size and churn grow. No Product Import-specific autovacuum reloptions are currently defined.

Do **not** hardcode arbitrarily aggressive settings without evidence; tune per table from realistic churn/load measurements and monitor bloat continuously.

## Tasks

- [x] Review indexes for job/status/row-number batch scans.
- [x] Establish baseline table-health metrics for `product_import_rows` and `product_import_jobs`: live/dead tuples, autovacuum/analyze timestamps, table/index bloat, vacuum duration and transaction age.
- [x] Define Product Import-specific per-table autovacuum/analyze reloptions from 50k-row churn benchmarks, with materially lower thresholds/scale factors for the high-churn row table where measurements justify them.
- [x] Evaluate `autovacuum_vacuum_scale_factor`, `autovacuum_vacuum_threshold`, `autovacuum_analyze_scale_factor`, `autovacuum_analyze_threshold` and, where supported/appropriate, insert-vacuum settings rather than tuning only one knob.
- [x] Validate that the chosen settings do not create vacuum storms or starve foreground import work.
- [x] Add observability/alerts for autovacuum lag and sustained dead-tuple/bloat growth.
- [x] Re-test autovacuum tuning after the final retention/compaction policy is implemented because retention directly changes table churn.
- [x] Add normalized-barcode staging indexes needed for SQL duplicate joins.
- [x] Keep all import indexes tenant-prefixed where tenant isolation/query shape requires it.
- [x] Benchmark validation queries at 50k rows.
- [x] Benchmark import selection with large mixed VALID/INVALID/IMPORTED populations.
- [x] Verify no repeated full table scans.
- [x] Verify row locks and skip-locked behavior under concurrent workers.
- [x] Verify RLS plans do not cause pathological regressions.

> **Phase 15 closure:** the existing tenant-prefixed row/status and normalized-barcode staging indexes were verified as the correct access paths; no redundant duplicate index was added. Repeated full-job execution scans were removed, validation now performs one reconciliation aggregate per lifecycle, and 50k real-table EXPLAIN ANALYZE benchmarks verify indexed validation/execution/existence paths, SKIP LOCKED concurrency and FORCE-RLS plans. Evidence-based autovacuum/analyze reloptions plus periodic table-health/bloat/autovacuum-lag observability were added and re-tested with the final Phase 10 retention/compaction policy in place. See `domains/simple_products/imports/PHASE15_DATABASE.md` and `scripts/audit_product_import_phase15_scale.py`.

---

# Phase 16 — API and contract cleanup

## Tasks

- [ ] Move import HTTP transport into the module-local API layer.
- [ ] Keep endpoint functions thin: auth/permission, request parsing, application call, response mapping.
- [ ] Move job payload shaping to explicit contracts/DTOs.
- [ ] Move mapping validation authority out of the global Product API file.
- [ ] Keep all user-facing response codes stable or migrate them deliberately.
- [ ] Version contracts if a breaking response/state change is required.
- [ ] Add API tests for create/status/errors/mapping/retry/correction/cancel/template.
- [ ] Add negative tenant-isolation tests for every import endpoint.

---

# Phase 17 — Performance and failure-injection gates

Before declaring Product Import production-grade:

- [ ] 50,000-row CSV import passes bounded-memory gate.
- [ ] 50,000-row XLSX import passes bounded-memory gate.
- [ ] Mixed valid/invalid 50,000-row import completes valid rows and reports invalid rows.
- [ ] 100,000 candidate barcodes do not use one giant parameterized `IN` query.
- [ ] One deterministic bad row in a 100-row execution batch does not block the other 99.
- [ ] Worker crash during parsing resumes safely.
- [ ] Worker crash during validation resumes safely.
- [ ] Worker crash after a successful product commit does not duplicate that Product.
- [ ] Duplicate queue delivery does not duplicate Products.
- [ ] Database/transient failure triggers retry instead of fake row errors.
- [ ] Permission revoked after queueing fails closed before further writes.
- [ ] Cross-company job/row access remains impossible through API, worker and repository paths.
- [ ] Cancellation is safe at each resumable phase.
- [ ] Production build/backend gates/architecture gates all pass.

---

# Phase 18 — Final cleanup

- [ ] Remove obsolete legacy import code paths.
- [ ] Remove compatibility imports created only for migration.
- [ ] Update `ARCHITECTURE.md` with the final module boundary and import execution semantics.
- [ ] Update operational runbook and worker launcher.
- [ ] Update Product import documentation.
- [ ] Confirm no root-level Product Import business files remain.
- [ ] Confirm no Product Import god-file has replaced the old worker under a new name.
- [ ] Confirm all plan items above are `[x]`.
- [ ] Declare Product Import V1 backend production-hardened.

---

# Explicit decisions locked by this plan

1. **Module organization:** Product Import belongs inside the Product/Simple Products domain, not as loose root files and not as a permanent top-level API file.
2. **Execution semantics:** best-effort across rows, atomic for each successful committed unit, idempotent across retries.
3. **Validation semantics:** invalid rows are recorded and do not block unrelated valid rows.
4. **Retry semantics:** retry failed rows inside the same durable job identity; never replay imported rows.
5. **Batch failure semantics:** batch first for speed; deterministic savepoint/bisection for isolation; system failures retry/fail the job.
6. **Memory semantics:** row-count-scale collections are forbidden; parsing, staging and validation are bounded/batched.
7. **Duplicate detection:** database-backed/set-based, not giant Python lists and giant `IN` parameter sets.
8. **Audit semantics:** successful row lineage is retained according to policy; it is not immediately deleted.
9. **Domain authority:** import is an ingestion/orchestration capability, never a second Product/Pricing/Tracking authority.
10. **Architecture rule:** future Product ingestion channels (API, feeds, SFTP, integrations) must reuse the same canonical ingestion/application contracts rather than creating parallel business logic.
