# Wanasah — Unified Final Audit Report

> **Phase 13 Deliverable** — Master Summary Across All 12 Review Phases  
> **Reports Aggregated**: `auth.md`, `dispatch.md`, `warehouse.md`, `driver.md`, `dashboard.md`, `flutter.md`, `schema.md`, `security.md`, `cross-stack/system.md`, `production_readiness.md`  
> **Cross-Referenced Against**: `.ai-review/04_BUSINESS_RULES.md`  
> **Date**: 2026-07-24

---

## 1. Total Issue Counts — By Severity & System Layer

### 1.1 Aggregate Severity Distribution

| Severity | Count | Percentage |
|----------|-------|------------|
| 🔴 Critical | **15** | 12.5% |
| 🟠 High     | **35** | 29.2% |
| 🟡 Medium   | **47** | 39.2% |
| 🟢 Low      | **23** | 19.2% |
| **TOTAL**   | **120** | 100% |

### 1.2 Distribution by System Layer

| Layer | Module / Report | Critical | High | Medium | Low | Subtotal |
|-------|-----------------|----------|------|--------|-----|----------|
| **Backend** | `auth.md` | 0 | 1 | 4 | 4 | **9** |
| **Backend** | `dispatch.md` | 1 | 2 | 8 | 4 | **15** |
| **Backend** | `warehouse.md` | 1 | 1 | 3 | 2 | **7** |
| **Backend** | `driver.md` | 1 | 1 | 2 | 2 | **6** |
| **Database** | `schema.md` | 1 | 4 | 5 | 3 | **13** |
| **Frontend** | `dashboard.md` | 3 | 7 | 10 | 4 | **24** |
| **Frontend** | `flutter.md` | 3 | 8 | 5 | 0 | **16** |
| **Security** | `security.md` | 1 | 3 | 5 | 3 | **12** |
| **Cross-Stack** | `system.md` | 4 | 8 | 5 | 3 | **20** |

| **Grand Total** | | **15** | **35** | **47** | **23** | **120** |

### 1.3 Distribution by OWASP / Flaw Category (Top Categories)

| Flaw Category | Count | Severity Mix |
|---------------|-------|-------------|
| Race Condition (TOCTOU / Stale Read / Lost Update) | 18 | 4C, 8H, 6M |
| Missing Validation / CheckConstraint | 15 | 2C, 3H, 7M, 3L |
| Missing Index / N+1 Risk | 7 | 0C, 4H, 3M |
| Contract Mismatch (Cross-Stack) | 6 | 2C, 2H, 2M |
| Missing Security Header / Rate Limit / CORS | 6 | 0C, 4H, 2M |
| Fire-and-Forget / Silent Data Loss | 5 | 2C, 2H, 1M |
| Missing `ondelete` / Referential Integrity | 3 | 0C, 1H, 1M, 1L |
| Config Hardcoding / Unsafe Default | 5 | 2C, 2H, 1M |
| JWT Misconfiguration | 3 | 0C, 0H, 3M |
| State Management / UI Freeze | 4 | 0C, 2H, 2M |

---

## 2. TOP 20 Most Critical System Flaws

> Ranked by impact: financial data corruption > security bypass > operational bricking > deployment impossibility.

| Rank | Issue ID(s) | Severity | Layer(s) | File(s) | Impact Summary |
|------|------------|----------|----------|---------|----------------|
| **1** | `schema.md C-01` | 🔴 Critical | Database | `wa_backend/models.py:1` | **`text` not imported → `NameError` at module load → entire backend crashes at startup.** All 3 partial unique indexes on `DispatchRoute` never created in any database. Route concurrency protection absent. |
| **2** | `dashboard.md C-01` + `dashboard.md C-02` | 🔴 Critical | Frontend | `dashboard/src/pages/Login.tsx:43`, `dashboard/src/hooks/useAuthFetch.ts:6` | **Dashboard hardcoded to `127.0.0.1:5000/login`.** Cannot deploy to staging/production. Empty API fallback produces broken protocol-relative URLs. Combined: dashboard is 100% non-functional outside localhost. |
| **3** | `driver.md Finding #1` | 🔴 Critical | Backend | `wa_backend/api/driver.py:682-708` | **Indentation bug: accounting/balance update block indented inside `elif Postponed` → dead code.** Shop balances, debt payments, and `DEBT_COLLECTION` audit logs never written for `Sale`/`NoSale` visits. Entire financial accounting engine is a no-op. |
| **4** | `CS-WH-01` | 🔴 Critical | Cross-Stack | `warehouse.py:57-67`, `MainInventory.tsx` | **Duplicate supplier invoice booking via TOCTOU.** Unlocked `SELECT` + no dashboard debounce + no DB `UNIQUE` constraint = same invoice booked twice. Warehouse stock permanently inflated. |
| **5** | `CS-03` | 🔴 Critical | Cross-Stack | `sync_repository.dart:279-288` | **Fire-and-forget `new_balance` update silently dropped.** The ONLY mechanism for server-authoritative financial state sync to local SQLite (BR §6.5) is never awaited. Driver sees stale shop balances permanently. |
| **6** | `CS-02` | 🔴 Critical | Cross-Stack | `sync_repository.dart:81-107`, driver refresh endpoint | **Empty server product response atomically wipes all local inventory.** Atomic transaction becomes atomic data annihilation. Driver bricked in the field. |
| **7** | `security.md S-01` | 🔴 Critical | Security | `wa_backend/main.py:97-98`, `auth.py` | **`X-Forwarded-For` spoofing bypasses brute-force protection.** Attacker sends each attempt with a different forged IP → rate counter never triggers → unlimited password guessing. |
| **8** | `dispatch.md Finding #1` | 🔴 Critical | Backend | `wa_backend/api/dispatch.py:1983-2013` | **Phantom stock fabrication: negative carton input credits warehouse stock.** `abs(delta_packs)` credited to `MainWarehouse` when admin submits negative quantity. Sidesteps `chk_vload_qty` by deleting the row instead of writing negative value. Warehouse stock manufactured out of thin air. |
| **9** | `flutter.md Issue #3` | 🔴 Critical | Frontend | `wanasah_frontend/lib/repositories/sync_repository.dart:81-107` | **Empty product list from server wipes local stock data.** Same as CS-02 from Flutter perspective. `refreshSessionData(visitModels, [])` deletes all products, inserts zero rows. |
| **10** | `CS-04` | 🟠 High | Cross-Stack | `local_database.dart`, `sync_repository.dart`, driver endpoints | **Ghost pending syncs survive server-side session deletion.** `clearSessionData()` preserves `pending_sync` table. Old invoices from deleted sessions pollute new session queue, causing 404/403 loops or financial misattribution. |
| **11** | `CS-05` | 🟠 High | Cross-Stack | `visit_bloc.dart:171-177`, `api/driver.py` | **Flutter BLoC Equatable excludes `errorMessage` → server rejection messages are invisible to drivers.** Server correctly sends detailed Arabic rejection messages; Flutter BLoC correctly captures them; Equatable considers new state identical to old → UI never rebuilds. Driver retries indefinitely with no feedback. |
| **12** | `security.md S-02` | 🟠 High | Security | `wa_backend/main.py` | **Zero rate limiting on all endpoints.** Financially sensitive operations (`/dispatch/settle-session`, `/warehouse/inbound`) have no protection. Volumetric DoS can exhaust `pool_size=50` in seconds. No distinction between authenticated and unauthenticated rate limits. |
| **13** | `CS-06` | 🟠 High | Cross-Stack | `Login.tsx:43`, `useAuthFetch.ts:6` | **Dashboard undeployable.** Combined hardcoded login URL + empty API fallback. Every non-localhost deployment scenario is broken. Production CORS origins are placeholders. |
| **14** | `CS-WH-02` | 🟠 High | Cross-Stack | `warehouse.py:611-630`, `MainInventory.tsx` | **Concurrent invoice adjustments corrupt ledger via stale-read delta computation.** `current_invoice_total_packs` read without lock, delta computed, then `MainWarehouse` locked. Classic lost-update: two admins see 500 packs, each adjusts to different totals, final state is wrong. |
| **15** | `dispatch.md Finding #2` | 🟠 High | Backend | `wa_backend/api/dispatch.py:439-466` | **Deadlock risk: `settle_session` locks `SessionInventory` BEFORE `VehicleLoad`/`MainWarehouse`.** Violates mandated lock order (BR §1.8). Text-book deadlock with concurrent `dispatch_route`/`adjust_route_inventory`. |
| **16** | `dashboard.md C-03` | 🔴 Critical | Frontend | `dashboard/src/pages/DispatchBoard.tsx:787-795` | **DOM-manipulation product search breaks under React reconciliation.** Uses `document.querySelectorAll` and inline `style.display` mutation. Any state change (setInterval refresh, tab switch) resets filters silently. Search appears functional but is architecturally incompatible with React. |
| **17** | `flutter.md Issue #4` | 🟠 High | Frontend | `sync_repository.dart:279-288` | **Fire-and-forget SQL update for shop balance on sync.** `await _db.database.then((db) { db.rawUpdate(...) })` only awaits `.then()` scheduling, not the `rawUpdate`. Same root cause as CS-03 from Flutter perspective. |
| **18** | `dispatch.md Finding #3` | 🟠 High | Backend | `wa_backend/api/dispatch.py:2620-2628` | **Logic bug: dict-overwrite ordering in `add_shortages` produces wrong visit selection.** Query orders by `id DESC` intending newest, but dict comprehension keeps oldest per shop. Financial corruption shield operates on stale visit row. |
| **19** | `flutter.md Issue #1` | 🔴 Critical | Frontend | `wanasah_frontend/lib/core/db/local_database.dart:90-141` | **SQLite type mismatch: TEXT vs REAL on monetary columns diverges between fresh install and upgrade path.** `SUM(cash_collected)` returns different results depending on column affinity. Silent financial data corruption differing per user install history. |
| **20** | `security.md S-03` | 🟠 High | Security | `wa_backend/main.py` | **Missing all HTTP security headers.** No HSTS (SSL-stripping), no CSP (XSS), no X-Frame-Options (clickjacking), no X-Content-Type-Options (MIME-sniffing). Admin dashboard vulnerable to clickjacking; JWT exfiltratable in cleartext without HSTS. |

---

## 3. Production Readiness Verdict

### Final Score: **20 / 100 (20%)** — 🔴 NOT PRODUCTION READY

The system is architecturally well-conceived (strong domain modeling for FMCG field operations, correct identification of business invariants, well-designed mid-day handshake and offline-sync patterns) but **operationally unsafe** for any production deployment in its current state.

### Key Blocking Factors

| Factor | Root Cause(s) | Consequence |
|--------|---------------|-------------|
| **Cannot deploy** | Dashboard hardcoded to `127.0.0.1:5000`; backend crashes on import (`text` not imported) | Neither frontend nor backend can run outside dev machine |
| **Financial data corruption** | Indentation bug dead-codes accounting engine; duplicate invoice TOCTOU; fire-and-forget balance writes; stale-read ledger deltas | Shop balances never update; stock inflated; driver debt views permanently stale |
| **Security defenseless** | No rate limiting; `X-Forwarded-For` spoofing bypasses brute-force; no security headers; weak JWT config; API docs exposed by default | Unlimited password guessing; volumetric DoS; JWT exfiltration; clickjacking |
| **Offline sync brittle** | Empty product response wipes inventory; ghost pending syncs survive session reset; Equatable suppresses server errors | Drivers bricked in field; old invoices pollute new sessions; no error feedback |
| **Observability absent** | Log level hardcoded to ERROR; no correlation IDs; DB passwords leak into logs; no successful login audit | Incident response impossible; compliance (PCI/ISO) violated |

---

## 4. Surgical Remediation Roadmap

### Phase 1: DB & Imports (Day 0 — Before Any Other Work)

**Objective**: Make the system start and create all required database objects.

| Step | Issue | Action | File(s) |
|------|-------|--------|---------|
| 1.1 | `schema.md C-01` | Add `text` to SQLAlchemy imports | `wa_backend/models.py:1` |
| 1.2 | `schema.md H-01` | Widen partial unique indexes to cover `waiting`/`postponed` statuses | `wa_backend/models.py:251-255` |
| 1.3 | `schema.md H-02` | Add `ondelete='SET NULL'` to `Zone.governorate_id` FK | `wa_backend/models.py:64` |
| 1.4 | `schema.md H-03` | Add `CheckConstraint('quantity >= 0')` to `ShortageRequest.quantity` | `wa_backend/models.py:379` |
| 1.5 | `schema.md H-04` | Create composite index `ix_ws_driver_unsettled` | `wa_backend/models.py` (WorkSession) |
| 1.6 | `schema.md M-01` | Add `UniqueConstraint('name', 'country_id')` on Governorate | `wa_backend/models.py` (Governorate) |
| 1.7 | `schema.md M-02` | Add `UniqueConstraint('name', 'governorate_id')` on Zone | `wa_backend/models.py` (Zone) |
| 1.8 | `schema.md M-03` | Create composite index `ix_visit_shop_timestamp` | `wa_backend/models.py` (Visit) |
| 1.9 | `schema.md M-04` | Create composite index `ix_visit_session_outcome` | `wa_backend/models.py` (Visit) |
| 1.10 | `CS-WH-01` (DB) | Add partial `UNIQUE` index on `WarehouseLedger(reference_id)` for supplier invoices | `wa_backend/models.py` (WarehouseLedger) |
| 1.11 | `CS-11` | Add `CheckConstraint('packs_per_carton > 0')` on `ProductVariant.packs_per_carton` | `wa_backend/models.py:131` |

**Estimated Effort**: 2–4 hours. All changes are additive (indexes, constraints) or single-line fixes. Run Alembic migration after changes.

---

### Phase 2: Security & Rate Limits (Day 1–2)

**Objective**: Close the security perimeter — prevent unlimited brute-force, add rate limiting, configure security headers.

| Step | Issue | Action | File(s) |
|------|-------|--------|---------|
| 2.1 | `security.md S-01` | Replace manual `X-Forwarded-For` parsing with hardened `get_real_ip()` using trusted proxy CIDRs | `wa_backend/main.py` + new `wa_backend/security.py` |
| 2.2 | `security.md S-02` | Add `slowapi` rate limiter (200/min global, 10/min login, 30/min dispatch) | `wa_backend/main.py`, `api/auth.py`, `api/dispatch.py` |
| 2.3 | `security.md S-03` | Add `SecurityHeadersMiddleware` with HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy | `wa_backend/main.py` |
| 2.4 | `security.md S-04` | Restrict CORS `allow_methods`/`allow_headers` to explicit lists; externalize origins to env var | `wa_backend/main.py:50-61` |
| 2.5 | `security.md S-05` | Change `ENVIRONMENT` default to `"production"`; add explicit `ENABLE_API_DOCS` flag | `wa_backend/main.py:37,43-45` |
| 2.6 | `security.md S-08` | Enforce `SECRET_KEY` minimum 32-char length + entropy diversity at startup | `wa_backend/config.py:8-11` |
| 2.7 | `security.md S-06` | Add `BodySizeLimitMiddleware` (10MB) + Nginx `client_max_body_size` | `wa_backend/main.py` + Nginx config |
| 2.8 | `security.md S-10` | Add `sanitize_error_message()` to redact `DATABASE_URL` from stack traces | `wa_backend/main.py` |
| 2.9 | `auth.md Finding #1` | Replace two-step brute-force (check then log) with atomic `record_and_check_brute_force` | `wa_backend/api/auth.py:33-92` |
| 2.10 | `auth.md Finding #2` | Add `iat`, `jti`, `type` claims to JWT tokens | `wa_backend/api/auth.py:27-31` |

**Estimated Effort**: 8–12 hours. Most items are middleware additions or single-function refactors.

---

### Phase 3: Financial & Offline Sync Integrity (Day 3–5)

**Objective**: Fix data-corruption bugs in accounting, warehouse, and offline sync paths.

| Step | Issue | Action | File(s) |
|------|-------|--------|---------|
| 3.1 | `driver.md Finding #1` | Fix indentation: outdent accounting/balance update block from `elif Postponed` to top-level | `wa_backend/api/driver.py:682-708` |
| 3.2 | `dispatch.md Finding #1` | Reject negative `new_cartons` before delta computation in `update_route_status` | `wa_backend/api/dispatch.py:1983-2013` |
| 3.3 | `CS-WH-01` (Backend) | Add `pg_advisory_xact_lock` on normalized invoice reference before duplicate check | `wa_backend/api/warehouse.py:57-67` |
| 3.4 | `CS-WH-02` | Reorder `adjust_warehouse_entry`: lock `MainWarehouse` FIRST, then compute invoice sum | `wa_backend/api/warehouse.py:611-630` |
| 3.5 | `dispatch.md Finding #2` | Fix lock ordering in `settle_session`: `VehicleLoad` → `MainWarehouse` → `SessionInventory` | `wa_backend/api/dispatch.py:439-466` |
| 3.6 | `dispatch.md Finding #6` | Add `.with_for_update()` to `DispatchRoute` read in `settle_session` | `wa_backend/api/dispatch.py:429-430` |
| 3.7 | `dispatch.md Finding #7` | Add `.with_for_update()` to `WorkSession` read in `dispatch_route` | `wa_backend/api/dispatch.py:763-764` |
| 3.8 | `dispatch.md Finding #8` | Add `.with_for_update()` to `VehicleLoad` read in `update_route_status` driver-switch branch | `wa_backend/api/dispatch.py:1895` |
| 3.9 | `CS-03` | Fix fire-and-forget `new_balance` update: properly `await` the database operation | `wanasah_frontend/lib/repositories/sync_repository.dart:279-288` |
| 3.10 | `CS-02` | Guard `syncDown()` against empty product list — do not truncate table when data is empty | `wanasah_frontend/lib/repositories/sync_repository.dart:81-107` |
| 3.11 | `CS-04` | Add `clearPendingSyncs` parameter to `clearSessionData()`; pass `true` on server-side session reset | `wanasah_frontend/lib/core/db/local_database.dart`, `dashboard_screen.dart` |
| 3.12 | `CS-WH-04` | Include `pending_transfers` in session refresh endpoint response | `wa_backend/api/driver.py` (session refresh) |
| 3.13 | `flutter.md Issue #1` | Normalize TEXT→REAL monetary columns via safe v7 migration | `wanasah_frontend/lib/core/db/local_database.dart` |
| 3.14 | `flutter.md Issue #2` | Guard database singleton with `Future`-based lock | `wanasah_frontend/lib/core/db/local_database.dart:36-39` |
| 3.15 | `CS-01` | Move `cash_collected`/`debt_paid` inside `Sale`/`NoSale` guard in Flutter payload | `wanasah_frontend/lib/blocs/visit/visit_bloc.dart:440-457` |

**Estimated Effort**: 16–24 hours. Financial correctness is non-negotiable; every change in this phase must be accompanied by a targeted test.

---

### Phase 4: Frontend Fixes (Day 6–8)

**Objective**: Make the dashboard deployable and fix critical UI bugs.

| Step | Issue | Action | File(s) |
|------|-------|--------|---------|
| 4.1 | `dashboard.md C-01` | Replace hardcoded `127.0.0.1:5000/login` with `VITE_API_URL` | `dashboard/src/pages/Login.tsx:43` |
| 4.2 | `dashboard.md C-02` | Validate `VITE_API_URL` at startup; throw clear error if missing | `dashboard/src/hooks/useAuthFetch.ts:6` |
| 4.3 | `dashboard.md C-03` | Replace DOM-manipulation search with React state + `useMemo` filtered list | `dashboard/src/pages/DispatchBoard.tsx:787-795` |
| 4.4 | `dashboard.md H-01` | Remove legacy `token` fallback from localStorage read | `dashboard/src/hooks/useAuthFetch.ts:9` |
| 4.5 | `dashboard.md H-02` | Pass `AbortController` signal to all concurrent fetch calls | `dashboard/src/pages/DispatchBoard.tsx:173-175` |
| 4.6 | `dashboard.md H-04` | Implement exponential backoff with jitter on polling (30s base, 120s max) | `dashboard/src/pages/OperationsDashboard.tsx:144-149` |
| 4.7 | `dashboard.md H-05` | Add JWT expiry check in `ProtectedRoute` | `dashboard/src/App.tsx:17-18` |
| 4.8 | `dashboard.md H-06` | Remove `admin_name`/`admin_id` from localStorage; derive from JWT payload | `dashboard/src/pages/Login.tsx:64-66` |
| 4.9 | `dashboard.md H-07` | Add `isNavigating` guard to prevent multiple `navigate("/login")` calls | `dashboard/src/hooks/useAuthFetch.ts:21-25` |
| 4.10 | `CS-05` | Add `errorMessage` to Flutter BLoC `Equatable` props | `wanasah_frontend/lib/blocs/visit/visit_bloc.dart:171-177` |
| 4.11 | `CS-WH-03` | Fetch `warehouse_status` on DispatchBoard mount; display warning banner when locked | `dashboard/src/pages/DispatchBoard.tsx` |
| 4.12 | `flutter.md Issue #5` | Replace `assert` with runtime `StateError` in `ApiClient.instance` | `wanasah_frontend/lib/core/network/api_client.dart:82-88` |
| 4.13 | `flutter.md Issue #10` | Add `sendTimeout: Duration(seconds: 30)` to Dio `BaseOptions` | `wanasah_frontend/lib/core/network/api_client.dart:95-106` |
| 4.14 | `flutter.md Issue #11` | Use `jsonEncode` instead of string interpolation for pending sync payloads | `wanasah_frontend/lib/screens/dashboard_screen.dart:254-257` |
| 4.15 | `flutter.md Issue #13` | Add `clearPendingSyncs: true` on 404 session reset | `wanasah_frontend/lib/screens/dashboard_screen.dart` |

**Estimated Effort**: 12–16 hours. Many fixes are single-line changes. The DispatchBoard search refactor (4.3) is the largest item.

---

### Phase 5: Observability & Hardening (Day 9–10)

**Objective**: Add logging, tracing, and monitoring for production operations.

| Step | Issue | Action | File(s) |
|------|-------|--------|---------|
| 5.1 | `security.md S-12` | Add `RequestIDMiddleware` with UUID generation and `X-Request-Id` response header | `wa_backend/main.py` |
| 5.2 | `security.md S-09` | Log `SUCCESSFUL_LOGIN` events to `SystemAuditLog` | `wa_backend/api/auth.py` |
| 5.3 | (Not filed) | Make `LOG_LEVEL` configurable via `LOG_LEVEL` env var; default to `INFO` | `wa_backend/main.py:14` |
| 5.4 | `auth.md Finding #3` | Implement JWT `TokenBlacklist` table + logout endpoint | `wa_backend/models.py`, `wa_backend/api/auth.py`, `wa_backend/api/dependencies.py` |
| 5.5 | `auth.md Finding #7` | Add `get_current_driver_owned` dependency for IDOR prevention | `wa_backend/api/dependencies.py` |
| 5.6 | `warehouse.md Finding #7` | Replace catch-all `else` in `balance_before` reconstruction with explicit whitelist | `wa_backend/api/warehouse.py:432-437` |
| 5.7 | `driver.md Finding #4` | Validate `payload.response` ∈ `['accepted', 'rejected']` in `respond_to_transfer` | `wa_backend/api/driver.py:935-936` |
| 5.8 | `CS-WH-05` | Store `balance_before_packs` as column on `WarehouseLedger` (eliminate reconstruction) | `wa_backend/models.py` (WarehouseLedger) |
| 5.9 | `CS-07` | Add `RequestTimeoutMiddleware` (45s) to release DB connections from hanging requests | `wa_backend/main.py` |
| 5.10 | `CS-14` | Reset `ledgerFetchedRef` on stocktake completion; add `fetchLedger(true)` to stocktake callback | `dashboard/src/pages/inventory/MainInventory.tsx` |

**Estimated Effort**: 8–12 hours.

---

## 5. Post-Remediation Re-Test Checklist

Before any production deployment, verify:

- [ ] `python -c "from wa_backend.models import DispatchRoute"` succeeds (Phase 1.1).
- [ ] Dashboard login works from `https://staging-api.example.com` (Phase 4.1).
- [ ] `POST /warehouse/inbound` with duplicate `reference_id` returns 409 under concurrent load (Phase 3.3).
- [ ] `POST /dispatch/settle-session` does not deadlock when run concurrently with `POST /dispatch/route` (Phase 3.5).
- [ ] Flutter `syncDown()` with empty server `inventory` does not wipe local products (Phase 3.10).
- [ ] Flutter visit submission rejected by server → red SnackBar appears with server's Arabic message (Phase 4.10).
- [ ] `GET /admin/sessions/today` has rate limit header; 6th request in 1 minute returns 429 (Phase 2.2).
- [ ] `curl -H "X-Forwarded-For: 1.2.3.4" https://api/health` logs the correct real client IP, not `1.2.3.4` (Phase 2.1).
- [ ] `traceback.format_exc()` output in `error.log` contains `***REDACTED***` instead of DB password (Phase 2.8).
- [ ] `GET /docs` returns 404 in production when `ENABLE_API_DOCS=false` (Phase 2.5).

---

## 6. Risk Acceptance / Known Residuals

The following items are acknowledged as **non-blocking for initial go-live** but should be tracked:

| Item | Risk | Mitigation |
|------|------|------------|
| No WebSocket/SSE for real-time dashboard updates | Admins must manually refresh or rely on polling | Acceptable for single-digit admin count; implement in v1.1 |
| `OfferRule` has no per-product targeting (`schema.md M-05`) | Global-only offers; per-product promotions require migration | Acceptable for MVP; document schema migration path |
| No horizontal scaling (single FastAPI process) | Traffic limited to pool_size=50 connections | Acceptable for <50 concurrent drivers; add Gunicorn workers + load balancer for v1.1 |
| Flutter local returns handling asymmetry (`CS-12`) | Driver local stock may drift from server truth | Mitigated by periodic `syncDown()`; implement full local return tracking in v1.1 |
| `SystemSetting` has no value validation at schema level (`security.md S-11`) | Typo in `warehouse_status` value causes silent failure | Mitigated by CheckConstraint added in Phase 1; full enum migration in v1.1 |

---

*End of Phase 13 — Unified Final Audit Report*

---

## Appendix A: Quick Reference — All Issues by ID

| ID | Severity | Report | Description (Abbreviated) |
|----|----------|--------|---------------------------|
| C-01 (schema) | Critical | schema.md | `text` not imported → backend crashes at startup |
| C-01 (dashboard) | Critical | dashboard.md | Login URL hardcoded to `127.0.0.1:5000` |
| C-02 (dashboard) | Critical | dashboard.md | Empty API fallback → protocol-relative URLs |
| C-03 (dashboard) | Critical | dashboard.md | DOM search breaks under React reconciliation |
| #1 (dispatch) | Critical | dispatch.md | Phantom stock via negative carton input |
| #1 (warehouse) | Critical | warehouse.md | Duplicate invoice via TOCTOU (unlocked SELECT) |
| #1 (driver) | Critical | driver.md | Indentation bug dead-codes accounting engine |
| #1 (flutter) | Critical | flutter.md | TEXT vs REAL type mismatch on monetary columns |
| #2 (flutter) | Critical | flutter.md | Database singleton race condition |
| #3 (flutter) | Critical | flutter.md | Empty server product list wipes local inventory |
| S-01 | Critical | security.md | X-Forwarded-For spoofing bypasses brute-force |
| CS-01 | Critical | system.md | Flutter sends cash/debt for Postponed visits |
| CS-02 | Critical | system.md | Empty product response wipes local inventory |
| CS-03 | Critical | system.md | Fire-and-forget new_balance update |
| CS-WH-01 | Critical | system.md | Dashboard forks duplicate supplier invoices |
| *(35 High issues — see per-report details)* | | | |
| *(47 Medium issues — see per-report details)* | | | |
| *(23 Low issues — see per-report details)* | | | |

---

## Appendix B: Report File Inventory

| # | Report Path | Issues | Date |
|---|-------------|--------|------|
| 1 | `.ai-review/reviews/backend/auth.md` | 9 | 2026-07-24 |
| 2 | `.ai-review/reviews/backend/dispatch.md` | 15 | 2026-07-24 |
| 3 | `.ai-review/reviews/backend/warehouse.md` | 7 | 2026-07-24 |
| 4 | `.ai-review/reviews/backend/driver.md` | 6 | 2026-07-24 |
| 5 | `.ai-review/reviews/frontend/dashboard.md` | 24 | 2026-07-24 |
| 6 | `.ai-review/reviews/frontend/flutter.md` | 16 | 2026-07-24 |
| 7 | `.ai-review/reviews/database/schema.md` | 13 | 2026-07-24 |
| 8 | `.ai-review/reviews/security/security.md` | 12 | 2026-07-24 |
| 9 | `.ai-review/reviews/cross-stack/system.md` | 20 | 2026-07-24 |
| 10 | `.ai-review/production/production_readiness.md` | (Assessment) | 2026-07-24 |
| 11 | `.ai-review/FINAL_REPORT.md` | (This file) | 2026-07-24 |

---

*End of Document — Wanasah Unified Final Audit Report*