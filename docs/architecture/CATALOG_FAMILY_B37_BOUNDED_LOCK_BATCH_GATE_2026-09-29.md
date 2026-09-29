# B3.7 — bounded family-name advisory locks, tenant prefetch, and durable race validation

**Checkpoint:** 2026-09-29. **Branch:** `hardening/catalog-index-worker-fairness`. **Scope:** `wa_backend/domains/simple_products/service.py`. **Result:** B3.7 scoped correctness/performance gate **PASS**; actual XLSX/Procrastinate full-import and Phase B durable active-catalog bloat correction **NOT YET PASS**. No changes to `main`, production source indexes, active PostgreSQL extension/reloptions, pricing semantics, stock or COGS.

## Why bulk UPSERT-by-name is not the authorized fix

`products` is the product-master/family table. Its schema has no `UNIQUE(company_id, lower(name))`: `family_mode="none"` must create an independent master even with an equal name; `family_mode="new"` rejects an existing equal name; omitted mode/legacy name resolves a single existing master, but duplicate same-name masters must raise ambiguity. A blind `ON CONFLICT(name) DO NOTHING` is both unsupported by current indexes and would change these business contracts. `ON CONFLICT` without a relevant unique arbiter does **not** guarantee one master per normalized name. No name uniqueness migration is approved.

The preexisting B3.7 code had already batched the RLS-aware matching `SELECT` for all distinct normalized names in a product batch. It still issued a separate `SELECT pg_advisory_xact_lock(company_id,hashtext(lower(name)))` for each distinct name — 1,000 remote statements/1,000 distinct names over 10×100 batches. `SELECT .. FOR UPDATE` is **not** the current code path. Logical advisory-lock acquisitions are not inherently deadlocks; but roundtrip amplification was real, and acquiring overlapping sets in contradictory order is a deadlock risk.

## Actual implemented B3.7 change

- Added `_lock_distinct_family_names` with a **single recursive SQL statement per bounded batch**. It consumes an explicitly sorted, unique lowercase name array, acquires the SAME old company/name advisory lock at each recursive step, and forces materialization of acquired lock tokens through `count(lock_token)`. Every step depends on its predecessor; an unordered set-based function call with an arbitrary optimizer-dependent target-list evaluation order is not used.
- Preserved `_family_name_lock` and its namespace for independent one-name operations; both paths coordinate on the same advisory locks. Advisory locks are **transaction-scoped**, and the caller commits/rolls back under the existing workflow.
- Preserved the existing one-query RLS-aware name prefetch, up-to-two matches per normalized name, per-transaction `_BatchFamilyLookup`, `remember()` of newly created same-transaction parents, and the exact `none/new/existing/legacy` row error contracts. Did not add a unique name constraint or silently upsert an explicit-new family.
- The recursion still acquires **one logical lock per distinct family name**; it reduces database **roundtrips/SQL statements**, not the number of internal PostgreSQL lock acquisitions, and it does not promise immunity from all deadlocks involving other transactional resources. No table-level lock or removal of integrity constraints.
- Explicit `family_id` lookups are still per row on the older path; they are uncommon in the measured Excel import mapping, which supplies a family name. A separate tenant-ID cache could change timing of an observed parent deletion; do not silently claim this unmeasured path is optimized.

## Observed database and performance evidence

Real synthetic tenant-2 RLS tests `wa_backend/tests/test_catalog_family_batch_b37_db.py`: **10/10 PASS** on the real developer PostgreSQL with per-test outer ROLLBACK (previously 8 tests, now two additional sorted/duplicate-order guards). Verified 50 advisory locks held after **one** batch-lock call, 100 reverse-ordered names normalized to a sorted list, repeated family reuse, explicit new conflict, independent same-name `none` parent masters and subsequent ambiguity, explicit-family-ID and cross-tenant RLS authority. None of these tests requires physical customer writes.

The disposable PostgreSQL16 full-index core benchmark uses **10 committed batches × 100 actual SKU creations**, the normal Pricing publication domain (2 price entries per SKU), and the current live audit/outbox/UOM tracking paths. Two workload shapes were measured:

| Scenario | Prior B3.6 / per-SKU family lock-read | B3.7 current | Measured change |
|---|---:|---:|---|
| 1,000 unique product/family names — SQL statements | 8,355 | **6,375** | **−1,980 SQL statements** |
| 1,000 unique names — wall time | 18.935 s (earlier separate run) | **13.011 s** (new run) | non-paired measurement; do NOT promise 31% speed gain |
| 1,000 rows, **50 recurring family names** — SQL statements (paired independent same-cluster clones) | 7,406 | **5,426** | **−1,980 SQL statements** |
| 1,000 rows, 50 families — wall time (paired independent same-cluster clones) | **12.029 s** | **12.342 s** | **slightly slower** in this pair: SQL reduction ≠ guaranteed wall-time reduction |
| Same recurring-family A/B — parent masters, variants | **50 / 1,000** | **50 / 1,000** | invariant holds |

The 1,000-unique B3.7 result has **273 SELECT / 5,023 INSERT / 1,049 UPDATE / 30 WITH** commands, **6,375 total**. The earlier 8,355 used **2,263 SELECT / 5,023 INSERT / 1,049 UPDATE / 20 WITH**. The recursive lock query replaces ten groups of individual lock SQL, and the existing batched name lookup replaces per-row reads. The first and second workloads differ by the number of actual parent inserts; neither is the entire XLSX/queue/import-validation pipeline. Index and WAL totals are recorded by the isolated run but were not used to authorize production maintenance.

Durable independent-transaction race gate `wa_backend/scripts/b37_family_race_disposable.py` **PASS** inside the disposable-only PG16 cluster: (1) two committed workers reuse one shared name without duplicate parent; (2) workers request the same two names in opposite orders, both commit and resolve the same IDs without the tested deadlock; (3) two workers attempt explicit new on the same name, second receives the expected `SIMPLE_PRODUCT_FAMILY_NAME_CONFLICT`. Lock and statement timeouts are bounded. This establishes the **tested** concurrency scenarios, not mathematical deadlock-freedom across all application workflows.

Broader checked regressions for product import, A2 family semantics, B3 cached UOM/tracking, bounded pricing, explicit FIFO/moving-average policy, actual inbound, sale, refund, transaction races and history: **223/223 backend PASS, 0 failures/errors/skips**. Stage 74 costing static contract: **48/48 PASS**.

## Next release steps (not covered by B3.7)

- Full HTTP/XLSX/Procrastinate staging and execution 1k→5k→10k→50k, measuring parser/staging/queue waiting/worker batches and source-sized tenant DB latency with identical valid/invalid distribution. No 50k-in-under-one-minute SLA has been measured or promised.
- Actual sized ~217k-index rows and insert/update/delete/VACUUM cycles, per-index bloat/density and safe autovacuum policy after real-load measurements. The old shadow-table REINDEX result is NOT a production REINDEX recommendation.
- Potential further structural set-based inserts must preserve SKU identities, DRAFT→ACTIVE lineage, immutable audit/outbox, duplicate handling, company RLS/FKs and published prices. `session.execute(insert(...))` is a candidate requiring focused rollback/concurrency tests, not an unconditional replacement of ORM `add()`.
- Do not merge until owner-agreed stabilization, reviewing the seven existing original-worktree changes and all required release gates.

**Safety:** `pgstattuple` activated only in disposable benchmark database. No source DB schema change, live index removal, REINDEX/VACUUM, worker restart, trigger disable, or original `main`-checkout edit occurred in B3.7.
