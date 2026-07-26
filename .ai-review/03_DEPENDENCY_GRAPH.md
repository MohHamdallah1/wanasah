# Wanasah — Dependency Graph Analysis

> Phase 4 Deliverable — Dependency Graph Report
> Scope: Inter-module import topology, shared contracts/utilities, third-party dependencies, and structural hotspots across the three sub-projects.
> This document does not review code for bugs/syntax errors and does not modify any existing file. It builds on `.ai-review/00_PROJECT_MAP.md`, `.ai-review/01_ARCHITECTURE.md`, and `.ai-review/02_DATA_FLOW.md`.

---

## 1. Sub-Project Import Topology

### 1.1 Backend (`wa_backend`) — Python Import Tree



**Dashboard fan-in / fan-out table (local-module edges only):**

| Module | Fan-in | Fan-out | Note |
|---|---|---|---|
| `lib/utils.ts` (`cn`) | **45** | 0 | Highest fan-in in the whole dashboard — pure, stable, leaf utility |
| `components/ui/modal.tsx` | **17** | 0 | Shared modal shell consumed by nearly every dispatch/operations/inventory modal |
| `types/dispatch.ts` | **15** | 0 | Shared type contracts for the dispatch domain (13 components + DispatchBoard + custom-select) |
| `components/ui/custom-select.tsx` | **7** | 1 (types/dispatch.ts) | Shared searchable-select primitive |
| `data/dashboard-data.ts` | 3 (legacy only: ActiveOperationsTable, DriverSidebar, MetricCards) | 0 | Feeds only the dead `components/dashboard/*` branch |
| `data/operations-data.ts` | 3 (OperationsDashboard, OperationsSidebar, SettlementModal) | 0 | Feeds the live, routed branch |
| `hooks/useAuthFetch.ts` | 5 (OperationsDashboard, DispatchBoard, MainInventory, Tab2Inbound, Tab4Ledger) | 0 | Transport-only boundary (not domain-typed) |
| `pages/DispatchBoard.tsx` | 1 (App.tsx) | **19** | Highest fan-out — single-file structural hub |
| `App.tsx` | 1 (main.tsx) | 9 | Route table + top-level providers |
| `components/ui/sidebar.tsx` | 1 | 8 | Second-highest fan-out in the `ui/` layer (internally composed of many sub-primitives) |
| `pages/OperationsDashboard.tsx` | 1 | 6 | |
| `pages/inventory/MainInventory.tsx` | 1 | 6 | |

No cycles detected. `Login.tsx` is a structural outlier: it does **not** import `useAuthFetch.ts` and instead uses raw `fetch()` against a hardcoded URL — an intentional/accidental topology break from the rest of the graph.

---

### 1.3 Flutter (`wanasah_frontend/lib`) — Dart Import Tree



**Flutter fan-in / fan-out table (local-module edges only):**

| Module | Fan-in | Fan-out | Note |
|---|---|---|---|
| `models/visit_model.dart` | **7** | 0 | Highest fan-in — consumed by screens, blocs, repository, local_database |
| `core/db/local_database.dart` | **7** | 2 (product_model, visit_model) | Offline schema/persistence hub |
| `models/product_model.dart` | **6** | 0 | Second-highest fan-in |
| `core/network/api_client.dart` | **5** | 1 (api_constants) | Sole HTTP entry point for every screen/bloc/repository |
| `services/api_constants.dart` | 1 (api_client) | 0 | Leaf — base URL resolution |
| `repositories/sync_repository.dart` | 3 (dashboard_bloc, visit_bloc, visit_list_screen) | 4 | Sole online/offline reconciliation boundary |
| `screens/dashboard_screen.dart` | 1 (main.dart via splash) | **8** | Highest fan-out |
| `blocs/dashboard/dashboard_bloc.dart` | 1 (main.dart, dashboard_screen) | 5 | |

No cycles detected. Dependency direction is strictly one-way: `screens → blocs → repositories → core/models`, matching the DIP-friendly layering noted in `01_ARCHITECTURE.md`.

---

## 2. Shared Domain Models & Contracts

### 2.1 Pydantic Contracts (`wa_backend/schemas.py`) — 78 classes, grouped by consumer

| Contract Group | Representative Classes | Consumed By |
|---|---|---|
| Auth | `LoginRequest`, `LoginResponse` | `api/auth.py` |
| Shop CRUD | `ShopBase`, `ShopCreate`, `ShopResponse`, `EditShopDetailsRequest`, `BulkUpdateShopItem`, `BulkImportShopItem`, `BulkImportRequest` | `api/driver.py`, `api/dispatch.py` |
| Product/Variant | `ProductVariantResponse`, `SimpleProductVariantItem`, `AddProductVariantRequest` | `api/driver.py`, `api/warehouse.py` |
| Visit lifecycle | `VisitProductMin`, `VisitShopResponse`, `VisitDetailsResponse`, `VisitItemInput`, `VisitReturnInput`, `VisitUpdateRequest`, `DriverVisitResponse`, `GetVisitsContract` | `api/driver.py` (exclusively) |
| Driver session/transfer | `SessionStartRequest`, `BreakToggleRequest`, `TransferResponseRequest`, `BatchTransferResponseRequest`, `PendingBatchResponse`, `ActiveSessionResponse` | `api/driver.py` |
| Admin dashboard/settlement | `AuthorizeSessionRequest`, `AdminDashboardDriverResponse`, `AdminSessionInfo`, `AdminFinancials`, `AdminSettlementInfo`, `SessionSettlementReportResponse`, `SettleSessionRequest`, `SettleSessionResponse` | `api/dispatch.py` |
| Dispatch/Zone/Route | `DispatchInitResponse`, `DispatchRouteRequest`, `ActiveRouteResponse`, `UpdateRouteStatusRequest`, `AddZoneRequest`, `UpdateZoneRequest`, `ArchivedZoneResponse` | `api/dispatch.py` |
| Shortage | `ShortageResponseItem`, `CreateShortageItem` | `api/dispatch.py` |
| Warehouse | `WarehouseInboundRequest`, `WarehouseStocktakeRequest`, `ToggleLockRequest`, `WarehouseAlertItem`, `WarehouseInventoryItem`, `WarehouseLedgerItem`, `WarehouseStatusResponse`, `AdjustWarehouseEntryRequest` | `api/warehouse.py` |
| Generic | `MessageResponse` | All 4 routers |

`schemas.py` has **zero local imports** — it is a pure, self-contained contract layer sitting directly on top of `models.py`'s ORM classes via `ConfigDict(from_attributes=True)`, but with no shared base/mixin reused across groups beyond `MessageResponse`.

### 2.2 SQLAlchemy Tables (`wa_backend/models.py`) — 26 entities, single source of truth

Geography: `Country` → `Governorate` → `Zone`. Identity: `Driver`. Catalog: `Product` → `ProductVariant`, `OfferRule`. Fleet: `Vehicle` → `VehicleLoad`. Sessions: `WorkSession` → `SessionInventory`, `WorkBreakLog`. Commerce: `Shop` → `DispatchRoute` → `Visit` → `VisitItem`/`VisitReturn`. Operations: `ShortageRequest`, `ImportLog`, `InventoryLedger`, `SystemAuditLog`, `InventoryTransfer`. Warehouse: `MainWarehouse`, `DamagedItemLog`, `WarehouseLedger`. Config: `SystemSetting`.

These 26 classes are the **only** shared domain model in the entire system — neither the React dashboard nor the Flutter app has a local mirror; both consume them exclusively as serialized JSON via `schemas.py`.

### 2.3 SQLite Local Tables (`wanasah_frontend/lib/core/db/local_database.dart`)

| Table | Role | Relationship to backend models |
|---|---|---|
| `products` | Flat vehicle-stock snapshot | Denormalized projection of `VehicleLoad`/`SessionInventory`/`ProductVariant` — no FK structure |
| `visits` | Flat visit snapshot (`cart_items`/`returns` as embedded JSON text) | Denormalized projection of `Visit`/`VisitItem`/`VisitReturn` |
| `pending_sync` | Offline write-ahead queue | Not modeled on any backend table — client-only construct |

There is **no local `shops`/`zones`/`product_variants` table** — everything the UI needs is embedded directly on `visits`/`products` rows at `syncDown()` time (per `02_DATA_FLOW.md` §3).

### 2.4 React Types (`dashboard/src/types/dispatch.ts`, `data/*.ts`)

`types/dispatch.ts` defines `TabId`, `ScheduleStatus`, `RouteStatus`, `PendingRoute`, `Shop`, `Shortage`, `Zone`, `CustomSelectOption` — these are **hand-maintained, independent** re-declarations of shapes that also exist as Pydantic contracts in `schemas.py`; there is no code-generation or shared-schema linkage between the two (confirmed structurally — `schemas.py` has no exported OpenAPI/TS artifact consumed here). `data/dashboard-data.ts` (legacy) and `data/operations-data.ts` (live) each define their own `Driver`/`DriverData` shape independently of `types/dispatch.ts` and of each other.

---

## 3. Shared Utilities & Services

| Utility | Location | Consumers | Fan-in | Centralization Quality |
|---|---|---|---|---|
| `services.py` | `wa_backend/services.py` | `api/driver.py` only | 1 of 3 routers | **Poor** — designed to be shared (`get_setting`, `calculate_invoice`, `check_debt_limits`, `adjust_inventory`, `reverse_previous_visit_state`), but `dispatch.py`/`warehouse.py` re-implement equivalent logic inline instead of importing it |
| `useAuthFetch` | `dashboard/src/hooks/useAuthFetch.ts` | `OperationsDashboard.tsx`, `DispatchBoard.tsx`, `MainInventory.tsx`, `Tab2Inbound.tsx`, `Tab4Ledger.tsx` | 5 | **Good but transport-only** — not bypassed by these 5, but `Login.tsx` and 2 modals (`AdjustInventoryModal.tsx`, `ShopBulkImportModal.tsx`) independently re-implement raw `fetch`/token-read logic instead of using it |
| `cn` (`lib/utils.ts`) | `dashboard/src/lib/utils.ts` | ~45 files across `components/ui/*` and page components | 45 | **Excellent** — the single most reused module in the dashboard, pure and stable |
| `ApiClient` (Dio singleton) | `wanasah_frontend/lib/core/network/api_client.dart` | `auth_bloc`, `dashboard_bloc`, `sync_repository`, `add_shop_screen`, `dashboard_screen` | 5 | **Excellent** — sole HTTP entry point for the entire mobile app, no bypass found |
| `LocalDatabase` | `wanasah_frontend/lib/core/db/local_database.dart` | `sync_repository`, `dashboard_bloc`, `visit_bloc`, `visit_list_bloc`, `auth_bloc`, `visit_screen`, `dashboard_screen` | 7 | **Excellent** — sole SQLite access point, no direct `sqflite` usage found outside this file |
| `SyncRepository` | `wanasah_frontend/lib/repositories/sync_repository.dart` | `dashboard_bloc`, `visit_bloc`, `visit_list_screen` | 3 | **Excellent** — sole online/offline reconciliation boundary |
| `Modal` (`components/ui/modal.tsx`) | `dashboard/src` | 17 dispatch/operations/inventory modal components | 17 | **Good** — consistent shared modal shell across nearly all overlay UI |
| `CustomSelect` | `components/ui/custom-select.tsx` | 7 dispatch-domain components | 7 | **Good** — shared searchable-select primitive |
| Auth-token access (anti-pattern) | scattered `localStorage.getItem/setItem('admin_token'\|'token')` | `App.tsx`, `useAuthFetch.ts`, `TopBar.tsx`, `AdjustInventoryModal.tsx`, `ShopBulkImportModal.tsx` | 5 independent call sites | **Poor** — a cross-cutting concern with no centralizing module (no `authService.ts`/context), unlike every other shared concern in this table |

---

## 4. External Library Dependencies

### 4.1 Backend (`wa_backend/requirements.txt`) — critical path packages

| Package | Version | Drives |
|---|---|---|
| `fastapi` | 0.111.0 | HTTP routing, dependency injection, request/response lifecycle for all 4 routers |
| `sqlalchemy[asyncio]` | 2.0.30 | Async ORM — every table in `models.py`, every query in `api/*.py` |
| `asyncpg` | 0.29.0 | PostgreSQL async driver underlying the engine in `database.py` |
| `pydantic` | 2.7.1 | Every contract in `schemas.py`; `BeforeValidator`-based financial sanitization |
| `pydantic-settings` | 2.2.1 | Present in manifest; `config.py` itself uses plain `os.environ` rather than `pydantic-settings.BaseSettings` |
| `pyjwt` | 2.8.0 | JWT issuance/decoding in `api/auth.py` and `api/dependencies.py` |
| `bcrypt` | 4.1.2 | Password hashing/verification in `models.py` (`Driver.set_password`) and `api/auth.py` |
| `python-dotenv` | 1.0.1 | `.env` loading in `config.py` |
| `uvicorn[standard]` | 0.30.1 | ASGI server (not imported in code, invoked at process level per `RUN.txt`) |

Alembic (migrations) is present as a directory (`alembic/`) but not pinned in `requirements.txt` — a manifest/runtime-dependency mismatch at the dependency-declaration level.

### 4.2 React Dashboard (`dashboard/package.json`) — critical path packages

| Package | Drives |
|---|---|
| `react` / `react-dom` 18.3.1 | Component runtime for the entire dashboard |
| `react-router-dom` 6.30.1 | `App.tsx` route table, `ProtectedRoute`/`PublicRoute` guards, all `useNavigate` calls |
| `@tanstack/react-query` 5.83.0 | `QueryClientProvider` wraps the app in `App.tsx`, but no page in the reviewed tree is confirmed to use `useQuery`/`useMutation` hooks — pages fetch manually via `useAuthFetch` instead, indicating the library is wired but under-leveraged relative to its declared role in `00_PROJECT_MAP.md` |
| `@radix-ui/react-*` (accordion, dialog, dropdown, tabs, tooltip, select, etc.) | Underlies nearly every file in `components/ui/*` — the shadcn-style primitive layer |
| `tailwindcss` 3.4.17 + `tailwindcss-animate` | Styling substrate for all components |
| `framer-motion` | Animation in `OperationsDashboard.tsx`, `DispatchBoard.tsx`, `CommandCenter.tsx`, `PulseBar.tsx`, `custom-select.tsx`, `modal.tsx` |
| `react-hook-form` + `zod` + `@hookform/resolvers` | Present in manifest; `components/ui/form.tsx` wraps them, but no page component in the reviewed tree was found wiring a `zod` schema to a form — another declared-but-thinly-used dependency |
| `papaparse` / `xlsx` | `ShopBulkImportModal.tsx` — CSV/XLSX parsing for bulk shop import |
| `recharts` | Underlies `components/ui/chart.tsx` |
| `sonner` | Toast notifications used across `DispatchBoard.tsx`, inventory tabs, and multiple modals |
| `lucide-react` | Icon set used in virtually every component file |

### 4.3 Flutter (`wanasah_frontend/pubspec.yaml`) — critical path packages

| Package | Drives |
|---|---|
| `flutter_bloc` 9.1.1 + `equatable` 2.0.7 | All 4 BLoCs (`AuthBloc`, `DashboardBloc`, `VisitBloc`, `VisitListBloc`) and their event/state classes |
| `dio` 5.7.0 | `ApiClient` singleton — sole HTTP transport for the entire app |
| `sqflite` 2.4.1 + `path` 1.9.1 + `path_provider` 2.1.5 | `LocalDatabase` — offline SQLite persistence |
| `flutter_secure_storage` 9.0.0 | JWT/driver-id persistence, read by `AuthInterceptor`, `AuthBloc`, `DashboardBloc` |
| `flutter_dotenv` 6.0.0 | `.env` → `API_BASE_URL`, loaded in `main.dart`, resolved in `api_constants.dart` |
| `geolocator` 11.0.0 | GPS capture in `dashboard_screen.dart` (session start) and `add_shop_screen.dart` |
| `map_launcher` 3.3.0 / `url_launcher` 6.3.0 | Navigation/contact actions in `visit_list_screen.dart` |
| `intl` 0.19.0 + `flutter_localizations` | Arabic date formatting (`initializeDateFormatting('ar', null)` in `main.dart`), used across screens |
| `flutter_inset_box_shadow` 1.0.8 | Cosmetic UI effect, isolated to presentation layer |

---

## 5. Dependency Hotspots & Risks

### 5.1 High fan-in modules (breaking changes here ripple widely)

| Module | Fan-in | Risk if modified |
|---|---|---|
| `wa_backend/models.py` | 7 | Any schema change (column rename/type change) forces review of every router, `services.py`, `db_manager.py`, and every Alembic migration |
| `wa_backend/database.py` | 6 | Session-factory/engine changes affect every router and the maintenance CLI simultaneously |
| `wa_backend/schemas.py` | 4 | A contract change ripples into whichever router(s) reference it, with no compile-time cross-check on the React/Flutter side |
| `dashboard/src/lib/utils.ts` | 45 | Extremely low individual risk (tiny, stable `cn` helper) but the **single highest blast-radius** file in the dashboard by raw count |
| `dashboard/src/components/ui/modal.tsx` | 17 | A behavioral change (e.g., animation timing, focus trap) affects 17 independent overlay UIs at once |
| `dashboard/src/types/dispatch.ts` | 15 | Renaming/narrowing a field breaks compilation across the entire dispatch domain instantly (this is a **positive** risk — TypeScript catches it at build time, unlike the backend/React JSON boundary) |
| `wanasah_frontend/.../visit_model.dart` | 7 | Field changes ripple into screens, blocs, repository, and local_database simultaneously — but Dart's static typing plus `fromJson` factories make this a caught-at-compile-time risk, not a silent-runtime risk |
| `wanasah_frontend/.../local_database.dart` | 7 | Schema/version bump (already at v6) requires careful `onUpgrade` migration coverage for all 7 dependents |
| `wanasah_frontend/.../api_client.dart` | 5 | Any interceptor/timeout change affects every network call app-wide |

### 5.2 High fan-out modules (many things can break them / hard to isolate for testing)

| Module | Fan-out | Risk |
|---|---|---|
| `wa_backend/api/dispatch.py` (2968 lines) | 4 local + heavy inline logic | Largest file in the repo; combines HTTP handling, business computation, and persistence with no delegation to `services.py` — the single riskiest file to refactor in the backend |
| `wa_backend/api/driver.py` (1647 lines) | 5 (highest backend fan-out) | Second-largest file; the only router that *does* depend on `services.py`, making it structurally inconsistent with its siblings |
| `dashboard/src/pages/DispatchBoard.tsx` (1211 lines) | 19 (highest in dashboard) | Single component spanning 7 sub-domains (zones, shops, routes, inventory, shortages, scheduling, bulk import) — a refactor of any one sub-domain risks touching the same 1200-line file as five other concerns |
| `dashboard/src/App.tsx` | 9 | Central route table; low line count but couples routing, auth-guard logic, and provider setup in one file |
| `wanasah_frontend/.../dashboard_screen.dart` (1077 lines) | 8 (highest in Flutter) | Combines session lifecycle, break toggling, GPS capture, and dashboard rendering |
| `wanasah_frontend/.../visit_screen.dart` (1398 lines) | 4 | Largest Flutter file; full visit workflow UI concentrated in one screen |

### 5.3 Structural risk points specific to the dependency graph (not previously enumerated as import-graph findings)

1. **`services.py` is a designed-but-orphaned dependency.** It has the *shape* of a shared kernel (fan-in target = 3 routers) but the *actual* fan-in is 1. This is the single clearest "intended dependency that never materialized" in the whole system — the dependency graph shows a shared node with almost no real inbound edges from its intended consumers.
2. **Duplicate parallel subgraph with zero live inbound edges.** `components/dashboard/*` (5 files) plus its private dependency `data/dashboard-data.ts` form a fully self-contained subgraph that is provably unreachable from `App.tsx`'s routed tree — this is visible directly in the import graph as a disconnected component, not just a code-review observation.
3. **Asymmetric reliance on `useAuthFetch` creates two divergent trust boundaries.** 5 files properly route through the shared hook; `Login.tsx` + 2 modals bypass it — meaning the "single authenticated transport" claim in `01_ARCHITECTURE.md` is contradicted by 3 independent edges in the actual import/call graph.
4. **No shared schema package bridges backend↔React.** `schemas.py` (Pydantic) and `types/dispatch.ts` (hand-written TS) model overlapping domain concepts with **zero dependency edge** between them (no codegen, no OpenAPI-to-TS pipeline) — a structural gap that makes the React side's fan-in numbers (e.g., `types/dispatch.ts` at 15) safe *only* within the frontend, with no cross-language safety net.
5. **Flutter's dependency graph is the only one of the three with fully consistent, constructor-injected fan-out** (`SyncRepository({ApiClient? api, LocalDatabase? db})`, etc.), meaning its high-fan-in nodes (`local_database.dart`, `api_client.dart`) are the *safest* high-fan-in nodes in the system to refactor behind a stable interface — the opposite risk profile from the backend's `models.py`/`database.py`, which have no such injection seam.
6. **Warehouse/Dispatch duplication is a dependency-graph symptom, not just a logic symptom.** Because `api/dispatch.py` and `api/warehouse.py` do not import `services.py`, the graph itself shows two isolated islands of inventory-mutation logic that happen to read/write the same tables (`MainWarehouse`, `SessionInventory`, `InventoryLedger`, `WarehouseLedger`) without a shared code dependency enforcing consistency between them.

---

## 6. Summary Metrics

| Metric | Backend | Dashboard | Flutter |
|---|---|---|---|
| Circular dependencies | None | None | None |
| Highest fan-in (module, count) | `models.py` (7) | `lib/utils.ts` (45) | `visit_model.dart` / `local_database.dart` (7) |
| Highest fan-out (module, count) | `api/driver.py` (5) | `pages/DispatchBoard.tsx` (19) | `screens/dashboard_screen.dart` (8) |
| Shared business-logic module fan-in | `services.py`: 1 of 3 possible routers | N/A (no domain service layer exists) | `SyncRepository`: 3 of 3 relevant consumers |
| Dead/disconnected subgraph | None found | `components/dashboard/*` (5 files) + `data/dashboard-data.ts` | None found |
| Cross-project shared code | None (integration only via HTTP/JSON contract in `schemas.py`) | — | — |
