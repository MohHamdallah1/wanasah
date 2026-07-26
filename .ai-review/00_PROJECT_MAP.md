# Wanasah — Project Map

> Phase 1 Deliverable — Project Mapping Report
> Scope: Structural and architectural mapping of the existing codebase only.
> This document does not review code quality, does not evaluate missing/unbuilt features, and does not modify any existing file in the repository.

---

## 1. System Description

**Wanasah** is a field sales & distribution management platform composed of three cooperating sub-systems that share one backend as the single source of truth:

- A **FastAPI backend** (`wa_backend/`) that owns all business data (drivers, shops, zones, products, vehicles, dispatch routes, work sessions, visits/sales, warehouse inventory, financial ledgers, and audit logs) persisted in PostgreSQL.
- A **React/TypeScript admin dashboard** (`dashboard/`) used by office/operations staff to dispatch drivers, monitor live field operations, manage shops/zones, settle driver sessions, and manage the central warehouse.
- A **Flutter mobile application** (`wanasah_frontend/`) used by field drivers to run their daily delivery/sales route, record visits (sales, returns, samples, debt collection), manage inventory handshakes, and work fully offline with local SQLite storage that synchronizes with the backend when connectivity is available.

Together, these three projects implement an end-to-end distribution workflow: warehouse stock → vehicle loading/dispatch → driver field visits and sales → cash/debt settlement → warehouse ledger and audit reporting.

---

## 2. Technology Stack

### 2.1 Backend — `wa_backend/`

| Layer | Technology |
|---|---|
| Language / Runtime | Python (async) |
| Web framework | FastAPI `0.111.0` |
| ASGI server | Uvicorn `0.30.1` (standard extras) |
| ORM | SQLAlchemy `2.0.30` (async engine/session API) |
| Database driver | `asyncpg` `0.29.0` (PostgreSQL) |
| Data validation | Pydantic `2.7.1`, `pydantic-settings 2.2.1` |
| Auth | `pyjwt 2.8.0` (JWT/HS256), `bcrypt 4.1.2` (password hashing) |
| Config | `python-dotenv 1.0.1` (`.env` loading) |
| Migrations | Alembic (async `env.py`, `alembic.ini`, `versions/`) |
| Logging | Python `logging` with `RotatingFileHandler` → `error.log` |

### 2.2 Admin Dashboard — `dashboard/`

| Layer | Technology |
|---|---|
| Language | TypeScript `5.8.3` |
| UI framework | React `18.3.1` |
| Build tool | Vite `5.4.19` (`@vitejs/plugin-react-swc`) |
| Routing | `react-router-dom 6.30.1` |
| Data/query layer | `@tanstack/react-query 5.83.0` |
| Styling | Tailwind CSS `3.4.17`, `tailwindcss-animate`, `@tailwindcss/typography` |
| UI components | Radix UI primitives (accordion, dialog, dropdown, tabs, tooltip, etc.), `shadcn`-style local `components/ui` library |
| Icons / motion | `lucide-react`, `framer-motion` |
| Forms / validation | `react-hook-form 7.61.1`, `zod 3.25.76`, `@hookform/resolvers` |
| Charts | `recharts` |
| Notifications | `sonner` |
| Data import/export | `papaparse`, `xlsx` |
| Testing | `vitest`, `@testing-library/react`, `@testing-library/jest-dom`, `jsdom` |
| Lint | ESLint `9.32.0` + `typescript-eslint` |
| Dev tooling | `lovable-tagger` (dev-only Vite plugin) |

Vite dev server config (`vite.config.ts`): host `::`, port `8080`, HMR overlay disabled, polling-based file watch, `@` alias → `src/`.

### 2.3 Mobile Field App — `wanasah_frontend/`

| Layer | Technology |
|---|---|
| Language / SDK | Dart, Flutter (SDK constraint `^3.7.2`) |
| State management | `flutter_bloc 9.1.1`, `equatable 2.0.7` |
| HTTP client | `dio 5.7.0` (singleton `ApiClient` + interceptors) |
| Local/offline storage | `sqflite 2.4.1`, `path 1.9.1`, `path_provider 2.1.5` |
| Secure storage | `flutter_secure_storage 9.0.0` (JWT/session cache) |
| Environment config | `flutter_dotenv 6.0.0` (`.env` → `API_BASE_URL`) |
| Location services | `geolocator 11.0.0` |
| Navigation/maps | `map_launcher 3.3.0`, `url_launcher 6.3.0` |
| Localization | `flutter_localizations`, `intl 0.19.0` (Arabic locale) |
| UI extras | `flutter_inset_box_shadow 1.0.8`, `cupertino_icons` |
| Lint | `flutter_lints 5.0.0` |
| Platform targets present | Android, iOS, Web, Windows, Linux, macOS (native runner scaffolding under each folder) |

---

## 3. All System Modules

### 3.1 Backend Modules (`wa_backend/`)

| Module | Files |
|---|---|
| App bootstrap & middleware | `main.py` |
| Configuration | `config.py` |
| Database engine/session | `database.py` |
| Database maintenance CLI | `db_manager.py` |
| ORM domain models | `models.py` |
| API request/response contracts | `schemas.py` |
| Shared business services | `services.py` |
| Auth API | `api/auth.py` |
| Shared auth dependencies | `api/dependencies.py` |
| Driver-facing API | `api/driver.py` |
| Admin/Dispatch API | `api/dispatch.py` |
| Warehouse API | `api/warehouse.py` |
| Migrations | `alembic/env.py`, `alembic/script.py.mako`, `alembic/versions/` |

Domain entities defined in `models.py`: `SystemSetting`, `Country`, `Governorate`, `Zone`, `Driver`, `Product`, `ProductVariant`, `Vehicle`, `VehicleLoad`, `WorkSession`, `SessionInventory`, `Shop`, `DispatchRoute`, `Visit`, `VisitItem`, `VisitReturn`, `ShortageRequest`, `OfferRule`, `ImportLog`, `InventoryLedger`, `SystemAuditLog`, `WorkBreakLog`, `InventoryTransfer`, `MainWarehouse`, `DamagedItemLog`, `WarehouseLedger`.

### 3.2 React Dashboard Modules (`dashboard/src/`)

| Module | Files |
|---|---|
| App bootstrap | `main.tsx`, `App.tsx` |
| Auth page | `pages/Login.tsx` |
| Operations page | `pages/OperationsDashboard.tsx` |
| Dispatch page | `pages/DispatchBoard.tsx` |
| Warehouse/Inventory pages | `pages/inventory/MainInventory.tsx`, `Tab1LiveStock.tsx`, `Tab2Inbound.tsx`, `Tab3Stocktake.tsx`, `Tab4Ledger.tsx`, `inventoryUtils.ts` |
| Not-found page | `pages/NotFound.tsx` |
| Operations components | `components/operations/DashboardLayout.tsx`, `OperationsSidebar.tsx`, `TopBar.tsx`, `PulseBar.tsx`, `FleetRadar.tsx`, `CommandCenter.tsx`, `SettlementModal.tsx` |
| Dispatch components | `components/dispatch/*` — `ShopTable`, `ShopFormModal`, `ShopBulkImportModal`, `ZoneModal`, `ZoneRecycleBinModal`, `RecycleBinModal`, `RouteManagementModal`, `PendingRoutesTable`, `PostponedRoutesModal`, `ScheduleModal`, `ShortageModal`, `TransfersRadarModal`, `BulkTransferModal`, `AdjustInventoryModal` |
| Legacy/alt dashboard components | `components/dashboard/ActiveOperationsTable.tsx`, `DriverSidebar.tsx`, `HeroSettlement.tsx`, `MetricCards.tsx`, `TopNav.tsx` |
| Shared UI library | `components/ui/*` (accordion, alert, avatar, badge, button, calendar, card, carousel, chart, checkbox, collapsible, command, custom-select, dialog, drawer, dropdown-menu, form, hover-card, input, input-otp, label, menubar, modal, navigation-menu, pagination, popover, progress, quantity-input, radio-group, resizable, scroll-area, select, separator, sequence-input, sheet, sidebar, skeleton, slider, sonner, switch, table, tabs, textarea, toast/toaster, toggle/toggle-group, tooltip) |
| Data helpers/types | `data/dashboard-data.ts`, `data/operations-data.ts`, `types/dispatch.ts` |
| Hooks | `hooks/useAuthFetch.ts`, `hooks/use-mobile.tsx`, `hooks/use-toast.ts` |
| Lib utilities | `lib/utils.ts` |
| Tests | `test/setup.ts`, `test/example.test.ts` |

### 3.3 Flutter Modules (`wanasah_frontend/lib/`)

| Module | Files |
|---|---|
| App bootstrap | `main.dart` |
| Network layer | `core/network/api_client.dart` |
| Local persistence | `core/db/local_database.dart` |
| Sync engine | `repositories/sync_repository.dart` |
| API configuration | `services/api_constants.dart` |
| Auth BLoC | `blocs/auth/auth_bloc.dart`, `auth_event.dart`, `auth_state.dart` |
| Dashboard BLoC | `blocs/dashboard/dashboard_bloc.dart`, `dashboard_event.dart`, `dashboard_state.dart` |
| Visit BLoC | `blocs/visit/visit_bloc.dart` |
| Visit List BLoC | `blocs/visit_list/visit_list_bloc.dart`, `visit_list_event.dart`, `visit_list_state.dart` |
| Models | `models/cart_item_model.dart`, `models/product_model.dart`, `models/visit_model.dart` |
| Screens | `screens/splash_screen.dart`, `screens/login_screen.dart`, `screens/dashboard_screen.dart`, `screens/visit_list_screen.dart`, `screens/visit_screen.dart`, `screens/add_shop_screen.dart` |
| Native platform hosts | `android/`, `ios/`, `linux/`, `macos/`, `windows/`, `web/` (Flutter-generated runner/platform scaffolding for each target) |

---

## 4. Module Responsibilities

### 4.1 Backend

- **`main.py`** — Creates the FastAPI application, configures CORS, exposes `/health` and `/ready` probes, registers global/HTTP exception handlers that translate errors into a uniform `{"message": ...}` JSON shape, wires a rotating error-log handler, disposes the DB engine on shutdown (lifespan), and mounts the four routers (`auth`, `driver`, `dispatch`, `warehouse`).
- **`config.py`** — Loads environment variables via `dotenv` and exposes a `Config` class requiring `SECRET_KEY` and `DATABASE_URL`, plus SQLAlchemy connection-pool settings.
- **`database.py`** — Normalizes the configured database URL to the async PostgreSQL driver, builds the async engine and `AsyncSessionLocal` session factory, and exposes the `get_db()` FastAPI dependency.
- **`db_manager.py`** — Standalone CLI utility (run via `python db_manager.py`) for database maintenance: full reset & seed, cleaning operational data, injecting extra sample data, deleting a product by SKU, and two levels of "reset except essentials/logins" operations.
- **`models.py`** — Defines the relational schema for geography (country/governorate/zone), identity (`Driver`), catalog (`Product`/`ProductVariant`/`OfferRule`), fleet (`Vehicle`/`VehicleLoad`), work sessions and personal inventory (`WorkSession`/`SessionInventory`/`WorkBreakLog`), shops, dispatch routes, visits and their line items/returns, shortage requests, import logs, inventory/warehouse ledgers, system audit logs, inventory transfers ("handshake"), the main warehouse table, and damaged-goods logging.
- **`schemas.py`** — Pydantic request/response contracts for every API surface: auth, shop CRUD, product/variant projections, visit detail/list contracts, driver session/break/transfer contracts, admin dashboard/settlement contracts, dispatch/zone/shop/shortage/import contracts, and warehouse inbound/stocktake/status/ledger/product contracts. Includes reusable sanitizing validators for currency/decimal/int fields.
- **`services.py`** — Shared, reusable business logic used by the API routers: reading typed system settings, computing invoice totals (base amount, discounts/offers, tax, bonus units) from cart quantities, checking a shop's debt ceiling before allowing new debt, adjusting a driver's session inventory with mandatory ledger logging, formatting pack/carton quantities for display, and reversing a previously recorded visit's inventory/financial effects.
- **`api/auth.py`** — Implements `/driver/login` and `/login` (admin), including a timing-attack shield (dummy bcrypt hash), IP-based brute-force throttling backed by `SystemAuditLog`, and JWT issuance (`HS256`, 24h expiry) containing subject id, admin flag, and username.
- **`api/dependencies.py`** — Provides `get_current_driver` (JWT bearer decoding + DB lookup + active-account check) and `get_current_admin` (adds an `is_admin` guard) as reusable FastAPI dependencies.
- **`api/driver.py`** — Endpoints for the driver mobile experience: starting/ending work sessions (with route/vehicle inventory handshake), toggling breaks, submitting/updating visits, fetching the driver dashboard, responding to pending inventory transfers (single and batch), listing pending transfers, adding new shops, listing product variants, listing driver visits/visit details, and checking active session state.
- **`api/dispatch.py`** — Endpoints for the admin/dispatch experience: authorizing a driver session to sell, aggregating today's live session data for the operations dashboard, generating settlement reports, settling a session, initializing dispatch reference data, creating/launching dispatch routes, reading vehicle/route inventory, adjusting route inventory, listing route transfers, managing shops (list/bulk-update/add/edit/bulk-import), managing active routes and route status (including "undo end work"), managing zones (add/archive/update/list-archived/restore), and managing shortage requests (list/add/delete).
- **`api/warehouse.py`** — Endpoints for the central warehouse: receiving supplier inbound stock, performing stocktake/audit adjustments, toggling the audit lock, listing low-stock alerts, listing warehouse inventory and warehouse ledger entries, reporting warehouse lock status, listing simple product variants, adding new product variants, and adjusting a warehouse ledger entry.

### 4.2 React Dashboard

- **`main.tsx` / `App.tsx`** — Bootstraps the React root, wires `react-query`, tooltip/toast providers, and defines the route table: `/login` (public-only), and a protected layout (`DashboardLayout`) hosting `/` (operations), `/dispatch`, and `/inventory`, guarded by presence of `admin_token` in `localStorage`.
- **`hooks/useAuthFetch.ts`** — Centralized authenticated fetch wrapper: attaches the bearer token, prefixes calls with `VITE_API_URL`, parses JSON, and redirects to `/login` while clearing stored tokens on a `401` response.
- **`pages/Login.tsx`** — Admin login screen that authenticates against the backend and stores the returned token for subsequent authenticated requests.
- **`pages/OperationsDashboard.tsx`** — Live "mission control" view: polls `/admin/sessions/today`, aggregates per-product sold quantities for a sales breakdown modal, renders fleet radar and command-center panels, and lets an admin toggle sell authorization, approve settlements, and undo an end-of-work action.
- **`pages/DispatchBoard.tsx`** — The dispatch management surface: loads `/dispatch/init`, shops, active routes, and shortages; manages zone scheduling, shop CRUD/reordering/bulk import, route launch/transfer/status changes, inventory preload/adjustment, and a recycle-bin/restore flow for zones and shops.
- **`pages/inventory/MainInventory.tsx`** (+ `Tab1–Tab4`) — Warehouse management surface with four tabs: live stock, inbound receiving, stocktake/audit lock, and ledger history, all backed by the `/warehouse/*` API group.
- **Component libraries under `components/operations`, `components/dispatch`, `components/dashboard`, `components/ui`** — Provide the modals, tables, sidebars, and reusable UI primitives consumed by the pages above.
- **`data/*`, `types/dispatch.ts`** — Shared static/reference data helpers and TypeScript types for the dispatch domain.

### 4.3 Flutter App

- **`main.dart`** — Initializes Flutter bindings, Arabic date formatting (`intl`), loads `.env` via `flutter_dotenv`, initializes the `ApiClient` singleton (wiring a 401 → logout callback into `AuthBloc`), registers `AuthBloc` and `DashboardBloc` via `MultiBlocProvider`, configures the app theme/localization, and sets `SplashScreen` as the initial route.
- **`core/network/api_client.dart`** — Singleton Dio-based HTTP client: `AuthInterceptor` injects the stored bearer token into every request and reports `401` responses (except on the login path) through an `onUnauthorized` callback; exposes typed `get/post/put/patch/delete` helpers.
- **`services/api_constants.dart`** — Resolves the backend base URL from the `API_BASE_URL` env var, falling back to the Android-emulator loopback address.
- **`core/db/local_database.dart`** — Manages the local SQLite database (`wanasah_offline.db`) with `products`, `visits`, and `pending_sync` tables; provides batch inserts, session-data clearing, pending-sync queue management, local inventory deduction/reversal for offline sales, and a transactional full refresh from server data.
- **`repositories/sync_repository.dart`** — The synchronization engine: `syncDown()` pulls the driver's visits/inventory from the backend into SQLite (after first attempting to flush pending items), `saveInvoice()` submits a visit update immediately and falls back to a local pending-sync record on network/service failure, and `syncUp()` replays queued pending records (currently `submit_sale` and `toggle_break`) against the backend.
- **`blocs/auth/auth_bloc.dart`** — Checks/persists authentication state in secure storage, performs driver login against `/driver/login`, and clears both secure storage and local SQLite tables on logout.
- **`blocs/dashboard/dashboard_bloc.dart`** — Loads dashboard state from local cache, force-syncs with the backend, fetches the live driver dashboard (`/driver/{id}/dashboard`) with offline fallback to cached values, and manages pending inventory-transfer notifications and responses (single/batch).
- **`blocs/visit/visit_bloc.dart`** — Manages the in-visit shopping cart/returns/samples state, computed invoice totals, cash/debt collection inputs, restoring a previously completed/offline visit's data, and submitting the finished visit through `SyncRepository`.
- **`blocs/visit_list/visit_list_bloc.dart`** — Loads the driver's visit list from local SQLite and applies status-based filtering (All/Completed/Pending).
- **`screens/splash_screen.dart`** — Dispatches the initial auth check and navigates to the dashboard or login screen based on the resulting `AuthState`.
- **`screens/login_screen.dart`** — Collects driver credentials and dispatches `LoginRequested` to `AuthBloc`.
- **`screens/dashboard_screen.dart`** — Driver home screen: starts/ends work sessions (with GPS capture), toggles breaks (with offline queuing), and surfaces dashboard data/pending transfers from `DashboardBloc`.
- **`screens/visit_list_screen.dart`** — Displays the day's visit list (normal + emergency tabs) with filtering, manual sync, map/contact actions, and shop-add navigation.
- **`screens/visit_screen.dart`** — Full visit workflow UI: product catalog/cart entry, returns/samples, cash/debt collection, geofencing/authorization context, and restoring drafts from local/offline storage.
- **`screens/add_shop_screen.dart`** — Captures new-shop details (including GPS or manual location) and submits them via `ApiClient` to `/shops`.

---

## 5. Key & Critical Files Index

| File | Why it is critical |
|---|---|
| `wa_backend/main.py` | Backend application entry point; wires middleware, error handling, and all routers |
| `wa_backend/config.py` | Enforces presence of `SECRET_KEY`/`DATABASE_URL`; central runtime configuration |
| `wa_backend/database.py` | Defines the async DB engine/session factory and `get_db` dependency used everywhere |
| `wa_backend/models.py` | Single source of truth for the relational schema (25 domain models) |
| `wa_backend/schemas.py` | Defines every API request/response contract |
| `wa_backend/services.py` | Shared financial/inventory business logic reused across routers |
| `wa_backend/api/dependencies.py` | Central JWT auth/authorization guard used by all protected endpoints |
| `wa_backend/db_manager.py` | Operational CLI for resetting/seeding/maintaining the database |
| `wa_backend/alembic.ini`, `alembic/env.py` | Database migration configuration and async migration runner |
| `wa_backend/requirements.txt` | Backend dependency manifest |
| `dashboard/src/main.tsx` | React application bootstrap |
| `dashboard/src/App.tsx` | Route table and top-level providers/guards |
| `dashboard/src/hooks/useAuthFetch.ts` | Single authenticated HTTP entry point used across the dashboard |
| `dashboard/vite.config.ts` | Build/dev-server configuration and `@` path alias |
| `dashboard/package.json` | Frontend dependency manifest and npm scripts |
| `wanasah_frontend/lib/main.dart` | Flutter application bootstrap and provider wiring |
| `wanasah_frontend/lib/core/network/api_client.dart` | Singleton HTTP client and auth interceptor used by all API calls |
| `wanasah_frontend/lib/core/db/local_database.dart` | Offline SQLite schema and persistence logic |
| `wanasah_frontend/lib/repositories/sync_repository.dart` | Online/offline synchronization engine (core of offline-first design) |
| `wanasah_frontend/lib/services/api_constants.dart` | Resolves backend base URL for the mobile app |
| `wanasah_frontend/pubspec.yaml` | Flutter dependency manifest and asset declarations |
| `RUN.txt` | Informal developer notes describing how each sub-project is started locally |

---

## 6. System Initialization

### 6.1 Backend (`wa_backend/`)

1. Environment variables are loaded from `.env` (via `python-dotenv`) when `config.py` is imported.
2. `Config` validates that `SECRET_KEY` and `DATABASE_URL` are present, raising immediately if not.
3. `database.py` normalizes the DB URL to the `postgresql+asyncpg://` scheme and creates the async SQLAlchemy engine and `AsyncSessionLocal` session factory using the pool settings from `Config`.
4. `main.py` builds the FastAPI app (`Wanasah API Core`), with Swagger/OpenAPI docs enabled only when `ENVIRONMENT != "production"`.
5. CORS middleware is configured: permissive (`*`) in development, restricted to named dashboard domains in production.
6. Global and HTTP exception handlers are registered, and a rotating file logger (`error.log`) is attached.
7. The four routers — `auth`, `driver`, `dispatch`, `warehouse` — are included on the app.
8. On shutdown, the FastAPI `lifespan` context disposes the async engine to release DB connections.
9. The app is served by an ASGI server (Uvicorn) as noted informally in `RUN.txt`.
10. Separately, `db_manager.py` can be run as a standalone script (`python db_manager.py`) to reset/seed/maintain the database outside of the HTTP server lifecycle.

### 6.2 React Dashboard (`dashboard/`)

1. `npm run dev` starts the Vite dev server (host `::`, port `8080`), or `vite build`/`vite preview` for production builds.
2. `index.html` loads `src/main.tsx`, which calls `createRoot(...).render(<App />)`.
3. `App.tsx` sets up `QueryClientProvider`, tooltip/toast providers, and `BrowserRouter`.
4. Route guards (`ProtectedRoute`/`PublicRoute`) check for an `admin_token` in `localStorage` to decide whether to render `Login` or the protected `DashboardLayout` subtree.
5. Once authenticated, page components (`OperationsDashboard`, `DispatchBoard`, `MainInventory`) mount and immediately issue authenticated requests (via `useAuthFetch`) against the FastAPI backend, using `VITE_API_URL` as the base URL.

### 6.3 Flutter App (`wanasah_frontend/`)

1. `flutter run` launches the app; `main()` in `main.dart` calls `WidgetsFlutterBinding.ensureInitialized()`.
2. Arabic date formatting is initialized via `initializeDateFormatting('ar', null)`.
3. `.env` is loaded via `dotenv.load(fileName: ".env")`, with a guarded fallback if the file is missing.
4. `ApiClient.init(...)` constructs the singleton Dio client (base URL from `ApiConstants.baseUrl`, timeouts, headers) and attaches the `AuthInterceptor`, wiring its `onUnauthorized` callback to dispatch `LogoutEvent` on `AuthBloc`.
5. `runApp(const MyApp())` builds a `MultiBlocProvider` exposing `AuthBloc` and `DashboardBloc`, wraps the app in `MaterialApp` with Arabic localization and a global theming/`SafeArea`/gradient shell, and sets `SplashScreen` as the `home` route.
6. `SplashScreen` dispatches `CheckAuthEvent`; `AuthBloc` reads secure storage for a token/driver id and emits `AuthAuthenticated` or `AuthUnauthenticated`, and the splash screen's `BlocListener` navigates to `DashboardScreen` or `LoginScreen` accordingly.
7. On `DashboardScreen` init, `LoadDashboardData` (local cache) and `FetchDashboardData` (live backend fetch via `ApiClient`, triggering `SyncRepository.syncDown()`) are dispatched to `DashboardBloc`, populating the driver's session/visit/inventory state for the rest of the app.

---

## 7. Entry Points

| Sub-project | Entry point | Description |
|---|---|---|
| Backend | `wa_backend/main.py` | FastAPI ASGI application; primary HTTP entry point serving all `/driver`, `/admin`, `/dispatch`, `/warehouse`, `/shops`, `/product_variants`, `/login`, `/health`, `/ready` routes |
| Backend (maintenance) | `wa_backend/db_manager.py` | Standalone CLI entry point (`asyncio.run(main())`) for database reset/seed/cleanup operations, independent of the HTTP server |
| React Dashboard | `dashboard/src/main.tsx` → `dashboard/src/App.tsx` | Browser application entry point rendered into `index.html`; defines the client-side route table |
| Flutter App | `wanasah_frontend/lib/main.dart` | Cross-platform Flutter application entry point (`main()` / `MyApp`), landing on `SplashScreen` |
| Flutter Android host | `wanasah_frontend/android/app/src/main/kotlin/.../MainActivity.kt` | Native Android launcher activity embedding the Flutter engine |
| Flutter iOS/macOS host | `wanasah_frontend/ios/Runner/AppDelegate.swift`, `wanasah_frontend/macos/Runner/AppDelegate.swift` | Native Apple platform launcher embedding the Flutter engine |
| Flutter Windows/Linux host | `wanasah_frontend/windows/runner/main.cpp`, `wanasah_frontend/linux/runner/main.cc` | Native desktop launchers embedding the Flutter engine |
| Flutter Web host | `wanasah_frontend/web/index.html` | Web host page for Flutter's web renderer |

---

## 8. Cross-Project Relationships

- **Single backend, two clients.** Both the React dashboard and the Flutter app are independent HTTP clients of the same FastAPI backend (`wa_backend/`). Neither frontend talks to the database directly; all shared state flows through the backend's REST API.
- **Shared transport & auth model.** All inter-project communication uses JSON over HTTP with JWT bearer authentication issued by `wa_backend/api/auth.py` (`create_access_token`, HS256, 24h expiry). Both clients attach the token as an `Authorization: Bearer <token>` header:
  - React: `useAuthFetch` (`dashboard/src/hooks/useAuthFetch.ts`) reads the token from `localStorage` and calls the API at `import.meta.env.VITE_API_URL`.
  - Flutter: `AuthInterceptor` (`wanasah_frontend/lib/core/network/api_client.dart`) reads the token from `flutter_secure_storage` and calls the API at `ApiConstants.baseUrl` (from `API_BASE_URL`).
- **Role-separated API surfaces on one backend.**
  - The React dashboard primarily consumes the **admin/dispatch/warehouse** endpoint groups (`api/dispatch.py`, `api/warehouse.py`, plus the admin `/login` route in `api/auth.py`), reflecting its role as the office/operations control surface.
  - The Flutter app primarily consumes the **driver** endpoint group (`api/driver.py`, plus the driver `/driver/login` route and shared `/shops`, `/product_variants` routes), reflecting its role as the field-operations client.
  - Both surfaces are backed by the same underlying domain models in `wa_backend/models.py` (e.g., `WorkSession`, `Visit`, `InventoryTransfer`, `MainWarehouse`), so actions taken in one client (e.g., an admin authorizing a session, or a warehouse dispatch) become visible to the other client through subsequent API calls.
- **Offline-first field client vs. always-online admin client.** The Flutter app maintains a local SQLite cache (`core/db/local_database.dart`) and a pending-operations queue, synchronized through `SyncRepository` (`syncDown`/`syncUp`/`saveInvoice`), allowing drivers to keep working without connectivity and reconcile with the backend later. The React dashboard has no offline/local-storage layer of its own and instead polls the backend directly (e.g., `OperationsDashboard` polling `/admin/sessions/today`) for near-real-time visibility into what field drivers are doing.
- **Operational handshake loop.** Dispatch/warehouse actions performed in the React dashboard (e.g., launching a route with a vehicle inventory load via `POST /dispatch/route`, or approving an inventory transfer) create backend state that the Flutter app later reads and acts on (e.g., a driver starting a work session via `POST /driver/{id}/sessions/start`, or responding to a pending transfer via `PUT /driver/transfers/{id}/respond`). Conversely, driver-submitted visits (`PUT /visits/{id}`) and settlement data flow back into the dashboard's settlement and reporting views (`/admin/sessions/{id}/settlement_report`, `/admin/sessions/{id}/settle`).
- **Database as shared ground truth.** PostgreSQL, accessed exclusively through `wa_backend/database.py` and the SQLAlchemy models in `wa_backend/models.py`, is the only persistent shared state between the two client applications; Alembic (`wa_backend/alembic/`) manages its schema evolution independently of either frontend.
