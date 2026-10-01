# Product Import — Production Hardening Plan

**Status:** BACKEND HARDENING PHASES 1–18 CLOSED; V1 RELEASE ACCEPTANCE / CORRECTION UX OPEN
**Scope:** Product/Catalog bulk import backend (CSV/XLSX)  
**Architecture authority:** `ARCHITECTURE.md`  
**Catalog identity dictionary:** `docs/architecture/CATALOG_IDENTITY_GLOSSARY.md` (Product Master, sellable SKU, category, packaging, legacy import behavior)  
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
- [x] Preserve strict tenant/company isolation and PostgreSQL RLS.
- [x] Preserve permission re-checks inside asynchronous execution.
- [x] Preserve Catalog/Product, Pricing, Tracking and UOM domain authority; import code must orchestrate them, never duplicate them.
- [x] Preserve durable queueing and network-request idempotency.
- [x] Preserve fail-closed behavior for ambiguous tenant, permission, mapping and system-state conditions.
- [x] Separate deterministic row/data errors from transient/system/runtime failures.
- [x] No silent conflict handling and no `ON CONFLICT DO NOTHING` for business invariants.
- [x] No unbounded in-memory collection proportional to file row count.
- [x] No tenant/user can exhaust import storage or queue capacity by submitting many individually-valid uploads; admission control must happen before durable payload storage.
- [x] Import progress delivery must not depend on high-frequency polling that scales request volume linearly with active users/jobs.
- [x] No raw technical exception text in user-facing error contracts.
- [x] Every structural move must have architecture/import-boundary tests before old paths are removed.
- [x] Do not alter unrelated Product business behavior while hardening import infrastructure.

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

- [x] Move import HTTP transport into the module-local API layer.
- [x] Keep endpoint functions thin: auth/permission, request parsing, application call, response mapping.
- [x] Move job payload shaping to explicit contracts/DTOs.
- [x] Move mapping validation authority out of the global Product API file.
- [x] Keep all user-facing response codes stable or migrate them deliberately.
- [x] Version contracts if a breaking response/state change is required.
- [x] Add API tests for create/status/errors/mapping/retry/correction/cancel/template.
- [x] Add negative tenant-isolation tests for every import endpoint.

> **Phase 16 closure:** Product Import HTTP transport remains module-local, explicit Pydantic DTOs now own stable response shaping, mapping authority moved to the application facade, and no ORM row/job object is returned directly from HTTP endpoints. Existing URLs/status codes and payload fields were preserved, so no contract version bump was required. Integrated TestClient coverage exercises create/status/errors/mapping/retry/correction/cancel/template, while negative tenant-isolation tests fail closed for every job-scoped HTTP path (including mapping, retry, lineage and correction upload before file read). Verified by `test_product_import_phase16_api.py` and `gate_product_import_phase16_api.py`.

---

# Phase 17 — Performance and failure-injection gates

Before declaring Product Import production-grade:

- [x] 50,000-row CSV import passes bounded-memory gate.
- [x] 50,000-row XLSX import passes bounded-memory gate.
- [x] Mixed valid/invalid 50,000-row import completes valid rows and reports invalid rows.
- [x] 100,000 candidate barcodes do not use one giant parameterized `IN` query.
- [x] One deterministic bad row in a 100-row execution batch does not block the other 99.
- [x] Worker crash during parsing resumes safely.
- [x] Worker crash during validation resumes safely.
- [x] Worker crash after a successful product commit does not duplicate that Product.
- [x] Duplicate queue delivery does not duplicate Products.
- [x] Database/transient failure triggers retry instead of fake row errors.
- [x] Permission revoked after queueing fails closed before further writes.
- [x] Cross-company job/row access remains impossible through API, worker and repository paths.
- [x] Cancellation is safe at each resumable phase.
- [x] Production build/backend gates/architecture gates all pass.


> **Phase 17 closure:** the complete Product Import backend suite passes (125 tests), the final failure-injection gate passes 15/15, and the full backend gate sweep reports `ALL_FINAL_BACKEND_GATES=PASS`. The 50,000-row CSV working set remains effectively flat (~0.68 MiB at 50k), the real 50,000-row XLSX stream remains inside the explicit 16 MiB budget (~8.7 MiB measured), mixed 49,999-valid/1-invalid behavior is preserved, barcode validation remains set-based, and crash/retry/duplicate-delivery/DB-failure/permission-revocation/tenant-isolation/cancellation proofs all pass. Dashboard Product Import realtime tests pass 2/2 and the Vite production build completes successfully.

---

# Phase 18 — Final cleanup

- [x] Remove obsolete legacy import code paths.
- [x] Remove compatibility imports created only for migration.
- [x] Update `ARCHITECTURE.md` with the final module boundary and import execution semantics.
- [x] Update operational runbook and worker launcher.
- [x] Update Product import documentation.
- [x] Confirm no root-level Product Import business files remain.
- [x] Confirm no Product Import god-file has replaced the old worker under a new name.
- [x] Confirm all plan items above are `[x]`.
- [x] Declare Product Import V1 backend production-hardened.


> **Phase 18 closure:** runtime Product Import source execution is SourceStore-only; the legacy inline-payload fallback and migration-only application alias are removed, unexpected barcode-staging conflicts fail loudly, the architecture constitution documents the final boundary/execution semantics, and canonical module documentation/runbook/worker launcher are present. Architecture cleanup gates prove no root-level executable Product Import business path and no renamed god-worker replacement. All hardening-plan checklist items are closed.

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


---

# Phase 19 — V1 Post-Hardening Release Acceptance & Assisted Error Correction (OPEN)

## 2026-09-30 current work order — single V1 checklist, after urgent-plan archive

The former urgent Catalog/Index/Worker roadmap is archived at `docs/archive/WANASAH_URGENT_CATALOG_INDEX_QUEUE_SCALING_PLAN_2026-09-29.md`; it is **not** another mandatory V1 execution queue. Its remaining *actual import work* is accounted for by the original detailed Phase 19 items below. Earlier 50k queue stalls are historical failure evidence, not proof of a current regression or current success. The owner reports an earlier observed 50k execution of approximately 45 minutes and a later approximately 14-minute execution after changes; neither figure by itself proves the **latest** code's real HTTP-to-commit runtime. No shortcut may bypass tenant isolation, money/stock authority or safe cancellation.

**Focused progress register — owner-approved sequence, 2026-09-30.** The older detailed items in sections 19.1/19.2 are retained as historical evidence and possible release acceptance cases; they are NOT 35 independent coding assignments or permission to launch another stress-test campaign.

- [x] **Phases 1–18**: existing Product Import backend implementation, architecture and focused hardening gates recorded above were completed (backend-only; not an end-to-end V1 release claim).
- [x] **19.1 prior real application/DB correction**: original 54-row developer import corrected to **54/54 IMPORTED**, previously imported identities retained; the existing service and repository reject forged/previously imported corrections in their recorded preflight. Real authenticated HTTP/browser acceptance is NOT implied.
- [x] **19.3 official file-correction UI**: PR #46 added same-job official XLSX download/upload, scoped durable request replay and AR/EN controls; **9/9** focused frontend/cancel tests, targeted lint, typecheck and Vite build passed. The existing diagnostic CSV remains separate. See the detailed `[x]` checkpoint in §19.3; inline cell editing is NOT included.
- [x] **D7-S tool preservation, not a V1 gate**: PR #47 kept the Codex Issue #38 staging driver permanently under `wa_backend/tools/staging_load/wanasah_d7s_mixed_load_driver.py` with operator guide `docs/operations/WANASAH_D7S_MIXED_LOAD_TOOL.md`. Its relocated mock contract suite passed 32/32; no true 1,000-connection acceptance occurred. This is deferred V2 work and **not** a blocker for finishing the present correction UI.
- [x] **19.3 Backend contract implemented, NOT live HTTP/DB accepted:** Codex commit `ad646ed`, merged as PR #50. The authorized bounded `GET/POST /simple-products/imports/{job_id}/correction/rows` contract exposes failed-row physical numbers, canonical mapped cell values, immutable row IDs, optimistic job/row versions, editable/retention states, and durable same-job cell patches delegated to the preexisting correction/queue authority. GET limit 1..100 is a **per-request technical bound**, not approval to display/edit any total number of rejected products in Dashboard. Codex reports 11/11 focused in-process tests with DB/queue doubles; real PostgreSQL/RLS, race and full HTTP/worker readback gates remain OPEN. No 5k/50k workload was run.
- [x] **19.3 Frontend inline editor source implemented, real HTTP/browser acceptance OPEN:** the owner delegated the cutoff choice; this V1 UI intentionally offers immediate inline editing only when the **total rejected-row count is 1..25**, and displays only the official correction Excel path for 26+ rejects (including 15,000). Within the bound, request only bounded `/correction/rows` DTO pages pinned to the initial job version (Backend may return short pages under its 256 KiB response cap); stop after 25 total rows or 512 KiB combined, and never re-enable the editor from stale previous-page data after a failed refresh. Show original Excel row numbers, mapped cell values, visible errors, focusable accessible Tooltip, one-row cards and literal changed-cell patch only. Scope tab-local drafts and durable same-ID/body replay to company/user/job; reject attempts to submit the file-correction route while an inline draft/save is pending and reject inline submission while a file-correction request is unresolved. Protect switching to a new import while **either** correction route has pending work, and resume the original progress watcher after server ACK. Separate large, historical diagnostic API paging from this small-only editor. Source + mocked UI original 15/15 focused tests and 2026-10-01 **11/11** targeted correction route/short-page follow-ups PASS, TypeScript, ESLint and Vite production build PASS. PR #54 follow-up (code-only): a stale inline draft now requires confirmation before discard; known zero-write correction-conflict 409 releases its uncommitted request identity and forces refreshed review; stale ACKs after unmount or a company/actor change do not update the new tenant/job UI; draft storage updates occur once per user event outside React state reducers. Correction/editor focused tests **14/14 PASS** plus TypeScript/ESLint/Vite production build PASS. This verifies client contracts only; no deployed browser, PostgreSQL/worker, real manual accessibility or tenant-role acceptance asserted.
- [ ] **19.1 final HTTP acceptance:** after implementing the contracts, one targeted real authorized HTTP/worker/database correction rehearsal with wrong-tenant/previously imported-row negatives, replay/ambiguous response and Product/Variant/Price/Audit lineage readback; preserve the completed original job and create fresh synthetic evidence only if necessary.
- [ ] **19.2 final 50k measured acceptance, deliberately last:** owner postponed every 5k/50k load run until all correction work is implemented. Perform source-first review, then one scoped final actual HTTP + SourceStore + worker + persisted Product/Variant/Price/Audit/Outbox exercise in an owner-approved **synthetic development/rehearsal scope**, with a small admission sanity case if needed; capture total and stage timings, counts, resource/queue health and resume/cancel integrity. An additional physical PostgreSQL database is preferred when available but is NOT inherently required by the original §19.2 policy; never mix real company data or erase historical jobs. Diagnose a newly reproduced stall before retrying; prior September stalls do not by themselves prove a current regression.
- [ ] **19.4–19.5 final closure:** concentrated architecture/build/test and real-browser keyboard/mobile/RTL-LTR/permission checks, then owner visual acceptance when ready. Archive this plan only after implementation evidence is recorded. Real customer installation D7-P/D8-P remains separately OPEN in `docs/operations/PRODUCT_IMPORT_V1_RELEASE_RUNBOOK_2026-09-30.md`.

**Already implemented; do not blindly reimplement:** the current Product Import capacity scheduler uses event-driven due candidates with atomic per-company queue insertion and separate execution/control/maintenance roles; the Dashboard already has a localized confirmed POST import-cancel command and focused source tests. Historical urgent C/F checkboxes predate these changes. Those implementation observations do **not** replace first-company runtime monitoring, durable cancellation/recovery and browser acceptance. Large-tenant fairness and hardware-scale index churn belong to V2 unless they cause a demonstrated V1 correctness/performance failure. Independent catalog/finance/Flutter coverage is tracked by the commercial foundation, not silently marked passed by this plan.


**Why this phase exists:** Phases 1–18 proved the backend hardening contract.
They do **not** by themselves prove that the complete user-facing import,
correction and 50,000-row execution journeys have passed live end-to-end
release acceptance. Do not mark this phase complete on the strength of
structural gates, parser benchmarks, or mocked failure injection alone.

**Test evidence recorded 2026-09-28 (development tenant only):**
- Mixed 54-product XLSX: one durable import finished with **38 IMPORTED +
  16 INVALID** rows (verified against persisted job-row states).
- Re-uploading that **same source as a new job** correctly produced **0
  IMPORTED + 54 INVALID** rows: 38 previously successful identifiers now
  conflict with active product barcodes; the original 16 input errors remain.
  This is **create-only** import, not upsert/synchronization. Re-upload is
  not a correction mechanism.
- New Dashboard success/review separation, localized in-modal messaging and
  company-scoped post-close receipt exist; automated focused UI tests pass.
  Manual browser/reload/filter/permission verification remains open.
- The **error-report CSV is NOT a correction artifact**. The actual
  correction API accepts the server-generated job-specific CSV/XLSX with
  immutable `__wanasah_row_identity` metadata.
- Keep completed imported rows and their barcode/Product/Pricing lineage
  intact. Never delete or reset successful rows just to retry testing.

## 19.1 Historical original-job correction evidence — 54/54 completed; HTTP acceptance open

- [x] Snapshot the original job and its imported identity set: baseline
  **38 IMPORTED + 16 INVALID**, **66 company Products** before a correction.
  The comparison uses the original job identity, not the all-invalid re-upload.
- [ ] Snapshot/compare active barcode rows, Pricing publications and full
  Product row versions as part of final end-to-end lineage verification.
- [x] Build the **original job's** official CSV and XLSX correction artifacts
  through the real application service: both had **16** source-rejected rows,
  16 distinct immutable row identities and the original 10 source headers;
  both parsed successfully. After one correction, future artifacts should
  contain only the remaining 15 invalid rows.
- [ ] Verify the equivalent **authenticated HTTP GET** correction download,
  exact physical row-number mapping and absence of exported successful rows
  in the real Dashboard-access flow.
- [x] Real-job application/repository safety preflight: malformed
  UUID, duplicate UUID, missing identity metadata, unexpected extra header,
  forged unknown row identity, previously IMPORTED row identity, and
  wrong-tenant job: **7/7 rejected**, with unchanged job-row status and
  Product counts.
- [ ] Repeat forbidden corrections through the authenticated HTTP endpoint
  and verify response codes, permission/RLS isolation, and no row mutation.
- [x] Prepare all **15 remaining** corrections in memory using canonical
  package/tracking codes, explicit positive amounts and unambiguous
  synthetic test barcodes. All 15 pass the current normalizer; all 28
  candidate barcodes have zero active tenant conflicts and product names
  have no existing collision.
- [x] Apply the 15-row correction to the **same original job** through
  the real correction service and active worker, after deterministic
  normalization and zero tenant-barcode conflict preflight.
  `corrected_rows=15`, then final `COMPLETED` with
  **54/54 IMPORTED, 0 INVALID**. Persisted correction idempotency
  ledger for the request is completed.
- [x] Confirm the original **39 imported variant identities were retained**
  unchanged as members of the final set of 54 distinct variant IDs.
  Those 15 added variants attach to **6 newly created Product parents**
  and **9 pre-existing Product parents** (family-based grouping).
  Baseline `products` table changed **67 → 73**, which is **correct**:
  there is no 1:1 guarantee between import rows and Product parents.
  The earlier helper script incorrectly expected 15 new Product parents;
  that test assertion was fixed. Use variant and reference integrity
  for future counts rather than an incorrect parent-count invariant.
- [x] Live application-service smoke: correct the missing name on **original
  Excel row 3** through a one-row server-generated correction artifact on
  the same job; the real worker resumed it. Status changed from **38
  IMPORTED / 16 INVALID** to **39 IMPORTED / 15 INVALID**; company Product
  count increased **66 → 67**.
- [x] Exact same correction request ID and same payload replayed with
  `replayed=True` and no extra Product. All 38 prior imported variant
  identities remained present in the original job.
- [ ] Repeat the same scenario via the **real authorized HTTP POST** and
  browser UX, with a lost-response/disconnect case and documented
  event-loop/runtime compatibility on the actual deployment launcher.
- [x] Prove previously imported variant IDs (all 39 by the final
  15-row correction) were retained; the earlier one-row correction's
  exact request-ID replay returned `replayed=True` with no extra
  Product. The final 15-row request has a completed durable
  `operation_idempotency` ledger record.
- [ ] Rebuild and replay the final 15-row **exact payload** against the
  correction endpoint and verify the read-back response matches;
  completed-job short-circuit does not itself demonstrate replay.
- [ ] Snapshot/compare historical Product/Variant row versions and
  price publication IDs at the same-job boundaries to verify that
  correction did not silently mutate pre-existing rows.
- [x] Correct the 15 remaining deliberately invalid test rows after
  preflight. A malformed fixture command (non-canonical Arabic package
  label) was rejected **before mutation**; the canonical code fixed it.
  Final 15 rows each have an independent, active Variant.
- [ ] Independently test a staged row whose next validation error is
  revealed only after an earlier error is corrected.
- [x] Real-database final 54-row readback: **54 distinct ACTIVE variants,
  39 Product parents, 93 active barcodes, 96 published price entries,
  42 commercial UOM conversions**; 42 packaged + 12 unit-only rows.
  Per-row checks against normalized source data passed for base/outer
  barcode, unit/outer price, tracking modes and exact UOM ratios.
  No missing variant, parent, active barcode or published price.
- [ ] Verify authenticated HTTP transport, variant/product versions,
  permission revocation, all foreign-key ownership/RLS negative paths
  and audit event contents before classing V1 release acceptance complete.
- [x] Use the original partially successful job as the correction target;
  the all-invalid re-upload was **not** modified and no previously imported
  Product was deleted. Never upload the unchanged original XLSX again.
- [ ] If the old job source/lineage is no longer correctable for retention
  reasons, use a deliberately isolated fresh test job and document why;
  never overwrite or delete historical successful Products.

## 19.2 50,000-row real end-to-end release exercise

### Live findings and release blocker — 2026-09-28

- [x] The original 54-row developer job `a586d11e-64fa-4392-9284-c5e62fe81b25`
  completed with **54 IMPORTED, 0 INVALID** and 54 distinct variant
  identities. Those variants belong to **39 reused Product family parents**,
  which is correct under the current family model. The same-job correction
  script's repeat dry-run returns `ALREADY_COMPLETED=PASS` without replay.
- [x] Live 100-row background import
  `e5ae4dac-3f7c-4cd8-9ca3-0e1ae8d02101`:
  **99 IMPORTED + 1 INVALID**.
- [x] Diagnose the *previous* 50,000-row background import
  `0f57c157-aa68-47cc-b97a-447d8b7f8fb0`:
  **FAILED**, 0 products executed; 46,348 VALID + 452 INVALID persisted
  out of the claimed 50,000. **3,200 nonblank source rows absent** in
  regular approximately 64-row gaps. Queue had three attempts; its
  `succeeded` task status merely indicates wrapper-caught terminal failure.
- [x] Reproduce on a fresh 1,000-row *real queue* import
  `c15e4040-6287-4265-910f-5a3628e7639b`: **FAILED**, only
  928 VALID + 9 INVALID persist; source rows 758–820 (63 rows) are absent.
  This is a blocking real-path row-fidelity defect, **not** a 50k runtime SLA.
- [x] Verify generated source SHA-256 and parser row counts match both
  failed jobs; RLS and index-vs-sequential counts do not account for
  missing rows. Independent ProactorEventLoop stage/validate exercises
  and exact 50k staging transaction have no row loss.
- [x] **Isolate reproducible Windows event-loop/batch interaction:**
  running the *same exact source* through the same committed
  `stage_source` with `asyncio.SelectorEventLoop` and a 1,000-row
  ORM insert batch persisted only **937/1,000**. With selector batch
  sizes **500, 250 or 100**, all 1,000 rows were preserved; a
  50,000-row SelectorEventLoop + 500-row insert transaction staged
  **50,000/50,000** (~10.4 seconds, excluding full Product execution).
  Do not label the underlying DB-driver defect independently proven;
  the source-safe mitigation is verified in this development runtime.
- [x] Change `staging_service.STAGE_BATCH` from 1,000 to **500** and
  add a **same-transaction actual STAGED-row count assertion** before
  committing validation status or clearing immutable SourceStore bytes.
  Short writes now roll back instead of advancing a corrupted job.
  Unit regression: `test_product_import_phase19_staging_integrity.py`
  tests a 937/1000 mismatch is rejected before commit.
- [x] Re-run focused backend Product Import suite: **144 tests PASS**;
  working branch HEAD after mitigation was `102bfa7`.
- [x] Restart the current Product Import Worker from the **new code**.
  Its prior PID (started 14:50) was older than the staging patch (15:26),
  explaining why the first new 1k queue attempt still reproduced the
  historical 937/1000 short-write. Stale worker processes were stopped
  only when no Product Import task was doing/todo, and the official visible
  PowerShell launcher started one fresh queue worker at 15:43.
- [x] Fresh **1,000-row real queue** test after worker restart:
  job `e0841a8f-7ee5-4d00-b8cd-32a2b787ec90` finished
  `COMPLETED_WITH_ERRORS` in **16.36 s**: **990 IMPORTED +
  10 deliberately INVALID**, 990 distinct imported Variant IDs,
  correct final physical Excel row 1001 and valid Product/Variant links.
  Source staging and full import both passed on this size.
- [x] Attempt a uniquely named **50,000-row real queue** job after
  the 1k pass. Job `694ca902-eecd-4b18-b3cb-a3975df97caa`
  was admitted and picked up by the fresh worker, but stalled in
  `PARSING`/staging with `total_rows=0` and no committed source
  rows. A PostgreSQL `INSERT INTO product_import_rows` connection
  remained `active` / `ClientRead` with an unchanged query for over
  285 seconds and worker CPU usage nearly static. The live harness
  observed `PARSING` continuously for ~477 seconds. This run was
  **NOT A PASS**; do not infer that 50k is production-ready.
- [x] Safely cancel the stalled **50k job only**, through the official
  cancellation service; after a targeted `pg_cancel_backend` failed
  to release the stuck ClientRead, targeted
  `pg_terminate_backend` released its transaction lock. Final
  job state `CANCELLED`, **0 staged rows, 0 products imported**,
  source bytes cleaned, queue wrapper task succeeded on its
  second attempt. There is no partial Product to delete.
- [x] **Staging diagnostic instrumentation, not root-cause closure:** PR #56
  emits source-safe, bounded per-batch START markers before SQLAlchemy
  multi-VALUES encoding/asyncpg transmission, with the existing wall-time
  `STAGING_SQL` phase completion/interruption record after each awaited
  statement. Markers include only company/job correlation IDs, bounded
  batch index/size and first/last physical source row numbers: no Product
  cells, barcodes, SQL query parameters or exception text. Operators can
  identify the last batch BEGIN lacking a matching completed phase if
  ClientRead recurs. The staging transaction, SourceStore retention, row
  integrity assertion, retry and cancel semantics were not modified.
  Focused staging integrity and secret-redaction checks **5/5 PASS**,
  syntax check PASS. **Actual queue/PG diagnosis and 5k/10k/50k execution
  are still OPEN and must not be inferred from these mocked tests.**
- [ ] **Blocking root-cause investigation before repeating 50k:**
  instrument the actual queue worker and source staging
  with bounded per-batch timing/progress and DB query/wait diagnostics;
  reproduce at intermediate sizes (e.g. 5k/10k) on the same launcher.
  Determine why real queue staging can hang while a separate
  50k SelectorEventLoop+500-row transaction was measured at ~10.4 s.
  Investigate asyncpg/SQLAlchemy parameter transmission, Windows
  event-loop behavior, connection cancellation, DB backpressure and
  driver/transaction configuration. Do **not** guess that using a 500-row
  batch alone fixes this second observed failure.
- [x] **Bounded staging wait/recovery implementation only — live acceptance OPEN:**
  Codex source changes add a per-staging-DB-step **120 s** watchdog,
  **10 s** cleanup/drain budget and owned-asyncpg-transport termination
  for unresponsive cancellation, scoped to the existing SQLAlchemy pool
  without terminating transports already checked in/reborrowed by another
  company. Preserve the original single transaction, actual staged-row
  reconciliation, retryable JOB error, SourceStore bytes and ambiguous
  COMMIT-replay authority. Peer review fixed a proven secondary edge where
  terminate() throwing on an already-failing connection could skip
  cancellation/drain and leak private diagnostics; reviewed **12/12**
  focused staging source/double tests and AST syntax PASS on the independent
  Windows worktree. See
  `wa_backend/domains/simple_products/imports/PHASE19_STAGING_RECOVERY.md`.
  No live PostgreSQL rollback/lock release, worker or HTTP acceptance is
  implied by this code-only checkpoint.
- [ ] **Actual staging cancellation/rollback/retry acceptance:**
  verify worker error recovery and official HTTP cancel on an **approved
  isolated synthetic rehearsal tenant**, including source retention,
  retry/restart, lost COMMIT acknowledgement and no stuck transaction or
  cross-tenant connection termination. Connection pre-ping and physical
  PostgreSQL lock release cannot be proved from mocked cancellation.
  The historical asyncpg/Windows ClientRead root-cause investigation
  and intermediate-size real queue measurements remain separately OPEN.
- [ ] Rerun 50k real-queue import with unique identities **only
  after** the staging-hang root cause and fresh intermediate-size gates
  pass. Measure actual E2E latency/resources/lineage; do not
  overwrite or retry failed historical fixtures as new imports.
- [ ] Verify real HTTP authorization/correction, tenant concurrency,
  cancellation/recovery and refresh/RTL/LTR for the production release.

- [x] Generate a realistic **new, uniquely run-labeled synthetic development**
  Product Import fixture with explicit package selection and a controlled mix
  of candidate-valid and intentionally invalid rows, empty physical CSV rows,
  Arabic/English/mixed authoritative headers and values, leading-zero
  EAN-13-format barcodes preserved as text, packaging and tracking variations.
  The verified offline generator is
  `wa_backend/tools/product_import/phase19_fixture.py` and operator notes are
  `docs/operations/PRODUCT_IMPORT_PHASE19_FIXTURE_RUNBOOK.md`. It produced
  **50,000 source rows / 1,612 intentionally empty physical lines / final
  physical row 51,613 / 2,000 injected-invalid candidates / 48,000 other
  candidates / 61,428 unique within-run text barcodes**, with byte-exact
  SHA-256 and a 4,688,383-byte CSV (below the 9 MiB source headroom cap).
  **Five focused offline parser/locale/source tests PASS**; the fixture is in
  the local development TEMP folder, not in Git, and no HTTP/DB/Worker
  request was sent. Runtime company_id, actual validation outcomes, unique
  barcode collision checks against the *existing tenant database* and true
  persisted Product/Variant/Price/Audit acceptance remain separately OPEN
  under the subsequent 19.2 execution items.
- [ ] Run within the explicitly authorized **development-only**
  PostgreSQL instance; a separate physical database is **not required**.
  Distinguish the 50k test job by a unique run identifier, names, barcodes,
  tenant scope (where feasible) and captured baseline. Never mix that
  fixture with the original 54-row correction evidence or another run.
  Require a current one-per-queue worker; record measured DB and system
  resource pressure. Treat per-run isolation as **data attribution and
  repeatability**, not a second mandatory DB installation.
- [ ] Measure actual upload admission, source-store write, queue wait,
  parser/staging, validation, barcode detection, row creation, pricing
  publication and completion separately, with timings, throughput, CPU,
  memory, database round trips, table/index health and queue metrics.
  Do not infer whole-job runtime from the Phase 17 **streaming-only** memory
  gate or Phase 15 query-plan audit.
- [ ] Assert every physical source-row number, **IMPORTED + INVALID +
  IMPORT_FAILED** reconciliation, no duplicate successful products, and
  expected product/price/barcode persistence. Test 0/100/1k/50k rows,
  near-100% invalid, and mixed 50k cases without inventing performance SLAs.
- [ ] Exercise crash/restart, lost HTTP response, duplicate queue delivery,
  permission revocation, cancellation, retention, concurrent tenants and
  worker-backpressure with the real pipeline where safe.
- [ ] Use measured baseline and representative target hardware/tenant
  load to define an evidence-based p50/p95 completion-time and resource
  acceptance envelope. Fail and investigate any regression; do not claim
  "50,000 rows fast" without real end-to-end measurement.
- [ ] Run full backend+frontend gates, audit tenant isolation and validate
  the Dashboard's large-job progress, row report, retry, and reconnection
  behavior with keyboard and both RTL/LTR locales.

- [x] **File-correction expired-source UI handling (PR #58, code-only):**
  after the now-authoritative file correction HTTP `410 /
  PRODUCT_IMPORT_CORRECTION_DETAILS_EXPIRED` is verified, clear that
  permanently ineligible selected XLSX and its scoped pending id so the
  company/job is not trapped in an unresolvable correction. **Do not** drop
  an ambiguous HTTP 503, connection-loss, or invalid ACK request identity:
  preserve its original same-file idempotent replay. Added Arabic/English
  fallback messages for invalid correction acknowledgements, missing file
  and oversized inline pages. Focused frontend correction/editor tests
  **16/16 PASS**; TypeScript, ESLint, Vite build PASS. In-process backend
  correction/staging suite **21/21 PASS** using an unreachable synthetic
  database DSN (no PostgreSQL/Worker writes). Authenticated real HTTP,
  RLS, and release acceptance remain OPEN.

## 19.3 V1 correction UX — file and small-inline code DONE; live acceptance OPEN

**Decision (owner sequencing updated 2026-09-30):** Implement the V1
correction UX and Backend DTO before the final one-time 50k import benchmark.
Authenticated HTTP acceptance is still required for actual release. The
user's earlier illustrative "20 errors" was **not** a business rule. On
2026-10-01 owner delegated a professional cutoff decision: Dashboard now
restricts live cell editing to **25 or fewer TOTAL rejected rows**; 26 or
more use the official same-job XLSX correction artifact. Backend 100-row
transport limits are independent from this intentional UX cap.

- [x] **File correction flow / frontend checkpoint (not inline editing):**
  On a terminal job with rejected rows, Products now offers official
  `GET /simple-products/imports/{job_id}/correction?format=xlsx` download
  and `POST /simple-products/imports/{job_id}/correction` of the edited
  **same-job** artifact with the exact multipart `request_id` / `file`
  contract. The browser retains one durable, tenant/user/job-scoped request
  identity bound to the selected file hash; ambiguous response keeps that
  identity for safe replay. An authoritative `VALIDATING` ACK resumes the
  existing progress watcher, and the old diagnostic error CSV stays
  explicitly separate from the correction XLSX. Arabic/English labels and
  accessible file controls are present; previously successful rows are
  never included as client-side editable correction targets. Evidence:
  `dashboard/src/pages/products/import/useImportCorrection.ts`,
  `ImportCorrectionPanel.tsx`, `createImportDownloads.ts` and
  `productImportFileDownload.ts`. Focused frontend correction/cancel
  regression **9/9 PASS**, targeted ESLint zero warnings and TypeScript
  PASS, plus direct Vite production build PASS on 2026-09-30.
  An earlier npm-wrapper build command exited nonzero without a diagnostic
  before the identical Vite build completed successfully. No real HTTP/DB,
  manual browser, inline cell editing, multi-company auth or 50k end-to-end
  acceptance is asserted by this checkbox.

- [x] **Read-only rejected-error review checkpoint (not inline cell editing):**
  Dashboard now shows a user-opened, job-scoped **Review rejected rows**
  section in both `VALIDATION_FAILED` and `COMPLETED_WITH_ERRORS`;
  fetches a bounded 25-row page from the existing authorized
  `GET /simple-products/imports/{job_id}/errors?after_row=...&limit=25`,
  displays the original physical Excel row numbers and safe localized
  reasons, allows previous/next cursor navigation and explicit retry,
  rejects non-advancing/unordered cursors, aborts abandoned requests
  and never loads the entire rejection set for the panel. The former
  fixed first-50-only list was replaced in the failed state; the partially
  successful state now has the same review. The diagnostic endpoint
  contains **no editable cell values**: this review is deliberately
  read-only until the separate Codex Backend inline correction DTO is
  integrated. This PR #49 checkpoint is **historical**: the active terminal
  screen now mounts the small-only inline editor rather than that unlimited
  optional diagnostic preview. Evidence: `ImportRejectedRowsReview.tsx`, status/modal/
  workflow wiring; **12/12** focused import/correction/cancel frontend
  tests, TypeScript, targeted ESLint and direct Vite production build
  PASS on 2026-09-30. No actual-browser or new authenticated HTTP/DB
  acceptance is claimed.
- [x] Implement a bounded job-specific **Review rejected rows** value view, with
  original Excel physical row numbers, canonical field identity,
  user-safe localized error text, and current row values; never expose
  successful Products as editable correction targets.
- [x] For 1..25 rejected rows, render accessible compact expandable
  editable row cards. Visually identify erroneous cells but also give every
  invalid field a **keyboard-focusable** error indicator, explicit message
  and non-hover-only help. Do not rely on red color alone.
- [x] For >25 rejected rows, hide the direct editor and show only the
  same job-specific official correction XLSX/CSV path; prior diagnostic
  retrieval is separately bounded/paginated. Never fetch 50k failed rows
  or entire files into React.
- [x] Implement correction as a patch to existing **failed row identities**,
  not as a fresh Product import; authorize tenant/job/field access and
  server-validate edited data again through existing Product/Pricing/
  Tracking/UOM authority before committing.
- [x] **Source implementation complete; live acceptance remains OPEN:**
  keep `IMPORTED` rows immutable; permit only `INVALID`/`IMPORT_FAILED`
  targets under job+row locks, tenant/job scoping and immutable row
  identities. Inline corrections use explicit `expected_job_version` and
  `expected_version`; official XLSX correction uses a serialized job lock,
  immutable request hash and failed-row eligibility instead of inventing a
  file-carried optimistic version. Both share the existing transactional
  mutation/queue/idempotency authority; unknown/cross-job/company row
  identities and previously successful rows fail closed. The UI persists
  only changed-cell drafts per company/actor/job, preserves same-ID retries
  on ambiguous outcomes and blocks overlapping correction routes.
  Existing `test_product_import_inline_correction.py` and no-DB Phase 8
  correction/idempotency classes **21/21 PASS** (on unreachable synthetic
  DSN), while frontend correction/rejected review **20/20 PASS** on this
  source revision, including a newly fixed case where corrupted tab-local
  JSON used to trap the user behind a hidden reset guard: it now exposes
  confirmed, non-silent draft discard even if the correction GET fails.
  Do **not** infer live PostgreSQL FORCE RLS, race, actual Worker execution,
  cross-tenant HTTP or Product/Variant/Price/Audit readback: independent
  19.1 and 19.3 browser acceptance checkboxes remain OPEN.
- [x] Represent **multiple possible issues** per row in UI contracts; a row may expose its
  next error only after the first is fixed. Show row-level and field-level
  feedback without promising that the first report is exhaustive.
- [x] Design and implement a server API for row data/pages and patch requests,
  design/review its DTO, masking, permissions, rate limits, storage/retention
  and audit contract first. Do not leak raw staged data in public error DTOs.
- [x] Do not duplicate validation or package/pricing authority in React.
  Use canonical error codes + field mapping + localization; locale and
  mixed-language inputs remain independent from canonical business rules.
- [x] Route correction ACK through the existing job watcher which refreshes Products queries without forced
  full-page reload; show saved, rejected and pending separately; support
  status resume after the modal closes or the browser refreshes.
- [ ] Test mobile, keyboard, screen reader, i18n, concurrent correction,
  stale drafts, tenant changes, unexpected worker failure, large error
  pagination and no Products/Prices/Barcodes duplication.

## 19.4 V1 product education and source semantics

- [x] Explain **base unit** as one business stock unit (piece, bottle,
  sealed pack, etc.), not necessarily a loose "piece"/"حبة".
- [x] Explain **outer packaging** as one fixed grouping of the same SKU,
  separate from physical shipping containers and multi-SKU kits, using
  concise Arabic/English tooltip and 1–3 real business examples.
- [x] Make outer-package selection explicit in the official template;
  require the base-unit count for an actual grouping and reject silent
  guessed carton conversions.
- [x] Surface an explicit saved-product count separately from rejected
  rows after import and retain a tenant-scoped, dismissible UI receipt.
- [ ] Manually verify the guide/tooltip, dynamic-locale template,
  "No outer package" semantics, role-restricted prices, result receipt,
  search/filter behavior and list freshness on real browsers/devices.
- [x] Record and classify actual owner-reported V1 UX confusion and
  code/acceptance boundaries in
  `docs/operations/PRODUCT_IMPORT_V1_UX_ACCEPTANCE_FINDINGS.md`:
  15k rejected rows vs 25-row total-edit cutoff, non-hover-only error
  reasons, correcting on the original job vs re-upload, 202 ACK vs
  finished Product/Price writes, physical source row vs Product parent/
  Variant counts, text vs Excel numeric/formula barcodes, and
  ambiguous-response/draft recovery. Each finding explicitly marks its
  **unverified live/browser acceptance** and keeps V1 correctness in V1.
  This closes the **recording/classification task only**, not manual user
  signoff, role-restricted browser or the release rule.

## 19.5 V1 release rule and references

- [ ] Close Phase 19 only with live correction results and a measured
  real 50k end-to-end run, complete accessibility/i18n and tenant/security
  verification, plus clean architecture/build/test gates.
- [ ] Do not call the **entire V1 product experience** release-ready until
  the above items close; "Product Import V1 backend is production-hardened"
  remains the **backend-only** Phase 18 claim.
- [x] **Repeatable V1 source-only gate + safe draft exit, 2026-10-01:**
  `wa_backend/scripts/run_product_import_v1_source_gate.ps1` combines the
  previously scattered, **explicitly non-DB** correction/metadata, source-row,
  synthetic mixed-language, staging contract, retry/idempotency and frontend
  cancellation/receipt/localization checks with TypeScript, selected ESLint
  and Vite production build. **45/45 Backend + 48/48 Dashboard focused tests,
  typecheck, lint, production build ALL PASS** on the Windows development
  machine; source gate printed `P19_REAL_HTTP_POSTGRES_WORKER_BROWSER_50K=OPEN`.
  In particular a stored valid draft is now recoverable with confirmation
  if correction GET fails or network is offline, without silently deleting
  the user's edited cells; two focused UI tests cover that edge case.
  Source runbook: `wa_backend/domains/simple_products/imports/RUNBOOK.md`.
  This completes **only** source-code regression automation and safe
  draft recovery; it does **not** replace the pending real HTTP/PostgreSQL,
  real queue/50k, manual accessibility, real tenant or customer-deployment
  acceptance.
- [ ] Add repeatable focused gates for the accepted correction workflow,
  real-load suite and representative small/mixed edge-case regressions.

Relevant external design references (patterns to evaluate, **not** feature
promises): Odoo product packaging and physical packages; SAP packaging
hierarchy; NetSuite purchase/stock/sale UOM defaults; ERPNext import
error/repair workflow; Microsoft Dynamics translations, per-variant UOM
and distinct catch-weight flow. Product/warehouse domains own actual
capability support, not a template or tooltip.

**Reference links:**
- https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/product_management/configure/packaging.html
- https://www.odoo.com/documentation/19.0/applications/inventory_and_mrp/inventory/product_management/configure/package.html
- https://help.sap.com/docs/SAP_S4HANA_ON-PREMISE/9905622a5c1f49ba84e9076fc83a9c2c/6289c4535cdeb44ce10000000a174cb4.html
- https://docs.oracle.com/en/cloud/saas/netsuite/ns-online-help/section_N2212390.html
- https://learn.microsoft.com/en-us/dynamics365/supply-chain/pim/tasks/manage-unit-measure
- https://learn.microsoft.com/en-us/dynamics365/supply-chain/pim/uom-conversion-per-product-variant
- https://learn.microsoft.com/en-us/dynamics365/supply-chain/warehousing/catch-weight-processing
- https://docs.frappe.io/erpnext/data-import
