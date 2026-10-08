# Wanasah Architecture Constitution

## Version 1 product-scope companion

`V1_SCOPE_FREEZE.md` is the canonical authority for **what must ship in Version 1 and where Version 1 stops**. This architecture constitution remains the authority for **how the platform is built and evolves**. A long-term architectural target, existing backend primitive, table, endpoint, page, or partial workflow in this document does not by itself make that capability a V1 requirement. Capabilities explicitly deferred beyond V1 remain governed by `VERSION_2_FUTURE_FEATURES.md`.

Any proposed implementation that would expand V1 must pass the change-control rule in `V1_SCOPE_FREEZE.md` before code changes begin.

## Mandatory delivery workflow — Owner directive (2026-09-30)

> من الآن راح أغيّر أسلوب الشغل: فحص مجمّع، تنفيذ محدد، اختبار قبول شامل، ثم Commit. وإذا فشل الاختبار نعالج السبب المثبت فقط، بدل دوامة اختبارات وإعادة تشغيل غير ضرورية. وما رح أعيد فحوصات D7-L الناجحة لمجرد التكرار.

**Binding across the project:** Diagnose related files and evidence in one consolidated pass; implement only the demonstrated change; run one complete, risk-appropriate acceptance gate and essential affected regressions; fix the proven cause of any failure rather than cycling through unrelated tests; then inspect the diff, update the plan accurately, and commit/push. Prefer GitHub reads and batched remote commands to conserve the monthly MCP quota. Reuse already-passing D7-L evidence unless relevant code or assumptions change. Never compromise tenant isolation, security, data integrity, business semantics, or required release gates to save time. An unavailable staging test remains OPEN rather than being misrepresented as PASS.

**Source-first root-cause requirement:** Before commissioning load tests, repeatedly running suites, or changing code, inspect the complete relevant implementation path and identify the likely concrete mechanism at the exact call site. Check obvious defaults, codecs, query shapes, transaction boundaries, resource costs, lock order, and existing contracts directly in source. Form a falsifiable, narrowly scoped hypothesis; use the smallest **single consolidated acceptance** to confirm the intended correction and preserve business invariants. Do not substitute repeated tests, trial-and-error rewrites, or superficial configuration changes for source analysis. If the source does not prove a cause, state the uncertainty and instrument precisely one needed gap.

## Codex / AI-assisted development safety workflow — Owner directive (2026-10-08)

The following rules are binding whenever Codex Desktop, Codex CLI, another local coding agent, or any AI tool is allowed to inspect or modify the Wanasah repository. They exist to preserve the project, the host machine, and the GitHub source of truth after the 2026-10-08 local data-loss incident. The incident's exact destructive mechanism is not asserted here; the policy is intentionally fail-safe.

### Default Codex safety posture

- Codex must start from a restrictive configuration: `sandbox_mode = "read-only"`, `approval_policy = "on-request"`, and desktop ambient suggestions disabled.
- Ambient/background suggestion workflows must remain disabled unless the owner explicitly re-enables them after reviewing the exact product behavior and risk.
- Read-only is the default posture, not a limitation to work around silently. When a task genuinely requires writes, Codex may request a **task-scoped** write escalation; the owner approves only the specific operation needed for the current isolated worktree.
- Never grant blanket approval for unrestricted filesystem access, profile-wide writes, drive-root writes, recursive cleanup, or commands whose target path is ambiguous.
- If Codex requests access outside the dedicated task worktree, to the user profile root, another drive root, Git internals, credentials, or unrelated project paths, deny the request and stop the task until the need is proven.

### Repository isolation and GitHub authority

- Codex must never work directly on `main`.
- Every Codex task starts from the newest verified `main` in a **clean dedicated branch/worktree** created for that task. The worktree is disposable; the canonical repository and independent backups are not.
- Codex must not push directly to GitHub, merge pull requests, force-push, delete remote branches/tags, rewrite remote history, change repository visibility, change repository rulesets/protection, or alter GitHub administration/security settings.
- GitHub reads are preferred for source inspection. GitHub mutations follow the controlled project workflow: reviewed branch commit -> push through the approved GitHub path -> PR -> required checks/review -> merge -> sync -> delete the disposable task branch/worktree after the stability point.
- The local Codex worktree should have remote push disabled or otherwise prevented whenever practical. Codex is a code-analysis/editing worker, not the authority that publishes or protects the repository.
- `main` must be protected by GitHub branch/ruleset controls that block deletion and force-push and require the approved PR/check flow. Independent off-GitHub backups remain mandatory because branch protection does not replace repository backup.

### Destructive-command and filesystem guards

- `git clean` is forbidden.
- `git reset --hard` is forbidden unless the owner gives an explicit one-time instruction after the exact branch/worktree and loss impact are shown.
- `RUN.txt` must never be reset, stashed, overwritten, cleaned, or deleted as a convenience operation.
- Broad recursive deletion commands such as `Remove-Item -Recurse -Force`, `rm -rf`, `rmdir /s`, or equivalents are forbidden against the user profile, repository parent, drive root, temp roots shared with unrelated work, or any path not proven to be task-owned.
- Deleting or rewriting `.git` internals is forbidden.
- Cleanup must enumerate the exact task-owned paths first and delete only those verified paths. Wildcard or variable-driven cleanup is rejected when the resolved target is not printed and checked first.
- No agent may run destructive disk, partition, filesystem-repair, credential, registry, account, or OS-reset operations as part of ordinary code work.

### Required Codex task flow

1. Read `ARCHITECTURE.md`, `.rules`, `AGENTS.md`, `SKILL.md`, the active plan, and the exact related source before changing code.
2. Verify the newest GitHub `main` commit and confirm an independent backup/mirror exists before a local write session.
3. Create one dedicated branch/worktree from that verified `main`; never reuse a dirty or unrelated worktree.
4. Let Codex analyze in read-only mode first. Require a concrete source-based hypothesis or implementation plan before approving writes.
5. Approve only narrowly scoped writes inside the dedicated worktree. Do not approve unrelated machine/profile access.
6. Run only the focused, risk-appropriate tests/gates required by the change. Analysis identifies the cause; tests prove the fix.
7. Inspect the complete diff and specifically check deletions, renamed files, generated files, migrations, permissions, tenant/location isolation, `RUN.txt`, and any unexpected path outside the intended scope.
8. Commit only the reviewed task diff on the task branch. No direct `main` commit.
9. Publish through the approved GitHub flow, open a PR, satisfy required checks/review, and merge only at the agreed stability point.
10. Sync from the merged `main`, then remove only the verified disposable branch/worktree. Mark the completed plan item `[x]` and record the stability checkpoint.

### Backup rule

Before high-risk refactors or any renewed Codex Desktop usage after a tooling/runtime change, keep at least one independent verified repository mirror outside the working disk. A GitHub-hosted repository alone is not treated as the only copy, and a local worktree on the same physical SSD is not an independent backup.

---

**Status:** CANONICAL ARCHITECTURE DIRECTION  
**Scope:** Entire repository and all future modules  
**Last updated:** 2026-10-08

This document is the architectural constitution of the Wanasah platform. It records the intended long-term direction so future work does not accidentally optimize one feature at the expense of the platform.

The current system is **a monolith that is progressively evolving into a Strict Modular Monolith (Modulith)**. It is intentionally **not** a microservices system today.

The target is better stated as:

> **Monolith operational simplicity and performance + microservice-grade domain boundaries and isolation.**

That is more precise than “Monolith speed + Microservices cleanliness”: we want one-process/in-process efficiency and transactional consistency, while enforcing domain ownership, explicit contracts, and extractable boundaries.

---

## Catalog naming companion (non-normative)

The canonical bilingual Product Master / Sellable Variant / Category / UOM vocabulary for code and API reviews is [CATALOG_IDENTITY_GLOSSARY.md](docs/architecture/CATALOG_IDENTITY_GLOSSARY.md). Use it to avoid confusing `products.id` (master) with `product_variants.id` (sellable SKU); this link does not authorize schema/API renames.

## Catalog / Inventory workflow boundaries (canonical companion)

The approved page/domain ownership and cross-module workflow rules for Products, Inventory, warehouses, batches, quality issues, multi-warehouse operation, and future fleet/driver integration are defined in [CATALOG_INVENTORY_WORKFLOW_BOUNDARIES.md](docs/architecture/CATALOG_INVENTORY_WORKFLOW_BOUNDARIES.md). New work touching these surfaces must preserve those ownership boundaries and must not make one page the mutation authority for another domain.

## Inventory accounting: one official profit/valuation authority

The V1 accounting decision is [INVENTORY_COSTING_FINANCIAL_TRUTH_DECISION.md](docs/architecture/INVENTORY_COSTING_FINANCIAL_TRUTH_DECISION.md): a company chooses one authorized cost formula (FIFO or MOVING_AVERAGE) before its first costed receipt; Inventory Costing is the sole authority for financial inventory value, COGS and accounting profit. Supplier receipt costs and physical FEFO batch evidence are retained independently **without building a second financial profit ledger or official "batch-profit" metric**. Future operational batch contribution analysis is optional and requires independent allocation/variance proof. The previously silent auto-activation of MOVING_AVERAGE has been blocked in C1, with tenant-scoped, actor-attributed explicit selection. Full first-receipt HTTP/retry, cross-domain cost corrections and period-close gates remain OPEN.

## 1. PRIME DIRECTIVE — FAIL-CLOSED ISOLATION

This rule is permanently first and overrides convenience, speed of implementation, UI assumptions, and developer shortcuts.

### 1.1 Tenant / company isolation

**Complete and strict isolation between companies is non-negotiable.**

- No read, write, cache entry, job, event, websocket message, report, search result, import/export, background task, or derived calculation may cross a company boundary.
- Tenant authority comes from authenticated server context. Never trust a client-supplied `company_id` as authority.
- Every tenant-owned persistence path must be tenant-scoped from the beginning.
- PostgreSQL RLS, composite tenant-safe foreign keys, backend authorization, negative isolation tests, and tenant-aware background jobs are defense-in-depth layers; no single layer replaces the others.
- Any missing, ambiguous, or inconsistent tenant context must **fail closed**.
- Platform-administration identity is a separate security boundary from company users.

### 1.2 Location / warehouse isolation

Within a company, operational inventory access must also be **explicitly and correctly scoped by location/warehouse**.

- A company membership never implicitly grants access to every warehouse.
- Warehouse/location reads and mutations must be authorized on the exact affected location(s).
- Cross-location operations must validate both source and destination authority.
- Inventory balances, batches, movements, stocktakes, inbound, outbound, transfers, and operational policies remain location-safe.
- No UI filtering is accepted as a security boundary; the backend is authoritative.

### 1.3 Flexible organizational isolation

Different customers organize staff differently, so the platform must support a **policy-driven scope model**, not one hardcoded organizational assumption.

A company may choose, subject to safe platform constraints, scopes such as:

- company-wide;
- branch;
- warehouse/location;
- route/territory;
- vehicle;
- team;
- user/role combinations.

Employees, drivers, sales representatives, vehicles, and other operational actors must receive only the scope required for their company workflow. Defaults should cover the common case, while the data model remains flexible enough for stricter customer-specific isolation.

Flexibility must never create implicit cross-scope access. Ambiguity fails closed.

---

## 2. CURRENT AND TARGET ARCHITECTURE

### Current state

The backend is one FastAPI application, one primary PostgreSQL database, and one deployable backend. Domain separation already exists in areas such as pricing, offers, sales calculation, simple products, inventory costing, live-stock projection, warehouse modules, and related authorities.

However, the repository is **not yet a Strict Modular Monolith** because shared/global structures still exist, including large central model/service/API files and direct cross-domain imports.

### Target state

Evolve incrementally into a **Strict Modular Monolith (Modulith)**:

- one deployable application by default;
- in-process module calls by default;
- one transactional database boundary where that is still the superior trade-off;
- explicit domain modules;
- strict dependency rules;
- clear data ownership;
- versioned public contracts;
- domain/application events where decoupling is justified;
- architecture gates that fail CI when boundaries are violated.

Do **not** perform a big-bang rewrite.

---

## 3. DOMAIN MODULE CONTRACT

Every significant business capability should progressively become a first-class module, for example:

- identity / tenant administration;
- catalog / products / UOM;
- inventory / warehouse;
- pricing;
- offers / promotions;
- taxation;
- sales;
- dispatch / routing;
- returns;
- costing / valuation;
- reporting;
- future CRM, accounting, purchasing, HR, manufacturing, etc.

A mature module should expose explicit layers such as:

- **domain** — business invariants and pure rules;
- **application** — use cases / commands / orchestration;
- **contracts** — public DTOs, events, errors, and interfaces;
- **infrastructure** — persistence and external integrations;
- **api** — transport adapters only.

Names may vary when a smaller module does not justify all folders, but the boundary rules remain.

---

## 4. STRICT BOUNDARIES

The long-term goal is a real architectural firewall, not a naming convention.

### Rules

- A module must not mutate another module's owned tables or internal state directly.
- A module must not import another module's private/internal implementation.
- Cross-module communication goes through documented public application interfaces/contracts or approved events.
- Shared code is allowed only for genuinely cross-cutting technical concerns; do not create a “shared” dumping ground for business logic.
- Circular domain dependencies are forbidden.
- New work must not deepen legacy coupling.
- When touching legacy coupling, move it toward the target boundary when practical and safe.

### Enforcement

Introduce automated architecture checks (for example import/dependency graph gates or a repository-specific AST/import gate) so illegal dependencies fail CI.

The architecture gate must eventually define:

- allowed dependency directions;
- forbidden cross-module imports;
- module-owned persistence boundaries;
- public contract entry points;
- exceptions that are explicit, documented, and temporary.

---

## 5. DATA OWNERSHIP

Each business concept has one authoritative owner.

Examples:

- Catalog owns product identity/UOM/barcode authority.
- Inventory owns physical stock truth and movement authority.
- Pricing owns price books/publications/resolution.
- Taxation owns tax-rule authority.
- Offers owns promotion authority.
- Sales owns sales-document workflow while consuming other domains through contracts.

A downstream module may store immutable evidence/snapshots required for historical truth, but it must not silently become a second live authority.

Do not duplicate mutable business truth across modules.

---

## 6. DATABASE AND TRANSACTION STRATEGY

A shared PostgreSQL database is acceptable and preferred while it gives us simpler operations, stronger transactions, and lower latency.

A shared database does **not** mean shared ownership.

- Tables must have a declared owning module.
- Cross-module direct writes are progressively prohibited.
- Cross-module reads should move toward public query/application contracts where practical.
- Multi-entity business operations that genuinely require one ACID transaction may remain in-process in the Modulith.
- Never split a transaction into distributed services merely to appear “microservice-like”.

---

## 7. MIGRATIONS, VERSIONED CONTRACTS, AND UPGRADES

From now on, every mature module must have clear ownership of its schema evolution and contracts.

### Migrations

- Alembic is the sole authority for application database creation and schema upgrades. A fresh PostgreSQL database must reach the current schema through `alembic upgrade head`; application startup, development reset scripts, and `Base.metadata.create_all()` must not create or repair production schema.
- The Alembic graph owns the full database contract required by the application, including tables, indexes, PostgreSQL extensions, functions, triggers, RLS/policies, grants, and the pinned worker-queue schema where applicable.
- Production uses a privileged migration role for DDL and a separate restricted runtime role for the application. Runtime credentials must not be promoted to schema-owner privileges.
- Clean-bootstrap CI must prove an empty database can migrate to the current head and that `alembic check` reports no model/migration drift.
- Development data is separate from schema creation. `wa_backend/seed_dev.py` is local-development-only and must fail closed against production/non-local databases. Production must never depend on seed data.
- `wa_backend/bootstrap_platform_admin.py` is not a seed: it is the one-time sovereign bootstrap for the first platform-owned administrator after the database is already at Alembic head. It must use the migration role and refuse to create a second platform administrator.
- Every schema change must identify its owning module.
- Continue using one controlled Alembic revision graph unless there is a proven reason to change it; avoid unnecessary multi-head migration complexity.
- Module ownership must be visible in migration naming/documentation.
- Destructive migrations require an explicit compatibility/rollout plan.
- Expand/contract migrations are preferred when compatibility across versions matters.

### Contracts

- Public module/API/event contracts are versioned when backward compatibility matters.
- Stable codes/enums remain language-neutral.
- Contract changes must define compatibility behavior instead of relying on accidental implementation details.

### Upgrade tests

Important module/schema upgrades must be tested from supported previous states to current head.

No module is considered mature if fresh-install tests pass but upgrade paths are unknown.

---

## 8. EVENTS, ASYNC WORK, AND OUTBOX

Use synchronous in-process calls for work that benefits from immediate consistency.

Use domain/application events when they provide real decoupling.

For asynchronous side effects that must survive crashes:

- use a transactional outbox or equivalent durable pattern;
- events/jobs must be tenant-scoped;
- handlers must be idempotent;
- retries must be bounded and observable;
- authorization/invariants must be revalidated when required.

Do not turn the whole platform into an event-driven system without a concrete reason.

### Reusable durable async/import foundation

Product Import V1 is the first production reference implementation for durable,
tenant-scoped bulk work. When a **second real domain** needs comparable import or
long-running asynchronous ingestion (for example Areas, Stores, Vehicles, or
Sales Representatives), do not copy Product Import's queue/recovery machinery
into that domain and do not create a platform-wide event bus by default.

At that point, extract only the already-proven **technical primitives** into a
small cross-domain durable-work/import foundation:

- immutable source persistence/integrity where file-backed ingestion needs it;
- transactional task registration / outbox-equivalent durable dispatch;
- tenant-scoped concurrency, admission/backpressure, and bounded worker budgets;
- job-delivery recovery and business-job/queue reconciliation;
- idempotent execution/replay envelopes;
- progress/readiness/observability and bounded retry contracts;
- retention hooks and operational lifecycle primitives.

The shared foundation owns **technical delivery semantics only**. Each consuming
domain keeps its own source mapping, validation, permissions, invariants,
business commands, persistence authority, and final execution policy behind a
small domain adapter/public application contract. Areas, Stores, Vehicles,
Representatives, Products, Pricing, Inventory, and other domains must never
share business truth merely because they share durable-work infrastructure.

Extraction is triggered by an actual second consumer and requires parity gates
against the proven Product Import behavior. Until then, Product Import remains
the concrete implementation rather than being prematurely generalized into a
framework. Future import channels should therefore reuse one durable engine
through explicit contracts, not duplicate one queue/recovery stack per screen.

---

## 9. MICROservices EXTRACTION POLICY

Microservices are **not** a target by themselves.

A module may be extracted into a separate service only when evidence shows a real need, such as:

- independently extreme scaling characteristics;
- materially different availability/failure-isolation requirements;
- a hard security/compliance boundary;
- a workload/runtime that is operationally different;
- independent deployment velocity that provides measurable value;
- team ownership scale that justifies the operational cost.

Before extraction, the module must already have a clean internal boundary. A well-built Modulith makes extraction possible later without requiring it now.

For a solo/small team, premature microservices are rejected.

---

## 10. SAAS EXPANSION PRINCIPLE

Wanasah starts as a focused distribution/operations system.

Future months/years may add adjacent systems such as shipping/logistics, accounting, CRM, purchasing, HR, manufacturing, or other capabilities.

We are **not** building all of those now.

Product capabilities intentionally deferred from Version 1 are tracked in the root-level `VERSION_2_FUTURE_FEATURES.md`. Treat that file as canonical scope: deferred foundations must not be silently deleted, re-enabled, or reclassified without reconciling that document.

We are building today's distribution product so that future modules can be added without:

- rewriting the core;
- leaking tenant data;
- coupling every module to every other module;
- duplicating authorities;
- breaking upgrade paths;
- turning one customization into a global fork.

Extension points and explicit contracts are preferred over broad magical inheritance/patching.

---

## 11. PERFORMANCE PRINCIPLE

Architecture must protect performance without sacrificing correctness.

Prefer:

- in-process calls over network hops when a service boundary gives no measurable value;
- set-based database operations;
- bounded pagination;
- explicit indexes backed by query evidence;
- bulk APIs where appropriate;
- exact transactions;
- bounded async work;
- caching only with clear invalidation/tenant scope;
- no N+1;
- no unbounded memory loads.

Strict modularity must not create needless serialization, HTTP calls, or distributed transactions inside the same deployable system.

---

## 12. SECURITY AND AUTHORIZATION

Authorization is a domain/backend responsibility, not a UI concern.

The future company-wide permission system should support:

- platform administration separated from tenants;
- company roles;
- module permissions;
- location/warehouse scope;
- optional branch/route/vehicle/team scope where required;
- explicit overrides with auditability.

Inventory-specific permissions are an initial slice of this broader authorization architecture, not the final system-wide location for all roles.

---

## 13. ARCHITECTURE EVOLUTION RULE

When implementing normal product work:

1. do not stop feature delivery to rewrite the whole architecture;
2. do not introduce new global coupling for convenience;
3. place new domain logic in the correct module/authority;
4. define ownership before adding duplicate state;
5. prefer public interfaces over internal imports;
6. add architecture gates gradually;
7. leave legacy extraction to an approved hardening stage unless the current change requires it.

---

## 14. FRONTEND PAGE OWNERSHIP AND FILE BOUNDARIES

Dashboard pages must follow the same ownership discipline as backend modules. A page must not become a single file that owns layout, state, network orchestration, durable-command recovery, validation, permissions, mutations, imports, dialogs, and unrelated workflows at once.

### Page-folder rule

- Every Dashboard page must have a dedicated page folder under `dashboard/src/pages/<page>/` (or an equivalent page-owned folder already established by the project).
- The route-level page entry should be a thin composition/orchestration layer. It may coordinate page-level state, but it must not become a dumping ground for every workflow and visual component.
- Page-specific components, hooks/workflows, runtime contracts, helpers, and display logic belong inside that page folder unless they are genuinely reusable across multiple pages.
- Shared folders are for truly cross-page technical primitives only. Do not move page-specific logic into a generic shared folder merely to make the page file smaller.

### Vertical feature-slice rule

- Within a page-owned folder, organize substantial functionality by **feature/workflow boundary**, not by global technical buckets such as one large `ui/` folder and one large `logic/` folder.
- A feature slice should co-locate the UI component(s), workflow/hook owner, feature-specific contracts/types, validators/helpers, and focused tests that change together, while continuing to use genuinely shared page contracts or cross-page primitives where appropriate.
- Example shape: `<page>/create/`, `<page>/import/`, `<page>/pricing/`, `<page>/family/`, with each slice owning its presentation and orchestration instead of scattering one workflow across unrelated folders.
- Co-location does **not** authorize frontend business authority. Domain policy, tenant/location authorization, lifecycle rules, financial rules, and other business truth remain backend-owned.
- A feature slice must not become a mini god-module. If one slice contains unrelated workflows, split it again by business responsibility.
- Prefer dependencies that point from the route/page composition layer into feature slices and shared page contracts; avoid feature-to-feature reach-through. Shared behavior must be promoted deliberately to a page-level or cross-page primitive rather than imported from another feature's internals.
- This rule is the default for future Dashboard pages and refactors unless a page has a documented architectural reason to use a different ownership shape.

### Single-responsibility rule

- No component, hook, function, or file should perform multiple unrelated responsibilities merely for convenience.
- Large workflows must be split by coherent responsibility, not by arbitrary line count.
- Presentational components must not silently become business authorities.
- Backend/domain authorities remain the source of business truth; React must consume contracts and present behavior, not reimplement domain rules.
- Async workflows that involve retries, durable request identity, cancellation, concurrency/version checks, or multi-step mutation recovery must have an explicit owner and must not be duplicated across components.
- Runtime contracts and stable coded errors remain centralized and explicit.

### Safe-refactor rule

When splitting an existing large page:

1. **Freeze behavior first.** Record the current tests, contracts, query keys, storage keys, durable-operation scopes, permissions, error codes, cancellation semantics, and mutation behavior.
2. **Do not combine structural refactoring with behavior or visual redesign.** A file move/extraction must preserve behavior exactly unless a separate approved change explicitly says otherwise.
3. **Extract leaf/presentational pieces first.** Move markup and pure rendering before moving stateful orchestration.
4. Move state, queries, mutations, and durable workflows only one responsibility at a time, with focused regression tests after each extraction.
5. Preserve request ordering, AbortController/request-sequence protection, optimistic-version checks, idempotency keys, retry semantics, and cache invalidation exactly.
6. After every extraction checkpoint, run the relevant type checks/tests/build before continuing.
7. If an extraction requires duplicating logic or weakening an authority boundary, stop and redesign the boundary instead of forcing the split.
8. **Deletion guard:** never remove an import, type, helper, state owner, query, mutation, callback, or durable-operation primitive merely because related markup moved. Before deletion, verify full-file/project usage and prove the symbol/path is genuinely stale.
9. **Parity guard:** before closing each structural checkpoint, compare the pre-refactor and post-refactor ownership of sensitive invariants such as query/mutation counts, query keys, durable-operation scopes, cursor/history resets, retry/refetch paths, storage keys, permission gates, and request-order/cancellation guards. Any unexplained delta blocks further extraction.
10. Delete stale/duplicate paths only after the replacement path is proven equivalent.

### Design-change rule

Visual redesign comes **after** structural behavior-preserving refactoring when the current page is too coupled to change safely. Styling/icon/layout work should not require touching unrelated business workflows.

### Color-mode / theme architecture

Wanasah is a **multi-color-mode UI architecture**, not a light-only interface. The supported presentation model must be able to carry at least Light and Dark modes, and may add approved branded modes later without rewriting page components.

- Color modes are presentation state only. They must never change business logic, backend authority, permissions, isolation, idempotency, request semantics, or domain behavior.
- Shared semantic design tokens are the authority for surfaces, text, borders, inputs, overlays, focus rings, status colors, and navigation surfaces.
- New UI and every page/feature slice touched by visual work must prefer semantic theme tokens over page-local hardcoded light-only colors.
- Existing hardcoded color utilities may be migrated incrementally when a page is actively worked on; do not perform risky unrelated mass rewrites.
- Light/Dark parity includes hover, focus, disabled, loading, error, success, overlays, modals, dropdowns, tables, mobile layouts, RTL/LTR, and accessibility contrast.
- Color must not be the only carrier of business meaning; text/icon/state semantics must remain understandable in every mode.
- Theme preference ownership belongs to a shared frontend presentation layer, not to business modules or individual pages.
- Theme changes must not invalidate server caches, alter API payloads, or create tenant/business state mutations.
- Visual regression/gates should progressively cover each supported mode as pages are migrated.

The goal is not "many small files." The goal is **clear ownership, predictable change impact, and the ability to modify one visual or functional concern without risking unrelated logic**.

---

## 15. APPROVED HARDENING STAGE

A future dedicated stage named **Architecture Foundation / Modulith Hardening** is approved and tracked in `INVENTORY_COMMERCIAL_FOUNDATION_PLAN.md`.

Its purpose is to move the existing system from “monolith with growing domain separation” to a **Strict Modular Monolith with enforced boundaries**, without a big-bang rewrite and without prematurely adopting microservices.

---

## 16. FUTURE SHIPPING / LOGISTICS EXPANSION

Wanasah is currently a distribution/operations platform, but the architecture must deliberately preserve a clean path to a broader shipping/logistics product in the future.

This is **not** permission to build shipping features prematurely in Version 1. It is an architectural constraint: today's domains must remain reusable and must not be designed in a way that forces a rewrite when shipping becomes an approved product scope.

### 16.1 Capabilities intended for direct reuse

The following foundations are expected to remain directly reusable, subject to their existing domain contracts and permissions:

- company/tenant isolation and policy-driven organizational scopes;
- warehouse/location isolation and authorization;
- Catalog/Product identity, UOM, barcode, and package authority;
- Inventory/Warehouse stock, inbound/outbound, batch, expiry, and movement evidence;
- Pricing/commercial calculation authority;
- driver/dispatch/route foundations where their current contracts match the future use case;
- durable idempotency, optimistic concurrency, audit, and transactional-outbox patterns;
- reporting/read-model architecture and tenant-scoped background work.

Direct reuse means **reuse the owning domain through public contracts**. It does not mean future shipping code may import or mutate another domain's internals.

### 16.2 Capabilities expected to need extension or minor customization

Future shipping/logistics will require concepts that are adjacent to the current system but should not be forced into today's Product, Inventory, Sales, or Dispatch entities merely because they look similar.

Likely future first-class concepts include:

- shipment / parcel identity and lifecycle;
- merchant/order intake from external sales channels;
- pickup and delivery jobs;
- hubs and cross-docking;
- carrier / 3PL assignment and integrations;
- fleet and vehicle operations;
- route planning/optimization, live location, ETA, and delivery exceptions;
- proof of delivery;
- cash-on-delivery collection and settlement;
- reverse logistics / shipment returns;
- shipping rates, customer-specific fees, and service levels;
- shipment tracking events and customer/merchant visibility.

These should be added as explicit modules or feature slices with clear ownership instead of expanding one existing table or API into a multi-purpose logistics god-domain.

### 16.3 Distribution-to-shipping boundary

Product stock and a shipment are related but are **not the same business aggregate**.

- Catalog owns what the item is.
- Inventory owns physical stock truth.
- Sales/Commercial owns commercial transaction evidence.
- Shipping/Logistics will own parcel/shipment movement and delivery lifecycle.
- Dispatch may coordinate assignments/routes, but must not silently become the owner of shipment identity, accounting, inventory, and customer truth at the same time.

Cross-domain coordination should use public application contracts and, where durability or loose coupling is required, transactional events/outbox.

### 16.4 Route and commercial evidence

As route/shipping workflows grow, commercial context that must remain historically stable should be locked/snapshotted at the correct operational boundary rather than re-resolved from mutable live configuration after execution has begun.

Examples may include:

- the applicable price/publication revision;
- assignment/route revision;
- source location / warehouse context;
- customer/merchant shipping terms;
- applicable fees or service level.

The exact evidence contract belongs to the owning future workflow, but mutable configuration must never silently rewrite completed operational history.

### 16.5 Extensibility rule

Future shipping support must be achievable primarily by **adding modules and contracts**, not by rewriting the existing distribution core.

When a future shipping requirement overlaps an existing Wanasah capability:

1. reuse the existing authority when the semantics are genuinely the same;
2. extend it through a public/versioned contract when only small additional context is required;
3. create a separate module when the lifecycle, ownership, or invariants are materially different;
4. never duplicate live mutable truth merely to make integration easier;
5. preserve tenant/location isolation, idempotency, auditability, upgrade paths, and Arabic/English contract neutrality from day one.

---

## 17. PRODUCT INGESTION & EXTERNAL CATALOG CONNECTIVITY ROADMAP

Product intake must evolve as multiple channels feeding **one canonical Product/Catalog application contract**. A new channel must never become a shortcut around Catalog/Product authority, Pricing authority, UOM/package rules, barcode uniqueness, tracking rules, lifecycle semantics, permissions, tenant isolation, idempotency, audit, validation, or observability.

### 17.1 Version 1 — file import is the production bulk-ingestion channel

Version 1 supports **CSV and XLSX** as the only external bulk Product-ingestion formats.

The V1 import experience must remain suitable for non-technical business users:

- one row represents one Product;
- localized/common headers may be recognized, with explicit column mapping as the fallback;
- lot/batch and expiry modes may differ per row (NONE, OPTIONAL, REQUIRED);
- blank per-row tracking values inherit the immutable defaults captured for that import;
- the UI must explain those rules before upload, not hide them only inside a downloaded workbook;
- the downloadable template must be safe when untouched and must not contain an importable sample Product;
- empty/header-only files are rejected before queueing when possible and again by backend authority;
- bounded file size, row count, archive safety, duplicate barcode validation, durable queueing, progress/recovery, error reporting, and all-or-nothing validation semantics remain enforced;
- direct PDF ingestion is intentionally excluded from V1 because PDF is a presentation/document format, not a reliable structured Product-data contract.

Manual Product creation remains available as a separate first-party UI workflow; it is not a replacement for bulk import.

### 17.2 Version 2 — programmable and scheduled ingestion

Version 2 may add the following channels, all reusing the same canonical ingestion/validation authority:

1. **B2B REST APIs**
   - versioned Product/batch ingestion contracts;
   - service-to-service authentication and scoped credentials;
   - idempotency keys, request limits, deterministic validation errors, audit, and tenant isolation;
   - synchronous validation for small writes and durable asynchronous jobs for large batches.

2. **Data Feeds / Sync Links**
   - scheduled or manual pull from approved HTTPS endpoints;
   - CSV, JSON, and XML feed adapters;
   - reusable mapping profiles;
   - ETag / Last-Modified / content-hash support where available;
   - dry-run/preview, change detection, conflict policy, retries, and observable sync history.

3. **Enterprise bulk drop channels**
   - SFTP and approved object-storage drop locations (for example S3-compatible storage) for companies that exchange large scheduled files;
   - files must enter the same import parser, validation, idempotency, audit, and tenant-scoped worker pipeline rather than creating a second importer.

Inbound webhooks/event push may complement REST/feed integrations for incremental changes, but they do not become a separate source of Product truth.

### 17.3 Version 3 — native ecosystem integrations

Version 3 is the default target for connector-heavy channels whose external contracts, OAuth lifecycle, reconciliation rules, and support burden are platform-specific:

- **native marketplace / commerce-platform integrations**;
- **native ERP connectors** where direct vendor-specific integration is justified by demand;
- **EDI (X12 / EDIFACT or regionally required equivalents)** for larger distributors, retailers, and supply-chain partners;
- a reusable connector framework for credentials, sync cursors, retries, rate limits, mapping, reconciliation, observability, and connector versioning.

A connector may be promoted earlier only when real customer demand justifies the operational and maintenance cost.

### 17.4 Channel-neutral ingestion rule

Regardless of source — Dashboard file upload, REST API, feed, SFTP/object storage, marketplace, ERP, or EDI — the source adapter is responsible only for transport, authentication, parsing, and mapping into the canonical import command.

Source adapters must **not** duplicate or override Product business rules. The owning Wanasah domains remain the final authority.

---

## 17.5 PRODUCT IMPORT V1 FINAL MODULE BOUNDARY

Product Import V1 is a production bulk-ingestion capability owned by
`wa_backend/domains/simple_products/imports/`. It is a reference implementation
of the module layering described by this constitution.

### Boundary

- `api/` is a transport adapter only. It owns authentication/permission entry,
  request parsing, HTTP error mapping, and explicit Pydantic response DTOs.
- `application/` owns import use cases and orchestration: source preparation,
  staging, validation, execution, correction, cancellation, retention-facing
  lifecycle, and API-facing application services.
- `domain/` owns import state/error contracts, normalization, mapping rules,
  source semantics, localization, and other import-specific invariants.
- `infrastructure/` owns PostgreSQL persistence, immutable SourceStore storage,
  CSV/XLSX parsing, Procrastinate queue integration, realtime relay, and
  operational/table-health monitoring.
- Product Import is an ingestion/orchestration capability. It does **not** become
  a second Product, Pricing, UOM, barcode, Tracking, Inventory, or permission
  authority.

The application worker is deliberately thin: source preparation -> validation ->
execution. Persistence and transport do not leak into that orchestrator, and no
root-level Product Import business module is an approved runtime entry point.

### Execution semantics

- Every job is durably identified by tenant-scoped `company_id + job_id`.
- Source bytes execute only through the immutable `SourceStore` contract.
  Inline/legacy source-payload execution is not an allowed runtime fallback.
- Source hash/size verification precedes parsing and retry parsing.
- Parsing/staging is bounded and transactional; a parser/worker crash cannot
  commit a half-staged source.
- Validation is best-effort across rows: deterministic invalid rows are recorded
  while unrelated valid rows continue.
- Execution is atomic for each committed Product/Pricing unit and idempotent by
  durable row identity. Duplicate delivery or retry after a successful commit
  replays durable evidence instead of creating a Product twice.
- Unexpected database/system failures remain retryable job failures; they are
  never converted into fabricated row errors.
- The worker revalidates the active actor and required permissions before further
  Product/Pricing writes. Permission revocation after queueing therefore fails
  closed.
- Cancellation shares the durable job-row transaction boundary with bounded
  validation/execution batches. Already committed units remain valid lineage;
  future effects stop.
- Company-scoped queue serialization is retained while imports share the
  company-default Pricing publication aggregate. Cross-company jobs may execute
  concurrently.

### Scale, isolation, and operations

- CSV/XLSX staging has explicit 50,000-row bounded-memory gates.
- Barcode validation is set-based/database-backed; import-sized Python candidate
  collections and giant parameterized `IN` lists are forbidden.
- Tenant-prefixed staging indexes plus PostgreSQL FORCE RLS remain defense in
  depth; API, application, worker, and repository paths all carry explicit
  tenant scope.
- User-facing failures expose stable safe codes/DTOs. SQL, constraints, and
  stack traces remain server-log-only with correlation IDs.
- The canonical worker launcher is
  `wa_backend/scripts/run_product_import_worker.ps1`; operational recovery and
  release verification are documented in
  `wa_backend/domains/simple_products/imports/RUNBOOK.md`.
- New ingestion channels must enter through the same canonical application/domain
  authority rather than reviving a root compatibility importer.

---

## 17.6 ERP-informed company-adaptive Product UX (locked principle)

**Model real business concepts in their owning domains, then show each
company only the workflow it needs. Do not copy large ERP screens wholesale.**
A juice distributor selling cartons should be able to create/import an ordinary
Product without encountering catch-weight tolerances, shipping handling-unit
hierarchies or mixed-product assembly configuration.

- The canonical **base stock unit**, product-specific **commercial outer
  packaging**, **UOM conversion**, and tracked **physical shipping package**
  are distinct concepts. Do not overload the user-facing term "package" or
  use a display label to determine business authority.
- Default V1 Simple Products to one base unit (EACH) and at most one
  fixed-count same-SKU outer grouping. A **sealed pack can itself be one
  base unit** if that is the business stock unit; do not interpret "EACH"
  as always "loose piece".
- Never infer a carton solely because a source has a units-per-package
  column. In the official template the operator chooses an explicit
  "No outer package" or a real grouping type, and a grouping requires a
  valid conversion count.
- Distinguish **stock, purchase and sale UOM defaults**, multiple
  hierarchical conversions, variable/catch weight, multi-SKU kits and
  physical handling units before designing advanced Product UX. They
  belong to the relevant Catalog/UOM, Pricing, Inventory, Purchasing,
  Sales and Logistics authorities; a feature flag or a locked Advanced
  UOM page does not by itself make them supported.
- Use language-neutral unit codes, per-company configuration and
  locale-specific explanatory labels/aliases. Tooltips and examples
  clarify "base unit" and "outer packaging" with the customer's actual
  business vocabulary; no hardcoded assumption that a unit is always
  "حبة" (loose piece).
- Make one easy, production-verified normal Product journey the default;
  expose draft/advanced configuration only on deliberate opt-in with
  lifecycle, permissions, mutation idempotency, tenant/RLS and release
  gates. Never add a UI business rule that contradicts backend authority.
- **V1 release and error-correction gates:** see
  `docs/operations/PRODUCT_IMPORT_FINAL_ACCEPTANCE_2026-10-02.md`.
- **V2 and beyond backlog and scope separation:** see
  `VERSION_2_FUTURE_FEATURES.md` sections 6–7.

This is a cross-module design rule, not authorization to change existing
Product lifecycle, quantity semantics, Pricing or warehouse flows
without a separate approved plan and proof.

---

## 18. PERMANENT DECISION SUMMARY

1. **Company/tenant isolation is absolute and fail-closed.**
2. **Warehouse/location isolation is explicit and backend-enforced.**
3. Organizational scoping is flexible/configurable but never implicitly permissive.
4. Current architecture: monolith progressively becoming a Modular Monolith.
5. Target architecture: **Strict Modular Monolith / Modulith**.
6. Goal: **Monolith operational simplicity/performance + microservice-grade domain boundaries/isolation**.
7. Microservices only when evidence justifies extraction.
8. Every module progressively owns its data, contracts, schema evolution, and upgrade tests.
9. Public contracts/events are explicit and versioned when compatibility matters.
10. No big-bang rewrite.
11. Future expansion must add modules without weakening today's distribution system.
12. Architectural boundaries will become executable CI gates, not documentation-only rules.
