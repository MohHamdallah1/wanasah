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

  SyncRepository({ApiClient? api, LocalDatabase? db})
    : _api = api ?? ApiClient.instance,
      _db = db ?? LocalDatabase.instance;

  // -----------------------------------------------------------------------
  // syncDown — السحب من السيرفر إلى القاعدة المحلية
  // -----------------------------------------------------------------------
  /// يُستدعى عند بداية كل جلسة عمل (أو عند تحديث يدوي).
  /// الترتيب: جلب البيانات → تفريغ الجداول القديمة → حفظ الجديدة.
  Future<void> syncDown() async {
    developer.log('[SyncRepository] Starting syncDown...');

    // 1. محاولة رفع المعلقات (دالة syncUp تعالج أخطاءها بنفسها ولا تكسر التطبيق)
    await syncUp();

    // 2. الجدار الواقي: ممنوع السحب إذا بقيت بيانات أوفلاين غير مرفوعة
    final pendingCheck = await _db.getPendingSyncs();
    if (pendingCheck.isNotEmpty) {
      developer.log(
        '[SyncRepository] Aborting syncDown: Pending syncs still exist.',
      );
      throw Exception(
        'يوجد عمليات أوفلاين معلقة. يجب أن ينجح إرسالها أولاً لحماية بياناتك من التصفير.',
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

      // +++ 3. تفريغ الجداول القديمة والحفظ بمعاملة (Transaction) واحدة فولاذية +++
      await _db.refreshSessionData(visitModels, productModels);

      developer.log('[SyncRepository] syncDown completed successfully.');
    } catch (e) {
      developer.log('[SyncRepository] Error in syncDown: $e');
      rethrow;
    }
  }

  // -----------------------------------------------------------------------
  // saveInvoice — إرسال فاتورة مع Fallback تلقائي
  // -----------------------------------------------------------------------
  Future<void> saveInvoice({
    required int visitId,
    required Map<String, dynamic> payload,
  }) async {
    // +++ الكيّ الجراحي المعماري: Deep Copy لمنع تدمير حالة الواجهة (In-place Mutation) +++
    final Map<String, dynamic> safePayload = jsonDecode(jsonEncode(payload));

    // 1. ترجمة المفاتيح المحاسبية بأمان على النسخة
    if (safePayload['cart_items'] != null) {
      for (var item in safePayload['cart_items']) {
        item['packs_quantity'] = item['packs'] ?? 0;
        item['sample_quantity'] = item['sample_cartons'] ?? 0;
        item['sample_packs_quantity'] = item['sample_packs'] ?? 0;
      }
    }
    if (safePayload['returns'] != null) {
      for (var ret in safePayload['returns']) {
        ret['quantity'] = ret['cartons'] ?? 0;
        ret['packs_quantity'] = ret['packs'] ?? 0;
      }
    }
    if (safePayload['samples'] != null) {
      for (var sample in safePayload['samples']) {
        sample['sample_quantity'] = sample['sample_cartons'] ?? 0;
        sample['sample_packs_quantity'] = sample['sample_packs'] ?? 0;
      }
    }

    try {
      // 2. محاولة الإرسال المباشر للسيرفر
      await _dispatchPendingRecord(
        type: 'submit_sale',
        payload: {...safePayload, 'visitId': visitId},
      );

      // 3. تحديث الحالة محلياً
      await _db.updateVisitStatus(
        visitId: visitId,
        status: 'Completed',
        outcome: safePayload['outcome'] ?? 'Sale',
      );
      developer.log('[SyncRepository] Invoice #$visitId synced immediately.');
    } catch (e) {
      // +++ الكيّ الجراحي: دمج الكتل (DRY) ومعالجة الفشل بذكاء +++
      if (e is DioException && e.response?.statusCode != null) {
        final statusCode = e.response!.statusCode!;
        if (statusCode >= 400 && statusCode < 500) {
          developer.log(
            '[SyncRepository] Server strict rejection ($statusCode). Halting save.',
          );
          rethrow;
        }
      }

      developer.log(
        '[SyncRepository] Offline mode triggered for invoice #$visitId. Reason: $e',
      );

      await _db.addPendingSync(
        type: 'submit_sale',
        payload: jsonEncode({...safePayload, 'visitId': visitId}),
      );

      // تحديث الداتابيز المحلية بالكاش والذمم للداشبورد الأوفلاين
      await _db.updateVisitStatus(
        visitId: visitId,
        status: 'Completed',
        outcome: safePayload['outcome'] ?? 'Sale',
        cashCollected:
            (safePayload['cash_collected'] as num?)?.toDouble() ?? 0.0,
        debtPaid: (safePayload['debt_paid'] as num?)?.toDouble() ?? 0.0,
      );

      // خصم المخزون محلياً إذا كانت العملية بيع
      if (safePayload['outcome'] == 'Sale' &&
          safePayload['cart_items'] != null) {
        await _db.deductInventoryLocal(safePayload['cart_items']);
      }
    }
  }

  // -----------------------------------------------------------------------
  // syncUp — إرسال كل العمليات المعلقة
  // -----------------------------------------------------------------------
  Future<int> syncUp() async {
    final pending = await _db.getPendingSyncs();
    if (pending.isEmpty) return 0;

    developer.log(
      '[SyncRepository] Found ${pending.length} pending records to syncUp.',
    );
    int successCount = 0;

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
          // +++ إصلاح ثغرة اللูป اللانهائي: حذف السجل إذا رفضه السيرفر نهائياً بسبب خطأ بالبيانات (4xx) +++
          if (statusCode >= 400 && statusCode < 500) {
            developer.log(
              '[SyncRepository] Server rejected pending #$recordId with $statusCode — Deleting to prevent infinite loop.',
            );
            await _db.deletePendingSync(recordId);
            continue; // تجاوز هذا الملف وانتقل للتالي بدون أن توقف المزامنة
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
          '[SyncRepository] Unexpected error for pending #$recordId: $e — stopping.',
        );
        break;
      }
    }

    developer.log(
      '[SyncRepository] syncUp() done — $successCount/${pending.length} synced.',
    );
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
        // إزالة visitId من الـ payload قبل الإرسال (هو جزء من الـ URL)
        final body = Map<String, dynamic>.from(payload)..remove('visitId');
        await _api.put('/visits/$visitId', data: body);
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
  return data.map((v) => VisitModel.fromJson(v)).toList();
}

List<ProductModel> _parseProducts(List<Map<String, dynamic>> data) {
  return data.map((p) => ProductModel.fromJson(p)).toList();
}
