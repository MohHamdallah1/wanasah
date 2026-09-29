# WANASAH — Urgent Catalog, Index & Worker Fairness Plan

## الملخص التنفيذي — اقرأ هذا أولًا

هذه خطة هندسية عاجلة للمشروع كله، وليست إصلاحًا سريعًا لملف الاستيراد فقط. **لا نغيّر مخطط قاعدة البيانات، ولا نزيل فهرسًا، ولا نزيد العمال قبل القياس.** كل بند ينتهي باختبارات وإثباتات مستقلة قبل وضع [x].

### القرارات الحالية المبنية على الكود

1. **تثبيت أسماء الجداول حاليًا:** جدول products يمثل المنتج الأب/الهوية المشتركة (ويسميه مسار المنتجات البسيطة «عائلة»)، وفيه الاسم والوصف والعلامة والتصنيف والكود. جدول product_variants يمثل الصنف/SKU القابل للبيع والتتبع. لا ننفذ إعادة تسمية مادية الآن؛ أي ترحيل محتمل لاحقًا يحتاج خريطة اعتماد لكل Backend وDashboard وFlutter وSQL وRLS والمهاجرات.
2. **المنتج بلا عائلة:** المسار الحالي ينشئ أو يعيد استخدام أب باسم الصنف نفسه داخل الشركة. هذا سلوك فعلي مثبت؛ لا نغيّره دون فحص أثره التجاري والمحاسبي وموافقة صاحب المشروع. الكرتونة وحدة قياس/تعبئة للصنف، وليست Variant مستقلًا.
3. **الأعداد الدقيقة:** في سياق الشركة 38، آخر COUNT(*) أظهر 8,035 أبًا و96,778 صنفًا، بينها 8 آباء بلا أصناف. أرقام 19,296 و217,055 السابقة كانت إحصاءات PostgreSQL تقديرية/عامة ولا تصلح عدًّا دقيقًا لهذه الشركة.
4. **الفهارس:** بعد REINDEX الذي نفذه المستخدم هبط حجم فهارس products من نحو 93.18 MB إلى 4,956,160 بايت، وproduct_variants من نحو 213.98 MB إلى 72,179,712 بايت. هذا يثبت وجود حجم كبير قابل للاستعادة، ولا يثبت بعد سبب تراكمه أو تحسن سرعة الاستيراد. الفهرس الفريد لا يجوز حذفه لمجرد أن idx_scan يساوي صفرًا.
5. **العمال:** يوجد تصميم منفصل لمسارات maintenance وnotifications وreports، ومسار product-import في Queue/تطبيق Procrastinate مستقل. الخلل المؤكد في التصميم الحالي هو مشاركة مراقبة الاستيراد لصف تنفيذ مهام الاستيراد، والجدولة كل خمس دقائق على مستوى شركات كثيرة. العزل الأمني شيء، وضمان العدالة في CPU/DB/queue wait شيء آخر.
6. **الإلغاء:** خدمة Backend الرسمية موجودة، لكن واجهة لوحة التحكم لا تربط زر إلغاء أثناء التنفيذ. إغلاق النافذة أو قتل Worker لا يلغي المهمة الدائمة؛ المطلوب إلغاء مصادق عليه، واستعادة آمنة بعد الإيقاف أو الانقطاع.
7. **بطء الاستيراد:** حصلنا على نتائج تشغيل حقيقية كبيرة، لكنها ليست تجربة مقارنة مضبوطة بين CSV وXLSX. يجب فصل زمن الانتظار والفحص والإضافة والأسعار والمعاملات والـDB قبل اختيار تحسين.

### مسار التنفيذ الإلزامي

- **A — هوية المنتج:** جرد كامل للعلاقات والتسميات وتأكيد سلوك الأب التلقائي، دون أي تغيير للجداول.
- **B — الفهارس:** قياس تضخمها ومصدر نموها وأثرها على القراءة/الكتابة، ثم إصلاح مثبت قابل للتراجع إن لزم.
- **C — الجدولة:** إثبات سبب تراكم مهام المراقبة وفشلها، تصميم تجميع/تحديد مستحقات ومراجعة atomic queueing locks والعزل بين مسارات العمل.
- **D — الأداء:** قياس مرحلي لخط الاستيراد الحقيقي مع 100 ثم 1,000 ثم 5,000 ثم 10,000 ثم 50,000 صف، وبنفس دلالات البيانات؛ لا قفز للاختبار الكبير عند وجود عطل.
- **E — عدالة الموارد:** Backpressure وحدود لكل شركة وحصص لفئات المهام واختبارات شركتين/10/100؛ لا زيادة عمياء في عدد العمال، ولا وعود بعزل مادي مطلق على خادم مشترك.
- **F — إلغاء واستعادة:** زر عربي قابل للوصول بلوحة التحكم مرتبط بخدمة الإلغاء، وحالات توقف/إعادة تشغيل/انقطاع شبكة مدققة.
- **G — بوابة الإنتاج:** اختبارات Backend وDashboard وFlutter عند تأثره، RLS وIdempotency والتسعير والمستودع، قياسات قبل/بعد، ومراجعة خطة Product Import Phase 19 قبل أي دمج.

**المنفذ حتى كتابة الملف:** تشخيص وقراءة فقط، مع إلغاء Job الإعادة الذي طلبه المستخدم سابقًا. لم تُنفذ تغييرات SQL Schema أو Business Logic أو زيادة Workers في هذه الخطة. تفاصيل كل مرحلة وتبعياتها وبوابات إغلاقها وأوامر PowerShell تجدها أدناه.

---

**Created:** 2026-09-29  
**Status:** EVIDENCE-BASED DIAGNOSTIC ROADMAP — implementation checkpoints OPEN  
**Work branch at creation:** verify/products-p9-5-final, HEAD initially 5ee2a5c  
**Companion plan:** PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md, especially Phase 19.2.  
**Architecture authority:** ARCHITECTURE.md, .rules, AGENTS.md, .cursor/rules/business-workflow-protection.mdc.  
**Scope:** backend, Dashboard, Flutter/offline contracts, PostgreSQL, Procrastinate, observability, scale tests. This file is an urgent track, not authorization to rewrite business workflows or bypass the existing Phase 19 gates.

## 0. Mandatory execution discipline

- Keep current product creation, pricing, inventory, audit, idempotency, tenant/company isolation and RLS unchanged unless a concrete defect and approved change require otherwise.
- Work on the existing verification branch. No merge, cleanup of test data, destructive reset, implicit migration, production REINDEX, or killing unrelated processes.
- Read actual files and verify current commit/file content before each surgical code edit. Respect any local dirty/untracked files; do not overwrite them. GitHub connector owns edits; Remote Desktop Commander is used for local read-only diagnostics and explicit gates.
- Begin with non-mutating evidence and controlled developer fixtures, then change one bounded technical concern at a time. Every item is checked only after direct measurements and a reproducible verification gate.
- Preserve one active Product Import job per company where company-default pricing serialization still requires it; never “fix” throughput by removing safety locks.
- Maintain Arabic-first i18n/RTL/LTR/keyboard accessibility and Flutter compatibility.
- Do not assume PostgreSQL or one queue can provide absolute CPU/memory/I/O partitioning per tenant: choose and test an explicit resource-policy contract.

## 1. Verified facts and precision warnings (2026-09-29)

### 1.1 Catalog semantics — source checked

- [x] wa_backend/models.py: Product -> public.products, a shared parent/master product containing company_id, code, name, description, brand, category, version; relationship to variants.
- [x] ProductVariant -> public.product_variants; SKU identity, product_id, UOM, lifecycle, tracking, packaging. Tenant-safe composite FK to Product; stores the sellable/inventory-relevant variant.
- [x] wa_backend/domains/simple_products/service.py: UI family endpoints create/list Product parent records. create_product_structures constructs a ProductVariant for every simple product spec, then barcodes/UOM conversions/pricing through owning services.
- [x] _resolve_family: explicit family_id wins; otherwise family_name is searched/created; if family_name omitted, spec.name is used as the parent name, reusing an existing same-name Product for that company when found. The system does NOT infer family from package size or product-name similarity.
- [x] A carton/pack multiplier and package barcode are UOM/packaging of a variant, NOT automatically a separate variant.
- [x] After 2026-09-28 original XLSX import, 34,999 imported rows each linked to a distinct ProductVariant; 7,510 distinct Product parents for that job. 15,000 INVALID rows. No loss indicated for that job by linked identity evidence.
- [x] Exact read-only COUNT(*) in company/RLS context 38: 8,035 visible Product masters; 96,778 visible ProductVariants; 8,027 parents with at least one variant; 8 parents with no variant. Counts can change later.
- [x] The previously cited 19,296 Product and ~217,055 Variant rows were PostgreSQL estimated/global table statistics (n_live_tup), NOT exact company-38 counts. Do not mix those populations or treat estimates as transactional counts.
- [ ] Inventory and pricing authority contract for every variant-vs-master reference must be mapped end-to-end (catalog, pricing, costing, warehouse, reports, APIs, Dashboard, Flutter/offline, raw SQL, events and migrations). Do not claim all modules use the same identity until this is verified.

### 1.2 Index evidence — source and DB checked

- [x] PostgreSQL version on developer DB: 16.9.
- [x] User ran REINDEX TABLE products and REINDEX TABLE product_variants on development DB; BEFORE sizes provided by user and corroborated by prior DB readings: products index bytes ~93.18 MB decimal; product_variants ~213.98 MB decimal.
- [x] AFTER rebuild, DB measured index bytes: products 4,956,160 bytes; product_variants 72,179,712 bytes. Data heap bytes respectively 2,662,400 and 49,045,504. These are physical global relation bytes, NOT per-company disk usage.
- [x] Big decrease after rebuilt index demonstrates large reclaimable prior physical index space; neither identifies the churn source nor proves future stability or a specific end-to-end speedup.
- [x] Relevant indexes include unique SKU/code/IDs, composite company/product identities, B-tree name seek, and GIN trigram search. idx_scan is cumulative planner scan usage; zero scans alone do not justify removing a UNIQUE or constraint-supporting index.
- [x] Plain REINDEX TABLE is not a routine live-production fix: it can block concurrent writes. For a warranted online rebuild, plan/assess REINDEX ... CONCURRENTLY with PostgreSQL 16 caveats, disk reserve, monitoring and recovery. Never automatically execute it on production.
- [ ] Identify separately the natural size of each current index, measured bloat/leaf density where possible (pgstattuple/pgstatindex with authorized read-only privileges), GIN pending list, tuple churn/autovacuum, planner scans, cache hit and write amplification. pgstattuple is not presently installed in the observed developer database; do NOT install without review.

### 1.3 Queue/runtime evidence — source and DB checked

- [x] wa_backend/workers/app.py uses schema worker_queue and queue names maintenance, notifications, reports; its default concurrency setting is 4. Development launchers exist independently for operational and reporting workers.
- [x] Product Import uses a separate Procrastinate App in public schema to atomically create business job and defer queue task, queue product-import; default import concurrency is 1, company queue lock product-import:{company_id}.
- [x] Product-import monitoring/retention/heartbeat/recovery tasks ALSO live in product-import queue, competing for the same worker slots as real import jobs.
- [x] Monitoring scheduler runs every five minutes, pages company IDs, and defers a separate capacity monitor for each company. Current child code uses a read-before-defer active-lock probe plus execution lock; no atomic per-company queueing_lock is used on child defer. Check race, backlog and recovery behavior; do not presume locks fully deduplicate.
- [x] Developer snapshot public.procrastinate_jobs: 87,452 successful monitoring tasks, 9,176 failed monitoring tasks, 867 queued monitoring tasks (867 distinct company IDs), 9,176 successful retention cleanup tasks, 19 succeeded import QUEUE TASKS and one queued import QUEUE TASK. Queue-task success is NOT equivalent to successful business import.
- [x] Monitor history covers 1,147 distinct company IDs; re-read real active/inactive company status. iter_retention_company_id_pages as inspected does not itself filter Company.is_active. Check whether another authoritative condition excludes inactive tenants.
- [x] User's repeat XLSX job 1ce94e25-4425-4e7d-a783-05001ac232d8 was officially cancelled from QUEUED with 0 staged/imported rows. Do not cancel or replay it again.
- [x] Product-import registry had 0 worker rows at a previous developer snapshot. A separate OS process snapshot showed uvicorn but no recognized procrastinate worker. This does NOT prove workers never run; check actual state before each benchmark.
- [x] Both Procrastinate apps retain succeeded jobs via delete_jobs=never; historical queue/event retention strategy and forensic requirements must be audited before purging.
- [ ] Inspect worker_queue.procrastinate_jobs and worker registry independently of public queue, all actual deployments/supervisors, scheduled bootstraps and process command lines. Confirm queues served and real slots rather than assuming source defaults match runtime.

### 1.4 Real import baseline and open blocker

- [x] CSV real-queue 50k developer job a4705bd9-5812-4f3a-938d-db6512272d92 completed with 49,500 imported + 500 invalid, approximately 24m30s.
- [x] XLSX 49,999 developer job bf943a8f-8607-474a-adfa-7d0784c0f912 completed with 34,999 imported + 15,000 invalid, approximately 45m46s from started_at to finished_at.
- [x] Previous Phase 19 real-queue staging experienced short-write and hangs; guarded 500-row multi-VALUES staging and same-transaction actual count verification were implemented and focused test suite passed. Do NOT assume this makes all cancellation and throughput gates closed.
- [ ] Establish reproducible phase timing for admission, queue wait, parsing/staging, validation/duplicate detection, Product and Variant creation, pricing publication, commit, and worker idle overhead. The 24–46 minute figures are whole-job measurements of DIFFERENT source shapes, not controlled format-only comparison.
- [ ] Reconcile and update the main Phase 19.2 plan after the new measurement gates; do not skip earlier unresolved status items.

## 2. Architecture decisions in force NOW

1. **NO PHYSICAL TABLE RENAME IN THIS URGENT TRACK.** Preserve public.products and public.product_variants, ORM names Product and ProductVariant, FK/RLS/migrations, API contracts and Flutter data model.
2. Publish an unambiguous domain glossary: **Product Master / Parent** (products; UI currently calls “family”) vs **Sellable Variant / SKU** (product_variants; visible product). Note that the Product parent owns name/code/description/brand/category — it is NOT an empty join table or unrelated marketing category.
3. Treat “no family selected -> same-name parent” as current authorized behavior, not an assumed accounting error. Audit ambiguity, duplicate-name rules, explicit opt-out, auto-parent creation and user-facing labels. Do not change that workflow without separate owner approval.
4. Preserve durable company/RLS isolation. Add a separate **resource fairness** contract: bounded queues, admission/backpressure, effective scheduling, visibility and bounded worker/database load. Tenant data isolation alone does not imply dedicated CPU/RAM per tenant.
5. Preserve the public-schema atomic business-job enqueue contract for Product Import. Do not move it into worker_queue merely to simplify queues; any queue split must retain same-transaction durability or provide a proven equivalent.
6. No automatic scale-out, shard, microservice migration, schema-wide index dropping, blind VACUUM FULL, blind REINDEX, full-table purge or status rewrites.
7. Prefer Strict Modular Monolith shared **technical** queue policies/contracts across future imports of products, shops, areas, vehicles, etc., while each business module keeps its own validation, RLS and idempotency authority.

## 3. Phase A — Complete dependency/identity audit (NO code/schema change)

- [ ] Produce a dependency inventory for products, product_variants, products FK references and raw SQL, migrations, views, triggers, audit/event payloads, API DTOs, Dashboard and Flutter/offline. Classify whether each reference points to Product master, Variant SKU, or just a user-facing label.
- [ ] Validate that all inventory movements, value/cost layers, sale lines and price entries choose the correct sellable SKU identity, with explicit negative tests against mismatched product_id and cross-company links.
- [ ] Document exact create behavior for explicit family ID, explicit new family name, blank family, duplicate same-name inputs and multi-size product. Confirm if auto-created parent brand/category/description are meaningful or left empty.
- [ ] Inspect 8 company-38 parents without linked variants; classify legitimate empty master vs historical fixture/failed flow, without deleting data.
- [ ] Add a small English/Arabic domain dictionary at a stable repository location and link from ARCHITECTURE.md, Product Import contract and UI-maintainer guidance. Distinguish product master from optional marketing category and from variant/SKU and packaging/UOM.
- [ ] Decide whether the actual source of confusion is documentation/UI labels (preferred safe fix) or a real domain mismatch. Do not start a rename migration based on table names alone.
- [ ] If a physical rename is eventually justified, open an independently approved expand/contract migration proposal, covering aliases, every FK/view/index/trigger/DDL/raw SQL/migration, background worker, existing tenants, Flutter offline compatibility and rollback on a deployment snapshot.

**Gate A:** a cross-platform identity matrix signed off against source, representative business flows pass, no pending undefined Product-vs-Variant authority, no unapproved database rename.

## 4. Phase B — Index forensics and durable growth policy

- [ ] Freeze a read-only t0 inventory after the user's REINDEX: per-index bytes/method/definition/uniqueness/constraint membership, heap/TOAST/index bytes, table tuple count estimates, exact scoped row counts, idx scans and statistics reset timestamp.
- [ ] Derive a safe measurement plan for B-tree density/deleted pages and GIN pending list; use authorized pgstattuple tooling where available, but do not install extensions or obtain superuser privilege without a change review.
- [ ] Gather n_tup_ins/upd/del/HOT ratio, dead tuples, last auto-vacuum/analyze, per-table reloptions, WAL bytes, storage latency and long-running transactions, during **controlled** import workloads.
- [ ] Compare same catalog dataset and **same semantics** at t0 vs after 1k, 5k, 10k and 50k new variants (if gated), including writes per variant and index growth per new variant, and after a normal autovacuum cycle. Do not mistake estimated global stats for exact tenant counts.
- [ ] Inspect production query patterns: table/tenant-safe keyset listing, barcode/SKU lookups, trigram search, name sorting, LIVE Stock and family aggregation. EXPLAIN (ANALYZE, BUFFERS) under FORCE RLS; assert no disallowed sequential plans at representative sizes.
- [ ] Classify each index: needed for PK/FK/UNIQUE, required query-plan index, duplicate/overlapping candidate, or unexplained growth. Read count=0 does not justify UNIQUE removal. Re-check against actual code/plans and stats horizon.
- [ ] Investigate recurrent index bloat by data churn, random identifier distribution, fillfactor/pages, GIN pending list, and the app's update/delete behavior. Evaluate autovacuum thresholds for the high-churn tables; do not copy Product Import row-table tuning blindly to products/variants.
- [ ] If a targeted index change is proven safe: one focused migration with concurrent/online build where appropriate, disk/headroom checks, multi-tenant RLS query-plan baseline, migration rollback and deployment window. Do not repeat REINDEX TABLE as routine symptom masking.
- [ ] Establish growth alarms based on **trend/ratio and saturation**, not arbitrary total-MB numbers alone.

**Gate B:** per-index cause/effect evidence, stable measured growth profile under controlled load, essential constraints retained, representative read/write latencies non-regressing, deployment and rollback runbook recorded.

## 5. Phase C — Worker/queue inventory and the monitoring scheduling defect

- [ ] Audit ALL real worker apps: public product-import vs worker_queue maintenance, notifications and reports; launchers, process supervisors, actual heartbeat/slots, recovery, schedules, DB connection pools and queue table cleanup.
- [ ] Separate metrics for business import jobs, maintenance monitors, retention, periodic schedulers, failed history, retry attempts, and active todo/doing. Status of a queue task must not be conflated with ProductImportJob.status.
- [ ] Reproduce the 867-monitor backlog and determine scheduler catch-up, company selection, child deferral burst size, duration, failure class and queue wait ordering. Inspect actual 1,147 company rows for active status and whether monitoring is useful for companies without active imports/sources.
- [ ] Determine why 9,176 capacity monitors failed; collect exception-code distributions and correlation ids. Fail closed on monitor errors; do not automatically discard failed jobs or suppress genuine alerts.
- [ ] Verify current read-before-defer/lock race with two scheduler processes. Distinguish execution lock from **atomic queueing lock** and from per-tenant worker capacity.
- [ ] Decide an on-demand/active-source monitor plus bounded global summary strategy, or an equally measured alternative, that still detects overdue jobs and source/storage risks for every affected company.
- [ ] Design atomic deduplication of periodic child jobs, maximum queued child work and a scheduler time budget. Procrastinate queueing_lock is a candidate requiring correctness tests and safe handling of AlreadyEnqueued, not an unverified copy-paste.
- [ ] Keep monitoring/recovery runnable when product-import queue is saturated, without weakening the atomic product-import enqueue or skipping necessary cleanup. Establish dedicated monitoring/maintenance capacity under a verified app/transaction contract.
- [ ] Bound public and worker_queue history/events separately, with audit retention approval, idempotency safety, failure forensics, rollback and safe batching. delete_jobs=never with no verified retention policy is NOT an indefinite scale plan.
- [ ] Verify no orphaned monitor alerts, stuck entries, wrong RLS context or missed tenant due to pagination/inactive status.

**Gate C:** 100/1000+ tenant fixture scheduling shows no unbounded per-tenant periodic backlog or duplicate concurrent monitor, stable real import queue wait despite monitor spikes, old failure explanation recorded, retention/recovery pass.

## 6. Phase D — End-to-end import latency root cause (do before tuning knobs)

- [ ] Add bounded per-stage counters/timestamps and per-100-row execution batch timings behind controlled observability, avoiding per-row log spam or secrets.
- [ ] Measure SELECT/INSERT/UPDATE counts and duration by Product/Variant family resolve, UOM, barcode conflict detection, tracking defaults, idempotency, audit, stock projection, pricing book/publication and commit.
- [ ] Specifically inspect create_product_structures / _resolve_family and publish_prices for N+1 and repeated advisory-lock/SQL roundtrips; keep business authority intact.
- [ ] Capture DB waits/locks via pg_stat_activity and pg_locks, EXPLAIN of hot queries, CPU, worker RSS, network/driver, pool wait, WAL and index growth. Validate Windows SelectorEventLoop vs production Unix runtime rather than assuming identical behavior.
- [ ] Benchmark controlled 100/1000/5000/10000 then 50000-row REAL QUEUE imports with unique company-scoped fixtures, controlled good/invalid distribution and safe cancel/timeout. Same semantic XLSX vs CSV comparison; do not infer input-format overhead from different validation failure rates.
- [ ] Preserve exact source row numbering, imported+invalid+failed=staged, one distinct variant per successful source row, no duplicate after timeout/retry, valid price/barcode links and no partial product from rollback.
- [ ] Identify and fix verified bottlenecks one at a time through owning domain/service boundaries. Changes that alter pricing/costing/stock or product-family semantics need separate owner approval.
- [ ] Re-run product-import Phase 19 real HTTP auth, worker recovery, cancellation, RLS/FK and persistence gates. Update PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md with verified new evidence; do not assume prior isolated 50k staging means full release gate pass.

**Gate D:** reproducible before/after phase trace for identical workloads, durable count/linkage invariants, measured p50/p95 and hardware-specific budget determined FROM baseline, no regressions in existing tests.

## 7. Phase E — Multi-tenant resource fairness / future imports

- [ ] Define resource classes (interactive, small import, bulk import, scheduled monitor, report, maintenance/recovery), admissions, priorities and reserved/weighted capacity. Do not let priority permanently starve old or small-company jobs.
- [ ] Enforce per-company maximum active import(s), per-company queued backlog and source-byte limits with durable admission / tenant-safe idempotency. Re-check actor authority before execution.
- [ ] Evaluate bounded jobs/chunks and yield points: a 50k job must not monopolize a single worker for its entire duration if fair interleaving is required. Any claim of preemption must match Procrastinate's actual whole-job scheduling; design safely resumable checkpoints if needed.
- [ ] Define queue boundaries by workload class and technical budget, keeping each domain's task handler and atomic submission authority: future shops/areas/vehicles imports may have separate queues/registrations, not all forced into product-import.
- [ ] Global DB connection/WAL/I/O guardrails: caps on concurrency/connection pools and bounded transaction duration, measured under multiple companies; PostgreSQL is still physically shared, so resource fairness is **bounded interference**, not absolute performance isolation.
- [ ] Simulate 2, 10 and 100 tenants with mixed small and large jobs plus periodic monitoring/report traffic, compare queue wait p50/p95, throughput, starvation, retry/cancel and CPU/RAM/DB headroom.
- [ ] Decide hardware-aware worker count ONLY AFTER admission and measurements; never scale concurrency blindly as a first fix. Any new infrastructure/service split needs independent cost/benefit evidence and explicit approval.
- [ ] Document per-queue and per-tenant health, dead-letter/recovery, backpressure errors, operator controls, and sane failure-domain separation.

**Gate E:** reproducible fairness tests show bounded waiting for small jobs under large-job load, no starvation, tenant leakage, duplicate delivery or DB overload, with documented tested worker/resource sizing.

## 8. Phase F — Operator cancellation and Dashboard UX

- [ ] Wire a visible, localized, keyboard-accessible cancellation control for QUEUED/PARSING/VALIDATING/IMPORTING/RETRYING to the existing authenticated POST /simple-products/imports/{job_id}/cancel endpoint. Do not mistake UI reset/dismiss for durable cancel.
- [ ] Require deliberate user confirmation; show durable pending/current-batch finish and eventual CANCELLED state; display number of rows already committed vs not imported where authoritative.
- [ ] Handle API disconnect/unknown result with the same job ID and idempotent status reconciliation; unauthorized actor and cross-tenant ID fail closed.
- [ ] Test waiting on job row lock, stage hang/statement timeout, restart after forced worker termination, stale queue todo delivery encountering CANCELLED, and consistency of immutable SourceStore cleanup.
- [ ] Publish a **development-only** operational runbook: list real process IDs/commands, soft Ctrl+C, targeted Stop-Process -Force, official per-company job cancellation; prohibit bulk kill of python.exe and manual SQL state mutation.
- [ ] Preserve operational audit and correlation IDs; verify keyboard and RTL/LTR, and no misleading “success” for job cancelled after partial commit.

**Gate F:** all active stages cancellable without duplicate/partial inconsistent writes; visible user state correct, backend authorization tested; force-stop and restart recovery proven.

## 9. Phase G — Cross-platform / production release

- [ ] Evaluate current worker scripts and actual production process supervisor independently (Win development, Unix/container recommended for production); ownership of restart, periodics and lease recovery must be explicit.
- [ ] Full product-import backend suites and independent architecture/perf gates; relevant inventory/product/pricing/workers/RLS regressions; dashboard ESLint/TS/Vite build; Flutter contract/offline sync tests when affected.
- [ ] Dedicated multi-tenant negative tests: Product master/variant FK authority, same-code different-company uniqueness, cross-tenant queue args, shared report caches, concurrent import, cancellation, recovery.
- [ ] Test migrations on an isolated snapshot, compare schema/constraint counts and rollback, verify index strategy under real data shapes; no in-place rename or unbounded index rebuild.
- [ ] Document p50/p95 latency, maximum safe file size, timeouts and failed-row semantics per tested hardware, with explicit product-import versus operational-worker health.
- [ ] End-of-phase evidence table with measured before/after, exact test command/output, commit SHA, modified paths, rollback, unresolved risks and signed release gate.
- [ ] Merge only when the existing branch's Phase 19 work and all urgent gates required for V1 have passed, after owner's explicit merge direction.

**Gate G:** no open release blocker for covered V1 workflows, measured operations + recovery and end-to-end 50k run are reproducible; clean documented handoff.

## 10. Direct developer commands (PowerShell)

**List active Procrastinate worker processes (all queue kinds, read-only):**

    Get-CimInstance Win32_Process |
      Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'procrastinate' -and $_.CommandLine -match 'worker' } |
      Select-Object ProcessId, ParentProcessId, CommandLine

**Force-stop one SELECTED worker PID only, after verifying its CommandLine:**

    Stop-Process -Id 12345 -Force

**Force-stop every discovered PRODUCT-IMPORT Python worker only, never all Python processes:**

    Get-CimInstance Win32_Process |
      Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'procrastinate' -and $_.CommandLine -match 'worker' -and $_.CommandLine -match 'product-import' } |
      ForEach-Object { Stop-Process -Id $_.ProcessId -Force }

**Cancel ONE business import safely through the application's service (developer administrator only):**

    cd C:\Users\admin\Desktop\wanasah\wa_backend
    .\venv\Scripts\python.exe -c "import asyncio,selectors;from uuid import UUID;from domains.simple_products.imports.application.cancellation_service import cancel_import_job;print(asyncio.run(cancel_import_job(company_id=38,job_id=UUID('REPLACE-WITH-JOB-UUID')),loop_factory=lambda:asyncio.SelectorEventLoop(selectors.SelectSelector())))"

Never confuse force-stopping worker process with cancelling the durable business job. Stopping worker alone permits delivery/retry on restart. In production use authenticated HTTP cancellation and audited supervision, not a user-controlled DB CLI.

**Queue distinction, read-only in PostgreSQL:**

    SELECT task_name, status, count(*) FROM public.procrastinate_jobs GROUP BY task_name, status ORDER BY task_name,status;
    SELECT queue_name, status, count(*) FROM worker_queue.procrastinate_jobs GROUP BY queue_name,status ORDER BY queue_name,status;

**Catalog cardinality for currently authorized tenant:**

    SELECT count(*) FROM products WHERE company_id = <authorized_company_id>;
    SELECT count(*) FROM product_variants WHERE company_id = <authorized_company_id>;

Use authenticated tenant DB context; NEVER remove RLS or silently use superuser to show other tenants.

## 11. References

Internal:
- wa_backend/models.py — Product and ProductVariant definitions.
- wa_backend/domains/simple_products/service.py — Product parent resolution; variant creation; pricing.
- wa_backend/domains/simple_products/imports/application/execution_service.py — bounded import execution and idempotency.
- wa_backend/domains/simple_products/imports/application/cancellation_service.py — official cancel.
- wa_backend/domains/simple_products/imports/infrastructure/queue.py, capacity_queue.py, retention_queue.py, runtime_monitor.py.
- wa_backend/workers/app.py, wa_backend/workers/README.md, ops/development/*worker.ps1.
- PRODUCT_IMPORT_PRODUCTION_HARDENING_PLAN.md — existing Phase 19 release obligations.

External (for technical implementation review; not replacements for live measurement):
- PostgreSQL 16 REINDEX and locking: https://www.postgresql.org/docs/16/sql-reindex.html
- PostgreSQL 16 index/tuple instrumentation: https://www.postgresql.org/docs/16/pgstattuple.html
- PostgreSQL 16 monitoring statistics: https://www.postgresql.org/docs/16/monitoring-stats.html
- Procrastinate atomic queueing locks: https://procrastinate.readthedocs.io/en/main/howto/advanced/queueing_locks.html
- Procrastinate worker concurrency and scheduling: https://procrastinate.readthedocs.io/en/main/howto/production/concurrency.html

## 12. Live checklist summary

- [x] Read the current architecture constitution, model semantics, import code and worker routing.
- [x] Capture initial size-before/after REINDEX and tenant-scoped cardinality evidence.
- [x] Find monitoring backlog and worker queue architecture mismatch.
- [x] Cancel the duplicate queued XLSX job safely.
- [ ] A — Catalog contract and dependency audit.
- [ ] B — Physical index root cause and growth policy.
- [ ] C — Monitor scheduling/backlog/worker topology fix.
- [ ] D — Full end-to-end import timing and performance fixes.
- [ ] E — Production-grade multi-tenant resource fairness.
- [ ] F — Cancel/recovery and user-facing control.
- [ ] G — Cross-platform V1 release gate.

**Current next action:** Phase A plus diagnostic-only baseline for B/C/D. Do not rename tables, delete indexes, bulk-kill workers or raise concurrency before the corresponding evidence gate.
