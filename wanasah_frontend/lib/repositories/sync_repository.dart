import 'dart:convert';
import 'dart:developer' as developer;
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart'; // +++ للـ Isolates (compute) +++
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
  bool _isSyncingDown = false;

  SyncRepository({ApiClient? api, LocalDatabase? db})
    : _api = api ?? ApiClient.instance,
      _db = db ?? LocalDatabase.instance;

  // -----------------------------------------------------------------------
  // syncDown — السحب من السيرفر إلى القاعدة المحلية
  // -----------------------------------------------------------------------
  Future<void> syncDown() async {
    if (_isSyncingDown) {
      developer.log('[SyncRepository] syncDown is already running. Skipped.');
      return;
    }
    _isSyncingDown = true;
    developer.log('[SyncRepository] Starting syncDown...');

    try {
      // 1. محاولة رفع المعلقات
      await syncUp();

      // 2. الجدار الواقي: فحص المعلقات *بعد* محاولة الرفع
      final pendingCheck = await _db.getPendingSyncs();
      bool hasBlockingPending = pendingCheck.any((p) => p['type'] != 'submit_sale');
      
      if (hasBlockingPending) {
        developer.log('[SyncRepository] Aborting syncDown: Blocking pending syncs still exist.');
        throw Exception('يوجد عمليات أوفلاين حساسة معلقة. يجب أن ينجح إرسالها أولاً لحماية بياناتك.');
      }

      // +++ الدرع الفولاذي لحماية المبيعات الأوفلاين (Bug 3): منع الكتابة فوق الفواتير غير المرفوعة +++
      bool hasUnsyncedSales = pendingCheck.any((p) => p['type'] == 'submit_sale');
      if (hasUnsyncedSales) {
        developer.log('[SyncRepository] Aborting local DB refresh: Un-uploaded offline sales exist.');
        throw Exception('يرجى الانتظار، جاري رفع بعض فواتير الأوفلاين للسيرفر أولاً.');
      }

      final response = await _api.get('/driver/visits');
      developer.log('🎯 URL Called: /driver/visits');
      
      List<Map<String, dynamic>> visitsData = [];
      List<Map<String, dynamic>> productsData = [];
      List<Map<String, dynamic>> transfersData = [];

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
        if (dataMap.containsKey('pending_transfers') && dataMap['pending_transfers'] != null) {
          transfersData = List<Map<String, dynamic>>.from(dataMap['pending_transfers']);
        }
      }

      final List<VisitModel> visitModels = await compute(_parseVisits, visitsData);
      final List<ProductModel> productModels = await compute(_parseProducts, productsData);

      // +++ الكي الجراحي لـ Bug 2: معالجة الزيارات والبضاعة بشكل مستقل (Decoupled Processing) +++
      if (visitModels.isEmpty && productModels.isEmpty) {
        developer.log('[SyncRepository] Server returned empty data. Clearing local session data.');
        await _db.clearSessionData(clearPendingSyncs: false);
      } else {
        // تحديث شامل إذا كان هناك أي بيانات (زيارات أو بضاعة أو كلاهما)
        await _db.refreshSessionData(visitModels, productModels, transfersData);
      }

      developer.log('[SyncRepository] syncDown completed successfully.');
    } catch (e) {
      developer.log('[SyncRepository] Error in syncDown: $e');
      rethrow;
    } finally {
      // +++ الكي الجراحي لـ Bug 1: القفل يُحرر دائماً داخل الـ finally +++
      _isSyncingDown = false; 
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

    final String finalStatus =
        (safePayload['outcome'] == 'Postponed') ? 'Pending' : 'Completed';

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

    bool dispatchSuccess = false;
    try {
      // 1. الإرسال للسيرفر أولاً وبشكل معزول
      await _dispatchPendingRecord(
        type: 'submit_sale',
        payload: {...safePayload, 'visitId': visitId},
      );
      dispatchSuccess = true; // السيرفر استلم الفاتورة وحفظها
    } catch (e) {
      // معالجة أخطاء الشبكة أو الرفض
      if (e is DioException && e.response?.statusCode != null) {
        final statusCode = e.response!.statusCode!;
        if (statusCode >= 400 && statusCode < 500) {
          developer.log('[SyncRepository] Server strict rejection ($statusCode).');
          rethrow;
        }
      }
      developer.log('[SyncRepository] Offline mode triggered for invoice #$visitId. Reason: $e');
    }

    // 2. معالجة الداتابيز المحلية (خارج الـ try/catch تبع الشبكة لمنع التدبيل)
    try {
      if (dispatchSuccess) {
        // نجاح أونلاين
        await updateDataTask();
        if (safePayload['cart_items'] != null) {
          await _db.deductInventoryLocal(safePayload['cart_items']);
        }
        developer.log('[SyncRepository] Invoice #$visitId synced and saved locally.');
      } else {
        // وضع الأوفلاين
        await _db.revertOfflineVisit(visitId);
        await _db.addPendingSync(
          type: 'submit_sale',
          payload: jsonEncode({...safePayload, 'visitId': visitId}),
        );
        await updateDataTask();
        if (safePayload['cart_items'] != null) {
          await _db.deductInventoryLocal(safePayload['cart_items']);
        }
      }
    } catch (localDbError) {
      developer.log('[SyncRepository] FATAL: Local DB error while saving invoice state: $localDbError');
      rethrow;
    }
  } // <--- الكارثة كانت هون! هاد القوس كان ممسوح بالغلط!

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
          if (!['submit_sale', 'toggle_break'].contains(type)) {
             developer.log('[SyncRepository] ☠️ Poison Pill detected: Unknown type "$type". Deleting record #$recordId');
             await _db.deletePendingSync(recordId);
             continue; 
          }

          await _dispatchPendingRecord(type: type, payload: payload);
          await _db.deletePendingSync(recordId);
          successCount++;
        } on DioException catch (e) {
          if (e.response != null && e.response!.statusCode != null) {
            final statusCode = e.response!.statusCode!;
            if (statusCode >= 400 && statusCode < 500) {
              if (statusCode == 401) {
                developer.log('[SyncRepository] Auth Error ($statusCode) - Halting sync to preserve offline data.');
                break;
              }
              final String errorMessage = e.response?.data?['message']?.toString() ?? e.response?.data?['detail']?.toString() ?? '';
              
              if (statusCode == 403 && errorMessage.contains('تم تسويتها')) {
                  developer.log('[SyncRepository] ⚠️ Settlement Collision: Invoice rejected. Deleting offline record.');
                  await _db.deletePendingSync(recordId);
                  continue;
              }
              
              if (statusCode == 400 && type == 'toggle_break') {
                  developer.log('[SyncRepository] ⚠️ Break record rejected by server. Deleting it to unblock sync.');
                  await _db.deletePendingSync(recordId);
                  continue;
              }

              developer.log(
                '[SyncRepository] Server rejected #$recordId with $statusCode. Keeping it in queue for manual fix.',
              );
              continue;
            }
          }
          developer.log(
            '[SyncRepository] Still offline or Server Error (5xx) — stopping syncUp after '
            '$successCount success(es).',
          );
          break;
        } catch (e) {
          developer.log(
            '[SyncRepository] Unexpected error for pending #$recordId: $e — skipping to next.',
          );
          continue; 
        }
      }
    } finally {
      _isSyncing = false; 
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

        if (response.data != null && response.data['new_balance'] != null) {
          final double newBalance =
              double.tryParse(response.data['new_balance'].toString()) ?? 0.0;
          await _db.updateShopBalanceLocally(visitId, newBalance);
        }
        break;

      case 'toggle_break':
        final String action = payload['action'];
        await _api.put(
          '/driver/sessions/break',
          data: {'action': action},
        );
        break;

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