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
  // +++ الكي الجراحي (توحيد طبقة المزامنة - Singleton): نسخة واحدة تحكم التطبيق بأكمله لمنع تكرار الفواتير +++
  static final SyncRepository instance = SyncRepository._internal();

  // -----------------------------------------------------------------------
  // Dependencies
  // -----------------------------------------------------------------------
  final ApiClient _api;
  final LocalDatabase _db;
  
  // الأقفال أصبحت الآن مركزية على مستوى التطبيق كله
  bool _isSyncing = false;
  bool _isSyncingDown = false;

  // البناء الداخلي المخفي
  SyncRepository._internal({ApiClient? api, LocalDatabase? db})
    : _api = api ?? ApiClient.instance,
      _db = db ?? LocalDatabase.instance;

  // +++ خدعة معمارية: أي BLoC يحاول كتابة SyncRepository() سيحصل على النسخة الموحدة إجبارياً +++
  factory SyncRepository() {
    return instance;
  }

  // -----------------------------------------------------------------------
  // syncDown — السحب من السيرفر إلى القاعدة المحلية
  // -----------------------------------------------------------------------
  // +++ الكي الجراحي: إرجاع bool لإبلاغ البلوك إذا تم التخطي بسبب قفل المزامنة الموحد +++
  Future<bool> syncDown() async {
    if (_isSyncingDown) {
      developer.log('[SyncRepository] syncDown is already running. Skipped.');
      return false; // تخطي صامت مقصود
    }
    _isSyncingDown = true;
    developer.log('[SyncRepository] Starting syncDown...');

    try {
      // 1. محاولة رفع المعلقات
      await syncUp();

      // 2. فحص المعلقات النشطة واستثناء المحجورات لمنع تجميد المزامنة (X1)
      final pendingCheck = await _db.getPendingSyncs();
      final activePending = pendingCheck.where((p) => !p['type'].toString().startsWith('quarantined_')).toList();

      bool hasBlockingPending = activePending.any((p) => p['type'] != 'submit_sale');
      if (hasBlockingPending) {
        developer.log('[SyncRepository] Aborting syncDown: Blocking active pending syncs exist.');
        throw Exception('يوجد عمليات أوفلاين حساسة معلقة. يجب أن ينجح إرسالها أولاً لحماية بياناتك.');
      }

      bool hasUnsyncedSales = activePending.any((p) => p['type'] == 'submit_sale');
      if (hasUnsyncedSales) {
        developer.log('[SyncRepository] Aborting local DB refresh: Un-uploaded offline sales exist.');
        throw Exception('يرجى الانتظار، جاري رفع بعض فواتير الأوفلاين للسيرفر أولاً.');
      }

      final response = await _api.get('/driver/visits');
      developer.log('🎯 URL Called: /driver/visits');
      
      List<Map<String, dynamic>> visitsData = [];
      List<Map<String, dynamic>> productsData = [];
      List<Map<String, dynamic>>? transfersData; // Nullable لمنع المسح العشوائي

      bool hasValidStructure = false;
      bool clearVisitsTarget = false;
      bool clearProductsTarget = false;

      if (response.data is List) {
        visitsData = List<Map<String, dynamic>>.from(response.data);
        hasValidStructure = true;
        clearVisitsTarget = true;
      } else if (response.data is Map) {
        final Map<String, dynamic> dataMap = response.data as Map<String, dynamic>;
        
        clearVisitsTarget = dataMap['visits'] != null && dataMap['visits'] is List;
        clearProductsTarget = dataMap['inventory'] != null && dataMap['inventory'] is List;
        hasValidStructure = clearVisitsTarget || clearProductsTarget;
        
        if (clearVisitsTarget) visitsData = List<Map<String, dynamic>>.from(dataMap['visits']);
        if (clearProductsTarget) productsData = List<Map<String, dynamic>>.from(dataMap['inventory']);
        if (dataMap['pending_transfers'] != null && dataMap['pending_transfers'] is List) {
          transfersData = List<Map<String, dynamic>>.from(dataMap['pending_transfers']);
        }
      }

      if (!hasValidStructure) {
        throw Exception('استجابة الخادم غير مفهومة أو لا تحتوي على الهيكل الصحيح للبيانات.');
      }

      final List<VisitModel> visitModels = await compute(_parseVisits, visitsData);
      final List<ProductModel> productModels = await compute(_parseProducts, productsData);

      // F4: إعادة الفحص لمنع مسح فاتورة سُجلت أثناء انتظار الشبكة (TOCTOU)
      final postCheck = await _db.getPendingSyncs();
      final postActive = postCheck.where((p) => !p['type'].toString().startsWith('quarantined_')).toList();
      if (postActive.any((p) => p['type'] == 'submit_sale')) {
         developer.log('[SyncRepository] Aborting local DB refresh: Offline sale occurred during fetch.');
         throw Exception('تم تسجيل فاتورة أوفلاين أثناء التحديث. يرجى المزامنة مجدداً.');
      }

      await _db.refreshSessionData(
        visitModels, 
        productModels, 
        transfersData,
        clearVisits: clearVisitsTarget,
        clearProducts: clearProductsTarget,
      );

      developer.log('[SyncRepository] syncDown completed successfully.');
      return true; // تمت المزامنة بنجاح
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
    Map<String, dynamic> safePayload;
    try {
      safePayload = jsonDecode(jsonEncode(payload));
      safePayload['idempotency_key'] ??= '${visitId}_${DateTime.now().microsecondsSinceEpoch}';
    } catch (e) {
      developer.log('[SyncRepository] Payload encoding failed: $e');
      rethrow;
    }

    final String finalStatus =
        (safePayload['outcome'] == 'Postponed') ? 'Pending' : 'Completed';

    final double cashCollected = double.tryParse(safePayload['cash_collected']?.toString() ?? '') ?? 0.0;
    final double debtPaid = double.tryParse(safePayload['debt_paid']?.toString() ?? '') ?? 0.0;
    final String outcome = safePayload['outcome'] ?? 'Sale';
    final String? cartItemsJson = safePayload['cart_items'] != null ? jsonEncode(safePayload['cart_items']) : null;
    final String? returnsJson = safePayload['returns'] != null ? jsonEncode(safePayload['returns']) : null;
    final String? notes = safePayload['notes']?.toString();
    final List<dynamic> cartItems = safePayload['cart_items'] ?? [];
    final List<dynamic>? returnsItems = safePayload['returns'];

    bool dispatchSuccess = false;
    try {
      await _dispatchPendingRecord(
        type: 'submit_sale',
        payload: {...safePayload, 'visitId': visitId},
      );
      dispatchSuccess = true;
    } catch (e) {
      if (e is DioException && e.response?.statusCode != null) {
        final statusCode = e.response!.statusCode!;
        if (statusCode >= 400 && statusCode < 500 && statusCode != 429 && statusCode != 408) {
          developer.log('[SyncRepository] Server strict rejection ($statusCode). Saving draft then rethrowing.');
          safePayload['quarantine_reason'] = 'Direct Validation Reject: $statusCode';
          await _db.addPendingSync(
            type: 'quarantined_draft_sale',
            payload: jsonEncode({...safePayload, 'visitId': visitId}),
          );
          rethrow; 
        }
      }
      developer.log('[SyncRepository] Offline mode triggered for invoice #$visitId. Reason: $e');
    }

    try {
      if (dispatchSuccess) {
        await _db.saveOnlineInvoiceAtomic(
          visitId: visitId, status: finalStatus, outcome: outcome,
          cashCollected: cashCollected, debtPaid: debtPaid,
          cartItemsJson: cartItemsJson, returnsJson: returnsJson, notes: notes,
          cartItems: cartItems, returnItems: returnsItems,
        );
        developer.log('[SyncRepository] Invoice #$visitId synced and saved atomically.');
      } else {
        await _db.saveOfflineInvoiceAtomic(
          visitId: visitId, payload: jsonEncode({...safePayload, 'visitId': visitId}),
          status: finalStatus, outcome: outcome, cashCollected: cashCollected, debtPaid: debtPaid,
          cartItemsJson: cartItemsJson, returnsJson: returnsJson, notes: notes,
          cartItems: cartItems, returnItems: returnsItems,
        );
        developer.log('[SyncRepository] Invoice #$visitId saved offline atomically.');
      }
    } catch (localDbError) {
      developer.log('[SyncRepository] FATAL: Local DB error while saving invoice state: $localDbError');
      rethrow;
    }
  }

  // -----------------------------------------------------------------------
  // respondToTransfer — الرد على حوالة مع Fallback تلقائي آمن
  // -----------------------------------------------------------------------
  // +++ الكي الجراحي: إرجاع bool لتحديد حالة الحوالة (true = أرسلت, false = أوفلاين) +++
  Future<bool> respondToTransfer({
    required int transferId,
    required String responseStr,
    String? reason,
  }) async {
    final incomingList = await _db.getIncomingTransfers();
    final contextData = incomingList.firstWhere(
      (t) => t['transfer_id'] == transferId || t['id'] == transferId, 
      orElse: () => <String, dynamic>{}
    );

    final payload = {
      'transferId': transferId,
      'response': responseStr,
      'reason': reason,
      'context_product_name': contextData['product_name'],
      'context_delta_cartons': contextData['delta_cartons'],
      'context_delta_packs': contextData['delta_packs'],
    };

    bool dispatchSuccess = false;
    try {
      await _dispatchPendingRecord(type: 'transfer_response', payload: payload);
      dispatchSuccess = true;
    } catch (e) {
      if (e is DioException && e.response?.statusCode != null) {
        final statusCode = e.response!.statusCode!;
        // +++ الكي الجراحي للثغرة: إحباط التخزين الأوفلاين الكاذب وإبلاغ البلوك بالرفض النهائي +++
        if (statusCode >= 400 && statusCode < 500 && statusCode != 429 && statusCode != 408) {
           throw Exception('تم رفض الرد من السيرفر (خطأ $statusCode). يرجى المحاولة مجدداً.');
        }
      }
      developer.log('[SyncRepository] Offline mode triggered for transfer #$transferId.');
    }

    try {
      if (dispatchSuccess) {
        await _db.removeIncomingTransfer(transferId);
        return true; // +++ أرسلت بنجاح +++
      } else {
        await _db.addPendingSync(
          type: 'transfer_response',
          payload: jsonEncode(payload),
        );
        await _db.removeIncomingTransfer(transferId);
        return false; // +++ دخلت طابور الأوفلاين +++
      }
    } catch (dbError) {
      developer.log('[SyncRepository] FATAL DB Error in respondToTransfer: $dbError');
      rethrow;
    }
  }

  // -----------------------------------------------------------------------
  // retryQuarantinedRecord — إعادة محاولة سجل محجور
  // -----------------------------------------------------------------------
  Future<void> retryQuarantinedRecord(int id) async {
    await _db.retryQuarantinedSync(id);
    await syncUp();
  }

  // -----------------------------------------------------------------------
  // syncUp — إرسال كل العمليات المعلقة
  // -----------------------------------------------------------------------
  Future<int> syncUp() async {
    // إغلاق القفل فوراً قبل أي await لمنع الـ Race Condition (H1)
    if (_isSyncing) {
      developer.log('[SyncRepository] syncUp is already running. Skipped.');
      return 0;
    }
    _isSyncing = true;
    int successCount = 0;
    List<Map<String, dynamic>> pending = []; // +++ إصلاح الـ Scope +++

    try {
      pending = await _db.getPendingSyncs();
      if (pending.isEmpty) return 0;

      developer.log(
        '[SyncRepository] Found ${pending.length} pending records to syncUp.',
      );

      for (final record in pending) {
        final recordId = record['id'] as int;
        final type = record['type'] as String;
        
        // +++ الكي الجراحي: تخطي السجلات المحجورة فوراً قبل لمسها أو محاولة فك تشفيرها (منع إعادة التدوير اللانهائي) +++
        if (type.startsWith('quarantined_')) continue;

        Map<String, dynamic> payload;
        // +++ H3: نسف الزومبي الدلالي (حماية الـ jsonDecode) +++
        try {
          payload = jsonDecode(record['payload'] as String);
        } catch (e) {
          developer.log('[SyncRepository] ☠️ Corrupted payload. Quarantining raw record #$recordId');
          // الاحتفاظ بالنص الأصلي (Raw Payload) لتمكين استرجاع البيانات يدوياً
          await _db.addPendingSync(type: 'quarantined_corrupt', payload: record['payload'] as String);
          await _db.deletePendingSync(recordId);
          continue;
        }

        try {
          if (!['submit_sale', 'toggle_break', 'transfer_response'].contains(type)) {
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
                developer.log('[SyncRepository] Auth Error ($statusCode) - Halting sync.');
                break;
              }
              if (statusCode == 429 || statusCode == 408) {
                developer.log('[SyncRepository] Transient error ($statusCode). Halting sync.');
                break;
              }

              String errorMessage = '';
              if (e.response?.data is Map) {
                errorMessage = e.response?.data?['message']?.toString() ?? e.response?.data?['detail']?.toString() ?? '';
              }
              
              if (statusCode == 403 && errorMessage.contains('تم تسويتها')) {
                  developer.log('[SyncRepository] ⚠️ Settlement Collision. Deleting offline record.');
                  await _db.deletePendingSync(recordId);
                  continue;
              }
              
              if (statusCode == 400 && type == 'toggle_break') {
                  developer.log('[SyncRepository] ⚠️ Break record rejected. Deleting it to unblock sync.');
                  await _db.deletePendingSync(recordId);
                  continue;
              }

              // +++ N3: حجر صحي مع حفظ سبب الرفض الصريح للتشخيص اللاحق +++
              developer.log('[SyncRepository] FATAL: Server strictly rejected #$recordId. Moving to Quarantine.');
              payload['quarantine_reason'] = 'Server Rejected: $statusCode | $errorMessage';
              await _db.addPendingSync(type: 'quarantined_$type', payload: jsonEncode(payload));
              await _db.deletePendingSync(recordId);
              continue;
            }
          }
          developer.log('[SyncRepository] Offline or 5xx — stopping syncUp.');
          break;
        } catch (e) {
          if (e.toString().contains('DatabaseException')) {
             developer.log('[SyncRepository] Transient DB Error in #$recordId: $e. Halting sync.');
             break;
          }
          developer.log('[SyncRepository] ☠️ Semantic/Type Error in #$recordId: $e. Quarantining. (Note: potential duplication window between add and delete)');
          payload['quarantine_reason'] = 'Local Type Error: $e';
          await _db.addPendingSync(type: 'quarantined_$type', payload: jsonEncode(payload));
          await _db.deletePendingSync(recordId);
          continue; 
        }
      }
    } finally {
      _isSyncing = false; 
      developer.log(
        '[SyncRepository] syncUp() completed. Processed successes: $successCount.',
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
        final int visitId = int.tryParse(payload['visitId']?.toString() ?? '') ?? 0;
        final body = Map<String, dynamic>.from(payload)
          ..remove('visitId')
          ..remove('idempotency_key')
          ..remove('quarantine_reason');
        
        final idempotencyKey = payload['idempotency_key']?.toString() ?? 'sync_${visitId}_fallback_${payload['cash_collected'] ?? 0}';

        final response = await _api.put(
          '/visits/$visitId', 
          data: body,
          options: Options(headers: {'X-Idempotency-Key': idempotencyKey})
        );

        if (response.statusCode == null || response.statusCode! < 200 || response.statusCode! >= 300) {
          throw DioException(
            requestOptions: response.requestOptions,
            response: response,
            type: DioExceptionType.badResponse,
          );
        }

        try {
          if (response.data is Map && response.data['new_balance'] != null) {
            final double newBalance = double.tryParse(response.data['new_balance'].toString()) ?? 0.0;
            await _db.updateShopBalanceLocally(visitId, newBalance);
          }
        } catch (dbError) {
          developer.log('[SyncRepository] Warning: Local DB update failed after successful sync: $dbError');
        }
        break;

      case 'toggle_break':
        final String action = payload['action']?.toString() ?? '';
        await _api.put(
          '/driver/sessions/break',
          data: {'action': action},
        );
        break;

      case 'transfer_response':
        final int tId = int.tryParse(payload['transferId']?.toString() ?? '') ?? 0;
        final body = {
          'response': payload['response'],
          'reason': payload['reason']
        };
        await _api.put('/driver/transfers/$tId/respond', data: body);
        break;
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