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

- [ ] Create the module package and explicit public entry point.
- [ ] Define allowed dependency directions for the import module.
- [ ] Move localization into the import domain layer.
- [ ] Move template generation into import infrastructure.
- [ ] Move queue implementation into import infrastructure.
- [ ] Split worker responsibilities into application orchestration + infrastructure/parser/repository components.
- [ ] Move Product-import HTTP endpoints out of the large `api/simple_products.py` file into the module-local API layer.
- [ ] Keep the application router registration thin and explicit.
- [ ] Introduce an import repository so application code no longer reaches global ORM models everywhere.
- [ ] Keep global model relocation as a controlled schema/model-ownership step; do not create circular imports just to move class declarations.
- [ ] Add an architecture gate that forbids new root-level `product_import_*.py` business files.
- [ ] Add an architecture gate that prevents import infrastructure from becoming Product/Pricing/Tracking business authority.
- [ ] Update worker launcher/runbook imports after the move.
- [ ] Update all tests/gates to use the module public path.
- [ ] Remove obsolete root-level import files only after all imports and gates pass.

### Phase 1 exit criteria

- [ ] No Product Import business/orchestration file remains loose in `wa_backend/` root.
- [ ] No Product Import endpoint remains buried in the oversized general Product API file.
- [ ] The import module has explicit domain/application/infrastructure/api boundaries.
- [ ] Existing runtime behavior is unchanged at this phase.

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

- [ ] Define one explicit import job state machine.
- [ ] Extract parser interfaces and format-specific parsers.
- [ ] Extract row normalization from job orchestration.
- [ ] Extract staging persistence into repository methods.
- [ ] Extract validation orchestration into its own application service.
- [ ] Extract import execution into its own application service.
- [ ] Extract failure classification and error recording.
- [ ] Extract job-state transition helpers and make illegal transitions fail closed.
- [ ] Keep queue task code thin: load context, call application use case, classify retryability.
- [ ] Add focused unit tests per responsibility.
- [ ] Add a size/complexity architecture guard so a new worker god-file cannot return.

---

# Phase 3 — Centralize and lock the import state machine / contracts

> **FOUNDATION PHASE:** centralize the state definitions and allowed transitions first. Do not enable best-effort/partial-import behavior yet. Track B begins only after the current state behavior is represented faithfully by one explicit state-machine authority.

## Problems

The current job mixes validation-terminal states, runtime-terminal states and resumable states. Status strings are spread across API, queue, worker, ORM constraints and migrations.

Validation currently behaves all-or-nothing, while import execution commits in batches. Those semantics are inconsistent.

## Foundation target

Phase 3 first captures the **current** job/row lifecycle in one authoritative state-machine contract so status strings and transitions are no longer scattered across API, queue, worker, ORM constraints and migrations.

The desired future Track B semantics are already decided, but they are **not activated during the foundation refactor**:

- **best-effort across rows** — one bad Product must not block unrelated valid Products;
- **atomic within each successfully committed import unit** — a Product must never be half-created without its required Product/UOM/barcode/price effects;
- **idempotent on retries** — a committed successful row is never created twice;
- **fail-closed for infrastructure/system errors** — database outages, bugs and invariant failures are not mislabeled as bad Product rows.

That future design achieves atomicity and best-effort at different, compatible levels. The whole 50,000-row job is not one giant transaction.

## Tasks

- [ ] Inventory every current job status, row status and transition before changing any of them.
- [ ] Centralize current state constants/contracts rather than scattering raw strings.
- [ ] Define canonical current job states and allowed transitions.
- [ ] Define canonical current row states and allowed transitions.
- [ ] Add state-transition tests for every current allowed and forbidden transition.
- [ ] Ensure ORM/database constraints and public API status contracts derive from or remain synchronized with the central contract.
- [ ] Preserve current runtime semantics through the end of Track A.
- [ ] Document the Track B state additions needed for partial success (including a future `COMPLETED_WITH_ERRORS` or equivalent) without enabling them yet.
- [ ] Document future deterministic validation/import-time row failure states and transient/system failure categories without enabling them yet.

### Foundation stop gate

- [ ] Phase 1 module ownership/placement is complete.
- [ ] Phase 2 worker decomposition is complete.
- [ ] Phase 3 state-machine authority is centralized and tested.
- [ ] Full existing Product Import regression suite passes with no intended behavior change.
- [ ] Architecture/import-boundary gates pass.
- [ ] No legacy code was deleted unless separately proven obsolete.
- [ ] Track A can be merged/stopped independently before any Track B import-engine redesign.

---

# Phase 4 — True bounded parsing and staging

## Problems

### CSV

The complete uploaded payload is decoded into one large string, then every parsed Product row is appended to a Python list before staging.

### XLSX

OpenPyXL is correctly opened in read-only mode, but every parsed row is still accumulated into a Python list before staging.

### Staging

`_stage_source` inserts in chunks, but only after the whole source has already been materialized in RAM.

## Target

Parsing and staging must be a bounded pipeline:

source → parse batch → stage batch → release batch → continue

Memory must be approximately proportional to batch size, not total Product count.

## Tasks

- [ ] Introduce a parser contract that yields rows with their original source row numbers.
- [ ] Stream CSV rows without building a complete `rows` list.
- [ ] Stream XLSX rows from read-only workbook iteration without building a complete `rows` list.
- [ ] Stage fixed-size batches directly as they are parsed.
- [ ] Preserve exact original row numbers, including when blank rows exist in the source.
- [ ] Track total staged rows incrementally.
- [ ] Enforce the 50,000-row limit incrementally without materializing the file.
- [ ] Keep XLSX zip-bomb/archive safety checks before workbook traversal.
- [ ] Guarantee workbook/file handles close on success and failure.
- [ ] Add memory-bounded tests/benchmarks at 1k, 10k and 50k rows.
- [ ] Prove that peak row-object accumulation is bounded by configured batch size.

---

# Phase 5 — Bounded validation instead of loading 50,000 ORM rows

## Problems

Validation currently loads every staged row into memory, then builds additional in-memory dictionaries for normalized rows, errors and barcode ownership.

This multiplies memory usage after parsing has already completed.

## Target

Validation must iterate staged rows with keyset/batch pagination and persist outcomes incrementally.

## Tasks

- [ ] Replace the full `.all()` staged-row load with ordered keyset/batch reads.
- [ ] Normalize each validation batch and persist normalized results/errors in bounded writes.
- [ ] Avoid keeping normalized data for the whole file in Python.
- [ ] Avoid keeping error dictionaries for the whole file in Python.
- [ ] Maintain aggregate valid/failed counters incrementally and safely.
- [ ] Make validation resumable from a durable cursor/checkpoint if interrupted.
- [ ] Ensure retry never reclassifies already finalized rows incorrectly.
- [ ] Add crash/restart tests during validation.

---

# Phase 6 — Move cross-row duplicate checks to scalable database-backed logic

## Problem

Import-wide barcode detection can build tens of thousands of barcode values in Python and later issue a very large `IN (...)` query against active barcodes.

At 50,000 Products with unit/package barcodes, candidate count can approach 100,000 values.

## Target

Use staging/database operations for set-based validation rather than giant Python collections and giant parameter lists.

## Tasks

- [ ] Persist normalized candidate barcodes in a queryable staging form.
- [ ] Detect duplicate barcodes inside the import through SQL grouping/join logic.
- [ ] Detect conflicts with existing active company barcodes through tenant-scoped SQL joins.
- [ ] Preserve the valid same-row shared unit/package barcode rule.
- [ ] Add appropriate staging indexes for job + barcode lookup.
- [ ] Avoid giant parameter lists.
- [ ] Prove query plans do not degrade into repeated full scans at 50k-row scale.
- [ ] Add concurrent-conflict tests so a barcode becoming active after validation is still caught safely at commit time.

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

## Tasks

- [ ] Remove the current “any validation error blocks all valid rows” policy.
- [ ] Continue from validation into import when at least one valid row exists.
- [ ] Preserve every invalid row and its error without creating Product data for it.
- [ ] Define outcome when zero rows are valid.
- [ ] Define progress counters as total / imported / invalid / import-failed / pending.
- [ ] Update public job payload to expose these outcomes clearly.
- [ ] Add tests for 49,999 valid + 1 invalid.
- [ ] Add tests for mixed tracking/package/price/barcode errors.
- [ ] Add tests proving invalid rows never block unrelated valid rows.

---

# Phase 8 — Row-safe idempotency and retry of failed rows

## Problem

Best-effort import is unsafe unless successful rows can never be duplicated during retries or correction flows.

Re-uploading the entire corrected file as a brand-new job can duplicate previously imported Products that have no naturally unique external identifier.

## Target

Retries of failed rows stay attached to the same durable import job and stable row identities.

Successful rows are immutable outcomes and are never replayed.

## Tasks

- [ ] Give every staged source row a stable immutable identity/token inside the job.
- [ ] Derive deterministic idempotency identity from job + row/sub-batch identity.
- [ ] Commit Product changes and the corresponding row outcome atomically.
- [ ] On worker retry, select only rows that are still eligible for execution.
- [ ] Never replay `IMPORTED` rows.
- [ ] Add a correction/retry contract for failed rows within the same job.
- [ ] Generate a correction artifact containing only failed rows plus stable hidden/explicit row identity.
- [ ] Validate that a correction can update only its matching failed rows.
- [ ] Reject correction files that attempt to mutate already imported row identities.
- [ ] Support retrying corrected failed rows without touching previous successes.
- [ ] Add crash tests for “Product committed / worker died immediately afterward”.
- [ ] Add duplicate client retry tests.
- [ ] Add duplicate queue delivery tests.

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

- [ ] Define deterministic row-attributable exception classes/codes.
- [ ] Define transient/system exception classes/codes.
- [ ] Add savepoint support around import execution attempts.
- [ ] Implement deterministic batch bisection.
- [ ] Stop recursion at one row and record its import-time error.
- [ ] Preserve domain authority by continuing to call the real Product creation service.
- [ ] Ensure Pricing publication behavior remains valid across successful sub-batches.
- [ ] Keep Product/UOM/barcode/pricing effects atomic inside each successful unit.
- [ ] Add tests where 1 of 100 rows violates a database constraint and the other 99 import.
- [ ] Add tests proving a database outage does not get converted into 100 fake row errors.

---

# Phase 10 — Preserve audit lineage instead of deleting successful staging rows immediately

## Problem

Current completion deletes `IMPORTED` ProductImportRow records immediately.

That removes the useful lineage:

source file → source row → normalized row → created Product

This weakens audit, support, correction and forensic capability.

## Tasks

- [ ] Stop immediate deletion of imported row lineage.
- [ ] Define a retention policy for raw source data, normalized row data and row outcome metadata.
- [ ] Keep durable linkage from source row to `product_variant_id`.
- [ ] Keep immutable source hash, row number/token and outcome.
- [ ] Define compaction after retention so long-term audit does not require keeping full raw JSON forever.
- [ ] Separate retention of uploaded file bytes from retention of row lineage.
- [ ] Add authorized audit/query path without exposing cross-tenant data.
- [ ] Add cleanup/retention worker with bounded batches and observability.
- [ ] Test cleanup under RLS and tenant boundaries.

---

# Phase 11 — Correct source-row fidelity and Excel semantics

## Problems

- Blank source rows can currently shift staged row numbering because numbering is reconstructed after filtering.
- Workbook `active` sheet is accepted silently.
- Formula/cached-cell behavior is not an explicit import contract.
- External Excel files can coerce barcode-like values to numbers and destroy leading zeros before Wanasah receives them.

## Tasks

- [ ] Preserve exact physical row number from CSV/XLSX parser.
- [ ] Define multi-sheet behavior explicitly.
- [ ] For Wanasah template files, select the canonical Products sheet by contract.
- [ ] For arbitrary XLSX files, require deterministic sheet selection when multiple candidate sheets exist; never silently choose an ambiguous sheet.
- [ ] Define formula policy: reject formulas where values must be literal, or explicitly accept only safe cached values with clear behavior.
- [ ] Format barcode columns as text in the official template.
- [ ] Detect suspicious numeric/scientific-notation barcode inputs and return a clear row error rather than silently changing identity.
- [ ] Add tests for blank rows, multiple sheets, formulas, leading-zero barcodes and scientific notation.

---

# Phase 12 — Upload/source-payload memory and storage boundary

## Current bounded condition

The HTTP endpoint currently reads at most 8MB + 1 byte into memory and stores the source payload durably in PostgreSQL until parsing completes.

This is bounded today, so it is not the same severity as the 50k-row materialization problem. However, the storage boundary must be explicit before file limits or ingestion channels expand.

## Tasks

- [ ] Keep the current upload size bound enforced server-side.
- [ ] Compute size/hash in a bounded manner rather than assuming future payloads can always be materialized.
- [ ] Introduce a SourceStore abstraction so queue/application logic references an immutable source rather than depending on one storage implementation.
- [ ] Decide and document the production SourceStore implementation based on deployment needs.
- [ ] If/when limits grow beyond the bounded DB-payload design, move source blobs to durable object storage without changing application contracts.
- [ ] Guarantee source cleanup after staging according to retention policy.
- [ ] Add hash verification before parsing/retry.

---

# Phase 13 — Queue concurrency, backpressure and worker availability

## Problems / decisions to make explicit

The queue currently serializes Product imports per company through a company-scoped lock. This is safe, but it is also a scalability policy.

The UI previously exposed the operational symptom of a worker not running as an endless queued spinner.

## Tasks

- [ ] Keep company-level serialization only if required by shared Product/Pricing invariants; document the reason.
- [ ] Otherwise reduce lock scope safely after concurrency tests.
- [ ] Add per-tenant active-import/backpressure limits.
- [ ] Add global worker capacity metrics.
- [ ] Add queue-age and oldest-job monitoring.
- [ ] Add worker-health/readiness signal.
- [ ] Add alerts for jobs stuck beyond expected stage duration.
- [ ] Define cancellation semantics for jobs that have not committed all rows.
- [ ] Ensure cancellation never leaves half-applied row effects.
- [ ] Test duplicate queue delivery, stalled-worker recovery and worker restarts.

---

# Phase 14 — Error contracts, security and user-safe diagnostics

## Problems

Some broad exception handlers currently store raw exception strings in row/job error fields. Those values may be too technical, unstable, or disclose implementation details.

Import error/report artifacts must also be safe when opened in spreadsheet software.

## Tasks

- [ ] Create stable import error codes by phase and category.
- [ ] Map deterministic domain errors to user-safe messages/context.
- [ ] Keep technical exception detail only in structured server logs/observability with correlation IDs.
- [ ] Never expose SQL/constraint/internal stack details to ordinary users.
- [ ] Preserve actionable row number + field + safe code for business errors.
- [ ] Sanitize generated CSV/error-report cells against spreadsheet formula injection.
- [ ] Validate MIME/extension/content consistency where useful without trusting client MIME as authority.
- [ ] Keep XLSX archive bomb, entry-count, compression-ratio and macro defenses.
- [ ] Add malformed/corrupt/adversarial CSV/XLSX tests.

---

# Phase 15 — Database/index strategy for staged import scale

## Tasks

- [ ] Review indexes for job/status/row-number batch scans.
- [ ] Add normalized-barcode staging indexes needed for SQL duplicate joins.
- [ ] Keep all import indexes tenant-prefixed where tenant isolation/query shape requires it.
- [ ] Benchmark validation queries at 50k rows.
- [ ] Benchmark import selection with large mixed VALID/INVALID/IMPORTED populations.
- [ ] Verify no repeated full table scans.
- [ ] Verify row locks and skip-locked behavior under concurrent workers.
- [ ] Verify RLS plans do not cause pathological regressions.

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
