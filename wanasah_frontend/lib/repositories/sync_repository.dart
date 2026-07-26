import 'dart:convert';
import 'dart:developer' as developer;
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart'; // +++ للـ Isolates (compute) +++
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../core/network/api_client.dart';
import '../core/db/local_database.dart';
import '../models/product_model.dart';
import '../models/visit_model.dart';

// الوظيفة: الوسيط (Sync Engine) بين السيرفر (ApiClient) وقاعدة البيانات المحلية (LocalDatabase).
//
//   syncDown()       — جلب بيانات السيرفر وحفظها محلياً (Online → Local)
//   saveInvoice()    — إرسال فاتورة مع Fallback تلقائي إلى Offline
//   syncUp()         — إعادة إرسال العمليات المعلقة عند عودة الإنترنت

class SyncRepository {
  // -----------------------------------------------------------------------
  // Dependencies
  // -----------------------------------------------------------------------
  final ApiClient _api;
  final LocalDatabase _db;
  
  // +++ الدرع المعماري: قفل لمنع تشغيل المزامنة مرتين في نفس اللحظة (Race Condition) +++
  bool _isSyncing = false;

  SyncRepository({ApiClient? api, LocalDatabase? db})
    : _api = api ?? ApiClient.instance,
      _db = db ?? LocalDatabase.instance;

  // -----------------------------------------------------------------------
  // syncDown — السحب من السيرفر إلى القاعدة المحلية
  // -----------------------------------------------------------------------
  /// يُستدعى عند بداية كل جلسة عمل (أو عند تحديث يدوي).
  /// الترتيب: جلب البيانات → تفريغ الجداول القديمة → حفظ الجديدة.
  
  // +++ الدرع المعماري: قفل لمنع تشغيل السحب (syncDown) مرتين في نفس اللحظة +++
  bool _isSyncingDown = false;

  Future<void> syncDown() async {
    if (_isSyncingDown) {
      developer.log('[SyncRepository] syncDown is already running. Skipped.');
      return;
    }
    _isSyncingDown = true;
    developer.log('[SyncRepository] Starting syncDown...');

    // 1. محاولة رفع المعلقات (دالة syncUp تعالج أخطاءها بنفسها ولا تكسر التطبيق)
    await syncUp();

    // 2. الجدار الواقي: ممنوع السحب إذا بقيت بيانات أوفلاين حساسة (غير الفواتير)
    final pendingCheck = await _db.getPendingSyncs();
    // +++ إصلاح قفل التطبيق: السماح للمندوب بتحديث يومه حتى لو كان عنده فواتير قديمة مرفوضة تحتاج تعديل +++
    bool hasBlockingPending = pendingCheck.any((p) => p['type'] != 'submit_sale');
    
    if (hasBlockingPending) {
      developer.log(
        '[SyncRepository] Aborting syncDown: Blocking pending syncs still exist.',
      );
      throw Exception(
        'يوجد عمليات أوفلاين حساسة معلقة. يجب أن ينجح إرسالها أولاً لحماية بياناتك.',
      );
    }

    try {
      final String? driverIdStr = await const FlutterSecureStorage().read(
        key: 'driver_id',
      );
      if (driverIdStr == null) throw Exception('Driver ID not found');
      final int driverId = int.parse(driverIdStr);

      // +++ 1. جلب البيانات من السيرفر أولاً (البيانات القديمة لا تزال بأمان) +++
      final response = await _api.get('/driver/$driverId/visits');
      // +++ الكاشف التقني (لمعرفة الحقيقة بدون تخمين) +++
      developer.log('🎯 URL Called: /driver/$driverId/visits');
      developer.log('🎯 API Response: ${response.data}');
      List<Map<String, dynamic>> visitsData = [];
      List<Map<String, dynamic>> productsData = [];

      // +++ الدرع الواقي: التحقق من نوع الاستجابة قبل القراءة (Defensive Parsing) +++
      if (response.data is List) {
        // الحالة الأولى: السيرفر أرسل قائمة الزيارات مباشرة
        visitsData = List<Map<String, dynamic>>.from(response.data);
      } else if (response.data is Map) {
        // الحالة الثانية: السيرفر أرسل كائناً يحتوي على مفاتيح
        final Map<String, dynamic> dataMap =
            response.data as Map<String, dynamic>;
        if (dataMap.containsKey('visits') && dataMap['visits'] != null) {
          visitsData = List<Map<String, dynamic>>.from(dataMap['visits']);
        }
        if (dataMap.containsKey('inventory') && dataMap['inventory'] != null) {
          productsData = List<Map<String, dynamic>>.from(dataMap['inventory']);
        }
      }

      // +++ 2. تحويل البيانات باستخدام الـ Isolates (لمنع تجميد الواجهة - Jank Free) +++
      final List<VisitModel> visitModels = await compute(
        _parseVisits,
        visitsData,
      );
      final List<ProductModel> productModels = await compute(
        _parseProducts,
        productsData,
      );

      // CS-02 / flutter.md Issue #3: Guard against empty product list — do NOT truncate products table if incoming list is empty
      // +++ تم سحق قنبلة المسح الشامل: && تضمن عدم لمس البضاعة إلا إذا جاءت بيانات كاملة +++
      if (productModels.isNotEmpty && visitModels.isNotEmpty) {
        await _db.refreshSessionData(visitModels, productModels);
      } else if (visitModels.isNotEmpty) {
        await _db.refreshVisitsOnly(visitModels);
      }

      developer.log('[SyncRepository] syncDown completed successfully.');
    } catch (e) {
      developer.log('[SyncRepository] Error in syncDown: $e');
      rethrow;
    } finally {
      _isSyncingDown = false; // +++ تحرير القفل دائماً لضمان عدم تجميد التطبيق للأبد +++
    }
  }

  // -----------------------------------------------------------------------
  // saveInvoice — إرسال فاتورة مع Fallback تلقائي
  // -----------------------------------------------------------------------
  Future<void> saveInvoice({
    required int visitId,
    required Map<String, dynamic> payload,
  }) async {
    final Map<String, dynamic> safePayload = jsonDecode(jsonEncode(payload));

    // +++ النسف المعماري لثغرة تصفير الفواتير: تم إعدام الكود الكارثي الذي كان يحول الكميات إلى صفر +++

    // +++ تعريف المتغير مرة واحدة فقط لمنع خطأ المترجم (Dart Error) +++
    final String finalStatus =
        (safePayload['outcome'] == 'Postponed') ? 'Pending' : 'Completed';

    // +++ النسف المعماري الشامل للثقب الأسود (تحديث الـ Local DB بالكامل في جميع الحالات) +++
    Future<void> updateDataTask() async {
      await _db.updateVisitStatus(
        visitId: visitId,
        status: finalStatus,
        outcome: safePayload['outcome'] ?? 'Sale',
        cashCollected: (safePayload['cash_collected'] as num?)?.toDouble() ?? 0.0,
        debtPaid: (safePayload['debt_paid'] as num?)?.toDouble() ?? 0.0,
        cartItemsJson: safePayload['cart_items'] != null ? jsonEncode(safePayload['cart_items']) : null,
        returnsJson: safePayload['returns'] != null ? jsonEncode(safePayload['returns']) : null,
        notes: safePayload['notes']?.toString(),
      );
    }

    try {
      await _dispatchPendingRecord(
        type: 'submit_sale',
        payload: {...safePayload, 'visitId': visitId},
      );

      await updateDataTask(); // +++ حفظ كل شيء محلياً عند النجاح المباشر لسد ثغرة السلة الفارغة +++
      // +++ الدرع البصري: خصم المخزون محلياً فوراً حتى تتحدث شاشة المندوب ولا يبيع بضاعة لا يملكها +++
      if (safePayload['cart_items'] != null) {
        await _db.deductInventoryLocal(safePayload['cart_items']);
      }
      developer.log('[SyncRepository] Invoice #$visitId synced immediately.');
    } catch (e) {
      if (e is DioException && e.response?.statusCode != null) {
        final statusCode = e.response!.statusCode!;
        if (statusCode >= 400 && statusCode < 500) {
          developer.log(
            '[SyncRepository] Server strict rejection ($statusCode).',
          );
          rethrow;
        }
      }

      developer.log(
        '[SyncRepository] Offline mode triggered for invoice #$visitId. Reason: $e',
      );

      // +++ النسف المعماري للخصم المزدوج: التراجع عن الفاتورة القديمة أوفلاين قبل حفظ التعديل الجديد +++
      await _db.revertOfflineVisit(visitId);

      await _db.addPendingSync(
        type: 'submit_sale',
        payload: jsonEncode({...safePayload, 'visitId': visitId}),
      );

      await updateDataTask(); // +++ حفظ كل شيء محلياً في وضع الأوفلاين +++

      // +++ إصلاح كارثة المرتجعات: خصم المبيعات (cart_items) فقط. المرتجعات نتركها للسيرفر لتجنب العبث بالعهدة +++
      if (safePayload['cart_items'] != null) {
        await _db.deductInventoryLocal(safePayload['cart_items']);
      }
    }
  }

  // -----------------------------------------------------------------------
  // syncUp — إرسال كل العمليات المعلقة
  // -----------------------------------------------------------------------
  Future<int> syncUp() async {
    if (_isSyncing) {
      developer.log('[SyncRepository] syncUp is already running. Skipped.');
      return 0;
    }

    final pending = await _db.getPendingSyncs();
    if (pending.isEmpty) return 0;

    _isSyncing = true;
    developer.log(
      '[SyncRepository] Found ${pending.length} pending records to syncUp.',
    );
    int successCount = 0;

    try {
      for (final record in pending) {
      final recordId = record['id'] as int;
      final type = record['type'] as String;
      final payload = jsonDecode(record['payload'] as String);

      try {
        await _dispatchPendingRecord(type: type, payload: payload);
        await _db.deletePendingSync(recordId);
        successCount++;
      } on DioException catch (e) {
        if (e.response != null && e.response!.statusCode != null) {
          final statusCode = e.response!.statusCode!;
          // +++ إصلاح ثغرة اللูป اللانهائي + حماية الفواتير من التبخر بسبب انتهاء التوكن +++
          if (statusCode >= 400 && statusCode < 500) {
            if (statusCode == 401 || statusCode == 403) {
              developer.log(
                '[SyncRepository] Auth Error ($statusCode) - Halting sync to preserve offline data.',
              );
              break;
            }
            // +++ حماية الفواتير من الانتحار: لا نمسح الفاتورة إذا رُفضت بسبب محاسبي (مثل تجاوز الذمة 400/409)، بل نتركها ليعدلها المندوب +++
            developer.log(
              '[SyncRepository] Server rejected #$recordId with $statusCode. Keeping it in queue for manual fix.',
            );
            continue; // نتجاوزها بدون حذفها
          }
        }
        // في حال انقطاع النت (لا يوجد response) أو سيرفر متعطل (500) نتوقف ونحاول لاحقاً
        developer.log(
          '[SyncRepository] Still offline or Server Error (5xx) — stopping syncUp after '
          '$successCount success(es).',
        );
        break;
      } catch (e) {
        developer.log(
          '[SyncRepository] Unexpected error for pending #$recordId: $e — skipping to next.',
        );
        // +++ النسف المعماري لقنبلة السجل المسموم (Poison Pill): يجب تخطي السجل التالف محلياً (continue) بدلاً من تجميد طابور المزامنة بالكامل (break) +++
        continue; 
      }
    }
    } finally {
      _isSyncing = false; // +++ تحرير القفل دائماً حتى لو حصل خطأ +++
      developer.log(
        '[SyncRepository] syncUp() done — $successCount/${pending.length} synced.',
      );
    }
    return successCount;
  }

  // -----------------------------------------------------------------------
  // Helper خاص: توجيه كل نوع عملية معلقة إلى endpoint الصحيح
  // -----------------------------------------------------------------------
  Future<void> _dispatchPendingRecord({
    required String type,
    required Map<String, dynamic> payload,
  }) async {
    switch (type) {
      case 'submit_sale':
        final visitId = payload['visitId'] as int;
        final body = Map<String, dynamic>.from(payload)..remove('visitId');

        final response = await _api.put('/visits/$visitId', data: body);

        if (response.statusCode != 200 && response.statusCode != 201) {
          throw Exception('فشل السيرفر في معالجة الفاتورة: ${response.data}');
        }

        // +++ النسف المعماري لمشكلة الذمة: تحديث رصيد المحل محلياً بناءً على استجابة السيرفر فور نجاح الرفع +++
        // CS-03 / flutter.md Issue #4: Properly await the rawUpdate (fix fire-and-forget)
        if (response.data != null && response.data['new_balance'] != null) {
          final double newBalance =
              double.tryParse(response.data['new_balance'].toString()) ?? 0.0;
          final db = await _db.database;
          await db.rawUpdate(
            'UPDATE visits SET shop_balance = ? WHERE visit_id = ?',
            [newBalance, visitId],
          );
        }
        break;

      // +++ إرسال الاستراحة المحفوظة أوفلاين إلى السيرفر +++
      case 'toggle_break':
        final int driverId = payload['driver_id'];
        final String action = payload['action'];
        await _api.put(
          '/driver/$driverId/sessions/break',
          data: {'action': action},
        );
        break;

      // قابل للتوسع: أضف أنواع عمليات جديدة هنا (return_visit, shortage, ...)
      default:
        developer.log(
          '[SyncRepository] Unknown pending type "$type" — skipping.',
        );
    }
  }
}

// -----------------------------------------------------------------------
// دوال معزولة (Top-Level Functions) لاستخدامها مع Isolate/compute
// -----------------------------------------------------------------------
List<VisitModel> _parseVisits(List<Map<String, dynamic>> data) {
  // +++ النسف المعماري: إزالة التلاعب بالموديل بعد إنشائه. الحقول تُملأ من داخل fromJson بأمان تام +++
  return data.map((v) => VisitModel.fromJson(v)).toList();
}

List<ProductModel> _parseProducts(List<Map<String, dynamic>> data) {
  return data.map((p) => ProductModel.fromJson(p)).toList();
}
