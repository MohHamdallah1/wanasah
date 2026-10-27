// File: lib/core/db/local_database.dart
//
// الوظيفة الكاملة لهذا الملف:
//   - إنشاء وإدارة قاعدة البيانات المحلية المعزولة فيزيائياً (wanasah_local_$companyCode.db).
//   - توفير نقطة وصول واحدة (Singleton) لتجنب فتح اتصالات متعددة.
//   - تعريف مخطط الجداول الثلاثة: products, visits, pending_sync.
//
// -----------------------------------------------------------------------
// pending_sync هو "الخزنة السرية": يحتفظ بالمبيعات والعمليات التي
// لم ترسل بعد إلى السيرفر بسبب انقطاع الإنترنت، وتُرسل عند عودة الاتصال.
// -----------------------------------------------------------------------

import 'package:sqflite/sqflite.dart';
import 'package:path/path.dart';
import 'package:path_provider/path_provider.dart';
import 'dart:developer' as developer;
import 'dart:convert'; // +++ إضافة مكتبة فك التشفير +++

// +++ استيراد الموديلات الذكية لفرض الحماية +++
import '../../models/product_model.dart';
import '../../models/visit_model.dart';
import '../sync/durable_command.dart';
import '../sync/pending_command_store.dart';
import 'visit/visit_local_persistence.dart';
import '../serialization/pending_transfer_quantity.dart';

class LocalDatabase {
  // -----------------------------------------------------------------------
  // Singleton Pattern
  // -----------------------------------------------------------------------
  LocalDatabase._privateConstructor();

  static final LocalDatabase instance = LocalDatabase._privateConstructor();

  late final PendingCommandStore pendingCommands = PendingCommandStore(
    databaseProvider: () => database,
    tenantProvider: () => currentTenant,
  );

  late final VisitLocalPersistence _visitPersistence = VisitLocalPersistence(
    databaseProvider: () => database,
    pendingCommands: pendingCommands,
  );

  // الاتصال الوحيد بقاعدة البيانات — null حتى يتم التهيئة للمرة الأولى
  static Database? _database;
  
  // +++ الدرع المعماري (Mutex Lock): منع التطبيق من محاولة فتح القاعدة مرتين بنفس اللحظة +++
  static Future<Database>? _initDbFuture;

  // +++ الدرع السيادي الفيزيائي (Physical Tenant Isolation) +++
  String? _companyCode;
  int _dbGeneration = 0; // +++ عداد الجيل (Generation Counter) لنسف سباق الأقفال +++

  Future<void> setTenant(String companyCode) async {
    if (_companyCode == companyCode) return; 

    _dbGeneration++; // إبطال أي عملية فتح جارية في الخلفية
    _companyCode = companyCode;

    if (_database != null) {
      await _database?.close(); // استخدام ?. لسحق خطأ الـ Null Safety
    }
    _database = null;
    _initDbFuture = null;

    developer.log('[LocalDatabase] 🛡️ Physical Tenant Isolation Active: $_companyCode (Gen: $_dbGeneration)');
  }

  Future<void> resetTenant() async {
    _dbGeneration++;
    if (_database != null) {
      await _database?.close();
    }
    _database = null;
    _initDbFuture = null;
    _companyCode = null;
    developer.log('[LocalDatabase] 🛡️ Tenant Identity Cleared. DB Closed.');
  }

  String get currentTenant {
    if (_companyCode == null) {
      throw Exception('🚨 حرج أمنياً: لم يتم حقن رمز الشركة (Tenant Code) في قاعدة البيانات. التطبيق يحاول كسر العزل.');
    }
    return _companyCode!;
  }

  /// نقطة الوصول العامة للاتصال.
  /// إذا لم يتم فتح الاتصال بعد، يتم استدعاء [_initDB] تلقائياً (Lazy Init).
  Future<Database> get database async {
    while (true) {
      if (_database != null && _database!.isOpen) return _database!;

      final currentGen = _dbGeneration;
      _initDbFuture ??= _initDB();

      try {
        final db = await _initDbFuture!;
        
        // +++ حارس الجيل: إذا تغير الجيل أثناء الفتح (تم تغيير الشركة)، نغلقها فوراً ونعيد المحاولة من خلال الحلقة +++
        if (currentGen != _dbGeneration) {
          developer.log('[LocalDatabase] ⚠️ Generation mismatch detected ($currentGen != $_dbGeneration). Reconnecting...');
          await db.close();
          _initDbFuture = null;
          continue; // عودة لبداية الـ while دون استدعاء ذاتي (Recursion)
        }
        
        _database = db;
        return _database!;
      } finally {
        if (currentGen == _dbGeneration) {
          _initDbFuture = null; 
        }
      }
    }
  }

  // -----------------------------------------------------------------------
  // التهيئة: فتح / إنشاء ملف قاعدة البيانات
  // -----------------------------------------------------------------------
  Future<Database> _initDB() async {
    final documentsDirectory = await getApplicationDocumentsDirectory();
    // +++ العزل الفيزيائي (Physical Isolation): اسم الملف يتغير تلقائياً حسب رمز الشركة +++
    final dbPath = join(documentsDirectory.path, 'wanasah_local_$currentTenant.db');

    developer.log('[LocalDatabase] Opening isolated database at: $dbPath');

    return await openDatabase(
      dbPath,
      version: 11, // V11: additive canonical pending-transfer display evidence
      onCreate: _onCreate,
      onUpgrade: _onUpgrade,
    );
  }

  Future<void> _safeAlterTable(Database db, String sql) async {
    try {
      await db.execute(sql);
    } catch (e) {
      if (!e.toString().contains('duplicate column name')) {
        rethrow;
      }
    }
  }

  // -----------------------------------------------------------------------
  // onCreate: بناء الجداول النظيفة (بدون company_id)
  // -----------------------------------------------------------------------
  Future<void> _onCreate(Database db, int version) async {
    developer.log('[LocalDatabase] Creating tables for version $version...');

    await db.execute('''
      CREATE TABLE products (
        id                 INTEGER PRIMARY KEY,
        name               TEXT    NOT NULL,
        price_per_carton   REAL    NOT NULL,
        price_per_pack     REAL    NOT NULL,
        packs_per_carton   INTEGER NOT NULL,
        starting_cartons   INTEGER DEFAULT 0,
        starting_packs     INTEGER DEFAULT 0,
        sold_cartons       INTEGER DEFAULT 0,
        sold_packs         INTEGER DEFAULT 0,
        current_cartons    INTEGER DEFAULT 0,
        current_packs      INTEGER DEFAULT 0
      )
    ''');

    await db.execute('''
        CREATE TABLE visits (
          visit_id INTEGER PRIMARY KEY, 
          shop_id INTEGER,
          shop_name TEXT,
          shop_balance REAL,
          max_debt_limit REAL DEFAULT 0.0,
          shop_zone_id INTEGER,
          allowed_zone_id INTEGER,
          status TEXT,
          outcome TEXT,
          visit_sequence INTEGER DEFAULT 999, 
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

    await db.execute('''
      CREATE TABLE incoming_transfers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        transfer_id INTEGER,
        product_variant_id INTEGER,
        product_name TEXT,
        delta_cartons INTEGER,
        delta_packs INTEGER,
        status TEXT,
        created_at TEXT,
        batch_id TEXT,
        quantity_contract TEXT,
        signed_base_quantity TEXT,
        base_uom_id INTEGER,
        base_uom_code TEXT,
        base_uom_name TEXT,
        quantity_scale INTEGER,
        quantity_step TEXT,
        display_uom_name TEXT,
        display_factor_to_base TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE pending_sync (
        id                 INTEGER PRIMARY KEY AUTOINCREMENT,
        type               TEXT    NOT NULL,
        payload            TEXT    NOT NULL,
        created_at         TEXT    NOT NULL,
        command_id         TEXT,
        state              TEXT    NOT NULL DEFAULT 'pending',
        owner_company_code TEXT,
        owner_driver_id    INTEGER,
        attempt_count      INTEGER NOT NULL DEFAULT 0,
        last_error_code    TEXT,
        last_error_message TEXT,
        last_request_id    TEXT,
        local_effect_applied INTEGER NOT NULL DEFAULT 0,
        updated_at         TEXT
      )
    ''');
    await db.execute(
      'CREATE INDEX IF NOT EXISTS ix_pending_sync_state_created '
      'ON pending_sync(state, created_at, id)',
    );

    developer.log('[LocalDatabase] All tables created successfully.');
  }

  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
    developer.log('[LocalDatabase] Upgrading DB from v$oldVersion to v$newVersion');
    if (oldVersion < 2) {
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN cash_collected REAL DEFAULT 0.0');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN debt_paid REAL DEFAULT 0.0');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN max_debt_limit REAL DEFAULT 0.0');
    }
    if (oldVersion < 3) {
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN visit_sequence INTEGER DEFAULT 999');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN is_emergency INTEGER DEFAULT 0');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN location_link TEXT');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN latitude REAL');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN longitude REAL');
    }
    if (oldVersion < 4) {
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN cart_items TEXT');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN returns TEXT');
    }
    if (oldVersion < 5) {
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN notes TEXT');
    }
    if (oldVersion < 6) {
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN shop_owner TEXT');
      await _safeAlterTable(db, 'ALTER TABLE visits ADD COLUMN shop_phone TEXT');
    }
    if (oldVersion < 7) {
      await db.execute('''
        CREATE TABLE visits_v7 (
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
      await db.execute('''
        INSERT INTO visits_v7 SELECT
          visit_id, shop_id, shop_name,
          CAST(IFNULL(NULLIF(shop_balance, ''), 0.0) AS REAL),
          CAST(IFNULL(NULLIF(max_debt_limit, ''), 0.0) AS REAL),
          shop_zone_id, allowed_zone_id, status, outcome,
          visit_sequence, is_emergency, location_link,
          latitude, longitude, shop_owner, shop_phone,
          CAST(IFNULL(NULLIF(cash_collected, ''), 0.0) AS REAL),
          CAST(IFNULL(NULLIF(debt_paid, ''), 0.0) AS REAL),
          cart_items, returns, notes
        FROM visits
      ''');
      await db.execute('DROP TABLE visits');
      await db.execute('ALTER TABLE visits_v7 RENAME TO visits');
      developer.log('[LocalDatabase] v7 migration: Normalized monetary columns to REAL.');
    }
    if (oldVersion < 8) {
      await db.execute('''
        CREATE TABLE IF NOT EXISTS incoming_transfers (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          transfer_id INTEGER,
          product_variant_id INTEGER,
          product_name TEXT,
          delta_cartons INTEGER,
          delta_packs INTEGER,
          status TEXT,
          created_at TEXT,
          batch_id TEXT
        )
      ''');
    }
    if (oldVersion < 9) {
      await _safeAlterTable(db, 'ALTER TABLE products ADD COLUMN starting_packs INTEGER DEFAULT 0');
      await _safeAlterTable(db, 'ALTER TABLE products ADD COLUMN sold_cartons INTEGER DEFAULT 0');
      await _safeAlterTable(db, 'ALTER TABLE products ADD COLUMN sold_packs INTEGER DEFAULT 0');
    }
    if (oldVersion < 10) {
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN command_id TEXT');
      await _safeAlterTable(db, "ALTER TABLE pending_sync ADD COLUMN state TEXT NOT NULL DEFAULT 'pending'");
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN owner_company_code TEXT');
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN owner_driver_id INTEGER');
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN attempt_count INTEGER NOT NULL DEFAULT 0');
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN last_error_code TEXT');
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN last_error_message TEXT');
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN last_request_id TEXT');
      await _safeAlterTable(
        db,
        'ALTER TABLE pending_sync ADD COLUMN local_effect_applied INTEGER NOT NULL DEFAULT 0',
      );
      await _safeAlterTable(db, 'ALTER TABLE pending_sync ADD COLUMN updated_at TEXT');

      await db.rawUpdate(
        "UPDATE pending_sync SET state = ? WHERE type LIKE 'quarantined_%'",
        [DurableCommandState.blocked.storageValue],
      );
      await db.rawUpdate(
        'UPDATE pending_sync SET owner_company_code = ? '
        'WHERE owner_company_code IS NULL OR TRIM(owner_company_code) = ?',
        [currentTenant, ''],
      );
      await db.rawUpdate(
        'UPDATE pending_sync SET updated_at = created_at WHERE updated_at IS NULL',
      );
      await db.execute(
        'CREATE INDEX IF NOT EXISTS ix_pending_sync_state_created '
        'ON pending_sync(state, created_at, id)',
      );
      developer.log(
        '[LocalDatabase] v10 migration: preserved pending_sync rows and added durable lifecycle metadata.',
      );
    }
    if (oldVersion < 11) {
      for (final column in const [
        'quantity_contract TEXT', 'signed_base_quantity TEXT', 'base_uom_id INTEGER',
        'base_uom_code TEXT', 'base_uom_name TEXT', 'quantity_scale INTEGER',
        'quantity_step TEXT', 'display_uom_name TEXT', 'display_factor_to_base TEXT',
      ]) {
        await _safeAlterTable(db, 'ALTER TABLE incoming_transfers ADD COLUMN $column');
      }
    }
  }

  // -----------------------------------------------------------------------
  // دوال مساعدة عامة للـ CRUD
  // -----------------------------------------------------------------------

  Future<void> clearSessionData({bool clearPendingSyncs = false}) async {
    final db = await database;

    if (clearPendingSyncs) {
      throw UnsupportedError(
        'Offline command evidence cannot be bulk-deleted by session cleanup.',
      );
    }

    final unresolvedCount = Sqflite.firstIntValue(
      await db.rawQuery('SELECT COUNT(*) FROM pending_sync'),
    );
    if (unresolvedCount != null && unresolvedCount > 0) {
      developer.log(
        '[LocalDatabase] Skipped clearing session tables: unresolved offline command evidence exists.',
      );
      return;
    }

    await db.transaction((txn) async {
      await txn.delete('products');
      await txn.delete('visits');
      await txn.delete('incoming_transfers');
    });
    developer.log('[LocalDatabase] Session tables cleared safely via transaction.');
  }

  Future<void> insertProducts(List<ProductModel> products) async {
    final db = await database;
    final batch = db.batch();
    for (final product in products) {
      batch.insert(
        'products',
        product.toJson(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
  }

  Future<void> insertVisits(List<VisitModel> visits) async {
    final db = await database;
    final batch = db.batch();
    for (final visit in visits) {
      batch.insert(
        'visits',
        visit.toJson(),
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
  }

  Future<int> addPendingSync({
    required String type,
    required String payload,
    String? commandId,
    DurableCommandState state = DurableCommandState.pending,
    int? ownerDriverId,
    String? lastErrorCode,
    String? lastErrorMessage,
    String? lastRequestId,
    Transaction? txn,
  }) {
    return pendingCommands.add(
      type: type,
      payload: payload,
      commandId: commandId,
      state: state,
      ownerDriverId: ownerDriverId,
      lastErrorCode: lastErrorCode,
      lastErrorMessage: lastErrorMessage,
      lastRequestId: lastRequestId,
      txn: txn,
    );
  }

  Future<List<Map<String, dynamic>>> getPendingSyncs({int? limit}) =>
      pendingCommands.all(limit: limit);

  Future<void> deletePendingSync(int id) =>
      pendingCommands.deleteAfterConfirmedSuccess(id);

  Future<void> markPendingSyncInFlight(int id) =>
      pendingCommands.markInFlight(id);

  Future<void> markPendingSyncPending(
    int id, {
    String? lastErrorCode,
    String? lastErrorMessage,
    String? lastRequestId,
  }) {
    return pendingCommands.markPending(
      id,
      lastErrorCode: lastErrorCode,
      lastErrorMessage: lastErrorMessage,
      lastRequestId: lastRequestId,
    );
  }

  Future<void> markPendingSyncBlocked(
    int id, {
    required String errorCode,
    String? errorMessage,
    String? requestId,
  }) {
    return pendingCommands.markBlocked(
      id,
      errorCode: errorCode,
      errorMessage: errorMessage,
      requestId: requestId,
    );
  }

  Future<void> updatePendingSyncPayload(int id, String payload) =>
      pendingCommands.updatePayload(id, payload);

  Future<void> updatePendingSyncCommandId(int id, String commandId) =>
      pendingCommands.updateCommandId(id, commandId);

  Future<List<Map<String, dynamic>>> getProducts() async {
    final db = await database;
    return db.query('products');
  }

  Future<List<Map<String, dynamic>>> getVisits() async {
    final db = await database;
    return db.query('visits');
  }

  Future<void> updateVisitStatus({
    required int visitId,
    required String status,
    required String outcome,
    double cashCollected = 0.0,
    double debtPaid = 0.0,
    double? newShopBalance,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    Transaction? txn,
  }) =>
      _visitPersistence.updateVisitStatus(
        visitId: visitId,
        status: status,
        outcome: outcome,
        cashCollected: cashCollected,
        debtPaid: debtPaid,
        newShopBalance: newShopBalance,
        cartItemsJson: cartItemsJson,
        returnsJson: returnsJson,
        notes: notes,
        txn: txn,
      );

  Future<void> deductInventoryLocal(
    List<dynamic> cartItems, {
    List<dynamic>? returnItems,
    Transaction? txn,
  }) =>
      _visitPersistence.deductInventoryLocal(
        cartItems,
        returnItems: returnItems,
        txn: txn,
      );

  @Deprecated(
    'Unresolved visit commands are immutable until reconciliation; use stageVisitCommandAtomic.',
  )
  Future<void> revertOfflineVisit(int visitId, {Transaction? txn}) =>
      _visitPersistence.revertOfflineVisit(visitId, txn: txn);

  Future<int> stageVisitCommandAtomic({
    required int visitId,
    required String payload,
    required String requestId,
    int? ownerDriverId,
  }) =>
      _visitPersistence.stageVisitCommandAtomic(
        visitId: visitId,
        payload: payload,
        requestId: requestId,
        ownerDriverId: ownerDriverId,
      );

  Future<bool> isFirstUnresolvedCommand(int commandRecordId) async {
    final rows = await getPendingSyncs(limit: 1);
    if (rows.isEmpty) return false;
    return (rows.first['id'] as num?)?.toInt() == commandRecordId;
  }

  Future<void> finalizeVisitCommandLocalState({
    required int commandRecordId,
    required int visitId,
    required String status,
    required String outcome,
    required double cashCollected,
    required double debtPaid,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    required List<dynamic> cartItems,
    List<dynamic>? returnItems,
  }) =>
      _visitPersistence.finalizeVisitCommandLocalState(
        commandRecordId: commandRecordId,
        visitId: visitId,
        status: status,
        outcome: outcome,
        cashCollected: cashCollected,
        debtPaid: debtPaid,
        cartItemsJson: cartItemsJson,
        returnsJson: returnsJson,
        notes: notes,
        cartItems: cartItems,
        returnItems: returnItems,
      );



  Future<void> updateShopBalanceLocally(
    int visitId,
    double newBalance,
  ) =>
      _visitPersistence.updateShopBalanceLocally(visitId, newBalance);

  Future<void> close() async {
    if (_database != null) {
      await _database!.close();
      _database = null;
      developer.log('[LocalDatabase] Database connection closed.');
    }
  }

  Future<void> refreshVisitsOnly(List<VisitModel> visits) async {
    final db = await database;
    await db.transaction((txn) async {
      await txn.delete('visits');
      final batch = txn.batch();
      for (final visit in visits) {
        batch.insert(
          'visits',
          visit.toJson(),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
      await batch.commit(noResult: true);
    });
  }

  Future<List<Map<String, dynamic>>> getIncomingTransfers() async {
    final db = await database;
    return db.query('incoming_transfers');
  }

  Future<void> refreshSessionData(
    List<VisitModel> visits,
    List<ProductModel> products,
    List<Map<String, dynamic>>? incomingTransfers, {
    bool clearVisits = false,
    bool clearProducts = false,
  }) async {
    final db = await database;
    await db.transaction((txn) async {
      if (clearProducts) await txn.delete('products');
      if (clearVisits) await txn.delete('visits');
      if (incomingTransfers != null) {
        await txn.delete('incoming_transfers'); 
      }

      final pendingResponses = await txn.query('pending_sync', where: "type = 'transfer_response'");
      final List<int> answeredTransferIds = pendingResponses.map((p) {
        try { return jsonDecode(p['payload'] as String)['transferId'] as int; } 
        catch (_) { return -1; }
      }).toList();

      final batch = txn.batch();

      for (final product in products) {
        batch.insert(
          'products',
          product.toJson(),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }

      for (final visit in visits) {
        batch.insert(
          'visits',
          visit.toJson(),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }

      if (incomingTransfers != null) {
        for (final transfer in incomingTransfers) {
          final int tId = int.tryParse(transfer['transfer_id']?.toString() ?? transfer['id']?.toString() ?? '') ?? 0;
          if (tId == 0 || answeredTransferIds.contains(tId)) continue;
          
          final String batchId = transfer['batch_id']?.toString() ?? 'SINGLE_${transfer['transfer_id'] ?? transfer['id']}';
          batch.insert(
            'incoming_transfers',
            {
              'transfer_id': transfer['transfer_id'] ?? transfer['id'],
              'product_variant_id': (transfer['product_variant_id'] as num?)?.toInt() ?? 0,
              'product_name': transfer['product_name']?.toString() ?? 'غير معروف',
              'delta_cartons': (transfer['delta_cartons'] as num?)?.toInt() ?? 0,
              'delta_packs': (transfer['delta_packs'] as num?)?.toInt() ?? 0,
              'status': transfer['status']?.toString() ?? 'pending',
              'created_at': transfer['created_at']?.toString(),
              'batch_id': batchId,
              ...?(PendingTransferQuantity.fromEvidence(transfer)?.toEvidence()),
            },
            conflictAlgorithm: ConflictAlgorithm.replace,
          );
        }
      }
      await batch.commit(noResult: true);
    });
  }

  Future<void> removeIncomingTransfer(int transferId) async {
    final db = await database;
    await db.delete(
      'incoming_transfers',
      where: 'transfer_id = ?',
      whereArgs: [transferId],
    );
  }

  Future<void> saveOnlineInvoiceAtomic({
    required int visitId,
    required String status,
    required String outcome,
    required double cashCollected,
    required double debtPaid,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    required List<dynamic> cartItems,
    List<dynamic>? returnItems,
  }) =>
      _visitPersistence.saveOnlineInvoiceAtomic(
        visitId: visitId,
        status: status,
        outcome: outcome,
        cashCollected: cashCollected,
        debtPaid: debtPaid,
        cartItemsJson: cartItemsJson,
        returnsJson: returnsJson,
        notes: notes,
        cartItems: cartItems,
        returnItems: returnItems,
      );

  @Deprecated(
    'Use SyncRepository.saveInvoice; durable identity must be staged before first send.',
  )
  Future<void> saveOfflineInvoiceAtomic({
    required int visitId,
    required String payload,
    required String status,
    required String outcome,
    required double cashCollected,
    required double debtPaid,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    required List<dynamic> cartItems,
    List<dynamic>? returnItems,
    String? commandId,
    int? ownerDriverId,
  }) =>
      _visitPersistence.saveOfflineInvoiceAtomic(
        visitId: visitId,
        payload: payload,
        status: status,
        outcome: outcome,
        cashCollected: cashCollected,
        debtPaid: debtPaid,
        cartItemsJson: cartItemsJson,
        returnsJson: returnsJson,
        notes: notes,
        cartItems: cartItems,
        returnItems: returnItems,
        commandId: commandId,
        ownerDriverId: ownerDriverId,
      );

  Future<List<Map<String, dynamic>>> getQuarantinedSyncs() =>
      pendingCommands.blocked();

  @Deprecated('Blocked offline evidence must not be deleted from field UI.')
  Future<void> deleteQuarantinedSync(int id) async {
    throw UnsupportedError(
      'Blocked offline command evidence cannot be deleted from field UI.',
    );
  }

  @Deprecated('Blocked offline evidence must not be bulk-deleted.')
  Future<void> clearAllQuarantinedSyncs() async {
    throw UnsupportedError(
      'Blocked offline command evidence cannot be bulk-deleted.',
    );
  }

  Future<void> retryQuarantinedSync(int id) =>
      pendingCommands.retryBlocked(id);

}
