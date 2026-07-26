# Cross-Stack System Integrity Audit — Wanasah

> Phase 11 Deliverable — Cross-Stack Integration Audit  
> Sources analyzed: `.ai-review/04_BUSINESS_RULES.md`, `.ai-review/reviews/backend/dispatch.md`, `.ai-review/reviews/backend/driver.md`, `.ai-review/reviews/backend/auth.md`, `.ai-review/reviews/frontend/dashboard.md`, `.ai-review/reviews/frontend/flutter.md`, `.ai-review/reviews/database/schema.md`, `.ai-review/reviews/security/security.md`  
> Audit Date: 2026-07-24  
> Scope: End-to-end integration disconnects between Flutter Mobile, React Dashboard, FastAPI Backend, and PostgreSQL Database

---

## Executive Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High     | 5 |
| Medium   | 4 |
| Low      | 2 |
| **Total** | **14** |

> This audit identifies integration flaws that **span two or more system layers**. Issues confined to a single layer (even if Critical within that layer) are cross-referenced here only when they create a cross-stack disconnect. For single-layer findings, see the respective per-module audit reports.

---

## 🔴 Critical

### CS-01: Flutter Sends Debt/Cash Fields for Postponed Visits — Server "Postponed Theft Shield" Enforces Opposite Contract

- **Severity**: **Critical**
- **Integration Boundary**: **Flutter BLoC (`visit_bloc.dart`) ↔ FastAPI Router (`api/driver.py` update_visit)**
- **Source Reports**: `flutter.md` Issue #11; `driver.md` (implicit in `update_visit` logic); `04_BUSINESS_RULES.md` §3.4

- **Flaw Description & Impact Analysis**:
  The Flutter `_onSubmitVisit` handler in `visit_bloc.dart` (lines 440–457) constructs a payload where `cash_collected` and `debt_paid` are placed at the top level of the JSON payload and sent **unconditionally for all outcomes**, including `Postponed`:

  ```dart
  // Flutter — visit_bloc.dart (from flutter.md Issue #11)
  final payload = {
    'visit_id': event.visitId,
    'visitId': event.visitId,
    'outcome': event.outcome,
    'notes': event.notes ?? '',
    'cash_collected': currentState.cashCollected,  // ← SENT UNCONDITIONALLY
    'debt_paid': event.debtPaid,                    // ← SENT UNCONDITIONALLY
  };
  ```

  Business Rule §3.4 explicitly states: **"Postponed must contain no cart items, no returns, and no debt payment — postponing a visit while sneaking in a sale to avoid immediate accounting is explicitly blocked ('Postponed Theft Shield')."**

  The server-side `update_visit` in `driver.py` enforces this rule. The cross-stack disconnect is:
  
  1. **Flutter sends `debt_paid > 0` on a Postponed visit** — this happens when a driver fills in cash/debt fields, then changes their mind and selects "Postponed" as the outcome. The Flutter payload still carries the non-zero values.
  2. **Server rejects with 400** — the "Postponed Theft Shield" check (`payload.outcome == 'Postponed' and (payload.cart_items or payload.returns or payload.debt_paid > 0)`) triggers and rejects the request.
  3. **Flutter receives 400** — but per `sync_repository.dart` offline rules (BR §6.3), a 4xx business rejection is **rethrown immediately and NOT queued** — the driver sees an error but the Flutter error message may be generic, not explaining that they need to clear the cash/debt fields before selecting Postponed.
  4. **Local SQLite is updated anyway** — `saveInvoice` in `sync_repository.dart` updates local state before the network call succeeds or fails (line 121 context in flutter.md). The local `cash_collected` and `debt_paid` columns get non-zero values for a Postponed visit, creating a **permanent local/server state divergence** that only a full `syncDown()` can correct — and `syncDown()` is blocked if non-`submit_sale` pending records exist (BR §6.4).

  The root cause is a **contract mismatch**: Flutter treats `cash_collected`/`debt_paid` as always-present fields, while the server treats their mere presence on a Postponed visit as a security violation. Neither side is wrong in isolation — the contract is ambiguous and implemented differently at each end.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix** (immediate): Move `cash_collected` and `debt_paid` inside the `if (event.outcome == 'Sale' || event.outcome == 'NoSale')` guard, so they are only sent when semantically valid:
     ```dart
     final payload = <String, dynamic>{
       'visit_id': event.visitId,
       'visitId': event.visitId,
       'outcome': event.outcome,
       'notes': event.notes ?? '',
     };
     if (event.outcome == 'Sale' || event.outcome == 'NoSale') {
       payload['cash_collected'] = currentState.cashCollected;
       payload['debt_paid'] = event.debtPaid;
       if (cartItems.isNotEmpty) payload['cart_items'] = cartItems;
       if (returns.isNotEmpty) payload['returns'] = returns;
     }
     ```

  2. **Backend fix** (defense-in-depth): In `driver.py update_visit`, add a specific, actionable error message when the Postponed Theft Shield triggers so the Flutter BLoC can surface it:
     ```python
     if payload.outcome == 'Postponed' and (payload.cart_items or payload.returns or debt_paid_input > Decimal('0')):
         raise HTTPException(
             status_code=400,
             detail="مرفوض: لا يمكن تأجيل الزيارة مع وجود مبيعات أو تحصيل ديون. الرجاء مسح العربة والمدفوعات أولاً."
         )
     ```

  3. **Contract formalization**: Document in the API schema (Pydantic model or OpenAPI description) that `cash_collected` and `debt_paid` MUST be `null` or absent for `Postponed` outcomes.

---

### CS-02: Flutter Empty Product Response from Server Wipes Local Inventory — Atomic Transaction Becomes Atomic Data Annihilation

- **Severity**: **Critical**
- **Integration Boundary**: **Flutter `syncDown()` (`sync_repository.dart`) ↔ FastAPI Router (`api/driver.py` session refresh endpoint)**
- **Source Reports**: `flutter.md` Issue #3; `04_BUSINESS_RULES.md` §6.4

- **Flaw Description & Impact Analysis**:
  Flutter's `syncDown()` calls a server endpoint that returns a response containing `visits` and `inventory` (products) keys. The `sync_repository.dart` code (lines 81–107) parses this response and calls `refreshSessionData(visitModels, productModels)`. Inside `refreshSessionData`, the implementation performs an **atomic SQLite transaction**:

  ```dart
  // LocalDatabase — from flutter.md Issue #3 analysis
  await txn.delete('products');   // DELETE ALL products
  // batch insert productModels    // INSERT from server response
  ```

  The cross-stack disconnect occurs when the server responds with a **valid HTTP 200** but the `inventory` key is **missing or empty**:
  
  1. **Server-side scenario**: A future API refactoring changes the response shape. An admin force-resets the driver's session mid-day. The driver's route has zero loaded products (empty vehicle load). The server-side endpoint hits an edge case where `inventory` is omitted from the response dict.
  2. **Flutter receives an empty `productsData = []`** — the `if dataMap.containsKey('inventory')` check at line 148 is `False`, so `productsData` remains `[]`.
  3. **`refreshSessionData(visitModels, [])` executes**: The atomic transaction deletes all `products` rows and inserts zero rows.
  4. **Result**: The driver's entire local stock snapshot is **annihilated**. The dashboard shows "لا يوجد بضاعة في السيارة حالياً." The driver cannot create any cart items for any visit offline or online until a full `syncDown()` succeeds with valid inventory.

  Business Rule §6.4 states the syncDown atomic transaction "guarantees no partially-written/torn local state can exist even if the app is killed mid-sync." This guarantee works perfectly for data integrity but **amplifies the blast radius of an empty server payload** — what should be a minor glitch becomes a field-operations incident.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix** (immediate safety net): Do not truncate a table when the incoming dataset is empty — only refresh tables that have data:
     ```dart
     if (productModels.isNotEmpty) {
       await txn.delete('products');
       // batch insert productModels
     }
     if (visitModels.isNotEmpty) {
       await txn.delete('visits');
       // batch insert visitModels
     }
     // If both are empty, do nothing — keep existing local data as fallback
     ```

  2. **Backend fix** (contract guarantee): Ensure the session refresh endpoint **always** returns an `inventory` key (even if the value is `[]`) and document this as a non-negotiable API contract:
     ```python
     # In the driver session refresh endpoint
     return {
         "visits": visits_data,
         "inventory": inventory_data,  # ALWAYS present, never None, minimum []
     }
     ```

  3. **Contract formalization**: Add a Pydantic response model that makes `inventory` a required field typed as `List[InventoryItem]` with `min_items=0`.

---

### CS-03: Flutter Fire-and-Forget Balance Update Silently Drops Server-Authoritative Financial State

- **Severity**: **Critical**
- **Integration Boundary**: **Flutter `syncUp()` (`sync_repository.dart`) ↔ FastAPI `update_visit` response `new_balance` field**
- **Source Reports**: `flutter.md` Issue #4; `04_BUSINESS_RULES.md` §6.5

- **Flaw Description & Impact Analysis**:
  Business Rule §6.5 explicitly states: **"The server's returned `new_balance` (from a successfully synced sale) is the ONLY mechanism by which the authoritative financial state is written back into local SQLite outside of a full `syncDown()`."** This is the single critical path for keeping the driver's local financial view consistent with server truth between full syncs.

  In `sync_repository.dart` lines 279–288, this mechanism is implemented as a **fire-and-forget, non-awaited SQL update**:

  ```dart
  // Flutter — sync_repository.dart (from flutter.md Issue #4)
  if (response.data != null && response.data['new_balance'] != null) {
    final double newBalance =
        double.tryParse(response.data['new_balance'].toString()) ?? 0.0;
    await _db.database.then((db) {       // ← AWAITS THE .then(), NOT rawUpdate
      db.rawUpdate(                        // ← FIRES AND FORGETS
        'UPDATE visits SET shop_balance = ? WHERE visit_id = ?',
        [newBalance, visitId],
      );
    });
  }
  ```

  **Why this is a cross-stack issue, not just a Flutter bug**:
  
  1. **The server correctly sends `new_balance`** — the backend's `update_visit` computes and returns the authoritative shop balance after every sale. The server fulfills its side of the contract (BR §6.5).
  2. **The Flutter code intends to consume it** — the `if` guard correctly checks for `new_balance` presence.
  3. **But the update is never actually awaited** — `_db.database.then((db) { db.rawUpdate(...); })` returns a `Future<void>` from `.then()`, but the outer `await` only waits for the `.then()` to **schedule** the callback, not for the `rawUpdate` to complete. The SQL `UPDATE` is a fire-and-forget.

  The cross-stack result: **the server's authoritative financial truth is transmitted correctly but silently discarded by the client**. The driver's next visit to the same shop sees a stale `shop_balance` until the next `syncDown()` (which may be hours later). If the driver extends debt based on the stale balance, they may exceed the shop's `max_debt_limit` — the server will reject the next sale with a debt-ceiling error (BR §4.2), but the driver will be confused because their local UI showed available credit.

  This is the most insidious type of cross-stack bug: **both sides individually appear to work correctly**, but the integration glue is broken.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix** (critical): Properly await the database operation:
     ```dart
     if (response.data != null && response.data['new_balance'] != null) {
       final double newBalance =
           double.tryParse(response.data['new_balance'].toString()) ?? 0.0;
       final db = await _db.database;
       await db.rawUpdate(
         'UPDATE visits SET shop_balance = ? WHERE visit_id = ?',
         [newBalance, visitId],
       );
     }
     ```

  2. **Flutter defensive fix**: After the update, **verify** it took effect:
     ```dart
     final result = await db.rawUpdate(...);
     if (result == 0) {
       developer.log('[SyncRepo] WARNING: balance update affected 0 rows for visit $visitId');
     }
     ```

  3. **Backend enhancement**: Consider returning `new_balance` in a dedicated response field rather than nested inside `response.data`, making it harder for client code to accidentally mishandle:
     ```python
     return {
         "message": "Visit updated successfully",
         "new_balance": float(shop.current_balance),  # Top-level, hard to miss
         "visit_id": visit.id
     }
     ```

---

## 🟠 High

### CS-04: Flutter Ghost Pending Syncs on 404 Session Reset — Offline Queue Survives Server-Side Session Deletion

- **Severity**: **High**
- **Integration Boundary**: **Flutter `clearSessionData()` ↔ FastAPI 404 Response on Session Deletion**
- **Source Reports**: `flutter.md` Issue #13; `04_BUSINESS_RULES.md` §2.3, §6.3

- **Flaw Description & Impact Analysis**:
  When an admin forcefully deletes or resets a driver's session (e.g., `settle_session` + route reassignment per BR §2.6), the server returns HTTP 404 for subsequent requests targeting that session. The Flutter app's `dashboard_screen.dart` (lines 139, 188) handles this by calling `LocalDatabase.instance.clearSessionData()` to wipe local state and redirect to a fresh session flow.

  However, `clearSessionData()` **deliberately preserves the `pending_sync` table**:

  ```dart
  // Flutter — local_database.dart (from flutter.md Issue #13)
  Future<void> clearSessionData() async {
    final db = await database;
    await db.delete('products');
    await db.delete('visits');
    // ← pending_sync is NOT deleted
    developer.log('[LocalDatabase] Session tables (products, visits) cleared.');
  }
  ```

  The cross-stack disaster unfolds as follows:
  
  1. **Old session deleted on server** — the admin resets or force-settles a session. All visits, inventory, and route assignments for that session are finalized server-side.
  2. **Flutter clears local state** — `products` and `visits` tables are wiped. The driver sees a clean slate.
  3. **But `pending_sync` still contains offline invoices from the old session** — these are `submit_sale` records with `visit_id` values that now point to non-existent or already-settled visits on the server.
  4. **New session starts** — the driver begins a fresh workday with new inventory and new visits.
  5. **`syncUp()` runs** — it finds the ghost records in FIFO order and attempts to `PUT /visits/{old_visit_id}` with the stale payload.
  6. **Server response possibilities**:
     - If the old `visit_id` was deleted → HTTP 404 → the 4xx handler in `syncUp()` **skips** the record but keeps it queued (per BR §6.3 "other 4xx: record is left queued").
     - If the old `visit_id` was settled (`is_settled = True`) → HTTP 403 (BR §3.5: "settled session visits can never be edited") → permanently stuck.
     - If the old `visit_id` still exists but belongs to the new session's shop → **financial corruption**: the sale is applied to the wrong session's ledger, and the ghost record is deleted from the queue after success, making the corruption permanent.

  The root cause is a **lifecycle contract gap**: the server treats session deletion as terminal; the Flutter client treats it as a UI reset but preserves the write-ahead queue.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix**: `clearSessionData` must accept a parameter to also purge `pending_sync` when called in response to a server-side session reset:
     ```dart
     Future<void> clearSessionData({bool clearPendingSyncs = false}) async {
       final db = await database;
       await db.delete('products');
       await db.delete('visits');
       if (clearPendingSyncs) {
         await db.delete('pending_sync');
         developer.log('[LocalDatabase] Pending sync queue cleared due to session reset.');
       }
     }
     ```
     Update `dashboard_screen.dart` lines 139 and 188 to pass `clearPendingSyncs: true`.

  2. **Backend enhancement**: When the server returns 404 for a session-scoped endpoint, include a specific error code or header that the Flutter interceptor can use to trigger the full wipe:
     ```python
     raise HTTPException(
         status_code=404,
         detail="SESSION_RESET: الجلسة لم تعد موجودة. يرجى مسح البيانات المحلية وبدء جلسة جديدة.",
         headers={"X-Wanasah-Reset": "true"}
     )
     ```

---

### CS-05: Flutter BLoC Equatable Silently Suppresses Server Business-Rule Rejection Messages

- **Severity**: **High**
- **Integration Boundary**: **Flutter BLoC State (`visit_bloc.dart`) ↔ FastAPI 4xx Error Responses (`api/driver.py`)**
- **Source Reports**: `flutter.md` Issue #6; `driver.md` Findings #1, #3; `04_BUSINESS_RULES.md` §6.1

- **Flaw Description & Impact Analysis**:
  Business Rule §6.1 states: **"A genuine business rejection from the server (any 4xx with an HTTP response) is treated as final: the exception is rethrown immediately and NOT queued — the driver must see and fix the rejection themselves."**

  The server correctly sends detailed Arabic error messages for business rule violations:
  - `"مرفوض محاسبياً: التحصيل أكبر من إجمالي الدين. الرصيد سيصبح بالسالب ({new_balance})."` (driver.md Finding #1)
  - `"تجاوزت حد الذمة"` (debt ceiling, BR §4.2)
  - `"المنتج موقوف"` (discontinued product, BR §1.7)

  The Flutter `_onSubmitVisit` handler in `visit_bloc.dart` catches these errors and emits a new state:
  ```dart
  emit(currentState.copyWith(errorMessage: errorMsg));
  ```

  However, the `VisitReady` class's `Equatable` props list **excludes `errorMessage`**:
  ```dart
  // Flutter — visit_bloc.dart (from flutter.md Issue #6)
  @override
  List<Object?> get props => [
    catalog, cart, shopBalance, cashCollected, debtPaid,
    // ← errorMessage is MISSING
  ];
  ```

  The cross-stack impact:
  1. **Server correctly rejects with a detailed Arabic message** — the server fulfills BR §6.1.
  2. **Flutter BLoC correctly captures the error** — `catch` block extracts `errorMsg` from the exception.
  3. **But BLoC state transition is invisible to the UI** — Equatable sees the new state as identical to the old state (all props match), so `BlocBuilder` does not rebuild.
  4. **The driver sees zero feedback** — no error snackbar, no toast, no red text. The cart screen remains unchanged.
  5. **The driver retries** — thinking the app glitched, they tap "Submit" again. Same rejection, same invisible failure. This burns through network calls, wastes field time, and erodes trust in the application.

  This is a **cross-stack error propagation failure**: the server speaks clearly, but the client's state management architecture swallows the message before it reaches human eyes.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix** (critical): Add `errorMessage` to the Equatable props list:
     ```dart
     @override
     List<Object?> get props => [
       catalog, cart, shopBalance, cashCollected, debtPaid, errorMessage,
     ];
     ```

  2. **Flutter defensive fix**: In the BLoC listener (in the UI widget), assert that an `errorMessage` in the state triggers a visible widget (SnackBar, AlertDialog) — do not rely solely on `BlocBuilder` reacting:
     ```dart
     // In the screen's BlocListener
     listener: (context, state) {
       if (state is VisitReady && state.errorMessage != null) {
         ScaffoldMessenger.of(context).showSnackBar(
           SnackBar(content: Text(state.errorMessage!), backgroundColor: Colors.red),
         );
       }
     }
     ```

  3. **Backend enhancement**: Consider returning machine-readable error codes alongside human-readable messages so the Flutter app can apply specific UI treatments (e.g., highlight the debt field in red for debt-ceiling errors):
     ```python
     raise HTTPException(
         status_code=400,
         detail={
             "message": "تجاوزت حد الذمة",
             "code": "DEBT_CEILING_EXCEEDED",
             "shop_id": shop.id,
             "current_balance": float(shop.current_balance),
             "max_limit": float(shop.max_debt_limit)
         }
     )
     ```

---

### CS-06: Dashboard Hardcoded Login URL + Empty API Fallback — Two Independent Failures That Both Break Backend Connectivity

- **Severity**: **High**
- **Integration Boundary**: **React Dashboard (`Login.tsx`, `useAuthFetch.ts`) ↔ FastAPI Backend (`main.py`)**
- **Source Reports**: `dashboard.md` C-01, C-02

- **Flaw Description & Impact Analysis**:
  Two independent critical flaws in the dashboard create a **combinatorial integration failure** with the backend:

  **Flaw A (C-01)**: `Login.tsx` line 43 has a hardcoded `http://127.0.0.1:5000/login` URL that bypasses the configured `VITE_API_URL` environment variable. Every authenticated request in the app uses `VITE_API_URL` via `useAuthFetch`, but the login page is hardcoded to localhost.

  **Flaw B (C-02)**: `useAuthFetch.ts` line 6 defaults to empty string when `VITE_API_URL` is not set: `const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "")`. This produces protocol-relative URLs like `//admin/sessions/today` that resolve unpredictably.

  The cross-stack impact of these combined flaws in a production deployment:

  | Scenario | `VITE_API_URL` set? | Can login? | Can use app after login? | Observable symptom |
  |----------|---------------------|------------|--------------------------|-------------------|
  | Local dev | Yes (`http://127.0.0.1:5000`) | ✅ (hardcoded matches) | ✅ | Everything works |
  | Staging | Yes (`https://staging-api.wanasah.com`) | ❌ (hardcoded hits localhost) | N/A | Login button spins forever |
  | Production | Yes (`https://api.wanasah.com`) | ❌ (hardcoded hits localhost) | N/A | Login fails with network error |
  | Production (misconfigured) | No (env var missing) | ❌ (hardcoded hits localhost) | ❌ (protocol-relative URLs) | Login fails; if bypassed, all pages fail |

  In every non-localhost environment, the dashboard is **unusable** because of the hardcoded login URL. Even if an admin somehow obtains a token (e.g., browser devtools), the missing `VITE_API_URL` would then break every authenticated request with protocol-relative URLs.

  This is not a theoretical edge case — it means the dashboard **cannot be deployed to any environment other than the developer's local machine** without code changes. Per `security.md` S-04, the production CORS origins are also hardcoded as placeholders (`https://dashboard.wanasah.com`), confirming the configuration is not yet production-ready.

- **Recommended Cross-Stack Resolution**:
  1. **Dashboard fix (C-01)**: Replace the hardcoded URL with the environment-configured API base:
     ```ts
     const API = (import.meta.env.VITE_API_URL || "").replace(/\/$/, "");
     const response = await fetch(`${API}/login`, { ... });
     ```

  2. **Dashboard fix (C-02)**: Validate the API URL at startup and fail fast with a clear error:
     ```ts
     const rawApi = (import.meta.env.VITE_API_URL || "").trim();
     if (!rawApi) {
       throw new Error("VITE_API_URL is not set. The dashboard cannot function without an API base URL.");
     }
     const API = rawApi.replace(/\/$/, "");
     ```

  3. **Infrastructure fix**: Add a `.env.example` file in the dashboard directory documenting all required environment variables. Add a pre-build validation script that checks `VITE_API_URL` is set and is a valid absolute HTTPS URL.

  4. **Backend alignment**: Ensure the backend's CORS origins (`main.py` line 50–53) are externalized to the same environment variable system (per `security.md` S-04 fix) so dashboard and backend configuration stay synchronized.

---

### CS-07: Flutter Missing `sendTimeout` + Backend `pool_size=50` = Combinatorial DoS Surface

- **Severity**: **High**
- **Integration Boundary**: **Flutter Dio HTTP Client (`api_client.dart`) ↔ FastAPI Connection Pool (`config.py`)**
- **Source Reports**: `flutter.md` Issue #10; `config.py` lines 19–23; `security.md` S-02

- **Flaw Description & Impact Analysis**:
  Two independently-designed resource limits combine to create a denial-of-service surface:

  **Flutter side**: `api_client.dart` configures `connectTimeout: 30s` and `receiveTimeout: 60s` but **omits `sendTimeout`**. On slow uplinks (common in field operations — EDGE/3G, remote areas), a request that establishes a TCP connection but stalls during body upload will hang **indefinitely**, consuming a Dio connection slot.

  **Backend side**: `config.py` sets `pool_size=50` and `max_overflow=20` — a maximum of 70 concurrent database connections. The backend has **no global rate limiting** (per `security.md` S-02).

  The cross-stack amplification:
  1. **Flutter hangs on uplink** — 50 drivers in the field each have one hanging `submit_sale` request due to slow uplink (no `sendTimeout`).
  2. **Backend holds 50 connections open** — each hanging request has acquired a database connection from the pool (the `get_db` dependency acquires on entry, releases on exit — but exit never happens because the request body hasn't finished uploading).
  3. **Connection pool exhausted** — `pool_size=50` is fully consumed by hanging requests.
  4. **Legitimate requests queue** — a driver with good connectivity tries to start their session (`POST /driver/{id}/sessions/start`), but no connection is available. The request times out at `pool_timeout=30s`.
  5. **Cascading failure** — the good-connectivity driver's timeout triggers a retry (Flutter retry logic), which also queues, further pressuring the pool.

  Neither the Flutter `sendTimeout` omission nor the backend `pool_size` limit is a bug in isolation. The integration bug is that **the client's indefinite wait perfectly aligns with the server's finite resource pool** — the system has no circuit breaker to prevent slow clients from starving fast clients.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix**: Add `sendTimeout` to Dio `BaseOptions`:
     ```dart
     BaseOptions(
       baseUrl: ApiConstants.baseUrl,
       connectTimeout: const Duration(seconds: 30),
       sendTimeout: const Duration(seconds: 30),     // ← ADD
       receiveTimeout: const Duration(seconds: 60),
       headers: { ... },
     ),
     ```

  2. **Backend fix**: Add per-endpoint rate limiting (per `security.md` S-02) and a request-body-size limit (per `security.md` S-06) to shed slow/malicious clients at the edge:
     ```python
     # main.py
     from slowapi import Limiter
     limiter = Limiter(key_func=get_real_ip, default_limits=["200/minute"])
     app.state.limiter = limiter
     ```

  3. **Backend fix**: Add a middleware that reads and discards request bodies that exceed a timeout, releasing the DB connection:
     ```python
     # Middleware to enforce request read timeout
     class RequestTimeoutMiddleware(BaseHTTPMiddleware):
         async def dispatch(self, request: Request, call_next):
             try:
                 return await asyncio.wait_for(call_next(request), timeout=45.0)
             except asyncio.TimeoutError:
                 return JSONResponse(status_code=408, content={"message": "Request timeout"})
     ```

---

### CS-08: Dashboard Aggressive 10s Polling + Backend No Rate Limiting = Self-Inflicted DoS Amplification

- **Severity**: **High**
- **Integration Boundary**: **React Dashboard Polling (`OperationsDashboard.tsx`) ↔ FastAPI Backend (no rate limiter)**
- **Source Reports**: `dashboard.md` H-04; `security.md` S-02; `04_BUSINESS_RULES.md` §2.4

- **Flaw Description & Impact Analysis**:
  The OperationsDashboard polls `/admin/sessions/today` **every 10 seconds** with no backoff, no jitter, and no maximum retry ceiling (dashboard.md H-04):

  ```ts
  // Dashboard — OperationsDashboard.tsx
  const poll = async () => {
    await fetchLiveOperations(isMounted);
    if (isMounted) {
      timerId = setTimeout(poll, 10000);  // 10s, unconditional
    }
  };
  ```

  The backend has **no rate limiting** on any endpoint (security.md S-02) and a `pool_size=50` connection pool.

  The cross-stack amplification:
  1. **5 admin tabs open** → 30 requests/minute to the same endpoint.
  2. **Server under load** (e.g., morning rush — 50 drivers starting sessions) → the `/admin/sessions/today` query involves joins across `WorkSession`, `Driver`, `DispatchRoute`, and may take 2–3 seconds.
  3. **Polling stacks** — the `await fetchLiveOperations` call blocks the `setTimeout`, so if the server takes 12 seconds to respond, the next poll fires **immediately** after the previous one completes (no minimum interval).
  4. **No backoff on failure** — if the server returns 500, the catch block at dashboard.md M-02 only calls `console.error` — the poll continues at 10s.
  5. **During a server outage**, every open dashboard tab hammers the recovering server at 10s intervals, preventing it from stabilizing — a **thundering herd problem** where the monitoring dashboard itself becomes the DDoS vector.

  The backend's lack of rate limiting means the server cannot distinguish between legitimate admin polling and an attacker — both look identical at the network layer. The dashboard's aggressive polling without backoff means it cannot adapt to server load signals.

- **Recommended Cross-Stack Resolution**:
  1. **Dashboard fix**: Implement exponential backoff with jitter and a minimum interval:
     ```ts
     const POLL_INTERVAL = 30_000; // 30 seconds base
     const MAX_BACKOFF = 120_000;

     const poll = async (attempt = 0) => {
       try {
         await fetchLiveOperations(isMounted);
         if (isMounted) timerId = setTimeout(() => poll(0), POLL_INTERVAL);
       } catch {
         if (isMounted) {
           const backoff = Math.min(POLL_INTERVAL * Math.pow(2, attempt), MAX_BACKOFF);
           const jitter = backoff * (0.5 + Math.random() * 0.5); // 50%-100% of backoff
           timerId = setTimeout(() => poll(attempt + 1), jitter);
         }
       }
     };
     ```

  2. **Backend fix**: Add per-endpoint rate limits (per `security.md` S-02) so the server can shed excess polling before it reaches the database.

  3. **Architectural improvement**: Replace polling with Server-Sent Events (SSE) or WebSocket for session status changes, so the server pushes updates only when state actually changes (per BR §2.4, authorization toggles happen infrequently at human speed).

---

## 🟡 Medium

### CS-09: Dashboard DispatchBoard Partial Refresh Creates Multi-Admin Split-Brain

- **Severity**: **Medium**
- **Integration Boundary**: **React Dashboard `setInterval` (`DispatchBoard.tsx`) ↔ FastAPI Dispatch Endpoints (multi-admin concurrency)**
- **Source Reports**: `dashboard.md` M-09; `dispatch.md` Finding #7 (TOCTOU); `04_BUSINESS_RULES.md` §2.1

- **Flaw Description & Impact Analysis**:
  The DispatchBoard's auto-refresh `setInterval` (every 60 seconds) updates only `pendingRoutes` and `shortages`, but **not** `zones`, `shops`, or `drivers`:

  ```ts
  // Dashboard — DispatchBoard.tsx (from dashboard.md M-09)
  const interval = setInterval(() => {
    authenticatedFetch("/dispatch/active_routes").then(data => setPendingRoutes(data));
    authenticatedFetch("/dispatch/shortages").then(data => setShortages(data));
    // ← zones, shops, drivers NOT refreshed
  }, 60000);
  ```

  The cross-stack impact in a multi-admin scenario:
  1. **Admin A** (Dashboard) opens DispatchBoard at 08:00 — loads zones, shops, drivers once.
  2. **Admin B** (Dashboard) creates a new zone "East District" at 08:05 and adds 20 shops to it.
  3. **Admin A's** 60s interval fires at 08:06 — updates routes and shortages, but **does not refresh zones**. Admin A still sees the old zone list without "East District."
  4. **Admin A** tries to create a dispatch route for a shop in "East District" — the shop appears in the dropdown (shops were loaded once at 08:00 and the new ones aren't visible), so Admin A can't dispatch.
  5. **Worse**: If a driver was reassigned to a different zone by Admin B, Admin A's stale driver list shows the old assignment, leading to a dispatch attempt that the backend rejects (BR §2.1: a driver can have at most one route in `{active, waiting}`).

  The 60s interval gives a **false sense of real-time data** when only 2 of 5 data domains are actually refreshed. This is a cross-stack problem because the backend correctly enforces the business rules (rejecting conflicting dispatches), but the dashboard's stale UI makes it appear buggy from Admin A's perspective.

- **Recommended Cross-Stack Resolution**:
  1. **Dashboard fix**: Either refresh all data domains uniformly, or remove the selective auto-refresh and replace with a visible "Last updated: X seconds ago — Refresh" button:
     ```ts
     const interval = setInterval(() => {
       fetchInitialData(); // full refresh of all domains
     }, 120_000);
     ```

  2. **Backend enhancement**: Return a `Last-Modified` or `ETag` header on zone/shop/driver list endpoints so the dashboard can do conditional `GET` requests (304 Not Modified) instead of full re-fetches.

---

### CS-10: Flutter `revertOfflineVisit` Ignores Returns — Local Custody Diverges from Server Truth

- **Severity**: **Medium**
- **Integration Boundary**: **Flutter SQLite `revertOfflineVisit` (`local_database.dart`) ↔ FastAPI `update_visit` Return Processing (`api/driver.py`)**
- **Source Reports**: `flutter.md` Issue #15; `flutter.md` Business Rules Cross-Reference (BR §6.2 partial compliance)

- **Flaw Description & Impact Analysis**:
  Business Rule §6.2 states: **"Before queuing a new offline edit of a visit, any previous offline draft for that same visit is first reverted (`revertOfflineVisit`) — this prevents a driver from repeatedly editing the same offline sale and having stock deducted multiple times."**

  `revertOfflineVisit` correctly reverses cart-item quantities (sales cartons/packs added back to `current_cartons`/`current_packs`), but **completely ignores the `returns` array**:

  ```dart
  // Flutter — local_database.dart (from flutter.md Issue #15 analysis)
  // revertOfflineVisit iterates cartItems, adds quantities back to products table.
  // The returns array is never processed in the revert path.
  ```

  The cross-stack impact during an offline edit cycle:
  1. **Driver records a visit with 5 sold cartons + 2 returned damaged cartons** — offline.
  2. **Flutter deducts 5 cartons from local stock** (`deductInventoryLocal`).
  3. **Driver edits the visit** — changes to 3 sold cartons + 1 return.
  4. **`revertOfflineVisit` fires** — adds back the original 5 cartons to local stock. But it does **not** reverse the 2 returned cartons.
  5. **New deduction applies** — deducts 3 new cartons.
  6. **Local stock after edit**: `original - 5 + 5 - 3 = original - 3` — correct for sales. But the 2 returned units are **still outstanding** in local math.
  7. **Server receives the new payload** — the server processes returns separately (they go into `VisitReturn` rows and/or `DamagedItemLog`). The server's stock accounting for returns is completely independent of the sales accounting.
  8. **The driver's local product quantity is now wrong** — the returns were never reversed locally, so the local `current_cartons` value is off by 2 cartons compared to server truth.

  This causes a slow, cumulative desync between local SQLite custody and server-side `SessionInventory.current_remaining_quantity` that only a full `syncDown()` can correct. For drivers with intermittent connectivity, this desync can grow across multiple offline edits.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix**: Include `returns` in the `revertOfflineVisit` logic symmetrically to `cartItems`:
     ```dart
     // For each return in the old draft, add quantity back to local stock
     for (final ret in oldReturns) {
       // Returns of sellable goods reduce custody — reverting means adding back
       if (ret.returnType == 'Good' || ret.returnType == 'Resellable') {
         // add ret.cartons, ret.packs back to products table
       }
     }
     ```

  2. **Flutter defensive fix**: After every `revertOfflineVisit` + new deduction cycle, compare local stock quantities against the server's `inventory` from the last successful `syncDown()` and log a warning if drift exceeds a threshold.

---

### CS-11: Flutter No `packs_per_carton` Zero Guard Offline vs. Server `packs_per_carton or 1` Default

- **Severity**: **Medium**
- **Integration Boundary**: **Flutter SQLite Raw Queries (`local_database.dart`) ↔ PostgreSQL `ProductVariant.packs_per_carton` Default**
- **Source Reports**: `flutter.md` Issue #14; `04_BUSINESS_RULES.md` §1.2; `schema.md` line 131

- **Flaw Description & Impact Analysis**:
  Business Rule §1.2 states: **"`packs_per_carton` is guarded against zero/None everywhere it is used (`variant.packs_per_carton or 1`) to prevent division-by-zero crashes."** The server-side Python code implements this guard correctly.

  However, the Flutter app's `revertOfflineVisit` function (and likely `deductInventoryLocal`) execute **raw SQLite queries** that perform division by `packs_per_carton` **without any zero guard**:

  ```sql
  -- Flutter — local_database.dart raw SQL (from flutter.md Issue #14)
  UPDATE products
  SET
    current_cartons = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) / packs_per_carton,
    current_packs = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) % packs_per_carton
  WHERE id = ?
  ```

  The server-side PostgreSQL schema defines `packs_per_carton` as `Integer, nullable=False, default=50` (schema.md line 131). The `NOT NULL` constraint and default of 50 prevent a zero value from existing in the database under normal circumstances.

  The cross-stack disconnect: **the server's zero-guard is in Python application code (`variant.packs_per_carton or 1`), not in the database schema**. If:
  1. A buggy migration or a direct DB update sets `packs_per_carton = 0` for a product.
  2. The server-side Python code uses `or 1` and continues functioning (BR §1.2).
  3. `syncDown()` transmits the zero value to Flutter's local SQLite.
  4. `revertOfflineVisit` executes the raw SQL with `packs_per_carton = 0` → **SQLITE_ERROR: division by zero**.
  5. The entire `saveInvoice` offline write path crashes, permanently blocking the driver from saving any further offline operations for that visit.

  The server's defense is at the application layer; the Flutter client's vulnerability is at the SQL layer. The two layers have **different failure boundaries** for the same invariant.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix**: Use SQLite's `MAX()` function to guarantee the denominator is never zero:
     ```sql
     UPDATE products
     SET
       current_cartons = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) / MAX(packs_per_carton, 1),
       current_packs = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) % MAX(packs_per_carton, 1)
     WHERE id = ?
     ```

  2. **Database fix** (defense-in-depth): Add a `CHECK` constraint on `ProductVariant.packs_per_carton` to prevent zero at the schema level:
     ```python
     # models.py
     packs_per_carton = Column(Integer, CheckConstraint('packs_per_carton > 0', name='chk_packs_per_carton_positive'), nullable=False, default=50)
     ```

  3. **Contract formalization**: The sync protocol should document that `packs_per_carton` is guaranteed ≥ 1, and the Flutter client should validate this invariant on all received product data, rejecting any product where `packs_per_carton <= 0` before inserting into local SQLite.

---

### CS-12: Flutter Returns Handling Asymmetry — Offline Revert and Local Deduction Treat Returns Differently

- **Severity**: **Medium**
- **Integration Boundary**: **Flutter `deductInventoryLocal` + `revertOfflineVisit` ↔ FastAPI `update_visit` Return Processing ↔ PostgreSQL `SessionInventory`**
- **Source Reports**: `flutter.md` Issue #15; `flutter.md` BR Cross-Reference (BR §6.2 note: "returns-related local stock state can only be corrected by the next full `syncDown()`")

- **Flaw Description & Impact Analysis**:
  The Flutter documentation in `revertOfflineVisit` explicitly acknowledges (per flutter.md BR Cross-Reference): **"we leave returns to the server to avoid tampering with custody"** — meaning returns are intentionally not reverted locally during offline edits. The server is the sole authority on return processing.

  However, this creates an asymmetry:
  1. **Sales** are tracked locally (deducted on submit, reverted on edit) → driver's local dashboard always reflects sale-adjusted custody.
  2. **Returns** are NOT tracked locally → the driver's local dashboard shows **inflated stock** compared to server truth (returns reduce custody server-side but the Flutter local state doesn't know about it).

  This is documented behavior, not a bug. But the cross-stack impact is **user confusion**: the driver sees "10 cartons available" locally, attempts to sell 10 cartons, and the server rejects with "insufficient stock" because server-side custody was reduced by 2 returned cartons the driver processed earlier. The driver doesn't understand why their app says 10 but the server says 8.

  The root cause is a **philosophical contract gap**: the Flutter app treats its local SQLite as a "dirty cache" that drifts from server truth by design (returns excluded), but the driver treats it as authoritative (the only number they can see).

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix**: After processing returns in `_onSubmitVisit`, immediately adjust local stock to reflect the custody impact:
     ```dart
     // After successful visit submission
     for (final ret in returns) {
       if (ret.returnType == 'Good' || ret.returnType == 'Resellable') {
         // Add returned sellable units back to local stock
         await _db.addToLocalStock(ret.productVariantId, ret.cartons, ret.packs);
       } else {
         // Damaged/expired returns: these reduce the driver's custody
         // (the server deducts 1 good unit for every damaged unit returned, per BR §3.6)
         await _db.deductFromLocalStock(ret.productVariantId, ret.cartons, ret.packs);
       }
     }
     ```

  2. **UI fix**: On the Flutter dashboard, display a "last synced" timestamp and warn when local stock may be stale due to un-synced returns.

---

## 🟢 Low

### CS-13: Flutter 401 Interceptor Does Not Guarantee Cross-Account Data Wipe on Multi-Driver Devices

- **Severity**: **Low**
- **Integration Boundary**: **Flutter `api_client.dart` Auth Interceptor ↔ Shared Device Local Storage (`local_database.dart`, `FlutterSecureStorage`)**
- **Source Reports**: `flutter.md` Issue #16; `auth.md` Finding #3 (no token revocation)

- **Flaw Description & Impact Analysis**:
  When the Flutter app receives a 401 Unauthorized response, the Dio interceptor triggers `onUnauthorized()` which navigates to the login screen. However, it does **not** guarantee the wiping of `wanasah_offline.db` and `FlutterSecureStorage`:

  ```dart
  // Flutter — api_client.dart (from flutter.md Issue #16)
  if (err.response?.statusCode == 401) {
    if (!err.requestOptions.path.contains('/login')) {
      onUnauthorized();  // ← Navigates to login, does NOT wipe local DB
    }
  }
  ```

  In a **shared-device scenario** (common in field operations — one tablet per vehicle, used by whichever driver is assigned to that vehicle that day):
  1. Driver A logs out (or their token expires — no revocation per auth.md Finding #3).
  2. Driver B logs in on the same device.
  3. Driver A's `pending_sync` records, local `products` cache, and `visits` history remain on disk.
  4. Driver B's first `syncUp()` finds Driver A's unsynced records in FIFO order and attempts to submit them.
  5. The server rejects them (different driver, wrong session) but **the records remain in the queue** (BR §6.3: 4xx records are skipped, not deleted).

  The cross-stack impact is **data boundary leakage**: Driver B's queue is polluted with Driver A's ghost records. While the server's authorization checks should ultimately reject them, the records consume queue slots, delay legitimate sync, and create confusing error logs on both client and server.

- **Recommended Cross-Stack Resolution**:
  1. **Flutter fix**: Force a hard wipe of local session data immediately when a 401 is intercepted, before triggering the UI redirect:
     ```dart
     if (err.response?.statusCode == 401) {
       if (!err.requestOptions.path.contains('/login')) {
         developer.log('[AuthInterceptor] 401 → Wiping local data and triggering logout');
         await LocalDatabase.instance.clearSessionData(clearPendingSyncs: true);
         await const FlutterSecureStorage().deleteAll();
         onUnauthorized();
       }
     }
     ```

  2. **Backend enhancement**: Include the authenticated `driver_id` in every pending-sync payload so the server can detect cross-account records and reject them with a specific error code that triggers queue cleanup on the client.

---

### CS-14: Dashboard `ledgerFetchedRef` Cache Never Invalidated on Stocktake — Stale Warehouse Ledger in UI

- **Severity**: **Low**
- **Integration Boundary**: **React Dashboard `MainInventory.tsx` State Cache ↔ FastAPI `warehouse_stocktake` Endpoint Side Effects**
- **Source Reports**: `dashboard.md` M-07; `04_BUSINESS_RULES.md` §1.4

- **Flaw Description & Impact Analysis**:
  The `MainInventory` component uses a `ledgerFetchedRef` to cache whether the warehouse ledger has been fetched, avoiding redundant network calls. However, the cache is never invalidated when the admin performs a stocktake operation (Tab 3), which **modifies the warehouse ledger**:

  ```ts
  // Dashboard — MainInventory.tsx (from dashboard.md M-07)
  const ledgerFetchedRef = useRef(false);
  // ...
  if (!force && ledgerFetchedRef.current) return;  // ← cache hit: skip fetch
  ```

  The cross-stack impact:
  1. Admin performs a stocktake via `POST /warehouse/stocktake` — this writes `AUDIT_ADJUSTMENT` rows to `WarehouseLedger` (BR §1.4).
  2. The stocktake's `onLockChange` callback updates `isAuditLocked` state but does **not** call `fetchLedger(true)` (the `force` parameter).
  3. `ledgerFetchedRef.current` is still `true` from the initial load.
  4. The admin switches to the Ledger tab (Tab 1) — sees **stale data** from before the stocktake. The new `AUDIT_ADJUSTMENT` rows are invisible.
  5. The admin assumes the stocktake didn't record properly and may re-run it, creating duplicate ledger entries.

  The backend correctly writes the ledger entries (BR §1.6: "ledger rows are never updated or deleted"), but the dashboard's cache prevents the admin from seeing them.

- **Recommended Cross-Stack Resolution**:
  1. **Dashboard fix**: Reset `ledgerFetchedRef` on component mount and after any operation that modifies the ledger:
     ```ts
     useEffect(() => {
       ledgerFetchedRef.current = false;
       fetchStatus(); fetchStock(); fetchAlerts();
       return () => { ledgerFetchedRef.current = false; };
     }, []);
     ```
     And in the stocktake callback:
     ```ts
     onLockChange={async (locked) => {
       setIsAuditLocked(locked);
       await Promise.all([fetchStock(), fetchAlerts(), fetchLedger(true)]);
     }}
     ```

  2. **Backend enhancement**: Return the count of affected ledger rows in the stocktake response so the dashboard can decide whether to invalidate its cache:
     ```python
     return {
         "message": "Stocktake completed",
         "ledger_entries_created": len(adjustment_entries)
     }
     ```

---

## Cross-Reference Matrix: Business Rules vs. Cross-Stack Compliance

| Business Rule (§) | Cross-Stack Status | Issue(s) |
|---|---|---|
| 1.2 Packs-as-atomic-unit / zero guard | ⚠️ Asymmetric | Server guards with `or 1`; Flutter SQL has no guard (CS-11) |
| 1.3 Negative-stock prevention | ⚠️ Asymmetric | Server enforces; Flutter local stock may drift (CS-10, CS-12) |
| 2.1 Route uniqueness (multi-admin) | ⚠️ Split-brain risk | Dashboard stale data (CS-09); Server enforces correctly |
| 3.4 Postponed Theft Shield | 🔴 Contract Mismatch | Flutter sends cash/debt unconditionally; Server blocks (CS-01) |
| 3.5 Settled session visit editing | ⚠️ Ghost records | Flutter pending syncs survive session reset (CS-04) |
| 5.3 Inventory reconciliation | ⚠️ Reporting gap | Dashboard ledger cache not invalidated after stocktake (CS-14) |
| 6.1 Write-path priority / 4xx rethrown | ✅ Cross-stack correct | Server rejects; Flutter rethrows; But error invisible due to Equatable bug (CS-05) |
| 6.3 Upload queue — 4xx handling | ⚠️ Queue pollution | Ghost records from old sessions accumulate (CS-04) |
| 6.5 `new_balance` as sole mechanism | 🔴 Broken | Fire-and-forget update silently drops server truth (CS-03) |

---

## Summary of Findings by Integration Boundary

| Integration Boundary | Count | Issues |
|---|---|---|
| Flutter ↔ FastAPI | 8 | CS-01, CS-02, CS-03, CS-04, CS-05, CS-07, CS-10, CS-11, CS-12, CS-13 |
| Dashboard ↔ FastAPI | 4 | CS-06, CS-08, CS-09, CS-14 |
| Cross-cutting (all layers) | 2 | CS-07 (timeout/pool), CS-08 (polling/rate-limit) |

---

## Warehouse Integration Gaps

> Source: `.ai-review/reviews/backend/warehouse.md` cross-referenced against `.ai-review/reviews/cross-stack/system.md`, `04_BUSINESS_RULES.md` §1.4–§1.8, §2.2

---

### CS-WH-01: Dashboard Forks Duplicate Supplier Invoices via TOCTOU — Two Admins Import Same Invoice Simultaneously

- **Severity**: **Critical**
- **Integration Boundary**: **React Dashboard (`MainInventory.tsx` inbound form) ↔ FastAPI `warehouse_inbound` ↔ PostgreSQL `WarehouseLedger`**
- **Source Reports**: `warehouse.md` Finding #1; `04_BUSINESS_RULES.md` §1.5; `dashboard.md` M-04 (Promise.all without rollback)

- **Flaw Description & Impact Analysis**:
  Business Rule §1.5 mandates: **"A supplier `reference_id` (invoice number) already present among prior `INBOUND_SUPPLIER`/`INBOUND_CORRECTION` ledger rows is rejected outright — the same supplier invoice can never be booked twice."**

  The server-side `warehouse_inbound` enforces this rule via a plain, unlocked `SELECT` (warehouse.md Finding #1):
  ```python
  stmt_ref = select(WarehouseLedger.id).filter(
      WarehouseLedger.transaction_type.in_(['INBOUND_SUPPLIER', 'INBOUND_CORRECTION']),
      func.lower(func.trim(WarehouseLedger.reference_id)) == func.lower(reference_id.strip())
  )
  existing_ref = (await db.execute(stmt_ref)).first()  # ← NO LOCK
  ```

  The dashboard's `MainInventory.tsx` inbound form submits via `authenticatedFetch` with no client-side duplicate-submission guard (no debounce, no button disable after click, no idempotency key). The cross-stack exploitation:

  1. **Admin A** opens the inbound form, enters invoice `INV-00125` with 10 line items, clicks "Submit."
  2. **Admin B** (or Admin A double-clicking on a laggy connection) submits the same invoice `INV-00125` within the same ~50ms window.
  3. **Both requests** pass the unlocked `SELECT` (neither sees the other's yet-uncommitted row).
  4. **Both requests** insert `INBOUND_SUPPLIER` ledger rows and increment `MainWarehouse.available_quantity_packs`.
  5. **Result**: Invoice `INV-00125` is booked **twice** — the warehouse stock is inflated by exactly the invoice quantity, the ledger audit trail is permanently corrupted, and the financial reconstruction (BR §1.6) shows double the actual received quantity.

  This is a cross-stack issue because:
  - The **server** has a TOCTOU vulnerability (no atomic guard on the uniqueness check).
  - The **dashboard** has no duplicate-submission guard (no idempotency token, no debounce, no disable-on-submit).
  - The **database** has no `UNIQUE` constraint on `(reference_id, transaction_type)` to serve as a last-resort backstop.
  - The **Flutter** app's `syncDown()` will receive the inflated stock quantities, causing the driver to think they have more inventory than physically exists (BR §1.1: "no negative-value commit" is undermined by positive-value fabrication).

- **Recommended Cross-Stack Resolution**:
  1. **Backend fix** (warehouse.md Finding #1): Use a Postgres advisory lock to serialize concurrent requests sharing the same normalized invoice number:
     ```python
     normalized_ref = reference_id.strip().lower()
     await db.execute(select(func.pg_advisory_xact_lock(func.hashtext(normalized_ref))))
     # Then the SELECT + INSERT are serialized for this invoice number
     ```

  2. **Database fix** (defense-in-depth): Add a partial unique index on `WarehouseLedger` for supplier invoice references:
     ```python
     # models.py — WarehouseLedger.__table_args__
     Index('uq_ledger_supplier_ref', 'reference_id', unique=True,
           postgresql_where=text("transaction_type IN ('INBOUND_SUPPLIER', 'INBOUND_CORRECTION') AND reference_id IS NOT NULL AND reference_id != 'بدون فاتورة'")),
     ```

  3. **Dashboard fix**: Disable the submit button on first click and add an idempotency key to the request:
     ```ts
     const [isSubmitting, setIsSubmitting] = useState(false);
     const idempotencyKey = useRef(crypto.randomUUID());

     const handleSubmit = async () => {
       if (isSubmitting) return;
       setIsSubmitting(true);
       try {
         await authenticatedFetch("/warehouse/inbound", {
           method: "POST",
           body: JSON.stringify({ ...formData, idempotency_key: idempotencyKey.current }),
         });
       } finally {
         setIsSubmitting(false);
       }
     };

     // Button: <Button disabled={isSubmitting}>...</Button>
     ```

---

### CS-WH-02: Dashboard Concurrent Invoice Adjustments Corrupt Ledger via Stale-Read Delta Computation

- **Severity**: **High**
- **Integration Boundary**: **React Dashboard Invoice Adjustment UI ↔ FastAPI `adjust_warehouse_entry` ↔ PostgreSQL `WarehouseLedger` & `MainWarehouse`**
- **Source Reports**: `warehouse.md` Finding #2; `04_BUSINESS_RULES.md` §1.6

- **Flaw Description & Impact Analysis**:
  Business Rule §1.6 mandates: **"Every mutation to `MainWarehouse.available_quantity_packs` must be paired with a `WarehouseLedger` row carrying a `balance_after_packs` snapshot — this snapshot is the audit mechanism that lets balances be reconstructed/verified after the fact."**

  The `adjust_warehouse_entry` endpoint computes the delta as:
  ```python
  # warehouse.py (from warehouse.md Finding #2)
  current_invoice_total_packs = (await db.execute(stmt_sum)).scalar() or 0  # ← UNLOCKED READ
  delta = int(payload.new_total_packs) - int(current_invoice_total_packs)

  # ... later ...
  stmt_variant = select(ProductVariant).with_for_update()  # ← LOCK ACQUIRED AFTER DELTA COMPUTED
  ```

  The cross-stack exploitation in a multi-admin scenario:
  1. **Admin A** opens the ledger, sees invoice `INV-00100` showing 500 packs total. Wants to correct it to 600.
  2. **Admin B** simultaneously sees the same invoice at 500 packs and wants to correct it to 550.
  3. **Admin A's request** reads `current_invoice_total_packs = 500` → computes `delta = 600 - 500 = +100`. Writes correction.
  4. **Admin B's request** also reads `current_invoice_total_packs = 500` (before Admin A's commit is visible) → computes `delta = 550 - 500 = +50`. Writes correction.
  5. **Final state**: Two `INBOUND_CORRECTION` rows exist: +100 and +50 = net +150. The admin(s) intended the invoice total to be either 600 or 550, but it's now 650 — a classic **lost-update anomaly** where the ledger silently diverges from either admin's intended state.

  The dashboard's ledger view (MainInventory Tab 1) displays the reconstructed totals to admins with **no indication that a concurrent edit occurred**. The dashboard has no optimistic-concurrency mechanism (no `ETag`, no version column, no "this record was modified by another user" warning).

- **Recommended Cross-Stack Resolution**:
  1. **Backend fix** (warehouse.md Finding #2): Acquire the `MainWarehouse` lock **first**, before reading the invoice sum, so concurrent adjustments on the same product are serialized before any computation:
     ```python
     # Lock MainWarehouse FIRST
     stmt_wh = select(MainWarehouse).with_for_update().filter_by(product_variant_id=original_entry.product_variant_id)
     wh_record = (await db.execute(stmt_wh)).scalar_one_or_none()
     # THEN compute the invoice total (now serialized)
     current_invoice_total_packs = (await db.execute(stmt_sum)).scalar() or 0
     delta = int(payload.new_total_packs) - int(current_invoice_total_packs)
     ```

  2. **Dashboard fix**: Add optimistic concurrency control — include a `version` or `last_modified` timestamp in the ledger entry response. When submitting an adjustment, include the expected version; if the server detects a mismatch, return 409 Conflict and refresh the ledger:
     ```ts
     const handleAdjust = async (entry: LedgerEntry) => {
       try {
         await authenticatedFetch(`/warehouse/ledger/${entry.id}/adjust`, {
           method: "POST",
           body: JSON.stringify({
             new_total_packs: newTotal,
             expected_version: entry.version,
           }),
         });
       } catch (err: any) {
         if (err.status === 409) {
           toast.error("تم تعديل هذه الفاتورة بواسطة مستخدم آخر. جاري تحديث البيانات...");
           await fetchLedger(true);
         }
       }
     };
     ```

---

### CS-WH-03: Warehouse Audit Lock Blocks Dashboard Dispatch — But Dashboard Has No Visual Lock Indicator on DispatchBoard

- **Severity**: **High**
- **Integration Boundary**: **React Dashboard `DispatcherBoard.tsx` ↔ FastAPI `dispatch_route` ↔ PostgreSQL `system_settings.warehouse_status`**
- **Source Reports**: `dashboard.md` M-09 (partial refresh); `dispatch.md` Finding #13 (missing rollback on AUDIT_LOCK check); `04_BUSINESS_RULES.md` §1.4; `warehouse.md` (implicit)

- **Flaw Description & Impact Analysis**:
  Business Rule §1.4 states: **"`dispatch_route` (creating a new route with an inventory load) is blocked while `AUDIT_LOCK` is active."** The server-side `dispatch_route` correctly checks `system_settings.warehouse_status` and raises 403 if locked.

  However, the dashboard's **DispatchBoard** component (`DispatchBoard.tsx`) has **no awareness** of the warehouse lock state:
  1. The `MainInventory` component reads and displays the lock status (Tab 2: Stocktake).
  2. But `DispatchBoard` does **not** fetch `warehouse_status` and does **not** display any warning.
  3. An admin on the DispatchBoard tab sees all zones, shops, drivers, and active routes as normal.
  4. The admin fills in the dispatch form, selects inventory quantities, clicks "Launch."
  5. The server rejects with `403: المستودع مقفل حالياً لغايات الجرد (Stocktake)` — a confusing error for an admin who is on a completely different tab and has no visibility into why their dispatch was blocked.

  The cross-stack disconnect: the warehouse lock is a **global system state** that gates operations across modules, but the dashboard architecture treats `MainInventory` and `DispatchBoard` as isolated tabs with no shared lock-state awareness. An admin performing a stocktake (Inventory tab) may not realize they are blocking another admin trying to dispatch routes (Dispatch tab).

- **Recommended Cross-Stack Resolution**:
  1. **Dashboard fix**: On `DispatchBoard` mount, fetch `warehouse_status` and display a persistent warning banner when `AUDIT_LOCK` is active:
     ```ts
     const [warehouseLocked, setWarehouseLocked] = useState(false);

     useEffect(() => {
       authenticatedFetch("/warehouse/status").then(data => {
         setWarehouseLocked(data.setting_value === 'AUDIT_LOCK');
       }).catch(() => {});
     }, []);

     // In the JSX, before the dispatch form:
     {warehouseLocked && (
       <Alert variant="destructive" className="mb-4">
         ⚠️ المستودع مقفل حالياً للجرد. لا يمكن إنشاء خطوط سير جديدة حتى يتم فتح المستودع.
       </Alert>
     )}
     ```

  2. **Backend fix**: Add a lightweight endpoint `GET /warehouse/status` that returns the current `warehouse_status` without requiring full warehouse data, so the dashboard can poll it cheaply.

  3. **Cross-module architectural improvement**: Implement a **global system-state WebSocket** or SSE channel so that warehouse lock/unlock events are pushed to all connected dashboard clients in real-time, rather than requiring each tab to poll independently.

---

### CS-WH-04: Flutter `syncDown` Inventory Snapshot vs. Warehouse Handshake Reservation — Driver Sees Stock That Is Already Reserved

- **Severity**: **High**
- **Integration Boundary**: **Flutter `syncDown()` Product Snapshot ↔ FastAPI Mid-Day Handshake (`dispatch_route` / `respond_to_transfer`) ↔ PostgreSQL `MainWarehouse.reserved_quantity_packs`**
- **Source Reports**: `04_BUSINESS_RULES.md` §2.2; `flutter.md` Issue #3 (empty product wipe); `dispatch.md` Finding #7 (TOCTOU on active_session)

- **Flaw Description & Impact Analysis**:
  Business Rule §2.2 defines the mid-day handshake flow: when an admin dispatches new stock to a driver who already has an active `WorkSession`, the delta is moved from `MainWarehouse.available_quantity_packs` into `reserved_quantity_packs` (an in-transit holding state), and a `pending` `InventoryTransfer` row is created. The driver's `SessionInventory` and `VehicleLoad` are **explicitly NOT touched** until the driver accepts the transfer.

  The Flutter app's `syncDown()` fetches the driver's current inventory snapshot from the session refresh endpoint. The cross-stack disconnect:

  1. **Admin dispatches 10 cartons of Product X** to Driver A at 10:30 AM (Driver A is mid-session).
  2. **Server creates pending `InventoryTransfer`** — `reserved_quantity_packs` is incremented by 10 × `packs_per_carton`. `SessionInventory` is unchanged.
  3. **Driver A pulls down to refresh** (`syncDown()`) at 10:31 AM.
  4. **The session refresh endpoint** returns the driver's `SessionInventory` — which does **not** yet include the pending transfer's 10 cartons.
  5. **Flutter local SQLite is updated** — shows the **pre-transfer** stock quantity.
  6. **Driver A sees 5 cartons available** (the old amount) and is confused because the admin told them "we loaded 10 more cartons for you."
  7. **Driver A does NOT see any UI indicator** that a pending transfer is waiting for their acceptance.

  The root cause: the server's mid-day handshake mechanism creates a **temporal gap** between the admin's action and the driver's acceptance, but the Flutter inventory snapshot endpoint does not include pending transfer information. The driver's local UI has no way to know that additional stock is available subject to their approval.

- **Recommended Cross-Stack Resolution**:
  1. **Backend fix**: Include pending `InventoryTransfer` information in the session refresh endpoint response alongside the regular inventory:
     ```python
     # In the session refresh endpoint
     pending_transfers = await db.execute(
         select(InventoryTransfer).filter_by(work_session_id=session.id, status='pending')
     )
     return {
         "visits": visits_data,
         "inventory": inventory_data,
         "pending_transfers": [
             {
                 "transfer_id": t.id,
                 "product_variant_id": t.product_variant_id,
                 "quantity_packs": t.quantity_packs,  # positive = incoming, negative = withdrawal
                 "status": t.status,
                 "created_at": t.created_at.isoformat()
             }
             for t in pending_transfers.scalars().all()
         ]
     }
     ```

  2. **Flutter fix**: On `syncDown()`, parse the `pending_transfers` key and display a notification on the dashboard:
     ```dart
     if (pendingTransfers.isNotEmpty) {
       final incoming = pendingTransfers.where((t) => t.quantityPacks > 0).toList();
       if (incoming.isNotEmpty) {
         showSnackBar('لديك ${incoming.length} حوالة بضاعة معلقة بانتظار موافقتك');
       }
     }
     ```

  3. **Flutter UI enhancement**: Add a "Pending Transfers" section to the dashboard that allows the driver to accept/reject transfers directly, rather than requiring the transfers to be synced invisibly.

---

### CS-WH-05: Warehouse Ledger `balance_before` Reconstruction Fragile Across Module Boundaries

- **Severity**: **Medium**
- **Integration Boundary**: **React Dashboard Ledger Display (`MainInventory.tsx`) ↔ FastAPI `get_warehouse_ledger` Sign-Guessing Logic ↔ Dispatch/Driver Module `transaction_type` Strings**
- **Source Reports**: `warehouse.md` Finding #7; `04_BUSINESS_RULES.md` §1.6; `dashboard.md` (ledger display in MainInventory)

- **Flaw Description & Impact Analysis**:
  The `get_warehouse_ledger` endpoint reconstructs `balance_before` for display in the dashboard's ledger table by **guessing the sign convention per `transaction_type` string**:

  ```python
  # warehouse.py (from warehouse.md Finding #7)
  if log.transaction_type in ['DISPATCH_LOAD', 'HANDSHAKE_RESERVE']:
      bal_before = log.balance_after_packs + log.quantity_packs
  elif log.transaction_type == 'HANDSHAKE_COMMIT':
      bal_before = log.balance_after_packs
  else:
      bal_before = log.balance_after_packs - log.quantity_packs  # ← DEFAULT CATCH-ALL
  ```

  The `else` branch is a **silent catch-all** that assumes any unrecognized `transaction_type` follows the "increase" convention (`balance_before = balance_after - quantity_packs`). The cross-stack fragility:

  1. **Dispatch module** (`dispatch.py`) writes transaction types like `DISPATCH_LOAD`, `DISPATCH_UNLOAD`, `DISPATCH_UNLOAD_FALLBACK`, `VEHICLE_ROLLOVER`, `END_DAY_CLEARANCE`.
  2. **Driver module** (`driver.py`) writes `HANDSHAKE_RESERVE`, `HANDSHAKE_COMMIT`, `HANDSHAKE_RELEASE`.
  3. If **any** of these modules introduces a **new `transaction_type` string** (e.g., `EMERGENCY_RESTOCK`, `BULK_ADJUSTMENT`) without also updating the sign-guessing logic in `warehouse.py`, the `else` branch silently produces a **wrong `balance_before`**.
  4. The dashboard displays this wrong number to the admin with **no visual indicator** that the value is computed from a fallback path.
  5. The admin makes financial decisions based on a wrong ledger display, and the audit trail (BR §1.6) appears inconsistent when manually verified.

  The root cause is a **cross-module contract** that is enforced only by string-matching in a single file, with no type system, enum, or centralized registry to guarantee consistency across the three modules that write ledger rows.

- **Recommended Cross-Stack Resolution**:
  1. **Backend fix** (warehouse.md Finding #7): Replace the catch-all `else` with an explicit whitelist per sign convention, and **log a warning + set `balance_before = None`** for unrecognized types rather than silently guessing wrong:
     ```python
     DECREASE_TYPES = {'DISPATCH_LOAD', 'HANDSHAKE_RESERVE'}
     NEUTRAL_TYPES = {'HANDSHAKE_COMMIT'}
     INCREASE_TYPES = {'INBOUND_SUPPLIER', 'INBOUND_CORRECTION', 'AUDIT_ADJUSTMENT',
                       'DISPATCH_UNLOAD', 'DISPATCH_UNLOAD_FALLBACK', 'VEHICLE_ROLLOVER',
                       'END_DAY_CLEARANCE', 'HANDSHAKE_RELEASE'}
     if log.transaction_type in DECREASE_TYPES:
         bal_before = log.balance_after_packs + log.quantity_packs
     elif log.transaction_type in NEUTRAL_TYPES:
         bal_before = log.balance_after_packs
     elif log.transaction_type in INCREASE_TYPES:
         bal_before = log.balance_after_packs - log.quantity_packs
     else:
         bal_before = None
         logger.warning(f"Unknown ledger transaction_type '{log.transaction_type}' (id={log.id})")
     ```

  2. **Architectural fix**: Store `balance_before_packs` as a **column on `WarehouseLedger`** at write time, eliminating the need for reconstruction entirely:
     ```python
     # models.py — WarehouseLedger
     balance_before_packs = Column(Integer, nullable=False)
     balance_after_packs = Column(Integer, nullable=False)
     ```
     This makes the ledger self-contained and immune to sign-convention drift. Every module that writes a ledger row is responsible for providing the before/after pair at write time — a contract enforced at the model level, not the display level.

  3. **Dashboard fix**: Display `balance_before` as "—" (unknown) when the server returns `null`, rather than silently showing a potentially wrong computed value.

---

### CS-WH-06: Warehouse Low-Stock Threshold Alerts Defined in Schema — No Dashboard Notification Mechanism Exists

- **Severity**: **Low**
- **Integration Boundary**: **PostgreSQL `MainWarehouse.min_threshold_packs` ↔ React Dashboard `MainInventory.tsx` ↔ FastAPI Warehouse Endpoints**
- **Source Reports**: `schema.md` line 530; `04_BUSINESS_RULES.md` §1.3; `dashboard.md` (MainInventory component)

- **Flaw Description & Impact Analysis**:
  The `MainWarehouse` model defines `min_threshold_packs` (schema.md line 530) with the comment "إشعارات العجز (Threshold Alerts): الحد الأدنى بالحبات." This column is present in the database and can be set per product variant.

  However, there is **no cross-stack mechanism** to surface threshold violations:
  1. **Server-side**: No scheduled job, background task, or endpoint that checks `available_quantity_packs < min_threshold_packs` and triggers an alert.
  2. **Dashboard-side**: The `MainInventory` component fetches stock levels but does **not** compare them against `min_threshold_packs` and does **not** highlight or sort low-stock items.
  3. **Mobile-side**: The Flutter dashboard shows the driver's vehicle stock, not warehouse stock — so the driver has no visibility into warehouse depletion.

  The result: `min_threshold_packs` is **dead data** — it can be configured and stored but has no active consumer in any layer of the stack. An admin must manually scan the inventory list and compare quantities against their memory of what the threshold was set to.

- **Recommended Cross-Stack Resolution**:
  1. **Dashboard fix**: In `MainInventory.tsx` stock table, sort products by `(available_quantity_packs / max(min_threshold_packs, 1))` ascending, and apply a red/orange highlight to rows where `available_quantity_packs <= min_threshold_packs`:
     ```ts
     const lowStockProducts = stockData.filter(
       p => p.available_quantity_packs <= p.min_threshold_packs && p.min_threshold_packs > 0
     );
     // Display a "Low Stock Alert" badge/count in the tab header
     ```

  2. **Backend fix**: Add a dedicated endpoint `GET /warehouse/low-stock` that returns only products below threshold, so the dashboard can poll it without fetching the entire inventory:
     ```python
     @router.get("/warehouse/low-stock")
     async def get_low_stock_alerts(db: AsyncSession = Depends(get_db), current_admin: Driver = Depends(get_current_admin)):
         stmt = select(MainWarehouse, ProductVariant).join(ProductVariant).filter(
             MainWarehouse.available_quantity_packs <= MainWarehouse.min_threshold_packs,
             MainWarehouse.min_threshold_packs > 0
         )
         results = (await db.execute(stmt)).all()
         return [{"product_name": v.variant_name, "available": wh.available_quantity_packs, "threshold": wh.min_threshold_packs} for wh, v in results]
     ```

---

*End of Phase 11.1 — Warehouse Integration Gaps*
