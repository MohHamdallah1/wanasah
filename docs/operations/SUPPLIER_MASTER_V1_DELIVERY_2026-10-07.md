# Supplier Master V1 — implementation and acceptance

Baseline: `976978d8313a902ebeb577073078dd4d6d8666b0`, fetched from `origin/main` before implementation.
Final integration base: latest `main` at `96fc4f18131dd2450d80125752c285f4149d515f`; the approved Stage 4 / legacy FIFO fixes from PR #144 are preserved.
Branch: `feat/suppliers-v1-20261007`. Scope: the frozen supplier inbound workflow and the already-approved whole-product quality return workflow. No expansion into Purchasing/AP.

## Ownership and file boundaries

- `wa_backend/domains/suppliers/`: company-wide identity, lifecycle, public selection contract, bounded repository, durable application commands, neutral errors and DTOs.
- `wa_backend/api/suppliers.py`: HTTP adaptation only; the existing permission catalog, idempotency records and audit/outbox remain canonical.
- `wa_backend/domains/inventory_supplier_evidence.py`: Inventory-owned immutable snapshots referencing posted movements. No mutable Supplier copy and no second stock/cost authority.
- `dashboard/src/features/suppliers/`: shared runtime contract, bounded/debounced search and a public keyboard-operable selector.
- `dashboard/src/pages/suppliers/`: page composition, table, editor and mutation/recovery owner. Inventory imports the public selector, never Supplier page internals.
- Quality and Inbound own their separate durable commands/drafts. The route entry and navigation are thin integrations.

## Data, migration and authorization

Revision: `b7f2a9c4d681`, parent `b8e4d7a91c52`, one Alembic head.

Supplier fields: `id`, `company_id`, required `name`, optional company-unique uppercase `code`, `contact_person`, `phone`, `email`, `address`, `notes`, `is_active`, optimistic `version`, timestamps and tenant-guarded creator/editor references. Names are not unique. No delete operation exists.

Company-only capabilities: `supplier.read` and `supplier.manage`, registered in the existing permissions authority and database catalog. Read does not confer management. Location grants do not confer these company-only capabilities. Existing exact-location inbound and whole-product Inventory permissions remain required, including on quality replay.

The migration adds Supplier Master and `inventory_supplier_evidence` only. It does not rewrite/backfill existing movements or fabricate identities. Evidence uses composite tenant FKs, immutable name/code, root operation UUID, FORCE RLS and restricted runtime grants. A database trigger blocks evidence updates/deletes even for privileged callers. Supplier searches use company/active/id indexes and a stored human-field search expression with a trigram GIN index; list reads use bounded keyset pagination, newest first, with filter/tenant-bound cursors.

Downgrade fails before dropping anything if Supplier identity or historical evidence exists. Permission catalog entries are retained. Existing physical constraint names are not passed back through naming conventions; the new constraints have explicit physical names.

## HTTP contracts

- `GET /suppliers?search=...&active=true|false&cursor=...&limit=...`: default 30, maximum 100; omit active for all states. Returns `items`, `next_cursor`, `has_more`. Search is 2–100 characters over name/code/contact/phone/email.
- `GET /suppliers/{id}`: company-scoped read, including inactive historical identities.
- `POST /suppliers`: details plus `request_id`; creates active Supplier.
- `PUT /suppliers/{id}`: supported details, `expected_version`, `request_id`.
- `PATCH /suppliers/{id}/state`: `is_active`, `expected_version`, `request_id` for deactivate/reactivate.

Mutations recheck current permission before durable replay. Request hashes include the target and normalized input; mismatched identity/input fails closed. Commands, Supplier changes, audit and outbox commit together. Errors use stable codes, context, safe reasons and the existing correlation middleware. Unexpected internals remain hidden.

## Business integrations and historical truth

New `POST /warehouse/inbound` commands require `supplier_id` after replay reconciliation. Selection verifies current company and active state and holds a shared Supplier row lock through posting. The unified movement/costing engine is unchanged. Each posted movement receives an immutable Supplier reference/name/code snapshot in the same transaction. The existing ledger contract presents that snapshot; legacy inbound remains readable with null Supplier fields. Rename/reactivation/deactivation never rewrites receipts.

New whole-product `RETURN_TO_VENDOR` commands select `supplier_id`, derive the recipient name server-side and snapshot it on terminal movement evidence and canonical audit. The operator chooses the one receiving Supplier; origins are neither inferred nor split. Current stock discovery, physical batches, valuation semantics, preview refresh/signature protection, exact-location checks and all-or-nothing Inventory authority remain intact. No batch/warehouse/handover/evidence selector/input is added.

Pre-Supplier request payloads are accepted only to replay an already-committed matching operation. They cannot create new receipts/manual returns: those fail with `SUPPLIER_REQUIRED` before posting. Legacy request hashes and frontend stored operation IDs are preserved during recovery. Manual historical recipient audit remains stored/readable, without guessed master references.

Frontend commands preserve full input and request identity across lost responses/refresh. Retry is explicit, with no silent browser mutation queue. New inputs cannot replace a pending operation. Unsubmitted Supplier, Inbound and Quality drafts are scoped to company/actor (and applicable product/location). Deterministic rejection after an idempotency lookup may release a failed command; ambiguous transport/5xx, malformed results and revoked-access replay remain pending.

This feature closes the remaining ledger `InventoryLocation` import blocker. Quality staging timestamps/status eligibility and legacy FIFO closeout are supplied by the approved latest main and preserved without duplication or alteration. The generic stock-status transition matrix, stock allocation, costing rules and approved quality semantics are preserved.

## Verification

- [x] Real PostgreSQL 16 Supplier acceptance: 12 tests, non-superuser runtime, actual permissions/FORCE RLS, create/update/state, cross-tenant direct APIs, inactive selection rejection, replay/mismatch, immutable inbound/return evidence, legacy reads/replay, migration preservation/downgrade guard, multi-supplier stock returned to one chosen recipient, all-or-nothing warehouse denial, revoked-location replay, unchanged disposal outcome.
- [x] Supplier architecture and affected Quality/Stage 4/legacy FIFO regression tests: 22 tests on latest main, plus 12 real PostgreSQL Supplier tests (34 backend tests overall). Inventory imports only public Supplier contracts; Supplier persistence/application are transport-independent; Products have no global Supplier property.
- [x] Existing focused frontend quality/boundary/preview tests: 22 tests.
- [x] Supplier frontend acceptance: 15 tests (contracts, Arabic/English, important states, read/manage visibility, active selector, semantic form/focus, durable retry, legacy recovery, scoped unsubmitted Quality drafts and preservation of 5xx ambiguity even with a known business-rejection code).
- [x] Production Vite build passed in an isolated environment installed once from the repository lockfile.
- [x] Affected ESLint: zero errors; one existing Quality memo dependency warning remains.
- [x] Full TypeScript diagnostics compared with unmodified baseline using the same dependencies: baseline 30 errors, current 29, zero introduced. The affected Inbound type-import blocker was corrected; unrelated baseline failures remain. **Full repository TypeScript is not claimed green.**
- [x] Exact-source frontend acceptance and affected lint pass. Existing catalog boundary/Quality/preview acceptance adds 22 tests to the 15 Supplier tests, for 37 focused frontend tests overall. Production build also passes independently.
- Independent exact-head GitHub Actions acceptance is the final delivery gate; the live immutable results are available in [PR #145 checks](https://github.com/MohHamdallah1/wanasah/pull/145/checks). Integration run [37608863129](https://github.com/MohHamdallah1/wanasah/actions/runs/37608863129) passed all stages; the final 5xx guard follows the same gate.
- [ ] Owner/reviewer approval and production deployment.

The DB gate upgrades an ORM-created schema matching main through the actual new Alembic revision; it preserves representative legacy rows. This is not a production database restore or a rerun of every historical Alembic migration. Authentication is deliberately overridden in the ASGI acceptance app; real SQL/RLS, API validation, correlation errors, permissions, movement/costing and audit execute. It is not a new login/session qualification or a claim of full-platform isolation.

The six existing environment-specific C2 receipt/customer-return gates have a shared synthetic Supplier identity fixture and pass that identity in new receipt requests. Their distinct external opt-ins were not executed or marked passed by this task; the new isolated acceptance gate covers the Supplier integration directly.

Run the DB gate only with `WANASAH_SUPPLIER_DB_GATE=1` and an explicitly isolated database named `supplier_master_gate`, with separate migration/runtime roles and the normal application configuration. `.github/workflows/suppliers-v1.yml` provides an independent PostgreSQL/locked-dependency gate. Do not point fixtures at customer data.

## Deferred capabilities

Purchase orders, invoices, AP balances/payments, credit/refund/replacement settlements, supplier tax settlement, approvals, terms/contracts, performance analytics, portal and procurement/EDI integrations remain outside this V1 work. No Product-global supplier or per-batch origin routing was introduced.

## Exact changed files

The final commit manifest follows below; local runtime artifacts are excluded. Local `main`, `RUN.txt` and the owner's untracked handoff were not changed.

- .github/workflows/suppliers-v1.yml
- V1_COMPLETION_AUDIT.md
- dashboard/scripts/check-types-against-baseline.mjs
- dashboard/src/App.tsx
- dashboard/src/components/operations/OperationsSidebar.tsx
- dashboard/src/features/inventory/quality/WholeProductQualityActionsPanel.tsx
- dashboard/src/features/inventory/quality/useProductQualityCommands.ts
- dashboard/src/features/inventory/quality/useWholeProductQualityDraft.ts
- dashboard/src/features/inventory/quality/wholeProductQualityResolveContract.ts
- dashboard/src/features/suppliers/SupplierSelector.tsx
- dashboard/src/features/suppliers/contracts.ts
- dashboard/src/features/suppliers/useSupplierSearch.ts
- dashboard/src/i18n/resources.ts
- dashboard/src/i18n/suppliers.ts
- dashboard/src/pages/inventory/Tab2Inbound.tsx
- dashboard/src/pages/inventory/Tab4Ledger.tsx
- dashboard/src/pages/inventory/TabInventoryAccess.tsx
- dashboard/src/pages/inventory/inbound/contracts.ts
- dashboard/src/pages/inventory/inbound/useInboundPosting.ts
- dashboard/src/pages/inventory/ledger/contracts.ts
- dashboard/src/pages/suppliers/SupplierEditor.tsx
- dashboard/src/pages/suppliers/SupplierTable.tsx
- dashboard/src/pages/suppliers/SuppliersPage.tsx
- dashboard/src/pages/suppliers/useSupplierCommands.ts
- dashboard/src/test/suppliers-v1.test.tsx
- docs/operations/SUPPLIER_MASTER_V1_DELIVERY_2026-10-07.md
- wa_backend/alembic/env.py
- wa_backend/alembic/versions/b7f2a9c4d681_supplier_master_v1.py
- wa_backend/api/suppliers.py
- wa_backend/api/warehouse/_shared.py
- wa_backend/api/warehouse/inbound.py
- wa_backend/api/warehouse/ledger.py
- wa_backend/api/warehouse/whole_product_quality.py
- wa_backend/domains/inventory_supplier_evidence.py
- wa_backend/domains/inventory_terminal_vendor.py
- wa_backend/domains/suppliers/__init__.py
- wa_backend/domains/suppliers/application.py
- wa_backend/domains/suppliers/contracts.py
- wa_backend/domains/suppliers/errors.py
- wa_backend/domains/suppliers/models.py
- wa_backend/domains/suppliers/public.py
- wa_backend/domains/suppliers/repository.py
- wa_backend/inventory_access.py
- wa_backend/main.py
- wa_backend/schemas.py
- wa_backend/tests/supplier_fixtures.py
- wa_backend/tests/test_committed_costed_inbound_race_c2_isolated.py
- wa_backend/tests/test_costed_driver_customer_return_c2_db.py
- wa_backend/tests/test_costed_inbound_asgi_http_c2_db.py
- wa_backend/tests/test_supplier_master_db.py
- wa_backend/tests/test_supplier_module_boundaries.py
- wa_backend/tests/test_warehouse_costed_inbound_c2_db.py
- wa_backend/tests/test_warehouse_inbound_concurrent_recovery_c2_db.py
- wa_backend/tests/test_warehouse_inbound_requires_cost_policy_c2_db.py
