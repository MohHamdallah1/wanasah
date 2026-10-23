# Wanasah project instructions

## Version 1 scope guard — mandatory before implementation

Read `V1_SCOPE_FREEZE.md` before implementing any feature, workflow expansion, optimization, redesign, or refactor that could affect product scope. It is the canonical authority for **what ships in V1 and where V1 stops**. `ARCHITECTURE.md` remains authoritative for **how the platform is built**, and `VERSION_2_FUTURE_FEATURES.md` remains the canonical deferred-capability backlog.

For every task, identify the concrete frozen V1 workflow it unblocks. If the task is outside V1, **stop before implementation and tell the owner**. Ordinary execution wording such as "نفذ", "اعملها", "كمل", urgency, repetition, or ease of implementation does not authorize V1 scope expansion. V1 scope may expand only after explicit owner approval to change the frozen V1 scope; update `V1_SCOPE_FREEZE.md` before implementing the newly approved capability.

Security, tenant/location isolation, data integrity, financial/inventory truth, and demonstrated breakage of an already-frozen required workflow remain valid V1 blockers. Do not use the scope guard to defer correctness or safety defects.

Read `ARCHITECTURE.md`, `.rules`, and `.cursor/rules/business-workflow-protection.mdc` before making
changes. `ARCHITECTURE.md` is the canonical architecture constitution for the entire repository and all future modules.
The workflow-protection rule applies to the entire repository and all future tasks.
No business workflow change is authorized without explicit prior discussion and approval from the project owner.

## Backend-owned complexity / minimum operator input — mandatory

- If Wanasah can safely derive or reconcile a fact from authoritative backend evidence, the operator must not be asked to supply the technical answer.
- Ask only for the smallest human-readable business fact required to resolve genuine ambiguity; deterministic cases resolve automatically and ambiguous unsafe cases fail closed rather than guess.
- Never expose database IDs, FEFO choices, internal Batch allocation, supplier-resolution mechanics, costing choices, idempotency/replay details, lock ordering, or reconciliation math as ordinary user work.
- Keep Dashboard and Flutter simple by putting complexity in canonical backend/domain authorities, never by duplicating or weakening inventory, financial, audit, tenant, location, or permission truth in a client.
- The full permanent rule is in `ARCHITECTURE.md` and applies to all future agents, pages, mobile workflows, imports, automation, and integrations.
- Before changing quality destinations, quarantine, damaged goods, disposal, vendor return, Vehicle→Warehouse reconciliation handoff, or related financial closure, read `INVENTORY_DAMAGED_GOODS_RETURNS_AND_REPRESENTATIVE_SETTLEMENT_PLAN.md` and preserve its execution order and closed-loop invariants.

## Canonical identity and authorization — mandatory

**Canonical cutover is DONE, not a new task:** `Driver.is_admin` was removed from the current ORM and retired by migration `f2c7a9d4e611`. Use only Canonical Identity + persisted Capability AND Scope Authorization. Owner = protected Backoffice/Dashboard; Backoffice employees = Dashboard roles/warehouse scopes; FieldRepresentative = Flutter/FIELD-only capabilities AND own WorkSession/route/visit/vehicle assignments; companies/channels must remain isolated. The seven FIELD V1 schema/grant/permission decisions were **explicitly owner-approved on 2026-10-23**, detailed in `ARCHITECTURE.md` §12 and `FLUTTER_V1_END_TO_END_CLOSURE_PLAN.md` §6.4. New `field_representative_roles` is only a canonical FIELD assignment under the existing shared Role/Permission catalog, never a second authorization system and never an excuse to modify unrelated Dashboard employee work. Guard against `DUAL_SPLIT` leakage, forbidden capability assignment **or later role edits**, revoked grants, wrong operational scope and accidental backfill lockout. User/company login stays tenant-aware by company code. Backend implementation/tests remain OPEN; the old flag migration must not be redone. Add the global source CI guard after zero-runtime-authority verification; preserve historical migrations/tests.


- `CompanyPrincipal` is the company credential/authentication root. Initial company principal types are `BACKOFFICE` and `FIELD_REPRESENTATIVE`; principal type classifies identity/access channel and is never authorization authority.
- `BackofficeUser` and `FieldRepresentative` are separate profiles with independent IDs. `CompanyPrincipal.id`, profile IDs, and legacy `Driver.id` must never be assumed equal or used as aliases.
- `CompanyOwner` is explicit protected Backoffice-linked authority, not a role name or generic admin boolean. Platform administration is a separate security realm.
- Backend authorization is `authenticated principal + access channel + capability + applicable scope -> decision`. Roles are bundles only; role names and JWT role/capability claims are never authority. Owner/full capability never bypasses tenant, object, location, structural, or business invariants.
- `Driver.is_admin` is a deprecated migration artifact. New or modified Runtime code must never use it for authentication, authorization, Owner detection, Backoffice/Field classification, representative selection, tenant identity, or scope decisions. Do not replace it with `is_superuser`, `is_manager`, `is_owner`, or another generic persona boolean used as business authority.
- A domain-specific boolean is allowed only when it represents real domain state and does not replace capability/scope authorization. No new identity, token, API, background, or realtime contract may introduce generic admin-flag authority.
- Legacy `Driver` may exist temporarily only for old FK/operational attribution. Temporary compatibility adapters must not acquire new business semantics and must be removed at final canonical cutover.
- Final identity acceptance requires zero Runtime authority/classification dependence on `is_admin`. Once Runtime reaches zero, add an automated source/architecture CI gate rejecting reintroduction except immutable historical migrations/evidence; do not add that gate prematurely while known legacy Runtime references remain.


## Mandatory internationalization and durable-command rules

Internationalization is a permanent project requirement. For every new frontend file and every frontend file modified from now on:
- use translation keys for user-facing text; do not introduce hardcoded UI copy;
- keep RTL/LTR locale-driven, never hardcoded;
- format numbers, money, dates, and times with locale-aware APIs;
- keep backend/API/UOM/status identifiers language-neutral and translate labels only at presentation boundaries;
- rely on backend error `code` + structured `context`, never localized message text, for program logic;
- require every API failure to expose a correlation/request id in the canonical error contract; dashboard transport must preserve code/context/safe reason/request id, show deterministic 4xx reasons instead of generic failures, and hide unexpected 5xx internals while surfacing the request id;
- localized CSV/XLSX headers must map to canonical language-neutral import fields.

Network failure is also a permanent architecture requirement. Every new or modified mutating workflow must:
- be server-idempotent (or provably state-idempotent);
- preserve one stable operation/request id across timeout, disconnect, and lost-response retries;
- reject reuse of the same id with different input;
- never silently queue administrative mutations in the browser for later execution;
- surface offline/unknown-result state and preserve user drafts where data loss would otherwise occur;
- make asynchronous workers tenant-safe, resumable, bounded, and authorization-aware;
- reconcile or safely replay after an ambiguous network result before creating a duplicate business operation.

Read the full requirements in `.rules` before editing.

## Windows development diagnostics — Wanasah Doctor

- Canonical read-only environment diagnostic: `ops/development/wanasah_doctor.ps1`.
- Run it from the repository root before random reinstall/downgrade/repair work when the Windows development environment, PostgreSQL, backend, Dashboard, Flutter, ports, Alembic, or Product Import startup is suspect.
- The Doctor diagnoses only; it must remain read-only and must not install packages, change configuration, start/stop services, run migrations, seed data, or modify the repository.
- Supporting probe: `wa_backend/scripts/wanasah_doctor_probe.py`; focused tests: `wa_backend/tests/test_wanasah_doctor.py`.
- When runtime topology changes materially (new required service/worker/port/environment variable or a changed startup contract), update the Doctor in the same work so its checks stay aligned with the current project.

## Stage 7.4 inventory costing authority
- Physical batch allocation and financial cost flow are separate authorities. Physical FEFO stays inside the backend and never requires the driver to choose a batch.
- Without per-carton serial/scan or enforced physical segregation, never claim the exact physical carton identity. Batch allocation is deterministic book allocation.
- Supplier receipts require actual purchase unit cost and purchase UOM. Preserve every receipt cost as immutable history; never overwrite an older cost.
- The company selects MOVING_AVERAGE or FIFO before its first costed supplier receipt; the method locks on that first receipt.
- Inventory valuation and official profit have ONE accounting COGS authority; preserve separate real receipt-cost and physical FEFO evidence, but do not create a second official per-batch profit ledger. See `docs/architecture/INVENTORY_COSTING_FINANCIAL_TRUTH_DECISION.md` (implementation gates remain open).
- Financial FIFO consumes acquisition cost layers by product/company acquisition order and must never be coupled to the physical FEFO batch selected for a sale.
- Internal warehouse/vehicle transfers move physical stock only and never create COGS or change company inventory value.
- Sale, sample, reward, exchange, and other external stock exits remain invisible to the driver at batch level but must create financial cost evidence when costing is active. Samples use VISIT_SAMPLE_OUT, not VISIT_ITEM_OUT.
