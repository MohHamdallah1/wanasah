# Product Import execution profiling (Issue #36)

Owner: Simple Products. Scope: the existing execution transaction of at most
100 VALID rows. Instrumentation is opt-in and does not close audits B/I or prove
a production performance target. No runtime benchmarks were executed for this
change.

## Enable in an isolated worker process

Set `PRODUCT_IMPORT_PROFILE_EVERY_N_BATCHES=10` in that process before invoking
the existing canonical worker launcher. This selects batches 1, 11, 21, ...
within each `execute_import` invocation, including a selected terminal batch.
Use 1 only for a short controlled acceptance run. Unset, 0, nondecimal,
non-ASCII, negative or values above 1,000,000 disable profiling. The setting is
read once per invocation; retries start their own ordinal sequence. Existing
worker concurrency/admission settings remain authoritative.

One `PRODUCT_IMPORT_BATCH_PROFILE` record contains a JSON object (schema 1),
tenant/job correlation, invocation-local batch ordinal, row counts, timings and
fixed-size counters. No source fields, product IDs, names, barcodes, prices,
SQL text, SQL parameters, exceptions, tokens or connection details are emitted.
The existing `observe_import_phase` helper logs every context separately;
reusing it for recursive attempts/per-product flushes would generate many logs.
This observer aggregates those contexts into one record instead.

## Per-statement timing detail (additive schema-1 fields)

Each **already-selected** batch now includes `sql_statement_timings`, a bounded
ordered list of **individual completed SQL cursor calls**. The existing opt-in
`PRODUCT_IMPORT_PROFILE_EVERY_N_BATCHES=10` selects the same batches as before;
profiling remains entirely off for unset/invalid/zero values. No new workers,
queries, transaction boundaries, global engine listeners or logging streams
are created by this change.

Each detail includes `ordinal` (execution-order number within the batch),
`phase` (the existing deepest phase), `sql_label` (an allowlisted static,
source-authored label or `unlabeled`), `sql_type` (an allowlisted SQL
operation label), `sql_sha256_16` (the first 16 hex characters of SHA-256 of
the DBAPI SQL **template**), `executemany`, and `wall_ms`. For example,
filter `phase=price_publish` to inspect the eleven calls individually;
aggregate by `sql_label` and `sql_sha256_16` to obtain count, total elapsed
and maximum elapsed per statement shape across sampled batches. A matching
fingerprint identifies the same **exact rendered SQL template**, not a unique
business entity or bound-parameter combination.

Pricing's existing SELECT/UPDATE/TextClause objects carry inert SQLAlchemy
`execution_options(wanasah_sql_trace_label="pricing_...")` metadata for
the company lock, maker/checker policy, publication/book locks, entries,
variant/UOM validation, predecessor check, effectivity conflict handling and
publishing updates. It changes **no SQL, WHERE condition, lock, transaction or
ORM flush semantics**, and only the selected import observer reads the tags.
SQL emitted implicitly by ORM flush may remain `sql_label=unlabeled`; its
`ordinal`, SQL type and template hash still distinguish it. User-controlled
labels are never accepted: unknown values become `unlabeled`.

**Privacy and bounds:** no statement text, query parameters, data values,
barcodes, product IDs, client details, SQL exceptions or business object
references are emitted. A selected batch retains at most **256 completed
calls**; `sql_statement_timings_limit=256` and
`sql_statement_timings_dropped` reveal when that bound is reached or detail
collection fails. `instrumentation_complete=false` means the record is
incomplete. An unsuccessful SQL call has no `after_cursor_execute` event:
the existing `sql_calls_without_completion` counter exposes the omission,
and no fictitious latency is assigned. The original phase totals and creation
counters remain unchanged.

The measured interval is driver-visible elapsed time between SQLAlchemy's
`before_cursor_execute` and `after_cursor_execute`; it includes driver
work, possible lock wait, network and PostgreSQL execution. It **cannot**
separate PostgreSQL CPU, disk IO or individual lock waits. No acceptance,
throughput or performance improvement is claimed until independently verified
by authorized observation of a future real import.

## Pricing lookup consolidation (stacked remediation PR)

The Pricing-domain helper `domains/pricing/validation_lookups.py` now loads
`ProductVariant` state and its `ProductUomConversion` UOM mapping with **one
tenant-constrained LEFT JOIN** per validation stage, replacing two separate
cursor calls in each of `create_draft_entries_bulk` and
`_validate_publication_entries`. The join includes the company predicate on
**both** tables and preserves base UOMs when no conversion exists. The result
is still bounded by the same requested variant IDs and the existing 200-entry
draft limit. No catalog data is cached beyond that validation call.

Static labels are `pricing_draft_variant_uom` and
`pricing_publish_variant_uom`. The original `PriceBookEntry FOR UPDATE`,
publish-time UOM/status/effectivity checks, audit/Outbox, SQL conflict guards,
maker/checker, tenant isolation, and transaction boundaries are unchanged.
**Both validations still happen:** this is a safe roundtrip-consolidation step,
not permission to reuse an earlier status/UOM snapshot across transactions or
between draft and publish. Fresh publish-time reads protect against concurrent
catalog changes.

Each stage replaces **two** queries with **one** SQL query at the Python call
site. This is not proof that the joined SQL runs faster on every data shape,
and no load tests, SQL execution or deployment were performed. The optional
per-statement observer can distinguish the consolidated query on a future
authorized real import.

## Same-transaction direct publication scope (stacked remediation PR)

The ordinary Simple Products create/price flow now requests
`create_direct_publication` from Pricing. Its opaque, single-use Pricing-owned
scope holds the exact just-created `PricePublication` and the `PriceBook`
already locked with `FOR UPDATE` under the Company `FOR NO KEY UPDATE`
mutex. It retains the originating root ORM transaction **and nested
savepoint identities** as invalidation boundaries, not a session-scoped
or cross-batch cache. The scope's `add_draft_entries` also reuses the
just-created publication's existing row lock, but checks DRAFT/version on
**every** bounded entry chunk and calls the SAME internal Pricing validation,
money rounding and DRAFT persistence helper used by the public
`create_draft_entries_bulk` interface.

During the existing draft -> publish flow, `scope.publish` still checks
Maker/Checker, DRAFT status and version, and executes the **unchanged**
publish-time entry/variant/UOM validation, authoritative predecessor lookup,
protected range-closing, overlap checking, publication updates and final
flush. It reuses the **already-held** Company, book and new-publication row
locks rather than re-requesting those same three SELECT locks; the public
`publish_publication` and `approve_publication` API paths retain every
original SELECT, lock and check. It cannot be used after commit, reuse,
rollback to another savepoint or a different root transaction.

The import still commits **every 100 active products**, maintains the
same publication and version per batch and the same 200-price-entry draft
limit. The same direct scope is valid for the Simple Products
update-existing-price path: existing-price predecessor, route/commercial
history, effective date and overlap checks remain enabled.

Estimated SQL round-trip *shape* per normal fresh-publication cycle
falls by four: the repeat `PricePublication FOR UPDATE` call in
`price_draft_entries`, and redundant Company, book and new-publication
lock reads in `price_publish`. The public generic draft entry and
publish interfaces still perform their original checks and locks.
The additional draft saving applies to each 200-entry chunk in the direct
scope. Real elapsed time and lock contention remain unknown. No benchmark,
SQL execution, tests, worker restart, schema change or deployment occurred.

## Publish validation query consolidation

Publication validation still takes a **fresh publish-time database snapshot** and
locks the same `PriceBookEntry` rows. The former two-step sequence
(`PriceBookEntry FOR UPDATE`, then a separate Variant/UOM lookup) is now one
tenant-scoped SELECT using LEFT JOINs and `FOR UPDATE OF price_book_entries`.
Only price entry rows are locked; Variant/UOM rows keep their previous unlocked
read semantics. Missing catalog references remain validation failures instead
of disappearing from the result set, and duplicate UOM-conversion rows are
folded back into the same per-variant UOM set.

Static trace label: `pricing_publish_entries_variant_uom`.

This is a **one-roundtrip reduction inside publish validation**, not removal of
publish-time validation. No elapsed-time improvement is claimed until a future
authorized real import records the new statement timings.

## Timing boundaries

All values are **client-visible wall time**, never PostgreSQL CPU or pure Python
CPU. Nested intervals overlap; do not add parent phase wall times to their
children, or subtract cursor wall from batch wall and label the result CPU.

| Phase | Boundary |
| --- | --- |
| `session_open_rls` | Await the existing tenant session opener; includes connection acquisition, checkout RLS hook and explicit RLS SQL. Hooks attach afterwards to the already-borrowed connection. |
| `input_python` | Build specs, stable batch request UUID and canonical JSON/hash before idempotency admission, for each attempt. |
| `idempotency` | Await the unchanged idempotency lock/read/create operation, including its internal flush. |
| `pricing_policy` | Existing mode checks, company load and default-book resolution/creation. |
| `product_structures` | Await all catalog creation work, including family locks/queries, UOM/tracking lookups and live-stock summary. |
| `barcode_python` | Normalize input barcodes and enforce in-batch uniqueness, before querying persisted barcodes. |
| `variant_objects` | Construct DRAFT variant objects and append them to the bounded staging list. |
| `activation_objects` | Construct conversion/barcode objects, perform the original ACTIVE transition, and add audit/outbox objects. No awaited SQL is inside this loop. |
| `family_flush` | Each explicit awaited master flush needed for its actual generated ID; aggregated over attempts. |
| `draft_flush` | Explicit awaited group flush of DRAFT variants for actual IDs. |
| `activation_flush` | Explicit awaited group flush of lifecycle/conversion/barcode/audit/outbox work. |
| `price_publication_create` | Await Pricing's unchanged publication creation, including lock and ID flush. |
| `price_entries_python` | Construct the exact existing base/package entry payloads. |
| `price_draft_entries` | Await the existing <=200-entry chunks, validation and internal flushes. |
| `price_publish` | Await original publication validation, D6 predecessor SQL, publish updates and final flush. |
| `savepoint_attempt` | Enter/save/leave each existing nested transaction, including preflush and exit flush; failed attempts remain in timing totals. Excludes recursive children after the failed attempt. |
| `row_outcome_python` | Construct durable response lineage and set row/idempotency outcomes for newly created products. Replay row transitions remain in the savepoint interval. |
| `commit` | Whole existing await of commit, including possible ORM flush, driver commit and connection return. |
| `rollback` | Existing exception-handler rollback await. Cancellation/early-return cleanup remains in its original session-close/rollback path. |
| `session_close` | Existing tenant session close/context reset, after hooks are removed. |
| `batch_other` | SQL/flush events outside named contexts, e.g. job/actor/permission/row reads and finalization. No inferred phase wall is assigned. |

`batch_wall_ms` includes the selected transaction's setup through close, excluding
the final record serialization/log write. `service_elapsed_wall_ms` is elapsed
since this execution invocation began, including unsampled batches, not total
queue/job lifetime. `queue_wait_ms` and `pool_checkout_ms` are null: this path
has no dispatch timestamp or isolated pool-wait boundary. The setup interval
must not be relabeled as pure pool wait. Other Python normalization, SQLAlchemy
bookkeeping, lock wait, driver/network, server/WAL/index costs are not separately
invented measurements.

## Count provenance and failure semantics

Instance-local public SQLAlchemy connection events count cursor calls started
and completed, plus calls marked executemany. One driver call may carry many
rows; these are not affected-row counts or server statements. Cursor wall is
measured between before/after callbacks only for completed calls, includes
driver/network/server/lock wait and excludes commit's direct DBAPI operation.
Started minus completed exposes missing completion on failure/cancellation;
no synthetic duration is assigned to such calls.

Instance-local Session before_flush/after_flush_postexec events count actual
ORM flush passes, including implicit query flushes, savepoint pre/exit flushes
and commit flushes. No-op flush calls do not fire these events. Explicit await
phase calls and observed passes are therefore separate counts. A pricing phase
may contain both internal explicit and implicit flushes; the observer does not
claim it can distinguish those triggers using public events. Completed flush
wall is the event-to-event interval, contains cursor wall and ORM bookkeeping,
and excludes a failed pass without after_flush_postexec. New/dirty/deleted
candidate totals at before_flush can include repeat candidates, unchanged dirty
objects and rolled-back work; they are not net SQL updates.

The public pending_to_persistent transition counts ORM object creations by a
fixed class allowlist. `attempted_new_objects` includes rolled-back creations.
A small dictionary checkpoint around each original savepoint removes creations
from failed attempts from retained totals. No business identity sets are held.
This execution path has no pending new objects before entering a new attempt;
row changes from prior attempts may preflush, but are not creation events.
`committed_new_objects` reports retained creations only after the outer commit
await returns. Core SQL updates (including price publication updates) are not
ORM creation events. Replay contributes imported rows without new products.
These counts are batch-local, not job-wide or exactly-once log delivery counts.

Commit state is `not_attempted`, `unknown` once the await begins, or `returned`
after it returns. Commit interruption/lost response never becomes a fabricated
known failure or zero net objects. Nonreturned commit records have null committed
object totals. A logger/observer setup failure cannot reject a business operation;
`instrumentation_complete=false` means its counters must not be trusted.
Hooks are removed in finally before session close; cancellation retains the
original cleanup and retry path. SQLAlchemy hooks are scoped to this session and
its already-established connection, with no global patch, new SQL or pool hooks.
The hook contracts are SQLAlchemy's public
[Session events](https://docs.sqlalchemy.org/en/20/orm/events.html) and
[connection events](https://docs.sqlalchemy.org/en/20/core/events.html).

## Source analysis and expected effect

- A successful 100-SKU batch has more than two flushes: idempotency, each newly
  resolved master, grouped DRAFT IDs, grouped ACTIVE evidence, live-stock summary,
  publication ID, draft prices and published state can flush. Query autoflush,
  nested transaction exit, commit and failed split attempts add others.
- The master/variant/publication flushes provide actual generated IDs. DRAFT to
  ACTIVE and audit/outbox ordering remains required. Price validation, version
  changes, effectivity, history and unique/GiST race guards remain untouched.
- Existing per-batch UOM/tracking/family lookups and grouped variant/price writes
  already reduce repeat work. D6's measured predecessor correction is retained.
  Static analysis does not prove another dispensable flush/SQL operation.
  Consequently this patch adds evidence only, with no throughput claim or
  speculative business/SQL optimization.

Default-off work adds one setting read and lightweight phase/no-op contexts,
with no listeners, timing calls or profile records. Selected transactions add
constant-size dictionaries, clock reads and O(1) callback work per SQL/creation
event, plus a fixed-width creation-count checkpoint per savepoint. Flush candidate
snapshots use public Session collections and can cost O(pending/dirty objects),
bounded by this transaction, rather than O(source rows).
Worst-case deterministic splitting of 100 rows has at most 199 attempts and
still one profile record. Memory does not grow with the source file or retain
ORM objects. Logging cost and callback overhead require independent acceptance
measurement. Large imports keep their existing 100-row transaction boundaries,
permissions, lock order, row identities, SourceStore, RLS, replay and cancellation;
sampling bounds additional log volume but is not a speed improvement.
