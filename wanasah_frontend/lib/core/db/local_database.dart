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
      version: 1,
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
    // يُخزِّن نسخة محلية من منتجات الشاحنة (يُحدَّث عند بداية كل جلسة عمل)
    await db.execute('''
      CREATE TABLE products (
        id                 INTEGER PRIMARY KEY,
        name               TEXT    NOT NULL,
        price_per_carton   REAL    NOT NULL DEFAULT 0,
        price_per_pack     REAL    NOT NULL DEFAULT 0,
        packs_per_carton   INTEGER NOT NULL DEFAULT 1,
        current_cartons    INTEGER NOT NULL DEFAULT 0,
        current_packs      INTEGER NOT NULL DEFAULT 0
      )
    ''');

    // --- جدول الزيارات ---
    // يُخزِّن قائمة زيارات اليوم (يُحدَّث عند بداية كل جلسة عمل)
    await db.execute('''
      CREATE TABLE visits (
        id             INTEGER PRIMARY KEY,
        shop_id        INTEGER NOT NULL,
        shop_name      TEXT    NOT NULL,
        shop_balance   REAL    NOT NULL DEFAULT 0,
        status         TEXT    NOT NULL DEFAULT 'Pending',
        outcome        TEXT    NOT NULL DEFAULT 'None'
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
    // سيتم تعريف منطق الترحيل (migration) هنا عند الحاجة
  }

  // -----------------------------------------------------------------------
  // دوال مساعدة عامة للـ CRUD
  // -----------------------------------------------------------------------

  /// حذف جميع بيانات الجلسة السابقة (products + visits) مع الحفاظ على pending_sync.
  /// يُستدعى في بداية كل جلسة عمل جديدة لضمان البيانات المحدَّثة.
  Future<void> clearSessionData() async {
    final db = await database;
    await db.delete('products');
    await db.delete('visits');
    developer.log('[LocalDatabase] Session tables (products, visits) cleared.');
  }

  /// إدراج أو استبدال مجموعة من المنتجات دفعةً واحدة (Batch Insert).
  Future<void> insertProducts(List<Map<String, dynamic>> products) async {
    final db = await database;
    final batch = db.batch();
    for (final product in products) {
      batch.insert(
        'products',
        product,
        conflictAlgorithm: ConflictAlgorithm.replace,
      );
    }
    await batch.commit(noResult: true);
    developer.log('[LocalDatabase] Inserted ${products.length} products.');
  }

  /// إدراج أو استبدال مجموعة من الزيارات دفعةً واحدة (Batch Insert).
  Future<void> insertVisits(List<Map<String, dynamic>> visits) async {
    final db = await database;
    final batch = db.batch();
    for (final visit in visits) {
      batch.insert(
        'visits',
        visit,
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
  }) async {
    final db = await database;
    await db.update(
      'visits',
      {'status': status, 'outcome': outcome},
      where: 'id = ?',
      whereArgs: [visitId],
    );
    developer.log(
      '[LocalDatabase] Visit #$visitId updated → status=$status, outcome=$outcome',
    );
  }

  /// إغلاق الاتصال بقاعدة البيانات (يُستخدم عند الاختبار أو عند إعادة التهيئة).
  Future<void> close() async {
    if (_database != null) {
      await _database!.close();
      _database = null;
      developer.log('[LocalDatabase] Database connection closed.');
    }
  }
}
