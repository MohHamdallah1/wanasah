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

  /// نقطة الوصول العامة للاتصال.
  /// إذا لم يتم فتح الاتصال بعد، يتم استدعاء [_initDB] تلقائياً (Lazy Init).
  Future<Database> get database async {
    if (_database != null) return _database!;
    _database = await _initDB();
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
      version: 7, // flutter.md Issue #1: v7 normalizes monetary columns to REAL
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
      await db.execute('DROP TABLE visits');
      await db.execute('ALTER TABLE visits_v7 RENAME TO visits');
      developer.log('[LocalDatabase] v7 migration: Normalized monetary columns to REAL.');
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
    if (clearPendingSyncs) {
      await db.delete('pending_sync');
    }
    developer.log('[LocalDatabase] Session tables (products, visits${clearPendingSyncs ? ', pending_sync' : ''}) cleared.');
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
    String? cartItemsJson, // +++ سد الثقب الأسود +++
    String? returnsJson, // +++ سد الثقب الأسود +++
    String? notes, // +++ سد الثقب الأسود +++
  }) async {
    final db = await database;
    final Map<String, dynamic> updateData = {
      'status': status,
      'outcome': outcome,
      'cash_collected': cashCollected,
      'debt_paid': debtPaid,
    };
    
    if (cartItemsJson != null) updateData['cart_items'] = cartItemsJson;
    if (returnsJson != null) updateData['returns'] = returnsJson;
    if (notes != null) updateData['notes'] = notes;

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
      int variantId = item['product_variant_id'];
      
      // +++ النسف المعماري لشبح البونص: مطابقة مفاتيح الـ Backend حرفياً لضمان دقة الجرد المحلي +++
      int qtyToDeduct =
          (item['quantity'] ?? 0) +
          (item['sample_quantity'] ?? item['sample_cartons'] ?? 0) +
          (item['bonus_quantity'] ?? 0); 
          
      int packsToDeduct =
          (item['packs_quantity'] ?? item['packs'] ?? 0) +
          (item['sample_packs_quantity'] ?? item['sample_packs'] ?? 0);

      if (qtyToDeduct > 0 || packsToDeduct > 0) {
        batch.rawUpdate(
          '''
          UPDATE products 
          SET 
            current_cartons = (((current_cartons * packs_per_carton) + current_packs - (? * packs_per_carton) - ?) / MAX(packs_per_carton, 1)),
            current_packs = (((current_cartons * packs_per_carton) + current_packs - (? * packs_per_carton) - ?) % MAX(packs_per_carton, 1))
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
    int? syncIdToDelete;

    for (var p in pendingSyncs) {
      if (p['type'] == 'submit_sale') {
        final payload = jsonDecode(p['payload'] as String);
        if (payload['visitId'] == visitId) {
          oldPayload = payload;
          syncIdToDelete = p['id'] as int;
          break;
        }
      }
    }

    if (oldPayload != null && syncIdToDelete != null) {
      final batch = db.batch();

      // 2. إرجاع البضاعة المباعة والمرتجعة والعينات والبونص إلى رصيد السيارة
      final List<dynamic> cartItems = oldPayload['cart_items'] ?? [];
      for (var item in cartItems) {
        int variantId = item['product_variant_id'];

        // +++ إرجاع البونص للعهدة عند التراجع عن الفاتورة +++
        int qtyToReturn =
            (item['quantity'] ?? 0) +
            (item['sample_quantity'] ?? item['sample_cartons'] ?? 0) +
            (item['bonus_quantity'] ?? 0);
            
        int packsToReturn =
            (item['packs_quantity'] ?? item['packs'] ?? 0) +
            (item['sample_packs_quantity'] ?? item['sample_packs'] ?? 0);

        if (qtyToReturn > 0 || packsToReturn > 0) {
          batch.rawUpdate(
            '''
            UPDATE products 
            SET 
              current_cartons = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) / MAX(packs_per_carton, 1),
              current_packs = ((current_cartons * packs_per_carton) + current_packs + (? * packs_per_carton) + ?) % MAX(packs_per_carton, 1)
            WHERE id = ?
            ''',
            [qtyToReturn, packsToReturn, qtyToReturn, packsToReturn, variantId],
          );
        }
      }

      // +++ الجراحة الرابعة (CS-10): إرجاع المرتجعات الصالحة لضبط العهدة +++
      final List<dynamic> returnItems = oldPayload['returns'] ?? [];
      for (var ret in returnItems) {
        final String retType = ret['return_type'] ?? '';
        // نعكس فقط البضاعة الصالحة لأن التوالف لا تضاف للعهدة المتاحة للبيع
        if (retType == 'Good' || retType == 'Resellable') {
          int variantId = ret['product_variant_id'];
          int qtyToDeduct = ret['quantity'] ?? 0;
          int packsToDeduct = ret['packs_quantity'] ?? ret['packs'] ?? 0;

          if (qtyToDeduct > 0 || packsToDeduct > 0) {
            // بما أن المرتجع (Offline) يضيف للعهدة، التراجع عنه يعني خصمه!
            batch.rawUpdate(
              '''
              UPDATE products 
              SET 
                current_cartons = (((current_cartons * packs_per_carton) + current_packs - (? * packs_per_carton) - ?) / MAX(packs_per_carton, 1)),
                current_packs = (((current_cartons * packs_per_carton) + current_packs - (? * packs_per_carton) - ?) % MAX(packs_per_carton, 1))
              WHERE id = ?
              ''',
              [qtyToDeduct, packsToDeduct, qtyToDeduct, packsToDeduct, variantId],
            );
          }
        }
      }

      // 3. حذف الفاتورة القديمة من الخزنة
      batch.delete(
        'pending_sync',
        where: 'id = ?',
        whereArgs: [syncIdToDelete],
      );

      await batch.commit(noResult: true);
      developer.log(
        '[LocalDatabase] Pre-emptive Strike successful: Reverted offline visit #$visitId.',
      );
    }
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
  Future<void> refreshSessionData(
    List<VisitModel> visits,
    List<ProductModel> products,
  ) async {
    final db = await database;
    await db.transaction((txn) async {
      // 1. مسح القديم
      await txn.delete('products');
      await txn.delete('visits');

      // 2. إدخال الجديد
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
      await batch.commit(noResult: true);
    });
    developer.log(
      '[LocalDatabase] Transaction complete: Session data refreshed safely.',
    );
  }
}
