// File: lib/core/db/local_database.dart
//
// الوظيفة الكاملة لهذا الملف:
//   - إنشاء وإدارة قاعدة البيانات المحلية SQLite (wanasah_offline.db).
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

class LocalDatabase {
  // -----------------------------------------------------------------------
  // Singleton Pattern
  // -----------------------------------------------------------------------
  LocalDatabase._privateConstructor();

  static final LocalDatabase instance = LocalDatabase._privateConstructor();

  // الاتصال الوحيد بقاعدة البيانات — null حتى يتم التهيئة للمرة الأولى
  static Database? _database;
  
  // +++ الدرع المعماري (Mutex Lock): منع التطبيق من محاولة فتح القاعدة مرتين بنفس اللحظة +++
  static Future<Database>? _initDbFuture;

  /// نقطة الوصول العامة للاتصال.
  /// إذا لم يتم فتح الاتصال بعد، يتم استدعاء [_initDB] تلقائياً (Lazy Init).
  Future<Database> get database async {
    if (_database != null) return _database!;
    
    _initDbFuture ??= _initDB();
    // +++ الكي الجراحي 6: حماية Mutex من تعليق الـ Future للأبد +++
    try {
      _database = await _initDbFuture;
    } finally {
      _initDbFuture = null; 
    }
    
    return _database!;
  }

  // -----------------------------------------------------------------------
  // التهيئة: فتح / إنشاء ملف قاعدة البيانات
  // -----------------------------------------------------------------------
  Future<Database> _initDB() async {
    // الحصول على مجلد التخزين الخاص بالتطبيق على الجهاز
    final documentsDirectory = await getApplicationDocumentsDirectory();
    final dbPath = join(documentsDirectory.path, 'wanasah_offline.db');

    developer.log('[LocalDatabase] Opening database at: $dbPath');

    return await openDatabase(
      dbPath,
      version: 9, // +++ ترقية فولاذية لدعم حقول المبيعات الصافية +++
      onCreate: _onCreate,
      onUpgrade: _onUpgrade,
    );
  }

  // -----------------------------------------------------------------------
  // onCreate: بناء الجداول عند إنشاء قاعدة البيانات لأول مرة
  // -----------------------------------------------------------------------
  Future<void> _onCreate(Database db, int version) async {
    developer.log('[LocalDatabase] Creating tables for version $version...');

    // --- جدول المنتجات ---
    // يُخزِّن قائمة المنتجات (مخزون السيارة) مع توسعة الاستلام
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

    // --- جدول الزيارات ---
    // يُخزِّن قائمة زيارات اليوم (محدث ليتطابق حرفياً مع VisitModel)
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

    // --- جدول المزامنة المعلقة (الخزنة السرية) ---
    // يُخزِّن أي عملية (بيع، إرجاع، ...) لم تصل إلى السيرفر بعد.
    //   type    : نوع العملية (مثال: "submit_sale", "return_visit")
    //   payload : بيانات العملية كاملة بصيغة JSON نصي
    //   created_at: توقيت الإنشاء بصيغة ISO 8601
    // --- جدول الحوالات الواردة (المصافحات) ---
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
        batch_id TEXT
      )
    ''');

    await db.execute('''
      CREATE TABLE pending_sync (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        type       TEXT    NOT NULL,
        payload    TEXT    NOT NULL,
        created_at TEXT    NOT NULL
      )
    ''');

    developer.log('[LocalDatabase] All tables created successfully.');
  }

  // -----------------------------------------------------------------------
  // onUpgrade: للاستخدام المستقبلي عند رفع version رقم الـ DB
  // -----------------------------------------------------------------------
  Future<void> _onUpgrade(Database db, int oldVersion, int newVersion) async {
    developer.log(
      '[LocalDatabase] Upgrading DB from v$oldVersion to v$newVersion',
    );
    if (oldVersion < 2) {
      await db.execute(
        'ALTER TABLE visits ADD COLUMN cash_collected REAL DEFAULT 0.0',
      );
      await db.execute(
        'ALTER TABLE visits ADD COLUMN debt_paid REAL DEFAULT 0.0',
      );
      await db.execute(
        'ALTER TABLE visits ADD COLUMN max_debt_limit REAL DEFAULT 0.0',
      );
    }
    // +++ الدرع الواقي: حماية التطبيق من الانهيار عند تحديث المندوب للنسخة الجديدة (v3) +++
    if (oldVersion < 3) {
      await db.execute(
        'ALTER TABLE visits ADD COLUMN visit_sequence INTEGER DEFAULT 999',
      );
      await db.execute(
        'ALTER TABLE visits ADD COLUMN is_emergency INTEGER DEFAULT 0',
      );
      await db.execute('ALTER TABLE visits ADD COLUMN location_link TEXT');
      await db.execute('ALTER TABLE visits ADD COLUMN latitude REAL');
      await db.execute('ALTER TABLE visits ADD COLUMN longitude REAL');
    }
    // +++ الترقية الفولاذية (v4) لدعم حفظ محتويات الزيارات المكتملة +++
    if (oldVersion < 4) {
      await db.execute('ALTER TABLE visits ADD COLUMN cart_items TEXT');
      await db.execute('ALTER TABLE visits ADD COLUMN returns TEXT');
    }
    if (oldVersion < 5) {
      await db.execute('ALTER TABLE visits ADD COLUMN notes TEXT');
    }
    // +++ الترقية الفولاذية (v6) لدعم معلومات الاتصال بالمالك +++
    if (oldVersion < 6) {
      await db.execute('ALTER TABLE visits ADD COLUMN shop_owner TEXT');
      await db.execute('ALTER TABLE visits ADD COLUMN shop_phone TEXT');
    }
    // flutter.md Issue #1 (v7): Normalize monetary columns from TEXT to REAL
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
          -- +++ الكي الجراحي 2: حماية التحويل من الفراغات والـ NULL لمنع انهيار الترقية +++
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

  // +++ الترقية الفولاذية (v8) لدعم المصافحات الأوفلاين +++
    if (oldVersion < 8) {
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
          batch_id TEXT
        )
      ''');
      developer.log('[LocalDatabase] v8 migration: Created incoming_transfers table.');
    }
  
  // +++ الترقية الفولاذية (v9) لدعم حقول المبيعات الصافية من السيرفر +++
    if (oldVersion < 9) {
      await db.execute('ALTER TABLE products ADD COLUMN starting_packs INTEGER DEFAULT 0');
      await db.execute('ALTER TABLE products ADD COLUMN sold_cartons INTEGER DEFAULT 0');
      await db.execute('ALTER TABLE products ADD COLUMN sold_packs INTEGER DEFAULT 0');
      developer.log('[LocalDatabase] v9 migration: Added sales tracking columns to products table.');
    }
  }

  // -----------------------------------------------------------------------
  // دوال مساعدة عامة للـ CRUD
  // -----------------------------------------------------------------------

  /// حذف جميع بيانات الجلسة السابقة (products + visits) مع الحفاظ على pending_sync.
  /// يُستدعى في بداية كل جلسة عمل جديدة لضمان البيانات المحدَّثة.
  /// CS-04 / flutter.md Issue #13: Add optional clearPendingSyncs parameter (default false)
  Future<void> clearSessionData({bool clearPendingSyncs = false}) async {
    final db = await database;
    await db.delete('products');
    await db.delete('visits');
    // +++ الكي الجراحي لـ Bug 2: تنظيف أشباح الحوالات السابقة لمنع تسربها لليوم التالي +++
    await db.delete('incoming_transfers');
    
    if (clearPendingSyncs) {
      await db.delete('pending_sync');
    }
    developer.log('[LocalDatabase] Session tables (products, visits, incoming_transfers${clearPendingSyncs ? ', pending_sync' : ''}) cleared.');
  }

  /// إدراج أو استبدال مجموعة من المنتجات دفعةً واحدة (Batch Insert) باستخدام الكائنات الذكية.
  Future<void> insertProducts(List<ProductModel> products) async {
    final db = await database;
    final batch = db.batch();
    for (final product in products) {
      batch.insert(
        'products',
        product.toJson(), // +++ تفكيك الكائن بأمان تام +++
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
    developer.log('[LocalDatabase] Inserted ${products.length} products.');
  }

  /// إدراج أو استبدال مجموعة من الزيارات دفعةً واحدة (Batch Insert) باستخدام الكائنات الذكية.
  Future<void> insertVisits(List<VisitModel> visits) async {
    final db = await database;
    final batch = db.batch();
    for (final visit in visits) {
      batch.insert(
        'visits',
        visit.toJson(), // +++ تفكيك الكائن بأمان تام +++
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
    developer.log('[LocalDatabase] Inserted ${visits.length} visits.');
  }

  /// إضافة عملية معلقة إلى الخزنة السرية (pending_sync).
  Future<int> addPendingSync({
    required String type,
    required String payload,
  }) async {
    final db = await database;
    final id = await db.insert('pending_sync', {
      'type': type,
      'payload': payload,
      'created_at': DateTime.now().toIso8601String(),
    });
    developer.log('[LocalDatabase] PendingSync added → id=$id, type=$type');
    return id;
  }

  /// جلب كل العمليات المعلقة (للإرسال عند عودة الإنترنت).
  Future<List<Map<String, dynamic>>> getPendingSyncs() async {
    final db = await database;
    return db.query('pending_sync', orderBy: 'created_at ASC');
  }

  /// حذف عملية معلقة بعد إرسالها بنجاح إلى السيرفر.
  Future<void> deletePendingSync(int id) async {
    final db = await database;
    await db.delete('pending_sync', where: 'id = ?', whereArgs: [id]);
    developer.log('[LocalDatabase] PendingSync deleted → id=$id');
  }

  /// جلب كل المنتجات المحلية.
  Future<List<Map<String, dynamic>>> getProducts() async {
    final db = await database;
    return db.query('products');
  }

  /// جلب كل الزيارات المحلية.
  Future<List<Map<String, dynamic>>> getVisits() async {
    final db = await database;
    return db.query('visits');
  }

  /// تحديث حالة زيارة محددة محلياً (عند إتمام البيع Offline).
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
  }) async {
    final db = await database;
    final Map<String, dynamic> updateData = {
      'status': status,
      'outcome': outcome,
      'cash_collected': cashCollected,
      'debt_paid': debtPaid,
      // +++ الكي الجراحي لـ Bug 3: إجبار كتابة הـ Null في قاعدة البيانات لمسح السلة والمرتجعات في حالة (لا يوجد بيع أو مؤجل) +++
      'cart_items': cartItemsJson,
      'returns': returnsJson,
      'notes': notes,
    };
    
    if (newShopBalance != null) updateData['shop_balance'] = newShopBalance; 

    await db.update(
      'visits',
      updateData,
      where: 'visit_id = ?',
      whereArgs: [visitId],
    );
    developer.log(
      '[LocalDatabase] Visit #$visitId updated locally with ALL financials and cart data.',
    );
  }

  // +++ دالة جديدة: خصم المخزون محلياً وقت البيع الأوفلاين لكي تتحدث الداشبورد +++
  Future<void> deductInventoryLocal(List<dynamic> cartItems) async {
    final db = await database;
    final batch = db.batch();
    for (var item in cartItems) {
      if (item['is_cancelled'] == true || item['is_cancelled'] == 1) continue;

      // +++ الكي الجراحي 5: التحويل الآمن للأرقام لمنع TypeError +++
      int variantId = (item['product_variant_id'] as num?)?.toInt() ?? 0;
      if (variantId == 0) continue;
      
      int qtyToDeduct =
          ((item['quantity'] as num?)?.toInt() ?? 0) +
          ((item['sample_quantity'] as num?)?.toInt() ?? (item['sample_cartons'] as num?)?.toInt() ?? 0) +
          ((item['bonus_quantity'] as num?)?.toInt() ?? 0); 
          
      int packsToDeduct =
          ((item['packs_quantity'] as num?)?.toInt() ?? (item['packs'] as num?)?.toInt() ?? 0) +
          ((item['sample_packs_quantity'] as num?)?.toInt() ?? (item['sample_packs'] as num?)?.toInt() ?? 0);

      if (qtyToDeduct > 0 || packsToDeduct > 0) {
        batch.rawUpdate(
          '''
          UPDATE products 
          SET 
            -- +++ الكي الجراحي 3: سحق قسمة السالب (Negative Modulo) بوضع MAX(0) +++
            current_cartons = (MAX(0, (current_cartons * packs_per_carton) + current_packs - (? * packs_per_carton) - ?)) / CASE WHEN packs_per_carton > 0 THEN packs_per_carton ELSE 1 END,
            current_packs   = (MAX(0, (current_cartons * packs_per_carton) + current_packs - (? * packs_per_carton) - ?)) % CASE WHEN packs_per_carton > 0 THEN packs_per_carton ELSE 1 END
          WHERE id = ?
        ''',
          [qtyToDeduct, packsToDeduct, qtyToDeduct, packsToDeduct, variantId],
        );
      }
    }
    await batch.commit(noResult: true);
    developer.log('[LocalDatabase] Local inventory deducted successfully.');
  }

  // +++ النسف المعماري (الضربة الاستباقية): التراجع عن فاتورة أوفلاين لحمايتها من الخصم المزدوج +++
  Future<void> revertOfflineVisit(int visitId) async {
    final db = await database;

    // 1. البحث عن الفاتورة القديمة في الخزنة
    final pendingSyncs = await db.query(
      'pending_sync',
      orderBy: 'created_at DESC',
    );
    Map<String, dynamic>? oldPayload;
    List<int> syncIdsToDelete = []; // +++ الكي الجراحي 4: حذف كل النسخ الوهمية (Ghost Replay) +++

    for (var p in pendingSyncs) {
      if (p['type'] == 'submit_sale') {
        final payload = jsonDecode(p['payload'] as String);
        if (payload['visitId'] == visitId) {
          oldPayload ??= payload; // نأخذ أحدث Payload فقط للتراجع
          syncIdsToDelete.add(p['id'] as int); // نجمع كل الأيديهات المكررة
        }
      }
    }

    if (oldPayload != null && syncIdsToDelete.isNotEmpty) {
      final batch = db.batch();

      // 2. إرجاع البضاعة المباعة والمرتجعة والعينات والبونص إلى رصيد السيارة
      final List<dynamic> cartItems = oldPayload['cart_items'] ?? [];
      for (var item in cartItems) {
        if (item['is_cancelled'] == true || item['is_cancelled'] == 1) continue;
        
        // +++ الكي الجراحي 5: التحويل الآمن +++
        int variantId = (item['product_variant_id'] as num?)?.toInt() ?? 0;
        if (variantId == 0) continue;

        int qtyToReturn =
            ((item['quantity'] as num?)?.toInt() ?? 0) +
            ((item['sample_quantity'] as num?)?.toInt() ?? (item['sample_cartons'] as num?)?.toInt() ?? 0) +
            ((item['bonus_quantity'] as num?)?.toInt() ?? 0);
            
        int packsToReturn =
            ((item['packs_quantity'] as num?)?.toInt() ?? (item['packs'] as num?)?.toInt() ?? 0) +
            ((item['sample_packs_quantity'] as num?)?.toInt() ?? (item['sample_packs'] as num?)?.toInt() ?? 0);

        if (qtyToReturn > 0 || packsToReturn > 0) {
          batch.rawUpdate(
            '''
            UPDATE products 
            SET 
              current_cartons = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) / CASE WHEN packs_per_carton > 0 THEN packs_per_carton ELSE 1 END,
              current_packs = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) % CASE WHEN packs_per_carton > 0 THEN packs_per_carton ELSE 1 END
            WHERE id = ?
            ''',
            [qtyToReturn, packsToReturn, qtyToReturn, packsToReturn, variantId],
          );
        }
      }

      // +++ الكي الجراحي 2: إعدام كود التراجع الخاص بالمرتجعات لأنه يسبب (Ghost Inventory Drain) +++

      // 3. حذف الفواتير القديمة المكررة من الخزنة
      for (var id in syncIdsToDelete) {
        batch.delete(
          'pending_sync',
          where: 'id = ?',
          whereArgs: [id],
        );
      }

      await batch.commit(noResult: true);
      developer.log(
        '[LocalDatabase] Pre-emptive Strike successful: Reverted offline visit #$visitId and cleared ${syncIdsToDelete.length} stale syncs.',
      );
    }
  }

  // +++ الكي الجراحي 1: دالة التحديث المحلي لرصيد المحل (تستخدم بعد نجاح رفع الفاتورة للسيرفر) +++
  Future<void> updateShopBalanceLocally(int visitId, double newBalance) async {
    final db = await database;
    await db.rawUpdate(
      'UPDATE visits SET shop_balance = ? WHERE visit_id = ?',
      [newBalance, visitId],
    );
    developer.log('[LocalDatabase] Shop balance updated locally to $newBalance for visit #$visitId.');
  }

  /// إغلاق الاتصال بقاعدة البيانات (يُستخدم عند الاختبار أو عند إعادة التهيئة).
  Future<void> close() async {
    if (_database != null) {
      await _database!.close();
      _database = null;
      developer.log('[LocalDatabase] Database connection closed.');
    }
  }

  // CS-02 / flutter.md Issue #3: Refresh only visits table, leaving products intact
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
    developer.log(
      '[LocalDatabase] Transaction complete: Visits refreshed (products left intact).',
    );
  }

  // +++ المعاملة الفولاذية (Transaction) لمزامنة السيرفر بدون فقدان بيانات +++
  // +++ إضافة دالة لجلب الحوالات الأوفلاين +++
  Future<List<Map<String, dynamic>>> getIncomingTransfers() async {
    final db = await database;
    return db.query('incoming_transfers');
  }

  // +++ المعاملة الفولاذية (Transaction) لمزامنة السيرفر بدون فقدان بيانات +++
  Future<void> refreshSessionData(
    List<VisitModel> visits,
    List<ProductModel> products,
    List<Map<String, dynamic>> incomingTransfers,
  ) async {
    final db = await database;
    await db.transaction((txn) async {
      // 1. مسح القديم
      await txn.delete('products');
      await txn.delete('visits');
      await txn.delete('incoming_transfers'); // +++ تنظيف الحوالات القديمة +++

      // 2. إدخال الجديد
      final batch = txn.batch();

      // +++ الكي الجراحي لـ Bug 2: بناء قاموس (Map) للمنتجات لجلب الأسماء وسعة الكرتونة بسرعة O(1) +++
      Map<int, ProductModel> productsMap = {};
      for (final product in products) {
        productsMap[product.id] = product;
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

      for (final transfer in incomingTransfers) {
        final int vId = (transfer['product_variant_id'] as num?)?.toInt() ?? 0;
        final int qtyPacks = (transfer['quantity_packs'] as num?)?.toInt() ?? 0;
        
        // +++ الكي الجراحي لـ Bug 2: قراءة بيانات المنتج الحقيقية بدلاً من الافتراضات +++
        final ProductModel? productInfo = productsMap[vId];
        final int packsPerCarton = productInfo?.packsPerCarton ?? 1;
        final String productName = productInfo?.name ?? 'غير معروف';
        final int safePpc = packsPerCarton > 0 ? packsPerCarton : 1;
        
        // +++ الكي الجراحي لـ Bug 3: قسمة الأرقام السالبة بأمان رياضي تام (Absolute Math) +++
        final int sign = qtyPacks < 0 ? -1 : 1;
        final int absPacks = qtyPacks.abs();
        final int deltaCartons = (absPacks ~/ safePpc) * sign;
        final int deltaLoosePacks = (absPacks % safePpc) * sign;
        
        batch.insert(
          'incoming_transfers',
          {
            'transfer_id': transfer['transfer_id'] ?? transfer['id'], // دعم الحالتين
            'product_variant_id': vId,
            'product_name': productName,
            'delta_cartons': deltaCartons,
            'delta_packs': deltaLoosePacks,
            'status': transfer['status'],
            'created_at': transfer['created_at'],
            'batch_id': transfer['notes'] ?? transfer['batch_id'] ?? 'SINGLE_${transfer['id']}'
          },
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
      await batch.commit(noResult: true);
    });
    developer.log(
      '[LocalDatabase] Transaction complete: Session & Transfers refreshed safely.',
    );
  }

  /// حذف الحوالة من الجدول المحلي بعد إتمام الرد عليها لتجنب تكرار ظهورها كشبح
  Future<void> removeIncomingTransfer(int transferId) async {
    final db = await database;
    await db.delete(
      'incoming_transfers',
      where: 'transfer_id = ? OR id = ?',
      whereArgs: [transferId, transferId],
    );
    developer.log('[LocalDatabase] Incoming transfer #$transferId removed locally.');
  }
}