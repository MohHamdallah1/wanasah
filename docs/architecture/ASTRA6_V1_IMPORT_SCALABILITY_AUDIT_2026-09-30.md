# Astra 6 — original complete audit (preserved verbatim)

Owner-provided audit, 2026-09-30. The following is archived source material; claims and suggested actions require separate verification. No application code or database is changed by this file.

---

**Decision: conditional V1 candidate, but unrestricted production readiness is not established.** The 14-minute observation is encouraging; it does not close cancellation, recovery, queue fairness, or concurrent-business latency gates. Further ORM rewrites and index tuning can wait for V2 unless measurements connect them to a failed V1 acceptance threshold.

Audited checkout: `0909b32226e56e025f60348a21081316b89eeaae`, exactly the requested baseline. No files changed, tests or benchmarks executed, live database accessed, or additional agents invoked.

The historical 45.76-minute run, owner-observed approximately 14-minute run, isolated XLSX profiles, and successful 5k/10k CSV queue exercises are different evidence sets—not a controlled A/B comparison.

**Evidence table**

Links identify current repository locations. “High” means confidence in the stated source behavior, not proof of production performance.

| Issue | Source file:line | Exact code behavior | Demonstrated evidence | Unproven hypothesis | Business impact | Confidence |
|---|---|---|---|---|---|---|
| Execution durability | [execution_service.py:576](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/imports/application/execution_service.py:576) | Opens a tenant session per iteration; locks job and up to 100 VALID rows; rechecks actor/permissions; commits results and progress together; closes session. | Current source; historical lineage checks. | Production crash/retry coverage is complete. | Strong atomicity foundation; recovery acceptance remains necessary. | High |
| Staging/cancellation | [staging_service.py:46](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/imports/application/staging_service.py:46), [repository.py:164](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/imports/infrastructure/repository.py:164) | All staging shares one transaction; 500-row explicit multi-VALUES inserts; actual row count checked before commit. | Current mitigation; historical short-write/stall evidence. | Current code still reproduces the historical stall—or guarantees bounded cancellation. | A stalled phase can retain resources and delay cancellation. | High behavior; unresolved runtime |
| ORM work | [service.py:1279](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/service.py:1279) | Constructs DRAFT variants, flushes together, attaches UOM/barcodes, applies lifecycle transition, records audit/outbox, flushes again. | B3.9: 31,629→3,046 statements; 52.402→58.037 seconds. | ORM bookkeeping dominates today’s 11 minutes. | Further optimization needs attribution. | High |
| Pricing serialization | [publishing.py:129](C:/Users/admin/Desktop/wanasah/wa_backend/domains/pricing/publishing.py:129), [core.py:92](C:/Users/admin/Desktop/wanasah/wa_backend/domains/pricing/core.py:92) | Locks Company FOR UPDATE, then book/publication; preserves historical-price proof and exclusion constraints. | B3.9: 11.011 seconds across 50 predecessor-proof calls. | Company waits or GiST maintenance caused that time. | Same-company commercial writes/Route Launch can wait. | High mechanism; unknown magnitude |
| Additional shared lock | [live_stock_projection/service.py:2251](C:/Users/admin/Desktop/wanasah/wa_backend/domains/live_stock_projection/service.py:2251) | Exclusive company-summary advisory guard plus summary FOR UPDATE, before import pricing publication. | Current source. | A production deadlock or inventory slowdown resulted. | Catalog activation/projection maintenance can contend. | High mechanism |
| Queue isolation/fairness | [worker launcher:10](C:/Users/admin/Desktop/wanasah/wa_backend/scripts/run_product_import_worker.ps1:10), [capacity_queue.py:189](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/imports/infrastructure/capacity_queue.py:189) | Default one import slot; monitoring children share queue and use read-before-defer plus execution lock. | Historical monitoring backlog; current queue topology. | Deployed slots match defaults; duplicate scheduling explains every backlog. | Long imports delay small imports and import monitoring/recovery. | High topology |
| Index growth | [models.py:269](C:/Users/admin/Desktop/wanasah/wa_backend/models.py:269), [search migration:81](C:/Users/admin/Desktop/wanasah/wa_backend/alembic/versions/d4a7c9e2f1b5_live_stock_native_trgm_search.py:81), [pricing constraint:1445](C:/Users/admin/Desktop/wanasah/wa_backend/models.py:1445) | SKU uniqueness uses B-tree; search uses GIN/TRGM; published price overlap uses GiST exclusion. | Reported size growth; disposable-clone pending-list/churn evidence. | Current index sizes prove pathological bloat or the slowdown. | Storage/write amplification possible; removing indexes risks correctness and reads. | High definitions; cause unproven |
| WebSocket credentials | [import router:547](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/imports/api/router.py:547), [dashboard:492](C:/Users/admin/Desktop/wanasah/dashboard/src/pages/products/import/useImportProductPolling.ts:492) | Access token travels in query string. Installed [Uvicorn:273](C:/Users/admin/Desktop/wanasah/wa_backend/venv/Lib/site-packages/uvicorn/protocols/websockets/websockets_impl.py:273) logs the path with query string. | Verified application and installed dependency code. | Production logging configuration actually records tokens. | Credential disclosure to log readers if unredacted. | High exposure path; deployment unknown |

**What the 100-SKU transaction actually does**

It acquires job/row locks, checks authorization, creates a stable batch operation identity and input hash, and enters a savepoint. The idempotency service rejects changed input and replays stored results ([services.py:2643](C:/Users/admin/Desktop/wanasah/wa_backend/services.py:2643)). Deterministic failures trigger recursive batch splitting; unexpected failures escape for retry.

For an ordinary successful batch with an existing default book, there are **seven explicit flush executions, plus one per newly created Product master**:

- Idempotency record: `services.py:2698`.
- New master: `simple_products/service.py:1000` or `1105`.
- Variants and lifecycle/dependent records: `service.py:1306`, `1390`.
- Live Stock summary: `live_stock_projection/service.py:2292` or `2304`.
- Publication, price entries, final publication state: `pricing/publishing.py:151`, `423`, `975`.

First-book setup and split/retry paths add work. Autoflush is not disabled in [database.py:113](C:/Users/admin/Desktop/wanasah/wa_backend/database.py:113); ORM queries/DML can trigger it. Savepoint entry/completion and commit also flush pending state. These are potential flush boundaries, not evidence that each emits SQL.

**“350 ORM flushes alone caused 11 minutes” is unsupported.** Approximately 350 is the number of successful 100-row batches for 34,999 rows, absent splits—not total flushes. A flush can generate multiple statements; a transaction contains many flushes/statements; statement count is not a complete network-round-trip count.

In the isolated B3.9 sample, variant INSERT cursor time was only **0.835 seconds**, versus **11.011 seconds** for predecessor proof and **12.322 seconds** for price INSERT/UPDATE combined ([B3.9 report:59](C:/Users/admin/Desktop/wanasah/docs/architecture/CATALOG_B39_ORM_BATCH_FLUSH_AND_PRICE_HOTSPOTS_2026-09-29.md:59)). This prioritizes investigation; it does not attribute the owner’s runtime.

**Connections, locks, and normal business operations**

A 14-minute import **does not necessarily monopolize one database connection**. Session construction is followed by an explicit tenant-setting query, which acquires the connection ([repository.py:32](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/imports/infrastructure/repository.py:32)). Execution and validation iterations commit/rollback and close; source reading uses a separate scoped connection.

Exceptions to “short batches”: staging spans the entire source; validation’s final barcode reconciliation spans the job ([validation_service.py:489](C:/Users/admin/Desktop/wanasah/wa_backend/domains/simple_products/imports/application/validation_service.py:489)). Bounded row counts do not guarantee bounded transaction time.

Locks include:

- Job FOR UPDATE; execution rows FOR UPDATE SKIP LOCKED.
- Idempotency advisory/record locks; sorted tenant/name family advisory locks.
- Live Stock company-summary advisory/row locks.
- Company, book and publication FOR UPDATE; updated price/history rows.
- Ordinary write/table locks, FK key-share checks, and unique/exclusion conflict waits. Barcode availability is a SELECT, **not** a pre-acquired barcode row lock; uniqueness resolves races.

Company pricing locks persist until batch transaction end, ordinarily starting after product construction; first-book setup can acquire them earlier. Route Launch explicitly shares that lock ([context.py:180](C:/Users/admin/Desktop/wanasah/wa_backend/domains/pricing/context.py:180)). Family create/rename share family guards; projection rebuilds share summary guards.

Price resolution uses reads ([resolver.py:182](C:/Users/admin/Desktop/wanasah/wa_backend/domains/pricing/resolver.py:182)); **every sale does not take the pricing write lock**. Inventory/inbound use lifecycle, location, batch and balance authorities ([services.py:3486](C:/Users/admin/Desktop/wanasah/wa_backend/services.py:3486)). Nevertheless, FK checks against a Company locked FOR UPDATE can delay same-company writes even without an explicit pricing-lock call.

The design permits invoices, pricing reads, stock operations and other tenants to continue, but acceptable latency is **NOT ESTABLISHED BY CURRENT EVIDENCE**. Neither pool exhaustion nor an actual deadlock is established. Defaults are five SQLAlchemy connections per process, zero overflow, three-second checkout timeout ([config.py:43](C:/Users/admin/Desktop/wanasah/wa_backend/config.py:43)); deployment process counts, separate queue connections and PostgreSQL capacity remain unknown.

**Workers, indexes, and diagnostic limits**

A long import occupies one task slot for its duration; transaction commits do not yield that slot to another task. With one import slot, smaller imports, capacity monitoring, retention and scheduled recovery wait. Maintenance, notifications and reports use the separate `worker_queue` app, default concurrency four ([workers/app.py:8](C:/Users/admin/Desktop/wanasah/wa_backend/workers/app.py:8)). Their actual deployment is unverified. Separate queues do not isolate PostgreSQL CPU, WAL or disk.

Index growth **does not prove bloat**. More live tuples, GIN pending entries, page allocation and lifecycle-update churn can enlarge indexes. True bloat requires physical utilization evidence; WAL volume and search regression require separate measurements. A specific index causing the current slowdown is **UNPROVEN—NOT ESTABLISHED BY CURRENT EVIDENCE**.

Dropping/rebuilding live indexes can introduce blocking, resource spikes and degraded tenant queries. Dropping UNIQUE/exclusion authority changes correctness; dropping FK-supporting indexes can worsen referential checks. Size growth alone justifies none of these actions.

The profiler measures stage wall time and elapsed client cursor calls ([profiler:72](C:/Users/admin/Desktop/wanasah/wa_backend/scripts/b38_profile_real_import_disposable.py:72)). Cursor time combines server execution, waits, transport and driver overhead; it is not pure PostgreSQL execution time. Residual wall time is not pure Python CPU. Queue wait/HTTP ingress, isolated commit latency, CPU, lock waits, WAL and I/O were not separately attributed. Post-import EXPLAIN cannot reproduce in-flight contention.

**Three highest-value investigations—not executed**

1. **Staging/recovery boundedness.** Smallest read-only diagnostic: a short time series of transaction age, query age, wait event and blocker IDs during an already-occurring stall/cancellation. Persistent `ClientRead` distinguishes client/transport waiting from `Lock`; cancellation blocked by the staging transaction confirms the dependency. This cannot prove crash/retry correctness: that requires the outstanding controlled acceptance exercise, not a read-only snapshot.

2. **Concurrent business contention during publication.** Smallest measurement: one bounded, parameter-free blocker/wait trace covering import publication and ordinary business requests. Company/summary blockers identify serialization; WAL/I/O waits suggest storage pressure; no waits leave CPU/driver cost unresolved. Correlate existing request durations to judge business impact. Do not collect raw SQL containing customer values.

3. **Actual queue capacity/fairness.** Smallest measurement: one read-only snapshot of registered live slots, running task kinds, oldest queued age and backlog by task kind across both queue apps. A sole occupied import slot plus aging monitors demonstrates queue delay; idle slots with growing eligible backlog indicates another scheduling problem.

Separately, settle token-log exposure by inspecting effective logging/redaction configuration and returning only a boolean indicating whether an existing handshake record contains a credential parameter—never its value.

**V1 conditions and V2 scope**

V1 approval requires bounded cancellation/recovery evidence, representative concurrent-business acceptance, deployed worker capacity verification, and closure of credential logging exposure if enabled. Existing [Phase 19 release gates](C:/Users/admin/Desktop/wanasah/PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md:960) remain open; later successful imports do not automatically close them.

Bulk ORM INSERT/Core INSERT may reduce identity tracking and object work, but must preserve correlated generated IDs, family reuse, lifecycle transitions, UOM/barcodes, audit/outbox, pricing versions and replay lineage. COPY is only a candidate staging optimization; direct COPY into RLS-protected targets is not a drop-in substitute.

These optimizations can be V2 work. Equivalent insert mechanics need no inherent business-contract change. Altering lifecycle order, publication grouping, cancellation boundaries or company serialization does. Index changes require reviewed migrations; auxiliary COPY staging may require schema/security changes. None is an established solution to the observed runtime.
