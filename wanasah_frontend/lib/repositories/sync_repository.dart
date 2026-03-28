// File: lib/repositories/sync_repository.dart
//
// الوظيفة: الوسيط (Sync Engine) بين السيرفر (ApiClient) وقاعدة البيانات المحلية (LocalDatabase).
//
//   syncDown()       — جلب بيانات السيرفر وحفظها محلياً (Online → Local)
//   saveInvoice()    — إرسال فاتورة مع Fallback تلقائي إلى Offline
//   syncUp()         — إعادة إرسال العمليات المعلقة عند عودة الإنترنت

import 'dart:convert';
import 'dart:io';
import 'dart:developer' as developer;

import 'package:dio/dio.dart';

import '../core/network/api_client.dart';
import '../core/db/local_database.dart';
import '../models/product_model.dart';
import '../models/visit_model.dart';

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
    developer.log('[SyncRepository] syncDown() started...');

    try {
      // +++ الدرع المعماري: تفريغ الخزنة السرية ورفع المبيعات الأوفلاين للسيرفر أولاً +++
      // لمنع السيرفر من الكتابة فوق مبيعات المندوب التي لم تُرفع بعد
      developer.log('[SyncRepository] Running pre-sync upload...');
      await syncUp();
      // ── 1. جلب المنتجات (حمولة الشاحنة) من السيرفر ──────────────────
      final productsResponse = await _api.get<Map<String, dynamic>>(
        '/driver/load',
      );

      final List<dynamic> rawProducts =
          (productsResponse.data?['load'] as List?) ?? [];

      final List<Map<String, dynamic>> products =
          rawProducts
              .map(
                (e) =>
                    ProductModel.fromJson(e as Map<String, dynamic>).toJson(),
              )
              .toList();

      // ── 2. جلب الزيارات المخطط لها من السيرفر ────────────────────────
      final visitsResponse = await _api.get<Map<String, dynamic>>(
        '/driver/visits',
      );

      final List<dynamic> rawVisits =
          (visitsResponse.data?['visits'] as List?) ?? [];

      final List<Map<String, dynamic>> visits =
          rawVisits.map((e) {
            final vm = VisitModel.fromJson(e as Map<String, dynamic>);
            return {
              'id': vm.id,
              'shop_id': vm.shopId,
              'shop_name': vm.shopName,
              'shop_balance': vm.shopBalance,
              'status': vm.status,
              'outcome': vm.outcome,
            };
          }).toList();

      // ── 3. تفريغ بيانات الجلسة السابقة وحفظ الجديدة ──────────────────
      await _db.clearSessionData();
      await _db.insertProducts(products);
      await _db.insertVisits(visits);

      developer.log(
        '[SyncRepository] syncDown() done — '
        '${products.length} products, ${visits.length} visits cached.',
      );
    } on DioException catch (e) {
      developer.log('[SyncRepository] syncDown() network error: ${e.message}');
      // لا نرمي الخطأ — التطبيق يعمل من البيانات المحلية القديمة
    } catch (e) {
      developer.log('[SyncRepository] syncDown() unexpected error: $e');
      rethrow;
    }
  }

  // -----------------------------------------------------------------------
  // saveInvoice — حفظ فاتورة مع Fallback تلقائي للوضع Offline
  // -----------------------------------------------------------------------
  /// [payload] : بيانات الفاتورة كاملة (ستُرسل كـ JSON للسيرفر)
  /// [visitId] : معرّف الزيارة لتحديث حالتها محلياً
  ///
  /// النتيجة: يُعيد `true` إذا تمّ الإرسال Online، أو `false` إذا حُفظ Offline.
  Future<bool> saveInvoice(Map<String, dynamic> payload, int visitId) async {
    developer.log('[SyncRepository] saveInvoice() for visit #$visitId...');

    try {
      // ── محاولة الإرسال للسيرفر ────────────────────────────────────────
      await _api.post<Map<String, dynamic>>(
        '/driver/visits/$visitId/submit',
        data: payload,
      );

      // ── نجح الإرسال: تحديث الحالة محلياً ─────────────────────────────
      await _db.updateVisitStatus(
        visitId: visitId,
        status: 'Completed',
        outcome: 'Sale',
      );

      developer.log('[SyncRepository] Invoice #$visitId sent online ✓');
      return true;
    } on DioException catch (e) {
      // ── التقاط أخطاء الشبكة / الاتصال فقط ───────────────────────────
      final isConnectionError =
          e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.sendTimeout ||
          e.error is SocketException;

      if (isConnectionError) {
        developer.log(
          '[SyncRepository] No connection — saving invoice #$visitId to pending_sync.',
        );

        // حفظ الـ payload في الخزنة السرية
        await _db.addPendingSync(
          type: 'submit_sale',
          payload: jsonEncode({'visitId': visitId, ...payload}),
        );

        // تحديث حالة الزيارة محلياً كـ Offline
        await _db.updateVisitStatus(
          visitId: visitId,
          status: 'Completed (Offline)',
          outcome: 'Sale',
        );

        developer.log('[SyncRepository] Invoice #$visitId queued offline ✓');
        return false;
      }

      // أخطاء أخرى (4xx, 5xx) — نرميها للـ UI ليعالجها
      developer.log(
        '[SyncRepository] Server error for invoice #$visitId: '
        '${e.response?.statusCode} ${e.response?.data}',
      );
      rethrow;
    } catch (e) {
      developer.log('[SyncRepository] saveInvoice() unexpected error: $e');
      rethrow;
    }
  }

  // -----------------------------------------------------------------------
  // syncUp — إرسال العمليات المعلقة عند عودة الإنترنت
  // -----------------------------------------------------------------------
  /// يُستدعى عند اكتشاف عودة الاتصال (أو عند فتح التطبيق).
  /// يُعيد عدد العمليات التي تمّ إرسالها بنجاح.
  Future<int> syncUp() async {
    developer.log('[SyncRepository] syncUp() started...');

    final pending = await _db.getPendingSyncs();
    if (pending.isEmpty) {
      developer.log('[SyncRepository] No pending operations to sync.');
      return 0;
    }

    developer.log(
      '[SyncRepository] Found ${pending.length} pending operation(s).',
    );

    int successCount = 0;

    for (final record in pending) {
      final int recordId = record['id'] as int;
      final String type = record['type'] as String;
      final Map<String, dynamic> payload =
          jsonDecode(record['payload'] as String) as Map<String, dynamic>;

      try {
        await _dispatchPendingRecord(type: type, payload: payload);
        await _db.deletePendingSync(recordId);
        successCount++;
        developer.log('[SyncRepository] Pending #$recordId ($type) synced ✓');
      } on DioException catch (e) {
        // إذا فشل بسبب الشبكة مجدداً: نوقف الـ loop ونحاول لاحقاً
        if (e.type == DioExceptionType.connectionError ||
            e.type == DioExceptionType.connectionTimeout ||
            e.error is SocketException) {
          developer.log(
            '[SyncRepository] Still offline — stopping syncUp after '
            '$successCount success(es).',
          );
          break;
        }
        // أخطاء السيرفر (4xx): نسجّل ونتجاوز لنحاول التالي
        developer.log(
          '[SyncRepository] Server rejected pending #$recordId: '
          '${e.response?.statusCode} — skipping.',
        );
      } catch (e) {
        developer.log(
          '[SyncRepository] Unexpected error for pending #$recordId: $e — skipping.',
        );
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
        await _api.post<Map<String, dynamic>>(
          '/driver/visits/$visitId/submit',
          data: body,
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
