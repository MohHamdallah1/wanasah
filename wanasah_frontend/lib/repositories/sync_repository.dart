// File: lib/repositories/sync_repository.dart
//
// الوظيفة: الوسيط (Sync Engine) بين السيرفر (ApiClient) وقاعدة البيانات المحلية (LocalDatabase).
//
//   syncDown()       — جلب بيانات السيرفر وحفظها محلياً (Online → Local)
//   saveInvoice()    — إرسال فاتورة مع Fallback تلقائي إلى Offline
//   syncUp()         — إعادة إرسال العمليات المعلقة عند عودة الإنترنت

import 'dart:convert';
import 'dart:developer' as developer;

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart'; // +++ لجلب رقم المندوب المطلوب للسيرفر +++

import '../core/network/api_client.dart';
import '../core/db/local_database.dart';
import '../models/product_model.dart';
import '../models/visit_model.dart'; // +++ الاستيراد المفقود الذي تسبب بالخطأ الأول +++

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
    try {
      final String? driverIdStr = await const FlutterSecureStorage().read(
        key: 'driver_id',
      );
      if (driverIdStr == null) throw Exception('Driver ID not found');
      final int driverId = int.parse(driverIdStr);

      // +++ 1. جلب البيانات من السيرفر أولاً (البيانات القديمة لا تزال بأمان) +++
      final response = await _api.get('/driver/$driverId/visits');

      final List<Map<String, dynamic>> visitsData =
          List<Map<String, dynamic>>.from(response.data['visits'] ?? []);
      final List<Map<String, dynamic>> productsData =
          List<Map<String, dynamic>>.from(response.data['inventory'] ?? []);

      // +++ 2. تحويل البيانات إلى كائنات ذكية (تطبيقاً للتعديل السابق) +++
      final List<VisitModel> visitModels =
          visitsData.map((v) => VisitModel.fromJson(v)).toList();
      final List<ProductModel> productModels =
          productsData.map((p) => ProductModel.fromJson(p)).toList();

      // +++ 3. تفريغ الجداول القديمة والحفظ (تفكيك اللغم: لا يحدث إلا إذا نجح الجلب والتحويل) +++
      await _db.clearSessionData();
      await _db.insertVisits(visitModels);
      await _db.insertProducts(productModels);

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
    // +++ 1. ترجمة المفاتيح المحاسبية (إصلاح الكارثة: مطابقة السيرفر لمنع العجز المالي) +++
    if (payload['items'] != null) {
      for (var item in payload['items']) {
        item['quantity'] = item['cartons'] ?? 0;
        item['packs_quantity'] = item['packs'] ?? 0;
      }
    }
    if (payload['returns'] != null) {
      for (var ret in payload['returns']) {
        ret['quantity'] = ret['cartons'] ?? 0;
        ret['packs_quantity'] = ret['packs'] ?? 0; // تم إضافة الحبات للمرتجعات
      }
    }
    if (payload['samples'] != null) {
      for (var sample in payload['samples']) {
        sample['sample_quantity'] = sample['sample_cartons'] ?? 0;
        sample['sample_packs_quantity'] = sample['sample_packs'] ?? 0;
      }
    }

    try {
      // 2. محاولة الإرسال المباشر للسيرفر
      await _dispatchPendingRecord(
        type: 'submit_sale',
        payload: {...payload, 'visitId': visitId},
      );

      // 3. تحديث الحالة محلياً
      await _db.updateVisitStatus(
        visitId: visitId,
        status: 'Completed',
        outcome: payload['outcome'] ?? 'Sale',
      );
      developer.log('[SyncRepository] Invoice #$visitId synced immediately.');
    } catch (e) {
      // 4. في حال فشل الاتصال، نحفظها في الخزنة السرية (Offline)
      developer.log(
        '[SyncRepository] Offline mode: queueing invoice #$visitId. Error: $e',
      );
      await _db.addPendingSync(
        type: 'submit_sale',
        payload: jsonEncode({...payload, 'visitId': visitId}),
      );
      // +++ إصلاح ثغرة الشاشة الرمادية: جعل الحالة Completed لكي تتعرف عليها واجهة المستخدم +++
      await _db.updateVisitStatus(
        visitId: visitId,
        status: 'Completed',
        outcome: payload['outcome'] ?? 'Sale',
      );
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

      // قابل للتوسع: أضف أنواع عمليات جديدة هنا (return_visit, shortage, ...)
      default:
        developer.log(
          '[SyncRepository] Unknown pending type "$type" — skipping.',
        );
    }
  }
}
