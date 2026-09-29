# Wanasah — Product Import Handoff
**Date:** 2026-09-28  
**Repository:** `MohHamdallah1/wanasah`  
**Local repo:** `C:\Users\admin\Desktop\wanasah`  
**Active branch:** `verify/products-p9-5-final`  
**Current verified HEAD:** `269f809 Align Product import localization test with modular backend`

---

# 1. READ THIS FIRST — CURRENT TRUTH

This handoff is the authoritative starting point for the next chat.

**Important:** do not infer the current state only from the last visible chat message. The branch advanced after stream interruptions. The actual repository state currently has:

- **Phase 1 through Phase 12 completed.**
- **Every task in Phase 11 is `[x]`.**
- **Every task in Phase 12 is `[x]`.**
- **Phase 13 has not started and all of its tasks remain `[ ]`.**
- Current branch matches `origin/verify/products-p9-5-final`.
- Do **not** redo Phase 11 or Phase 12.
- Next planned Product Import work is **Phase 13 — Queue concurrency, backpressure and worker availability**.

Latest direct verification before this handoff:

- `PRODUCT_IMPORT_PHASE11_SOURCE_SEMANTICS_GATE=PASS` — **20/20**
- `PRODUCT_IMPORT_TRACKING_GATE=PASS` — **23/23**
- `PRODUCT_IMPORT_PHASE12_SOURCE_STORE_GATE=PASS` — **28/28**
- Phase 11 focused tests — **13/13 PASS**
- Phase 4 Streaming Gate after Phase 11 dual XLSX reader changes — **15/15 PASS**

---

# 2. NON-NEGOTIABLE SAFETY WARNING

> **ABSOLUTE RED LINE: while moving, splitting, refactoring, or reorganizing files, never delete, drop, overwrite, or silently omit existing behavior/code by accident. Structural refactoring must preserve semantics unless the active phase explicitly authorizes a semantic change.**

Before deleting an old file after a move/split:

1. prove all behavior was migrated;
2. update every import/caller;
3. run targeted tests/gates;
4. verify no circular imports;
5. only then remove the obsolete file.

Never “clean up” unrelated code opportunistically.

Every plan item is marked `[x]` **only after implementation + verification are complete**.

---

# 3. PROJECT CONSTITUTION / ARCHITECTURAL AUTHORITIES

At the start of a new substantial task, read and obey:

- `.rules`
- `AGENTS.md`
- `ARCHITECTURE.md`
- `.cursor/rules/business-workflow-protection.mdc`
- `PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md` — **current active Product Import plan**
- `VERSION_2_FUTURE_FEATURES.md`
- `domains/simple_products/imports/SOURCE_STORE.md` — Phase 12 SourceStore production boundary

Core architectural direction: **Modular Monolith** — Monolith speed with strict module boundaries and domain ownership.

---

# 4. STRICT WORKING METHOD

## Canonical edit workflow

The canonical changes are made on GitHub on the active branch.

Normal workflow:

1. Inspect only files directly relevant to the current task.
2. Modify canonical files through the GitHub connector on `verify/products-p9-5-final`.
3. On the authorized development PC, use Remote MCP to:
   - `git pull --ff-only`
   - compile/import smoke test when relevant
   - run the narrow unit tests first
   - run the phase gate
   - then run required regressions
4. Only after PASS:
   - mark the corresponding plan items `[x]`
   - run `git diff --check`
   - inspect `git status`
5. Stop at the exact phase/boundary requested by the user.

Do not directly “hack” the local working tree as the source of truth.

## MCP/resource economy rule

The user explicitly requires strict economy in MCP usage.

- Do not crawl/search the whole repository without a reason.
- Prefer known exact files over broad recursive searches.
- Batch related Remote commands into one call when safe.
- Use GitHub `fetch_file` on exact paths before edits.
- Use Remote MCP mainly for runtime verification, DB checks, migrations, tests, and status.
- Do not repeatedly reread the same large file.
- Search only when the location/caller is unknown.
- Never spend tool calls on unrelated cleanup.

---

# 5. BRANCH LIFECYCLE RULE

When the current body of work is fully approved and ready:

1. finish all required gates;
2. owner/manual approval if applicable;
3. merge the branch into `main`;
4. delete the merged remote branch;
5. update local `main` with a clean fast-forward;
6. delete the obsolete local branch;
7. start the next body of work from a fresh branch based on updated `main`.

**Do not merge the current branch merely because this chat ended.** The Product Import hardening plan continues into Phase 13+.

---

# 6. DO NOT TOUCH THESE USER-LOCAL FILES

At the final status check before this handoff, local intentional changes/untracked files were:

- `RUN.txt`
- `dashboard/src/components/operations/OperationsSidebar.tsx`
- `dashboard/src/pages/products/list/ProductsListSection.tsx`
- `project_tree_clean.txt`
- `ChatGPT Image Sep 26, 2026, 03_55_02 AM-1.png`
- `ChatGPT Image Sep 26, 2026, 03_55_04 AM-2.png`
- `ChatGPT Image Sep 26, 2026, 09_06_47 AM.png`

Rules:

- never reset them;
- never stage them;
- never delete them;
- never overwrite them;
- never include them in commits accidentally.

If a future canonical change must touch `OperationsSidebar.tsx` or `ProductsListSection.tsx`, inspect/reconcile the user’s local modification first.

---

# 7. BUSINESS / WORKFLOW AUTHORITIES THAT MUST NOT BE BYPASSED

Never duplicate or bypass existing business authority inside Product Import.

Protect:

- Tenant/company isolation
- Permissions
- Product authority
- UOM/package authority
- Barcode authority
- Pricing authority
- Tracking authority
- Idempotency
- Audit semantics
- State machine
- Transaction boundaries
- Request semantics
- Lifecycle semantics

Product Import is an ingestion/orchestration module. It must not become a parallel Product domain.

`create_products_and_prices` remains the Product/Pricing execution authority.

Infrastructure must not copy business rules from the owning domain.

Global Product Import SQLAlchemy models remain in global `models.py` unless a separately controlled future step explicitly relocates them.

---

# 8. CURRENT PRODUCT IMPORT MODULE ARCHITECTURE

Main module:

`wa_backend/domains/simple_products/imports/`

## API
- `api/router.py`
- `api/__init__.py`

API must remain thin and explicit.

## Application
- `application/audit_service.py`
- `application/correction_service.py`
- `application/execution_service.py`
- `application/retention_service.py`
- `application/source_service.py`
- `application/source_store.py`
- `application/staging_service.py`
- `application/state_machine.py`
- `application/validation_service.py`
- `application/worker.py`
- `application/__init__.py`

`worker.py` must stay a **thin orchestrator**, not become a God-file again.

## Domain
- `domain/admission.py`
- `domain/errors.py`
- `domain/localization.py`
- `domain/mapping.py`
- `domain/normalization.py`
- `domain/retention.py`
- `domain/source_semantics.py`
- `domain/spreadsheet_dates.py`
- `domain/__init__.py`

Domain is a leaf layer: it must not depend on application, infrastructure, or API.

## Infrastructure
- `infrastructure/admission_repository.py`
- `infrastructure/audit_repository.py`
- `infrastructure/capacity_monitor.py`
- `infrastructure/capacity_queue.py`
- `infrastructure/correction_repository.py`
- `infrastructure/parsers.py`
- `infrastructure/postgres_source_store.py`
- `infrastructure/queue.py`
- `infrastructure/queue_dsn.py`
- `infrastructure/repository.py`
- `infrastructure/retention_queue.py`
- `infrastructure/retention_repository.py`
- `infrastructure/template.py`
- `infrastructure/upload_stream.py`
- `infrastructure/__init__.py`

## Module documentation
- `domains/simple_products/imports/SOURCE_STORE.md`

---

# 9. PHASE HISTORY — ALREADY COMPLETED

## Phase 1 — Module architecture / relocation
Completed.

- Product Import moved into `domains/simple_products/imports/`
- clean `api/application/domain/infrastructure` boundaries
- localization moved to domain
- template/queue moved to infrastructure
- endpoints extracted from oversized Product API
- DB operations extracted to repository
- old root `product_import_worker.py` removed after full migration
- architecture gates added

## Phase 2 — Break up responsibilities
Completed.

Separated:
- state machine
- normalization
- validation service
- execution service
- error taxonomy
- thin worker orchestration

## Phase 3 — Canonical states / error taxonomy
Completed.

Job outcomes include:
- `COMPLETED`
- `COMPLETED_WITH_ERRORS`
- `VALIDATION_FAILED`
- `FAILED` reserved for system-level failure

Rows distinguish:
- `STAGED`
- `VALID`
- `INVALID`
- `IMPORT_FAILED`
- `IMPORTED`

Migration:
- `c4d9e7a1b623_stage7_import_states_taxonomy.py`

## Phase 4 — True bounded parsing/staging
Completed.

- no import-sized Python row list
- parser yields rows incrementally
- staging writes fixed-size batches
- 50,000-row ceiling enforced incrementally
- context-managed resources
- XLSX archive security before traversal
- disk-backed SQLite sharedStrings keeps RAM bounded

Last verified:
- Phase 4 Gate **15/15 PASS**

## Phase 5 — Bounded validation
Completed.

- no `.all()` over full staged dataset
- bounded validation batches
- incremental persistence
- resumable validation
- crash tests
- tenant isolation preserved

## Phase 6 — DB-backed duplicate checks
Completed.

- normalized barcode staging
- internal duplicates via set-based SQL
- external conflicts via DB join
- no Python whole-file barcode set
- no huge `WHERE IN (...)`
- same unit/package barcode in the same row remains legal

Migration:
- `e8b4c1d7a6f2_stage7_import_barcode_staging.py`

## Phase 7 — Best-effort import
Completed.

- invalid rows do not block valid rows
- at least one valid row → execution
- zero valid rows → `VALIDATION_FAILED`
- execution fetches `VALID` only
- mixed result → `COMPLETED_WITH_ERRORS`
- system crash → `FAILED`
- counters include imported/invalid/import-failed/pending

## Phase 8 — Row-safe idempotency & correction
Completed.

- durable UUID `row_identity`
- immutable identity protection
- deterministic Product creation idempotency
- duplicate queue delivery does not duplicate Product
- retry never replays `IMPORTED`
- failed-row correction artifact CSV/XLSX
- same-job correction
- `IMPORTED` correction rejected
- correction upload is request-idempotent

Migration:
- `f2a6d8c4b901_stage8_import_row_identity.py`

## Phase 9 — Failure isolation
Completed.

- deterministic row-attributable errors separated from transient/system failures
- savepoints + deterministic batch bisection
- explicit 100-row test: 1 deterministic failure → **99 imported, 1 IMPORT_FAILED**
- DB outage remains job/system scoped and does not create fake row failures

Last known gate:
- Phase 9 **8/8 PASS**

## Phase 10 — Retention & audit lineage
Completed.

Retention:
- source bytes normally removed immediately after durable staging
- 7-day hard ceiling for retained terminal-job source bytes
- full raw/normalized row detail: 30 days
- compact row lineage: 365 days

Cleanup:
- tenant scoped
- terminal-job only
- cutoff bound
- bounded batches
- `FOR UPDATE SKIP LOCKED`
- no cross-tenant cleanup

Audit:
- tenant-scoped lineage API
- bounded/keyset pagination

Migration:
- `b7d3e9f1c204_stage10_import_retention_lineage.py`

Last known gate:
- Phase 10 **19/19 PASS**

## Phase 11 — Source-row fidelity & Excel semantics
**COMPLETED — DO NOT REDO.**

Every Phase 11 task is `[x]`.

### Row fidelity
Blank source rows never renumber later rows. `ParsedRow.row_number` carries the physical source row into staging unchanged.

### Multi-sheet XLSX
Parser never uses `workbook.active`.

Policy:
- official Wanasah workbook has hidden metadata marker naming canonical Products sheet
- official template selects it deterministically
- external workbook with one visible sheet may proceed
- external workbook with multiple visible sheets fails closed

### Formula policy
Paired bounded readers:
- `data_only=True`
- `data_only=False`

Policy:
- safe cached value accepted for non-identity field
- missing cached value → row error
- barcode formula → always rejected

### Barcode identity safety
Official template:
- unit/package barcode columns forced to Excel Text
- text-only validation through all 50,000 rows

Import:
- numeric XLSX barcode rejected
- scientific notation rejected
- literal text leading zeros preserved
- no guessing damaged identity

### Future spreadsheet date authority
Current Product Catalog import still does **not** import actual expiry/manufacture dates.

Reusable authority:
- `domain/spreadsheet_dates.py`
- `normalize_spreadsheet_date`

Handles:
- 1900/1904 epochs
- rejects phantom serial 60
- rejects fractional date-time serial
- accepts native date / naive midnight datetime
- accepts strict ISO `YYYY-MM-DD`
- rejects ambiguous locale text
- rejects timezone-aware coercion

### Phase 11 current verification
- focused tests **13/13 PASS**
- Phase 11 Gate **20/20 PASS**
- Tracking Gate **23/23 PASS**
- Phase 4 Streaming Gate still **15/15 PASS**

Gate:
- `scripts/gate_product_import_phase11_source_semantics.py`

## Phase 12 — Upload/source-payload memory & storage boundary
**COMPLETED — DO NOT REDO.**

Important: the actual branch contains Phase 12 complete even if an older transcript appears to stop around Phase 11.

### Upload boundary
Server ceiling remains:
- **8 MiB**

Upload path:
- 64 KiB incremental reads
- disk-backed bounded spool
- incremental size + SHA-256
- no full source materialization just to calculate hash/size

### SourceStore
Application owns storage-neutral immutable `SourceStore`.

Current V1 adapter:
- PostgreSQL-backed
- fixed **256 KiB chunks**
- immutable source metadata/chunks
- application/worker not coupled to PostgreSQL blob details

Future object storage can replace adapter behind the same port.

### Admission / capacity
Before persistence:
- per-user upload rate
- per-tenant upload rate
- active-job limits
- tenant live source byte limit
- global source-storage ceiling

Concurrency:
- tenant admission serialization/advisory lock
- durable atomic byte counters

Capacity denial:
- stable retryable code
- `Retry-After`
- rejected source is not persisted

### Source integrity
Before parsing/retry:
- chunks streamed in order
- exact size verified
- SHA-256 verified
- missing/reordered/tampered source fails closed

### Cleanup
After staging:
- SourceStore bytes removed immediately
- capacity released atomically
- Phase 10 remains 7-day hard ceiling for retained terminal source

Migration:
- `c9e5f2a7d310_stage12_import_source_store.py`

Documentation:
- `domains/simple_products/imports/SOURCE_STORE.md`

### Phase 12 current verification
Rerun immediately before this handoff:

`PRODUCT_IMPORT_PHASE12_SOURCE_STORE_GATE=PASS`

- **28/28 PASS**

---

# 10. IMPORTANT PRODUCT IMPORT MIGRATIONS

Relevant migrations currently include:

- `f7a1c3d5e9b2_stage7_async_product_import.py`
- `f3c8a1d4e6b2_product_import_tracking_defaults.py`
- `e7a1c4d9b2f6_import_tracking_constraints_repair.py`
- `c4d9e7a1b623_stage7_import_states_taxonomy.py`
- `e8b4c1d7a6f2_stage7_import_barcode_staging.py`
- `f2a6d8c4b901_stage8_import_row_identity.py`
- `b7d3e9f1c204_stage10_import_retention_lineage.py`
- `c9e5f2a7d310_stage12_import_source_store.py`

Do not touch unrelated Alembic drift during a Product Import phase unless explicitly asked.

---

# 11. IMPORTANT PRODUCT IMPORT GATES

Dedicated gates:

- `gate_product_import_architecture.py`
- `gate_product_import_state_taxonomy.py`
- `gate_product_import_tracking.py`
- `gate_product_import_phase4_streaming.py`
- `gate_product_import_phase5_validation.py`
- `gate_product_import_phase6_query_plans.py`
- `gate_product_import_phase7_best_effort.py`
- `gate_product_import_phase8_idempotency_correction.py`
- `gate_product_import_phase9_execution_isolation.py`
- `gate_product_import_phase10_retention_audit.py`
- `gate_product_import_phase11_source_semantics.py`
- `gate_product_import_phase12_source_store.py`

When changing a later phase, rerun affected earlier gate(s) if assumptions overlap.

---

# 12. CURRENT NEXT PHASE — PHASE 13

**Phase 13 has NOT started. All its plan items remain `[ ]`.**

Title:

**Queue concurrency, backpressure and worker availability**

Current Phase 13 scope:

1. Decide whether company-level queue serialization is truly required by Product/Pricing invariants; document reason.
2. If not required, reduce lock scope only after concurrency tests.
3. Add per-tenant active-import/backpressure limits.
4. Publish coarse-grained progress/state-change events only after durable state changes.
5. Deliver progress push-first via a dedicated tenant-scoped realtime/WebSocket channel using Wanasah’s existing realtime pattern.
6. Authorize each subscription against exact tenant/job; never trust client-supplied company ID as authority.
7. Coalesce/throttle events; never emit one network event per row.
8. Keep adaptive polling only as fallback with exponential backoff + jitter + stop on terminal/closed/hidden workflow.
9. Never poll every active import globally from browser.
10. Add connection/reconnect/backpressure tests.
11. Add global worker capacity metrics.
12. Add queue-age / oldest-job monitoring.
13. Add worker-health/readiness signal.
14. Add stuck-stage alerts.
15. Define cancellation semantics.
16. Ensure cancellation never leaves half-applied row effects.
17. Test duplicate queue delivery, stalled-worker recovery, and worker restarts.

**Do not start Phase 14 until Phase 13 is complete and the user explicitly allows moving on.**

---

# 13. PRODUCT IMPORT SEMANTICS TO REMEMBER

## Tracking precedence
1. explicit row tracking value wins;
2. blank row tracking cell uses this import’s default;
3. import default initially comes from company default but can be overridden for this import only.

The import-level value is a fallback for blank cells, not a third competing business rule.

## Best-effort semantics
- validation-invalid row does not block valid rows
- deterministic execution error may isolate one row
- transient/system error remains job/system scoped
- mixed success/errors → `COMPLETED_WITH_ERRORS`
- `FAILED` reserved for real system failure

## Retry/idempotency
- `IMPORTED` is terminal/immutable
- retries select only eligible rows
- row identity is durable UUID, not row number
- Product creation idempotency survives crash/retry windows
- corrections update failed rows within the same job

## Barcode identity
- text `001234` → preserve
- numeric XLSX → reject
- scientific notation → reject
- formula → reject
- duplicate/conflict checks remain DB set-based

## Source lifetime
- bounded upload memory
- immutable SourceStore persistence
- source integrity verified before parser use
- source removed after staging
- terminal retained bytes hard ceiling = 7 days

---

# 14. DEFERRED DASHBOARD TEST LIST IN RUN.txt

`RUN.txt` still contains a deferred section recording **14 Dashboard Vitest failures** from earlier work.

Do not opportunistically fix them while working on an unrelated Product Import backend phase.

Important: the list is historical/deferred. Later refactors have changed some of those areas, so **do not assume all 14 still fail today without rerunning them**.

---

# 15. BROADER PRODUCTS / FRONTEND RULES

- `dashboard/src/pages/products/ProductsPage.tsx` remains thin composition/orchestration.
- page/feature folders, no mega-file.
- do not replace god component with god hook.
- i18n mandatory.
- keyboard-first.
- RTL/LTR.
- responsive.
- Advanced Pricing visible-disabled/deferred V2.
- Advanced UOM deferred V2.
- do not touch unrelated Live Balance/inventory UI when task is Product Import only.

Design direction:
- dense professional enterprise SaaS
- navy + amber identity
- distinctive, not generic AI-looking
- avoid giant glass cards
- avoid excessive blank space
- avoid repetitive technical copy
- avoid yellow “AI alert” aesthetics

---

# 16. CURRENT GIT / LOCAL STATE

Branch:

`verify/products-p9-5-final`

Current verified HEAD:

`269f809 Align Product import localization test with modular backend`

At status check:
- branch aligned with origin
- only intentional user-local dirty/untracked files listed in section 6

Recent commits show Phase 12 is already complete. Do not reset/recreate it.

---

# 17. STARTUP CHECKLIST FOR NEXT CHAT

Before Phase 13:

1. Read this handoff.
2. Read `.rules`, `AGENTS.md`, `ARCHITECTURE.md`, `.cursor/rules/business-workflow-protection.mdc`.
3. Read Phase 13 in `PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md`.
4. Read `domains/simple_products/imports/SOURCE_STORE.md`.
5. Confirm branch is `verify/products-p9-5-final`.
6. Confirm HEAD has not advanced unexpectedly.
7. Inspect only Phase 13-relevant queue/realtime/worker files.
8. Do not reopen Phase 11/12 unless a real regression proves an issue.
9. Implement Phase 13 in controlled substeps.
10. For each item: implement → test → gate → mark `[x]`.
11. Stop before Phase 14 unless explicitly requested.

---

# 18. EXPECTED ENGINEERING BEHAVIOR

The user expects an **elite software architect**, not a passive code typist.

- If the user proposes a weak/unsafe solution, say so and implement the stronger design.
- Do not agree just to agree.
- Detect architectural issues the user may not notice.
- Prefer the strongest practical design available now; avoid deliberate technical debt.
- Do not expand scope beyond the active phase without approval.
- Do not dump unnecessary code in chat.
- Preserve existing semantics unless the phase explicitly changes them.
- Never mark a phase complete without evidence.

---

# 19. FINAL HANDOFF STATE

**Completed:** Product Import Phases 1–12.  
**Next:** Phase 13.  
**Phase 11:** closed + verified.  
**Phase 12:** closed + verified.  
**Phase 13:** untouched / all `[ ]`.  
**Branch:** `verify/products-p9-5-final`.  
**HEAD:** `269f809`.  
**Do not merge simply because a new chat is starting.**
