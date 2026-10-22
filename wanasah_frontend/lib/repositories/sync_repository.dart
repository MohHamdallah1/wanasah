import 'dart:convert';
import 'dart:developer' as developer;
import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart'; // +++ للـ Isolates (compute) +++
import 'package:uuid/uuid.dart';
import '../core/network/api_client.dart';
import '../core/db/local_database.dart';
import '../core/sync/durable_command.dart';
import '../core/visit/local_inventory_projection.dart';
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
      safePayload['request_id'] ??= _uuid.v4();
    } catch (e) {
      developer.log('[SyncRepository] Payload encoding failed: $e');
      rethrow;
    }

    final commandPayload = <String, dynamic>{
      ...safePayload,
      'visitId': visitId,
    };
    final requestId = safePayload['request_id'].toString();

    // Persist identity/body before the first mutation attempt. If the process
    // dies after the server commits, restart replays this exact command.
    final commandRecordId = await _db.stageVisitCommandAtomic(
      visitId: visitId,
      payload: jsonEncode(commandPayload),
      requestId: requestId,
    );
    final isQueueHead =
        await _db.isFirstUnresolvedCommand(commandRecordId);
    if (!isQueueHead) {
      await _finalizeVisitCommandLocalState(
        commandRecordId: commandRecordId,
        payload: commandPayload,
      );
      developer.log(
        '[SyncRepository] Visit #$visitId queued behind earlier unresolved evidence.',
      );
      return;
    }

    await _db.markPendingSyncInFlight(commandRecordId);

    try {
      await _dispatchPendingRecord(
        type: DurableCommandType.submitSale,
        payload: commandPayload,
      );
    } on DioException catch (e) {
      final statusCode = e.response?.statusCode;
      final incidentId = _requestIdFromDio(e);

      if (statusCode == 401) {
        await _db.markPendingSyncPending(
          commandRecordId,
          lastErrorCode: 'AUTH_REQUIRED',
          lastErrorMessage: _displayErrorFromDio(e),
          lastRequestId: incidentId,
        );
        rethrow;
      }

      if (statusCode != null &&
          statusCode >= 400 &&
          statusCode < 500 &&
          statusCode != 408 &&
          statusCode != 429) {
        await _db.markPendingSyncBlocked(
          commandRecordId,
          errorCode: _stableErrorCodeFromDio(e),
          errorMessage: _displayErrorFromDio(e),
          requestId: incidentId,
        );
        rethrow;
      }

      await _db.markPendingSyncPending(
        commandRecordId,
        lastErrorCode:
            statusCode == null ? 'NETWORK_AMBIGUOUS' : 'HTTP_$statusCode',
        lastErrorMessage: _displayErrorFromDio(e),
        lastRequestId: incidentId,
      );

      // The representative may continue offline. The local projection is
      // applied exactly once and is tied to the still-unresolved command.
      await _finalizeVisitCommandLocalState(
        commandRecordId: commandRecordId,
        payload: commandPayload,
      );
      developer.log(
        '[SyncRepository] Visit #$visitId preserved offline with durable request $requestId.',
      );
      return;
    } catch (e) {
      await _db.markPendingSyncBlocked(
        commandRecordId,
        errorCode: 'LOCAL_COMMAND_ERROR',
        errorMessage: e.toString(),
      );
      rethrow;
    }

    try {
      await _finalizeVisitCommandLocalState(
        commandRecordId: commandRecordId,
        payload: commandPayload,
      );
      await _db.deletePendingSync(commandRecordId);
      developer.log(
        '[SyncRepository] Visit #$visitId committed and locally finalized with durable request $requestId.',
      );
    } catch (localDbError) {
      // Do not delete the command. A later replay returns the Backend's stored
      // idempotent response and completes local finalization exactly once.
      developer.log(
        '[SyncRepository] Local finalize failed after visit dispatch: $localDbError',
      );
      rethrow;
    }
  }

  Future<void> _finalizeVisitCommandLocalState({
    required int commandRecordId,
    required Map<String, dynamic> payload,
  }) async {
    final visitId =
        int.tryParse(payload['visitId']?.toString() ?? '') ?? 0;
    if (visitId <= 0) {
      throw StateError('Visit command is missing a valid visitId.');
    }

    final outcome = payload['outcome']?.toString() ?? 'Sale';
    final finalStatus = outcome == 'Postponed' ? 'Pending' : 'Completed';
    final cashCollected =
        double.tryParse(payload['cash_collected']?.toString() ?? '') ?? 0.0;
    final debtPaid =
        double.tryParse(payload['debt_paid']?.toString() ?? '') ?? 0.0;
    final cartItems = payload['cart_items'] is List
        ? List<dynamic>.from(payload['cart_items'] as List)
        : <dynamic>[];
    final returnItems = payload['returns'] is List
        ? List<dynamic>.from(payload['returns'] as List)
        : null;

    await _db.finalizeVisitCommandLocalState(
      commandRecordId: commandRecordId,
      visitId: visitId,
      status: finalStatus,
      outcome: outcome,
      cashCollected: cashCollected,
      debtPaid: debtPaid,
      cartItemsJson:
          payload['cart_items'] != null ? jsonEncode(payload['cart_items']) : null,
      returnsJson:
          payload['returns'] != null ? jsonEncode(payload['returns']) : null,
      notes: payload['notes']?.toString(),
      cartItems: cartItems,
      returnItems: returnItems,
    );
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
          // FIFO fail-closed: never let later commands leapfrog unresolved evidence.
          break;
        }

        final type = DurableCommandType.normalizeLegacyType(rawType);

        if (DurableCommandType.isTemporal(type)) {
          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: 'STALE_TEMPORAL_COMMAND',
            errorMessage:
                'Offline break commands cannot be replayed after their original time.',
          );
          break;
        }

        if (!DurableCommandType.isReplayable(type)) {
          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: 'UNKNOWN_OFFLINE_COMMAND',
            errorMessage: 'Unsupported offline command type: $type',
          );
          break;
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
          break;
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
          if (type == DurableCommandType.submitSale) {
            await _finalizeVisitCommandLocalState(
              commandRecordId: recordId,
              payload: payload,
            );
          } else if (type == DurableCommandType.transferResponse) {
            final transferId =
                int.tryParse(payload['transferId']?.toString() ?? '') ?? 0;
            if (transferId > 0) {
              await _db.removeIncomingTransfer(transferId);
            }
          }
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
          break;
        } on LocalInventoryProjectionException catch (error) {
          await _db.markPendingSyncBlocked(
            recordId,
            errorCode: error.code,
            errorMessage: error.toString(),
          );
          break;
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
          break;
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