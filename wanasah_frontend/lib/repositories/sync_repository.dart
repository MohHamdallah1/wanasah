import 'dart:convert';
import 'dart:developer' as developer;
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart'; // +++ للـ Isolates (compute) +++
import 'package:uuid/uuid.dart';
import '../core/network/api_client.dart';
import '../core/db/local_database.dart';
import '../core/sync/durable_command.dart';
import '../models/product_model.dart';
import '../models/visit_model.dart';

// الوظيفة: الوسيط (Sync Engine) بين السيرفر (ApiClient) وقاعدة البيانات المحلية (LocalDatabase).
//
//   syncDown()       — جلب بيانات السيرفر وحفظها محلياً (Online → Local)
//   saveInvoice()    — إرسال فاتورة مع Fallback تلقائي إلى Offline
//   syncUp()         — إعادة إرسال العمليات المعلقة عند عودة الإنترنت

class SyncRepository {
  // +++  (توحيد طبقة المزامنة - Singleton): نسخة واحدة تحكم التطبيق بأكمله لمنع تكرار الفواتير +++
  static final SyncRepository instance = SyncRepository._internal();

  // -----------------------------------------------------------------------
  // Dependencies
  // -----------------------------------------------------------------------
  final ApiClient _api;
  final LocalDatabase _db;
  static const Uuid _uuid = Uuid();
  
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
  // +++   إرجاع bool لإبلاغ البلوك إذا تم التخطي بسبب قفل المزامنة الموحد +++
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

      // 2. أي سجل غير محسوم هو دليل محلي محمي. السجلات المحجورة
      // لا تُستثنى من الحماية لأنها قد تحمل مبيعات/مخزوناً لم يُسوَّ بعد.
      final pendingCheck = await _db.getPendingSyncs();
      final unresolved = pendingCheck.where(isUnresolvedOfflineCommand).toList();
      final blocked = unresolved.where((row) {
        final rawType = row['type']?.toString() ?? '';
        return DurableCommandState.fromStorage(row['state']) ==
                DurableCommandState.blocked ||
            DurableCommandType.isLegacyQuarantined(rawType);
      }).toList();

      if (blocked.isNotEmpty) {
        developer.log(
          '[SyncRepository] Aborting syncDown: blocked recovery evidence exists.',
        );
        throw Exception(
          'يوجد عمليات أوفلاين تحتاج معالجة قبل تحديث البيانات المحلية.',
        );
      }

      final activePending = unresolved;
      final hasBlockingPending = activePending.any(
        (p) => DurableCommandType.normalizeLegacyType(
              p['type']?.toString() ?? '',
            ) !=
            DurableCommandType.submitSale,
      );
      if (hasBlockingPending) {
        developer.log(
          '[SyncRepository] Aborting syncDown: unresolved non-sale commands exist.',
        );
        throw Exception(
          'يوجد عمليات أوفلاين حساسة معلقة. يجب تسويتها أولاً لحماية بياناتك.',
        );
      }

      final hasUnsyncedSales = activePending.any(
        (p) => DurableCommandType.normalizeLegacyType(
              p['type']?.toString() ?? '',
            ) ==
            DurableCommandType.submitSale,
      );
      if (hasUnsyncedSales) {
        developer.log(
          '[SyncRepository] Aborting local DB refresh: unresolved offline sales exist.',
        );
        throw Exception(
          'يرجى الانتظار، جاري رفع بعض فواتير الأوفلاين للسيرفر أولاً.',
        );
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

      // F4: أي أمر ظهر أثناء fetch يمنع استبدال الإسقاط المحلي حتى تتم
      // معالجته؛ لا نستثني blocked/quarantine من هذا الفحص.
      final postCheck = await _db.getPendingSyncs();
      final postUnresolved =
          postCheck.where(isUnresolvedOfflineCommand).toList();
      if (postUnresolved.isNotEmpty) {
        developer.log(
          '[SyncRepository] Aborting local DB refresh: unresolved command appeared during fetch.',
        );
        throw Exception(
          'تم تسجيل عملية أوفلاين أثناء التحديث. عالج المزامنة أولاً ثم أعد المحاولة.',
        );
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
      // +++  لـ Bug 1: القفل يُحرر دائماً داخل الـ finally +++
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
      // Generate once per business operation and persist the same UUID through
      // direct send, offline storage, automatic retry and syncUp replay.
      safePayload['request_id'] ??= _uuid.v4();
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
          await _db.addPendingSync(
            type: DurableCommandType.submitSale,
            payload: jsonEncode({...safePayload, 'visitId': visitId}),
            commandId: safePayload['request_id']?.toString(),
            state: DurableCommandState.blocked,
            lastErrorCode: 'HTTP_$statusCode',
            lastErrorMessage: 'Direct validation rejection',
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
          visitId: visitId,
          payload: jsonEncode({...safePayload, 'visitId': visitId}),
          status: finalStatus,
          outcome: outcome,
          cashCollected: cashCollected,
          debtPaid: debtPaid,
          cartItemsJson: cartItemsJson,
          returnsJson: returnsJson,
          notes: notes,
          cartItems: cartItems,
          returnItems: returnsItems,
          commandId: safePayload['request_id']?.toString(),
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
  // +++   إرجاع bool لتحديد حالة الحوالة (true = أرسلت, false = أوفلاين) +++
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
        // +++  للثغرة: إحباط التخزين الأوفلاين الكاذب وإبلاغ البلوك بالرفض النهائي +++
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
          type: DurableCommandType.transferResponse,
          payload: jsonEncode(payload),
          commandId: _uuid.v4(),
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
    if (_isSyncing) {
      developer.log('[SyncRepository] syncUp is already running. Skipped.');
      return 0;
    }

    _isSyncing = true;
    int successCount = 0;

    try {
      final pending = await _db.getPendingSyncs();
      if (pending.isEmpty) return 0;

      developer.log(
        '[SyncRepository] Found ${pending.length} unresolved command records.',
      );

      for (final record in pending) {
        final recordId = record['id'] as int;
        final rawType = record['type']?.toString() ?? '';
        final state = DurableCommandState.fromStorage(record['state']);

        if (state == DurableCommandState.blocked ||
            DurableCommandType.isLegacyQuarantined(rawType)) {
          continue;
        }

        final type = DurableCommandType.normalizeLegacyType(rawType);

        if (DurableCommandType.isTemporal(type)) {
          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: 'STALE_TEMPORAL_COMMAND',
            errorMessage:
                'Offline break commands cannot be replayed after their original time.',
          );
          continue;
        }

        if (!DurableCommandType.isReplayable(type)) {
          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: 'UNKNOWN_OFFLINE_COMMAND',
            errorMessage: 'Unsupported offline command type: $type',
          );
          continue;
        }

        Map<String, dynamic> payload;
        try {
          payload = jsonDecode(record['payload'] as String);
        } catch (e) {
          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: 'CORRUPT_OFFLINE_PAYLOAD',
            errorMessage: e.toString(),
          );
          continue;
        }

        if (type == DurableCommandType.submitSale &&
            (payload['request_id'] == null ||
                payload['request_id'].toString().trim().isEmpty)) {
          payload['request_id'] = _uuid.v4();
          await _db.updatePendingSyncPayload(recordId, jsonEncode(payload));
        }

        final existingCommandId = record['command_id']?.toString().trim() ?? '';
        if (existingCommandId.isEmpty) {
          final commandId = type == DurableCommandType.submitSale
              ? payload['request_id']?.toString() ?? _uuid.v4()
              : _uuid.v4();
          await _db.updatePendingSyncCommandId(recordId, commandId);
        }

        await _db.markPendingSyncInFlight(recordId);

        try {
          await _dispatchPendingRecord(type: type, payload: payload);
          await _db.deletePendingSync(recordId);
          successCount++;
        } on DioException catch (e) {
          final statusCode = e.response?.statusCode;
          final requestId = _requestIdFromDio(e);

          if (statusCode == 401) {
            await _db.markPendingSyncPending(
              recordId,
              lastErrorCode: 'AUTH_REQUIRED',
              lastErrorMessage: 'Authentication required before replay.',
              lastRequestId: requestId,
            );
            break;
          }

          if (statusCode == 408 ||
              statusCode == 429 ||
              statusCode == null ||
              statusCode >= 500) {
            await _db.markPendingSyncPending(
              recordId,
              lastErrorCode:
                  statusCode == null ? 'NETWORK_AMBIGUOUS' : 'HTTP_$statusCode',
              lastErrorMessage: _displayErrorFromDio(e),
              lastRequestId: requestId,
            );
            break;
          }

          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: _stableErrorCodeFromDio(e),
            errorMessage: _displayErrorFromDio(e),
            requestId: requestId,
          );
        } catch (e) {
          if (e.toString().contains('DatabaseException')) {
            await _db.markPendingSyncPending(
              recordId,
              lastErrorCode: 'LOCAL_DATABASE_TRANSIENT',
              lastErrorMessage: e.toString(),
            );
            break;
          }

          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: 'LOCAL_COMMAND_ERROR',
            errorMessage: e.toString(),
          );
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

  String? _requestIdFromDio(DioException error) {
    final header = error.response?.headers.value('x-request-id');
    if (header != null && header.trim().isNotEmpty) return header.trim();

    final data = error.response?.data;
    if (data is Map) {
      final nested = data['error'];
      if (nested is Map && nested['request_id'] != null) {
        final value = nested['request_id'].toString().trim();
        if (value.isNotEmpty) return value;
      }
      final topLevel = data['request_id']?.toString().trim() ?? '';
      if (topLevel.isNotEmpty) return topLevel;
    }
    return null;
  }

  String _stableErrorCodeFromDio(DioException error) {
    final data = error.response?.data;
    if (data is Map && data['error'] is Map) {
      final code = (data['error'] as Map)['code']?.toString().trim() ?? '';
      if (code.isNotEmpty) return code;
    }
    final status = error.response?.statusCode;
    return status == null ? 'NETWORK_ERROR' : 'HTTP_$status';
  }

  String? _displayErrorFromDio(DioException error) {
    final data = error.response?.data;
    if (data is Map) {
      if (data['error'] is Map) {
        final message = (data['error'] as Map)['message']?.toString().trim();
        if (message != null && message.isNotEmpty) return message;
      }
      final message = data['message']?.toString().trim();
      if (message != null && message.isNotEmpty) return message;
      final detail = data['detail']?.toString().trim();
      if (detail != null && detail.isNotEmpty) return detail;
    }
    return error.message;
  }

  // -----------------------------------------------------------------------
  // Helper خاص: توجيه كل نوع عملية معلقة إلى endpoint الصحيح
  // -----------------------------------------------------------------------
  Future<void> _dispatchPendingRecord({
    required String type,
    required Map<String, dynamic> payload,
  }) async {
    switch (type) {
      case DurableCommandType.submitSale:
        final int visitId = int.tryParse(payload['visitId']?.toString() ?? '') ?? 0;
        final body = Map<String, dynamic>.from(payload)
          ..remove('visitId')
          ..remove('idempotency_key')
          ..remove('quarantine_reason');

        final requestId = body['request_id']?.toString().trim() ?? '';
        if (requestId.isEmpty) {
          throw StateError(
            'submit_sale is missing its durable request_id.',
          );
        }

        final response = await _api.put(
          '/visits/$visitId',
          data: body,
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

      case DurableCommandType.legacyToggleBreak:
        throw StateError(
          'Historical offline break commands are not replayable.',
        );

      case DurableCommandType.transferResponse:
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