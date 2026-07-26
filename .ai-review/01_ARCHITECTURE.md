# Wanasah — Architecture Review

> Phase 2 Deliverable — Architecture Analysis Report
> Scope: Architectural patterns, structural design, and code organization of the existing codebase only.
> This document does not review code for bugs/syntax errors and does not evaluate missing/unbuilt features. It builds on `.ai-review/00_PROJECT_MAP.md`.

---

## 1. Architectural Style

The system is composed of three independently deployable sub-projects connected exclusively through a REST/JSON contract, rather than a single unified codebase:

- **`wa_backend/`** — A **layered monolith** built on FastAPI. The intended layering is: HTTP routers (`api/*.py`) → business services (`services.py`) → ORM data layer (`models.py`) → PostgreSQL. In practice, this layering is only partially realized (see Section 3): `api/driver.py` follows it, while `api/dispatch.py` and `api/warehouse.py` implement business and persistence logic directly inside route handlers ("fat controller" style within an otherwise layered design).
- **`dashboard/` (React)** — A **component-based, page-centric architecture**. There is no dedicated state-management library (no Redux/Zustand/Context store); each page component (`OperationsDashboard.tsx`, `DispatchBoard.tsx`, `MainInventory.tsx`) owns its own local state via `useState`/`useEffect`/`useCallback` and talks to the backend through a single shared transport hook (`useAuthFetch`). Real-time visibility into field operations is achieved through **client-side polling** (e.g., `OperationsDashboard` re-fetches `/admin/sessions/today` every 10s; `DispatchBoard` re-fetches active routes/shortages every 60s) rather than push-based updates.
- **`wanasah_frontend/` (Flutter)** — A **BLoC (Business Logic Component) architecture** combined with the **Repository pattern** and **offline-first client-server** design. `flutter_bloc` mediates all state transitions; `SyncRepository` is a dedicated synchronization/repository layer sitting between the BLoCs and two data sources (`ApiClient` for remote, `LocalDatabase`/SQLite for local), implementing an explicit online/offline reconciliation flow (`syncDown`, `saveInvoice` with fallback, `syncUp`).
- **System-level style** — An **API-first, multi-client client-server system**: one authoritative backend (FastAPI + PostgreSQL) exposing role-partitioned REST endpoints, consumed independently by two heterogeneous clients (an always-online web dashboard and an offline-capable mobile app), with **JWT bearer authentication** as the sole integration/trust boundary between all three sub-projects.

---

## 2. Directory & Folder Structure

### 2.1 `wa_backend/`
```
wa_backend/
├── main.py            (app bootstrap, middleware, routers)
├── config.py          (environment/settings)
├── database.py        (async engine/session factory)
├── models.py           (SQLAlchemy ORM — 25 entities, flat single file)
├── schemas.py          (Pydantic contracts — flat single file, 806 lines)
├── services.py         (shared business logic — used by only 1 of 3 routers)
├── db_manager.py        (standalone maintenance CLI)
├── api/
│   ├── auth.py
│   ├── dependencies.py  (JWT guards)
│   ├── driver.py        (1647 lines)
│   ├── dispatch.py      (2968 lines)
│   └── warehouse.py     (669 lines)
└── alembic/             (migrations)
```
Evaluation: The structure is **flat rather than domain-modularized** — there is no `repositories/`, `core/`, or per-domain sub-package. All ORM models live in a single `models.py` and all contracts in a single `schemas.py`. This is workable at the current scale but does not scale well as a pattern: `api/dispatch.py` alone (2968 lines) is larger than `models.py`, `schemas.py`, and `services.py` combined, indicating the folder structure does not reflect the actual concentration of logic in the codebase.

### 2.2 `dashboard/src/`
```
dashboard/src/
├── main.tsx / App.tsx
├── pages/               (Login, OperationsDashboard, DispatchBoard, inventory/*)
├── components/
│   ├── operations/       (actively routed — DashboardLayout, TopBar, FleetRadar, ...)
│   ├── dispatch/         (actively routed — 13 modal/table components)
│   ├── dashboard/         (NOT routed anywhere in App.tsx — legacy)
│   └── ui/                (shadcn/Radix primitives — 50+ files)
├── hooks/                (useAuthFetch, use-mobile, use-toast)
├── data/, types/, lib/
└── test/
```
Evaluation: Domain-oriented foldering (`operations/`, `dispatch/`) is a good practice, but the coexistence of `components/dashboard/` (a full parallel set of Driver/Metric/Hero/TopNav components) alongside `components/operations/`, with only the latter wired into `App.tsx`'s routes, indicates **structural duplication from a prior UI generation** that was not removed from the tree.

### 2.3 `wanasah_frontend/lib/`
```
wanasah_frontend/lib/
├── main.dart
├── blocs/
│   ├── auth/, dashboard/, visit/, visit_list/
├── core/
│   ├── network/api_client.dart
│   └── db/local_database.dart
├── repositories/sync_repository.dart
├── models/               (cart_item, product, visit)
├── screens/               (6 screens)
└── services/api_constants.dart
```
Evaluation: This is the **most consistently layered** folder structure of the three sub-projects — it cleanly separates presentation (`screens/`), application state (`blocs/`), synchronization orchestration (`repositories/`), low-level I/O (`core/`), and data contracts (`models/`), with the folder hierarchy matching the dependency direction described in Section 3.

---

## 3. Layer Separation & Boundaries

| Sub-project | Presentation | Business Logic | Data Access | Observed Boundary Quality |
|---|---|---|---|---|
| `wa_backend` | `api/*.py` route functions | Partly in `services.py`, but mostly **inlined into route handlers** in `dispatch.py`/`warehouse.py` | `models.py` (SQLAlchemy), queried directly from route handlers via `AsyncSession` | **Weak** — no consistent boundary between HTTP layer and persistence layer |
| `dashboard` (React) | JSX in page/component files | Computation (e.g., `aggregatedSales`, `sortZones`, reorder logic) **colocated inside page components** | `useAuthFetch` (generic transport only, not a domain data layer) | **Weak** — no dedicated service/data layer; pages do fetch + compute + render |
| `wanasah_frontend` (Flutter) | `screens/*.dart` (widgets only) | `blocs/*.dart` (all state transitions and validation) | `repositories/sync_repository.dart` + `core/network`, `core/db` | **Strong** — each layer has a single, distinct responsibility and a clear call direction (screen → bloc → repository → core) |

Backend detail: `wa_backend/schemas.py` (Pydantic) *does* provide a genuine, well-defined contract boundary between raw HTTP payloads and internal Python objects, with reusable field validators (`safe_decimal_input`, `clean_finance_str`, etc.). This is the backend's strongest boundary. However, this contract layer sits directly on top of route handlers that perform their own SQL construction, row locking (`with_for_update`), and inventory/ledger mutation — i.e., the "business logic" and "data access" layers are fused into the "presentation" (route handler) layer for 2 of the 3 routers (`dispatch.py`, `warehouse.py`). Only `api/driver.py` imports and delegates to `services.py` (`calculate_invoice`, `check_debt_limits`, `adjust_inventory`, `reverse_previous_visit_state`, `get_setting`).

React detail: `useAuthFetch` is a **transport-only** boundary (adds auth header, base URL, JSON parsing, 401 handling) — it is not a domain/data-access layer. Domain-specific fetch sequencing and business math live directly inside `DispatchBoard.tsx`, `OperationsDashboard.tsx`, and `MainInventory.tsx`, meaning presentation and business logic are not separated in the frontend.

---

## 4. SOLID Principles Compliance

- **Single Responsibility Principle (SRP)**
  - *Violated* in `wa_backend/api/dispatch.py` (2968 lines) and `api/driver.py` (1647 lines): individual route functions combine input validation, row-locking, business computation, persistence, and audit logging in one function body.
  - *Violated* in `dashboard/src/pages/DispatchBoard.tsx` (1211 lines, 19 local imports): a single component owns zone management, shop management, route launching, inventory adjustment, shortages, scheduling, and bulk import — seven distinct sub-domains in one file.
  - *Respected* in `wanasah_frontend`: each BLoC (`AuthBloc`, `DashboardBloc`, `VisitBloc`, `VisitListBloc`) is scoped to exactly one feature area, and `SyncRepository` is scoped to exactly one concern (online/offline reconciliation).
  - *Respected* in `wa_backend/models.py` and `schemas.py`: each class models exactly one entity/contract.

- **Open/Closed Principle (OCP)**
  - `services.calculate_invoice()` requires `active_offers` and `pre_fetched_tax` to be explicitly supplied by the caller (it raises `ValueError` if they are `None`) — new offer *data* (thresholds/values) can be added without code changes, but new offer *types* still require adding a new `elif best_offer.offer_type == '...'` branch inside the function, which is a partial OCP compliance (open to data/configuration extension, closed only nominally to new behavior types).
  - React's `TABS` array in `MainInventory.tsx` drives tab rendering from data, allowing new warehouse tabs to be added with minimal structural change — a small but genuine OCP-friendly pattern.

- **Liskov Substitution Principle (LSP)**
  - No meaningful class-inheritance hierarchies were found beyond conventional SQLAlchemy (`Base`) and Pydantic (`BaseModel`) base-class usage; no LSP violations observed in the reviewed code.

- **Interface Segregation Principle (ISP)**
  - FastAPI dependencies `get_current_driver` and `get_current_admin` (`api/dependencies.py`) are narrowly scoped and injected only where each specific guard is needed — a good ISP example.
  - Several Pydantic contracts (e.g., `VisitUpdateRequest`, `DispatchInitResponse`) aggregate many fields for a single large endpoint; this is reasonable for DTOs but does mean large route handlers consume "wide" contracts rather than several narrower ones.

- **Dependency Inversion Principle (DIP)**
  - `wa_backend` route handlers depend directly on the concrete `AsyncSession` and construct SQLAlchemy `select()` statements inline — there is no repository/interface abstraction between the API layer and the persistence layer, so higher-level (API) code is coupled to low-level (ORM) implementation details.
  - `wanasah_frontend` applies DIP consistently through constructor-injectable dependencies with concrete defaults, e.g.:
    ```dart
    SyncRepository({ApiClient? api, LocalDatabase? db})
    DashboardBloc({SyncRepository? syncRepository, LocalDatabase? db})
    VisitBloc({LocalDatabase? db, SyncRepository? syncRepo})
    AuthBloc({FlutterSecureStorage? storage})
    ```
    This pattern allows dependencies to be substituted (e.g., for testing) without modifying the consuming class — a genuine DIP implementation.
  - `dashboard` (React) has no DIP mechanism for its data layer: `useAuthFetch()` is called directly and identically in every page component; there is no interface/abstraction a page depends on that could be substituted independently of the concrete `fetch`-based implementation.

---

## 5. Coupling & Cohesion Analysis

Findings are based on a static import-graph analysis of all local (intra-project) imports in each sub-project.

**Backend (`wa_backend`) — Python import graph:**
```
main        → api.auth, api.dispatch, api.driver, api.warehouse, database
api.auth    → config, database, models, schemas
api.dispatch→ api.dependencies, database, models, schemas          (no services)
api.driver  → api.dependencies, database, models, schemas, services
api.warehouse → api.dependencies, database, models, schemas         (no services)
services    → models
database    → config
```
- `database.py` and `models.py` sit at the bottom of the graph with minimal/no internal dependencies — good low-level cohesion.
- `services.py` is only consumed by `api/driver.py`; `api/dispatch.py` and `api/warehouse.py` bypass it entirely and re-implement similar inventory/ledger mutation logic directly (see Section 6) — this is a **cohesion gap**: business logic that should be centralized is split between one shared module and two independent inline implementations.

**Dashboard (`dashboard/src`) — TS/TSX local import graph:**
- No cycles detected.
- Highest **fan-out** (most local dependencies from one file): `DispatchBoard.tsx` (19), `App.tsx` (9), `components/ui/sidebar.tsx` (8), `OperationsDashboard.tsx` (6), `MainInventory.tsx` (6) — `DispatchBoard.tsx` is a clear structural hub, consistent with the SRP concerns in Section 4.
- Highest **fan-in** (most depended-upon): `lib/utils.ts` (45), `components/ui/modal.tsx` (17), `types/dispatch.ts` (15), `components/ui/custom-select.tsx` (7) — these are shared low-level utilities/types, which is a healthy and expected coupling pattern (many components depending on a few small, stable, generic modules).

**Flutter (`wanasah_frontend/lib`) — Dart local import graph:**
- No cycles detected.
- Highest fan-out: `screens/dashboard_screen.dart` (8), `screens/visit_list_screen.dart` (6), `blocs/dashboard/dashboard_bloc.dart` (5), `repositories/sync_repository.dart` (4).
- Highest fan-in: `models/visit_model.dart` (7), `core/db/local_database.dart` (7), `models/product_model.dart` (6), `core/network/api_client.dart` (5) — dependencies flow from screens/blocs down into repositories/core/models, never the reverse, which reinforces the DIP-friendly layering observed in Section 4.

**Cross-project coupling:** React and Flutter share **no code** with the backend or each other; the only coupling point is the HTTP/JSON contract defined by `wa_backend/schemas.py` and consumed independently by each client. This is a deliberately loose, integration-only coupling at the system level, appropriate for a multi-client architecture.

---

## 6. Circular Dependencies & Structural Risks

**Circular dependencies:** A directed-graph cycle search was performed over the local import graphs of all three sub-projects (Python modules in `wa_backend`, TS/TSX modules in `dashboard/src`, Dart modules in `wanasah_frontend/lib`). **No circular imports were detected in any of the three codebases.**

**Structural risks identified (non-circular):**

1. **Duplicated business logic across backend routers.** `services.py` centralizes inventory/ledger mutation (`adjust_inventory`) and visit-reversal (`reverse_previous_visit_state`) logic, but only `api/driver.py` uses it. `api/warehouse.py` and `api/dispatch.py` independently implement their own inventory/ledger update sequences (e.g., locking `MainWarehouse`/`WarehouseLedger` rows and mutating `available_quantity_packs`/`reserved_quantity_packs` inline in `warehouse_inbound`, `warehouse_stocktake`, `adjust_warehouse_entry`, and the transfer-handshake endpoints in `dispatch.py`). Any future change to inventory accounting rules must be replicated in multiple, independently-maintained code paths.
2. **Oversized, multi-concern files acting as structural hotspots.** `api/dispatch.py` (2968 lines), `api/driver.py` (1647 lines), `dashboard/src/pages/DispatchBoard.tsx` (1211 lines), `wanasah_frontend/lib/screens/visit_screen.dart` (1398 lines), and `screens/dashboard_screen.dart` (1077 lines) each combine many unrelated sub-features. Large single files increase merge-conflict likelihood and make it harder to isolate and test individual pieces of logic.
3. **Legacy component duplication in the React dashboard.** `dashboard/src/components/dashboard/*` (`ActiveOperationsTable.tsx`, `DriverSidebar.tsx`, `HeroSettlement.tsx`, `MetricCards.tsx`, `TopNav.tsx`) is not referenced by `App.tsx`'s route table, which instead uses the parallel `components/operations/*` set. This is dead/duplicated structure left in the tree from an earlier UI iteration.
4. **Inconsistent API endpoint configuration in the dashboard.** `pages/Login.tsx` calls a hardcoded `http://127.0.0.1:5000/login` via raw `fetch`, while every other page uses the environment-driven `useAuthFetch` hook (`VITE_API_URL`). This creates two divergent conventions for reaching the same backend within one codebase.
5. **Scattered authentication-token access in React.** Direct `localStorage.getItem/setItem` calls for the auth token appear independently in `App.tsx`, `hooks/useAuthFetch.ts`, `components/operations/TopBar.tsx`, `components/dispatch/AdjustInventoryModal.tsx`, and `components/dispatch/ShopBulkImportModal.tsx`, instead of being centralized behind one auth service/context. This spreads a single cross-cutting concern (session/token management) across five otherwise-unrelated files.

---

## 7. Architectural Strengths

- **Clean system-level decomposition.** Three independently deployable sub-projects (backend, web dashboard, mobile app), each with its own dependency manifest and lifecycle, integrated solely through a documented REST/JWT contract — this keeps the overall system loosely coupled at the highest level.
- **No circular dependencies** in any of the three codebases, confirmed via static import-graph analysis.
- **Flutter's layered design is DIP-friendly and testable.** `SyncRepository`, the BLoCs, and `AuthBloc` all accept their dependencies via optional constructor parameters with sensible concrete defaults, allowing substitution without modifying the consuming class.
- **A single, well-encapsulated synchronization boundary in Flutter.** `SyncRepository` is the sole place where online/offline reconciliation logic lives (`syncDown`, `saveInvoice` with automatic offline fallback, `syncUp`), which keeps this cross-cutting offline-first concern out of the BLoCs and screens.
- **Strong contract boundary in the backend.** `schemas.py` defines explicit, reusable Pydantic validators (e.g., `safe_decimal_input`, `clean_finance_str`) that sanitize and normalize all HTTP payloads before they reach internal logic, forming a genuine, well-defined interface between the network and the domain.
- **Deliberate guard against hidden I/O in a core calculation function.** `services.calculate_invoice()` is written as a pure function that *requires* pre-fetched tax and offer data to be passed in (raising an explicit error otherwise) — a conscious architectural decision to keep a financial calculation free of implicit database access.
- **Domain-aligned foldering where it is used.** `wanasah_frontend/lib/blocs/{auth,dashboard,visit,visit_list}` and `dashboard/src/components/{operations,dispatch}` both map folder boundaries to business capabilities rather than technical layers alone.

---

## 8. Architectural Weaknesses & Structural Debt

- **Under-utilized service layer in the backend.** `services.py` exists as a business-logic module but is only consumed by one of three API routers; `dispatch.py` and `warehouse.py` re-implement comparable inventory/ledger logic inline, producing a "fat controller" pattern at the API layer and duplicated logic paths (see Section 6, item 1).
- **No persistence/repository abstraction in the backend.** Route handlers depend directly on `AsyncSession` and hand-written `select()` statements; there is no interface boundary between the API layer and SQLAlchemy, so the presentation layer is tightly coupled to ORM-level details (a DIP gap, Section 4).
- **No dedicated data/service layer in the React dashboard.** Beyond the generic transport hook `useAuthFetch`, there is no shared module responsible for domain-specific fetch orchestration or business calculations; each page (`DispatchBoard.tsx`, `OperationsDashboard.tsx`, `MainInventory.tsx`) independently implements its own fetching sequences and computations (e.g., `aggregatedSales`, `sortZones`, reorder/save logic), which reduces reusability and makes this logic harder to test in isolation from the UI.
- **Accumulated UI structural debt.** The parallel, unused `components/dashboard/*` set alongside the actively-routed `components/operations/*` set represents leftover structure from a previous iteration that adds navigation and maintenance overhead without contributing to the running application.
- **Inconsistent configuration boundaries.** The hardcoded backend URL in `Login.tsx` versus the environment-variable-driven `useAuthFetch` elsewhere undermines the otherwise centralized network-configuration boundary in the dashboard.
- **Fragmented cross-cutting concerns.** Authentication-token storage/retrieval is duplicated across five separate React files instead of being centralized, weakening the cohesion of the authentication boundary described as a strength of the backend's contract layer but not mirrored on the frontend.
- **Very large, multi-concern files across all three sub-projects** (`dispatch.py`, `driver.py`, `DispatchBoard.tsx`, `visit_screen.dart`, `dashboard_screen.dart`) indicate low internal cohesion at the file level; even though no circular dependencies exist between modules, these files bundle many independent responsibilities together, which is a maintainability and scalability risk as the system continues to grow.
