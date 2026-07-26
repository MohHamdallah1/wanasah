# Flutter Mobile App — Surgical Audit Report

> **Phase 8 Deliverable** — Frontend Module Audit
> **Scope**: Offline sync exploits, SQLite caching issues, BLoC state management bugs, memory leaks, duplicate network requests
> **Cross-referenced against**: `.ai-review/04_BUSINESS_RULES.md`
> **Date**: 2026-07-24

---

## Executive Summary

Total issues found: **11**  
- **Critical**: 3  
- **High**: 4  
- **Medium**: 4  

---

## Issue #1 — Type Mismatch Between Fresh Install and Upgrade Path (TEXT vs REAL)

- **Severity**: **Critical**
- **Flaw Category**: SQLite Schema Drift / Data Corruption
- **File & Line**: `wanasah_frontend/lib/core/db/local_database.dart`, Lines 90, 102 vs. Lines 134–135, 141
- **Current Flawed Code**:

  *onCreate (v6 fresh install) — Lines 88–105:*
  ```dart
  shop_balance TEXT,
  max_debt_limit TEXT DEFAULT '0.0',
  ...
  cash_collected TEXT DEFAULT '0.0',
  debt_paid TEXT DEFAULT '0.0',
  ```

  *onUpgrade (v1→v2 path) — Lines 134–141:*
  ```dart
  await db.execute(
    'ALTER TABLE visits ADD COLUMN cash_collected REAL DEFAULT 0.0',
  );
  await db.execute(
    'ALTER TABLE visits ADD COLUMN debt_paid REAL DEFAULT 0.0',
  );
  await db.execute(
    'ALTER TABLE visits ADD COLUMN max_debt_limit REAL DEFAULT 0.0',
  );
  ```

- **Impact Analysis**: A driver upgrading from an older app version gets `REAL` affinity on monetary columns; a new install gets `TEXT` affinity. SQLite uses type affinity to determine how values are stored and compared. `REAL` columns store `0.0` as an IEEE-754 float; `TEXT` columns store `'0.0'` as a string. When Dart code reads values via `double.tryParse()` or `(as num?)?.toDouble()`, both paths currently work — but SQL queries that compare or compute on these columns (e.g., `SUM(cash_collected)`, `WHERE debt_paid > 0`) behave differently depending on affinity. `SELECT SUM(cash_collected)` on a TEXT column returns `0.0` (SQLite attempts numeric coercion per row), while on a REAL column it returns the proper float sum. More critically, `WHERE cash_collected > 0` on a TEXT column containing `'0.0'` evaluates `'0.0' > 0` as **true** in SQLite (string-vs-number comparison rules), causing incorrect query results. This produces **silent financial data corruption** that differs between users based on install/upgrade history — the worst kind of bug.

- **Recommended Surgical Fix**: Normalize all monetary columns to a single type in `_onUpgrade`. For v7, migrate existing TEXT-typed columns to REAL via a safe migration:
  ```dart
  if (oldVersion < 7) {
    // Step 1: Create temp table with correct schema
    await db.execute('''
      CREATE TABLE visits_new (
        visit_id INTEGER PRIMARY KEY,
        shop_id INTEGER,
        shop_name TEXT,
        shop_balance REAL,
        max_debt_limit REAL DEFAULT 0.0,
        shop_zone_id INTEGER,
        allowed_zone_id INTEGER,
        status TEXT,
        outcome TEXT,
        visit_sequence INTEGER,
        is_emergency INTEGER DEFAULT 0,
        location_link TEXT,
        latitude REAL,
        longitude REAL,
        shop_owner TEXT,
        shop_phone TEXT,
        cash_collected REAL DEFAULT 0.0,
        debt_paid REAL DEFAULT 0.0,
        cart_items TEXT,
        returns TEXT,
        notes TEXT
      )
    ''');
    // Step 2: Migrate data with CAST
    await db.execute('''
      INSERT INTO visits_new SELECT
        visit_id, shop_id, shop_name,
        CAST(shop_balance AS REAL),
        CAST(max_debt_limit AS REAL),
        shop_zone_id, allowed_zone_id, status, outcome,
        visit_sequence, is_emergency, location_link,
        latitude, longitude, shop_owner, shop_phone,
        CAST(cash_collected AS REAL),
        CAST(debt_paid AS REAL),
        cart_items, returns, notes
      FROM visits
    ''');
    // Step 3: Swap tables atomically
    await db.execute('DROP TABLE visits');
    await db.execute('ALTER TABLE visits_new RENAME TO visits');
  }
  ```
  And update `_onCreate` to use `REAL` for all monetary columns as well.

---

## Issue #2 — Race Condition in Database Singleton Getter

- **Severity**: **Critical**
- **Flaw Category**: SQLite Lock / Concurrent Connection
- **File & Line**: `wanasah_frontend/lib/core/db/local_database.dart`, Lines 36–39
- **Current Flawed Code**:
  ```dart
  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB();
    return _database!;
  }
  ```

- **Impact Analysis**: The null-check on line 37 is followed by an `await _initDB()` which yields to the event loop. If two async callers invoke `database` simultaneously before either has set `_database`, both pass the `null` check, both call `_initDB()`, and two separate `Database` connections are opened. The second connection overwrites the `static Database? _database` reference, orphaning the first connection (which stays open consuming memory and file handles). All subsequent callers use whichever connection was assigned last. If an in-progress write batch was using the orphaned first connection, its writes may commit to a now-unreferenced handle — the caller sees no error but data may be lost or inconsistently read by the second connection's queries. Under high-concurrency scenarios (multiple BLoC events firing on app start, sync + dashboard load simultaneously), this leads to **intermittent data loss** and "SQLITE_BUSY" / "database is locked" crashes.

- **Recommended Surgical Fix**: Guard with a `Future`-based lock so concurrent callers await the same initialization:
  ```dart
  static Future<Database>? _initFuture;

  Future<Database> get database async {
    if (_database != null) return _database!;
    if (_initFuture != null) return _initFuture!;
    _initFuture = _initDB();
    _database = await _initFuture;
    _initFuture = null;
    return _database!;
  }
  ```

---

## Issue #3 — Empty Product List from Server Wipes Local Stock Data

- **Severity**: **Critical**
- **Flaw Category**: Offline Sync Exploit / Data Annihilation
- **File & Line**: `wanasah_frontend/lib/repositories/sync_repository.dart`, Lines 81–107
- **Current Flawed Code**:
  ```dart
  if (response.data is List) {
    visitsData = List<Map<String, dynamic>>.from(response.data);
  } else if (response.data is Map) {
    final Map<String, dynamic> dataMap = response.data as Map<String, dynamic>;
    if (dataMap.containsKey('visits') && dataMap['visits'] != null) {
      visitsData = List<Map<String, dynamic>>.from(dataMap['visits']);
    }
    if (dataMap.containsKey('inventory') && dataMap['inventory'] != null) {
      productsData = List<Map<String, dynamic>>.from(dataMap['inventory']);
    }
  }
  // ...
  await _db.refreshSessionData(visitModels, productModels);
  ```

- **Impact Analysis**: When the server responds with a `Map` that contains `visits` but does **not** contain an `inventory` key (e.g., a future API change, a partial response due to server-side filtering, or a mid-day refresh scenario where product data isn't included), `productsData` remains an empty list `[]`. On line 107, `refreshSessionData(visitModels, [])` is called, which runs:
  ```dart
  await txn.delete('products');   // ← WIPES ALL LOCAL STOCK
  // batch inserts 0 product rows  // ← driver now has ZERO stock locally
  ```
  The driver's entire local inventory snapshot is **annihilated** with no warning. The dashboard shows "لا يوجد بضاعة في السيارة حالياً" and the driver can no longer create any cart items for any visit until a full `syncDown()` with proper inventory data succeeds. In offline or poor-connectivity conditions, this effectively **bricks the driver's ability to sell** until they find stable internet.

  Cross-reference with business rules 6.4: the `syncDown` safety rules correctly guard against overwriting when blocking pending syncs exist, but there is **no guard against an empty or missing products payload from the server**. The atomic transaction guarantee becomes an atomic data-destruction guarantee when the server payload is incomplete.

- **Recommended Surgical Fix**: Only truncate and rewrite tables when the incoming data is non-empty; if the server returned zero products, skip the products table rewrite:
  ```dart
  if (productModels.isNotEmpty || visitModels.isNotEmpty) {
    // Both tables present: safe to refresh
    await _db.refreshSessionData(visitModels, productModels);
  } else if (visitModels.isNotEmpty) {
    // Visits only: refresh visits, leave products intact
    await _db.refreshVisitsOnly(visitModels);
  }
  ```
  Additionally, add a new method `refreshVisitsOnly` to `LocalDatabase` that only truncates and rewrites the `visits` table, leaving `products` untouched.

---

## Issue #4 — Fire-and-Forget SQL Update for Shop Balance After Sync

- **Severity**: **High**
- **Flaw Category**: Data Loss / Fire-and-Forget Async
- **File & Line**: `wanasah_frontend/lib/repositories/sync_repository.dart`, Lines 279–288
- **Current Flawed Code**:
  ```dart
  if (response.data != null && response.data['new_balance'] != null) {
    final double newBalance =
        double.tryParse(response.data['new_balance'].toString()) ?? 0.0;
    await _db.database.then((db) {
      db.rawUpdate(
        'UPDATE visits SET shop_balance = ? WHERE visit_id = ?',
        [newBalance, visitId],
      );
    });
  }
  ```

- **Impact Analysis**: The `_db.database` getter returns a `Future<Database>`. Calling `.then()` on it creates a **non-awaited** continuation. The `await` on line 282 awaits the `.then()` call itself (which returns immediately after registering the callback), **not** the `rawUpdate` inside it. The `rawUpdate` runs as an unawaited fire-and-forget operation. If the database is busy, locked, or throws an error, the exception is silently swallowed. More critically, if the app is terminated between the `deletePendingSync` (line 217 in `syncUp`) and the completion of this fire-and-forget update, the pending record is deleted (marked as synced) but the local `shop_balance` is never updated. The driver sees a stale balance until the next full `syncDown()`.

  Cross-reference with business rules 6.5: "The server's returned `new_balance` is the **only** mechanism by which the authoritative financial state is written back into local SQLite outside of a full `syncDown()`." If this single mechanism fails silently, the local financial state drifts from server truth **permanently** until the next manual refresh.

- **Recommended Surgical Fix**: Get the database reference first, then await the update properly:
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

---

## Issue #5 — Assert-Based Singleton Initialization Causes Release Crash

- **Severity**: **High**
- **Flaw Category**: Token Expiry Crash / Uninitialized Dependency
- **File & Line**: `wanasah_frontend/lib/core/network/api_client.dart`, Lines 82–88
- **Current Flawed Code**:
  ```dart
  static ApiClient get instance {
    assert(
      _instance != null,
      'ApiClient.init() must be called before accessing ApiClient.instance',
    );
    return _instance!;
  }
  ```

- **Impact Analysis**: Dart `assert` statements are **completely stripped** in release builds (`--release`). If `ApiClient.init()` is not called before the first access to `ApiClient.instance` (e.g., due to a race condition during app startup, or a code path that accesses the API client before main() reaches the init call), the release build will silently execute `return _instance!;` with `_instance` being `null`. The `!` null-assertion operator throws a `NullError` / `TypeError` at runtime with no meaningful error message — the app **crashes to a white screen** with no recovery path. Since this is the gateway to all network communication, the entire app becomes unusable.

- **Recommended Surgical Fix**: Replace `assert` with a proper runtime check:
  ```dart
  static ApiClient get instance {
    if (_instance == null) {
      throw StateError(
        'ApiClient.init() must be called before accessing ApiClient.instance',
      );
    }
    return _instance!;
  }
  ```

---

## Issue #6 — BLoC State Equality Ignores errorMessage (Silent Error Suppression)

- **Severity**: **High**
- **Flaw Category**: Unhandled BLoC State / UI Freeze
- **File & Line**: `wanasah_frontend/lib/blocs/visit/visit_bloc.dart`, Lines 171–177
- **Current Flawed Code**:
  ```dart
  @override
  List<Object?> get props => [
    catalog,
    cart,
    shopBalance,
    cashCollected,
    debtPaid,
  ];
  ```
  *The `VisitReady` class has an `errorMessage` field (line 128) but it is **not** included in the `Equatable` props list.*

- **Impact Analysis**: When `_onSubmitVisit` fails (line 465–478), it emits `currentState.copyWith(errorMessage: errorMsg)`. Because `errorMessage` is not in `props`, `Equatable` compares the old and new states and finds them **identical** (all props are the same). `BlocBuilder` receives no notification that the state changed, and the UI never rebuilds. The error message — which may contain a critical server rejection like "تجاوزت حد الذمة" (debt ceiling exceeded) or "المنتج موقوف" (product discontinued) — is **silently swallowed**. The driver sees the same cart screen with no feedback, has no idea why their submission failed, and may repeatedly attempt to submit, burning through their queue with identical rejections.

  Cross-reference with business rules 6.1: "A genuine business rejection from the server ... the exception is rethrown immediately ... the driver must see and fix the rejection themselves." The Flutter code correctly rethrows/captures the error but the BLoC fails to propagate it to the UI because of the Equatable bug.

- **Recommended Surgical Fix**: Add `errorMessage` to the props list:
  ```dart
  @override
  List<Object?> get props => [
    catalog,
    cart,
    shopBalance,
    cashCollected,
    debtPaid,
    errorMessage,  // ← ADD THIS
  ];
  ```

---

## Issue #7 — Stream Subscription Leak in RefreshIndicator onRefresh

- **Severity**: **High**
- **Flaw Category**: Memory Leak / Stream Subscription Leak
- **File & Line**: `wanasah_frontend/lib/screens/dashboard_screen.dart`, Lines 737–741
- **Current Flawed Code**:
  ```dart
  try {
    await bloc.stream.firstWhere((s) => s is! DashboardLoading)
        .timeout(const Duration(seconds: 5));
  } catch (_) {
    developer.log('[Dashboard] Refresh timeout reached, proceeding safely...');
  }
  ```

- **Impact Analysis**: `bloc.stream.firstWhere(...)` creates a **stream subscription** internally. If the widget is disposed before this future completes (e.g., the user navigates to VisitListScreen during the refresh, or the 401 logout interceptor fires and pushes LoginScreen), the subscription remains active. After disposal:
  1. **Memory leak**: The closure captures `bloc`, preventing GC until the subscription emits/completes.
  2. **Use-after-dispose**: When `firstWhere` eventually completes (or times out), the code after the `try/catch` (lines 743–752) accesses `context`, `mounted`, and `ScaffoldMessenger` on a disposed widget — this triggers a Flutter assertion error in debug mode, or undefined behavior in release mode.
  3. **SnackBar leak**: The "جاري رفع فواتير الأوفلاين" snackbar with `Duration(days: 1)` at line 728 is shown on the current `ScaffoldMessenger`. If the user navigates away, the snackbar persists on the new screen (it was registered on the old scaffold's messenger) or disappears — either way, the code at line 744 tries to `hideCurrentSnackBar()` on a potentially different scaffold, causing a `ScaffoldMessenger` state mismatch.

- **Recommended Surgical Fix**: Store the stream subscription and cancel it on dispose, or use a stateful approach:
  ```dart
  // Add to state class:
  StreamSubscription<DashboardState>? _refreshSubscription;

  // In onRefresh:
  final completer = Completer<void>();
  _refreshSubscription = bloc.stream.listen((s) {
    if (s is! DashboardLoading) {
      completer.complete();
    }
  });
  try {
    await completer.future.timeout(const Duration(seconds: 5));
  } catch (_) { ... }
  _refreshSubscription?.cancel();
  _refreshSubscription = null;

  @override
  void dispose() {
    _refreshSubscription?.cancel();
    super.dispose();
  }
  ```

---

## Issue #8 — Inventory Validation Race Condition on Rapid Cart Additions

- **Severity**: **Medium**
- **Flaw Category**: Duplicate State Mutation / Inventory Bypass
- **File & Line**: `wanasah_frontend/lib/blocs/visit/visit_bloc.dart`, Lines 330–345
- **Current Flawed Code**:
  ```dart
  void _onAddOrUpdateCartItem(
    AddOrUpdateCartItem event,
    Emitter<VisitState> emit,
  ) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;
    if (!event.item.hasEnoughInventory) { ... }
    final updatedCart = List<CartItemModel>.from(currentState.cart);
    final index = updatedCart.indexWhere(
      (i) => i.productVariantId == event.item.productVariantId,
    );
    if (index >= 0) {
      updatedCart[index] = event.item;
    } else {
      updatedCart.add(event.item);
    }
    emit(currentState.copyWith(cart: updatedCart));
  }
  ```

- **Impact Analysis**: The inventory check at line 338 relies on `event.item.hasEnoughInventory`, which was computed **at UI time** against the product's available stock (not accounting for items already in the cart). The BLoC does not re-verify inventory against `currentState.cart`. Scenario:
  1. Product A has 5 cartons available.
  2. User taps "+" to add 5 cartons of A → `hasEnoughInventory` is true, item added to cart.
  3. Before the BLoC state emits (async gap, or rapid tap), user taps "+" to add 3 more cartons of A.
  4. The second `CartItemModel` is built with available=5, so `hasEnoughInventory` is true.
  5. The second BLoC event processes against `currentState.cart` which is still empty (first event not yet emitted).
  6. Both items are added — the driver now has 8 cartons of A in their cart, exceeding the 5 available by 60%.

  This bypasses the local inventory guard entirely. The server will reject the sale with an inventory error (business rules 1.3: negative-stock prevention), but the driver will only discover this after attempting to submit — wasting time and creating confusion.

- **Recommended Surgical Fix**: Re-validate inventory inside the BLoC against the current cart state before accepting the item:
  ```dart
  // Compute total requested cartons/packs from both existing cart and new event
  final existingItem = currentState.cart.firstWhereOrNull(
    (i) => i.productVariantId == event.item.productVariantId,
  );
  final totalRequestedCartons = (existingItem?.cartons ?? 0) + event.item.cartons;
  final totalRequestedPacks = (existingItem?.packs ?? 0) + event.item.packs;
  // Check against product's available stock from catalog
  final product = currentState.catalog.firstWhereOrNull(
    (p) => p.id == event.item.productVariantId,
  );
  if (product != null) {
    if (totalRequestedCartons > product.currentCartons ||
        (totalRequestedCartons == product.currentCartons && totalRequestedPacks > product.currentPacks)) {
      emit(currentState.copyWith(errorMessage: 'الكمية المطلوبة تتجاوز مخزون السيارة'));
      return;
    }
  }
  ```
  *Requires importing `package:collection/collection.dart` for `firstWhereOrNull`.*

---

## Issue #9 — JSON Built with String Interpolation (Injection Risk)

- **Severity**: **Medium**
- **Flaw Category**: Data Integrity / Code Quality
- **File & Line**: `wanasah_frontend/lib/screens/dashboard_screen.dart`, Lines 254–257
- **Current Flawed Code**:
  ```dart
  await LocalDatabase.instance.addPendingSync(
    type: 'toggle_break',
    payload: '{"driver_id": ${widget.driverId}, "action": "$action"}',
  );
  ```

- **Impact Analysis**: The `payload` string is built by interpolating `$action` directly into a JSON template. While `action` is currently constrained to `'start'` or `'end'` (controlled by app logic), any future code change that introduces a user-supplied or unvalidated action value could produce malformed JSON. If the JSON is malformed, `jsonDecode` in `syncUp()` at line 213 throws a `FormatException`, which is caught by the catch block at line 243 — and the record is **skipped permanently** with no deletion. The pending_sync row rots in the queue forever (business rules 6.5: "a corrupted ... record type can remain permanently stuck").

- **Recommended Surgical Fix**: Use proper JSON encoding:
  ```dart
  import 'dart:convert';
  // ...
  await LocalDatabase.instance.addPendingSync(
    type: 'toggle_break',
    payload: jsonEncode({
      'driver_id': widget.driverId,
      'action': action,
    }),
  );
  ```

---

## Issue #10 — Missing Default sendTimeout on Base Dio Options

- **Severity**: **Medium**
- **Flaw Category**: Network Hang / Duplicate Network Request
- **File & Line**: `wanasah_frontend/lib/core/network/api_client.dart`, Lines 95–106
- **Current Flawed Code**:
  ```dart
  final dio = Dio(
    BaseOptions(
      baseUrl: ApiConstants.baseUrl,
      connectTimeout: const Duration(seconds: 30),
      receiveTimeout: const Duration(seconds: 60),
      // ← NO sendTimeout
      headers: { ... },
    ),
  );
  ```

- **Impact Analysis**: While `connectTimeout` (30s) and `receiveTimeout` (60s) are configured, `sendTimeout` is not set at the Dio base level. In poor network conditions, a request may establish a TCP connection but the uplink is too slow to transmit the request body (e.g., a large cart_items payload with images). Without `sendTimeout`, Dio waits **indefinitely** for the request body to finish uploading. This can cause:
  1. The UI to hang on a loading indicator with no feedback.
  2. A user to kill the app, potentially leaving a `pending_sync` record in an inconsistent state.
  3. In extreme cases, a hanging request keeps the Dio connection pool occupied, blocking subsequent requests.

  Some individual call sites set their own `sendTimeout` (e.g., `_startWork` at line 101, `_endWork` at line 153, `_toggleBreak` at line 222), but all raw `ApiClient.instance.put/get/post` calls without explicit options are vulnerable.

- **Recommended Surgical Fix**: Add a default sendTimeout to BaseOptions:
  ```dart
  BaseOptions(
    baseUrl: ApiConstants.baseUrl,
    connectTimeout: const Duration(seconds: 30),
    sendTimeout: const Duration(seconds: 30),
    receiveTimeout: const Duration(seconds: 60),
    headers: { ... },
  ),
  ```

---

## Issue #11 — Debt/Cash Fields Sent for Postponed Visits (Business Rule Violation)

- **Severity**: **Medium**
- **Flaw Category**: Business Rule Violation / Offline Sync Exploit
- **File & Line**: `wanasah_frontend/lib/blocs/visit/visit_bloc.dart`, Lines 440–457
- **Current Flawed Code**:
  ```dart
  final payload = {
    'visit_id': event.visitId,
    'visitId': event.visitId,
    'outcome': event.outcome,
    'notes': event.notes ?? '',
    'cash_collected': currentState.cashCollected,
    'debt_paid': event.debtPaid,
  };

  if (event.outcome == 'Sale' || event.outcome == 'NoSale') {
    if (cartItems.isNotEmpty) payload['cart_items'] = cartItems;
    if (returns.isNotEmpty) payload['returns'] = returns;
    // ...
  }
  ```

  *For `Postponed` visits, `cash_collected` and `debt_paid` are always included in the payload, even though the outcome is not `Sale` or `NoSale`.*

- **Impact Analysis**: Per business rules 3.4: "**`Postponed`** must contain **no cart items, no returns, and no debt payment** — postponing a visit while sneaking in a sale to avoid immediate accounting is explicitly blocked ('Postponed Theft Shield')." While the Flutter code correctly omits `cart_items` and `returns` for Postponed (they are inside the `if` block), `cash_collected` and `debt_paid` are placed at the top-level payload and sent unconditionally. If a driver accidentally enters cash/debt values and then chooses "Postponed," the server receives a Postponed visit with non-zero `debt_paid` — the server should reject this (rule 3.4), but the Flutter app should not be sending conflicting data. This also means the `saveInvoice` method at sync_repository.dart line 121 processes the Postponed visit with potentially non-zero debt values, updating the local database's `cash_collected` and `debt_paid` columns for a visit that is supposed to remain Pending.

- **Recommended Surgical Fix**: Only include cash/debt fields for Sale or NoSale outcomes:
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
    if (event.outcome == 'NoSale') {
      payload['no_sale_reason'] = event.notes ?? '';
    }
  }
  ```

---

## Cross-Reference Matrix: Business Rules vs. Frontend Compliance

| Business Rule (§) | Flutter Compliance | Notes |
|---|---|---|
| 6.1 Write-path priority (network first, 4xx rethrown) | ✅ Compliant | `saveInvoice` correctly attempts network call first, rethrows 4xx |
| 6.1 Local SQLite always updated after success OR fallback | ✅ Compliant | `updateDataTask()` called in both try and catch blocks |
| 6.2 Double-deduction prevention (revertOfflineVisit before new draft) | ✅ Compliant | `revertOfflineVisit` called at line 175 before `addPendingSync` at line 177 |
| 6.3 Upload queue — 401/403 halts loop | ✅ Compliant | Lines 224-228 correctly break on auth errors |
| 6.3 Upload queue — other 4xx skipped | ✅ Compliant | Lines 233-234 correctly continue (preserve record) |
| 6.3 Upload queue — 5xx/no-response halts | ✅ Compliant | Lines 242 correctly break |
| 6.3 Poison-pill handling (unknown exceptions skipped) | ⚠️ Partial | Records skipped but persist forever with no user indicator (see Issue #8 context) |
| 6.4 syncDown calls syncUp first | ✅ Compliant | Line 49 calls `await syncUp()` |
| 6.4 Hard block on non-sale pending records | ✅ Compliant | Lines 52-63 check for non-`submit_sale` types |
| 6.4 Atomic SQLite transaction for refresh | ⚠️ Partial | Atomic, but empty product list causes data wipe (see Issue #3) |
| 6.5 new_balance is only mechanism for financial state sync | ⚠️ Partial | Mechanism exists but fire-and-forget (see Issue #4) |
| 3.4 Postponed visits — no debt payment | ❌ Violation | Cash/debt fields sent unconditionally (see Issue #11) |
| 1.2 Packs-per-carton zero guard | ❌ Missing | Local SQL math in `deductInventoryLocal` has no zero guard |

---

## Summary

| Severity | Count | Issues |
|---|---|---|
| **Critical** | 3 | #1 (TEXT/REAL type drift), #2 (DB singleton race), #3 (empty product wipe) |
| **High** | 4 | #4 (fire-and-forget SQL), #5 (assert crash in release), #6 (Equatable silent error), #7 (stream subscription leak) |
| **Medium** | 4 | #8 (inventory race), #9 (JSON injection), #10 (missing sendTimeout), #11 (Postponed debt violation) |

**Immediate Action Items** (should be fixed before next release):
1. Fix the schema type mismatch (#1) — this silently corrupts financial data differently per user.
2. Fix the empty product wipe (#3) — this can brick a driver's entire day in the field.
3. Fix the fire-and-forget balance update (#4) — the single mechanism for server-authoritative balance sync is broken.
4. Fix the Equatable props (#6) — server rejection messages are completely invisible to drivers.


## Issue #12 — False Success Feedback on Refresh Timeout

- **Severity**: **High**
- **Flaw Category**: State Desync / False UI Feedback
- **File & Line**: `wanasah_frontend/lib/screens/dashboard_screen.dart`, Lines 737–752
- **Current Flawed Code**:
  ```dart
  try {
    await bloc.stream.firstWhere((s) => s is! DashboardLoading).timeout(const Duration(seconds: 5));
  } catch (_) {
    developer.log('[Dashboard] Refresh timeout reached, proceeding safely...');
  }

  if (mounted && hasPendingData) {
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('تم رفع الفواتير وتحديث البيانات بنجاح ✔️'),
        backgroundColor: Colors.green,
        duration: Duration(seconds: 3),
      ),
    );
  }

  Impact Analysis: The 5-second timeout in firstWhere throws a TimeoutException if the network is slow and the BLoC doesn't emit a non-loading state in time. The catch (_) block silently swallows this exception. Execution continues to line 744, where a green success SnackBar is displayed to the driver ("تم رفع الفواتير وتحديث البيانات بنجاح ✔️"). The driver falsely believes their offline invoices were successfully uploaded and reconciled, when in reality the sync is either still hanging or failed. This destroys trust in the UI and can lead to financial disputes at the end of the day.

Recommended Surgical Fix: Track the timeout state and show the appropriate UI feedback.
bool isSuccess = true;
try {
  await bloc.stream.firstWhere((s) => s is! DashboardLoading).timeout(const Duration(seconds: 5));
} catch (_) {
  developer.log('[Dashboard] Refresh timeout reached.');
  isSuccess = false; // +++ Mark as timed out +++
}

if (mounted && hasPendingData) {
  ScaffoldMessenger.of(context).hideCurrentSnackBar();
  if (isSuccess) {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('تم رفع الفواتير وتحديث البيانات بنجاح ✔️'),
        backgroundColor: Colors.green,
        duration: Duration(seconds: 3),
      ),
    );
  } else {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text('انتهى وقت الانتظار. سيستمر الرفع في الخلفية ⏳'),
        backgroundColor: Colors.orange,
        duration: Duration(seconds: 3),
      ),
    );
  }
}

Issue #13 — Ghost Pending Syncs on 404 Hard Reset
Severity: High

Flaw Category: Data Corruption / Ghost Records

File & Line: wanasah_frontend/lib/core/db/local_database.dart, Lines 153–158

Current Flawed Code:
Future<void> clearSessionData() async {
  final db = await database;
  await db.delete('products');
  await db.delete('visits');
  developer.log('[LocalDatabase] Session tables (products, visits) cleared.');
}

Impact Analysis: In dashboard_screen.dart (lines 139 & 188), when the server returns a 404 (indicating the session was forcefully deleted/reset by an admin), the app calls LocalDatabase.instance.clearSessionData() to wipe local data. However, this function deliberately leaves the pending_sync table untouched. When the driver starts a new session, those old offline invoices (belonging to the deleted session) remain in the queue. The next time syncUp() runs, it will blast these obsolete "Ghost Records" to the server, potentially causing HTTP 500s or silently corrupting the new session's ledger with duplicate financial transactions.

Recommended Surgical Fix: Add an optional parameter to wipe the sync queue during a hard reset.
Future<void> clearSessionData({bool clearPendingSyncs = false}) async {
  final db = await database;
  await db.delete('products');
  await db.delete('visits');
  if (clearPendingSyncs) {
    await db.delete('pending_sync');
  }
  developer.log('[LocalDatabase] Session tables cleared. Pending cleared: $clearPendingSyncs');
}

(Note: You must also update dashboard_screen.dart lines 139 & 188 to call clearSessionData(clearPendingSyncs: true)).

Issue #14 — SQLite Divide by Zero Crash in Revert Logic
Severity: Medium

Flaw Category: SQLite Crash / Unhandled Exception

File & Line: wanasah_frontend/lib/core/db/local_database.dart, Lines 284–285

Current Flawed Code:
UPDATE products 
SET 
  current_cartons = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) / packs_per_carton,
  current_packs = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) % packs_per_carton
WHERE id = ?

Impact Analysis: If a product is somehow stored locally with packs_per_carton = 0 (due to missing zero-guards on the backend or a corrupted payload from the dashboard), executing this raw SQL query throws an immediate SQLITE_ERROR: division by zero. This crashes the revertOfflineVisit pre-emptive strike function, completely halting the offline sync save-path (saveInvoice) and permanently preventing the driver from saving any further offline operations for that visit.

Recommended Surgical Fix: Use SQLite's MAX() function to guarantee the denominator is never zero.
UPDATE products 
SET 
  current_cartons = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) / MAX(packs_per_carton, 1),
  current_packs = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) % MAX(packs_per_carton, 1)
WHERE id = ?

## Issue #15 — Incomplete Custody Reversal on Offline Visit Edit (Returns Ignored)

- **Severity**: **High**
- **Flaw Category**: Offline Sync Exploit / State Desync
- **File & Line**: `wanasah_frontend/lib/core/db/local_database.dart`, `revertOfflineVisit`
- **Current Flawed Code**:
  The `revertOfflineVisit` function iterates over `cartItems` to return quantities back to local `current_cartons` and `current_packs`. It completely ignores the `returns` array.
- **Impact Analysis**: Failing to revert returns during an offline edit means that if a driver edits the same offline visit multiple times and modifies their returned items, the `pending_sync` payload is updated correctly for the server, but the local SQLite database never reflects the correct reversed state. This causes the driver's local visual custody (offline dashboard) to gradually desync from the actual payload, leading to confusion in field operations until a full online `syncDown` is performed.
- **Recommended Surgical Fix**: If local custody is intended to reflect returns offline, include the `returns` array in the `revertOfflineVisit` logic, symmetrically to how sales are handled.
  *(Note: This requires ensuring `deductInventoryLocal` also symmetrically handles returns to maintain a zero-sum balance).*

---

## Issue #16 — 401 Unauthorized Interceptor Leaks Sensitive Offline Data

- **Severity**: **High**
- **Flaw Category**: Security / Data Leak Risk
- **File & Line**: `wanasah_frontend/lib/core/network/api_client.dart`, Lines 44–50
- **Current Flawed Code**:
  ```dart
  if (err.response?.statusCode == 401) {
    if (!err.requestOptions.path.contains('/login')) {
      onUnauthorized();
    }
  }

  Impact Analysis: When a 401 Unauthorized is caught, the interceptor triggers onUnauthorized() which signals the BLoC to navigate to the login screen. However, it does not explicitly guarantee the wiping of wanasah_offline.db and FlutterSecureStorage at the network layer. If the UI simply redirects without a hard DB wipe, the previous driver's offline data, pending syncs, and customer locations remain physically on the device. A new driver logging into the same device could potentially sync the previous driver's pending records, crossing data boundaries and causing severe financial misattribution.

Recommended Surgical Fix: Force a hard wipe of the local session data immediately when a 401 is intercepted, before triggering the UI redirect.

if (err.response?.statusCode == 401) {
  if (!err.requestOptions.path.contains('/login')) {
    developer.log('[AuthInterceptor] 401 → Wiping local data and triggering logout');
    // +++ Hard Wipe to prevent cross-account data leaks +++
    LocalDatabase.instance.clearSessionData(clearPendingSyncs: true);
    const FlutterSecureStorage().deleteAll();

    onUnauthorized();
  }
}
