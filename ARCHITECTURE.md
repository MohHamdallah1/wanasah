# Wanasah Architecture Constitution

**Status:** CANONICAL ARCHITECTURE DIRECTION  
**Scope:** Entire repository and all future modules  
**Last updated:** 2026-09-24

This document is the architectural constitution of the Wanasah platform. It records the intended long-term direction so future work does not accidentally optimize one feature at the expense of the platform.

The current system is **a monolith that is progressively evolving into a Strict Modular Monolith (Modulith)**. It is intentionally **not** a microservices system today.

The target is better stated as:

> **Monolith operational simplicity and performance + microservice-grade domain boundaries and isolation.**

That is more precise than “Monolith speed + Microservices cleanliness”: we want one-process/in-process efficiency and transactional consistency, while enforcing domain ownership, explicit contracts, and extractable boundaries.

---

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

Future months/years may add adjacent systems such as accounting, CRM, purchasing, HR, manufacturing, or other capabilities.

We are **not** building all of those now.

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

The goal is not "many small files." The goal is **clear ownership, predictable change impact, and the ability to modify one visual or functional concern without risking unrelated logic**.

---

## 15. APPROVED HARDENING STAGE

A future dedicated stage named **Architecture Foundation / Modulith Hardening** is approved and tracked in `INVENTORY_COMMERCIAL_FOUNDATION_PLAN.md`.

Its purpose is to move the existing system from “monolith with growing domain separation” to a **Strict Modular Monolith with enforced boundaries**, without a big-bang rewrite and without prematurely adopting microservices.

---

## 16. PERMANENT DECISION SUMMARY

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
