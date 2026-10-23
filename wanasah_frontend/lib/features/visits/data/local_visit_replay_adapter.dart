import 'dart:convert';
import 'dart:developer' as developer;

import 'package:dio/dio.dart';

import '../../../core/db/local_database.dart';
import '../../../core/network/api_client.dart';
import '../application/visit_replay_adapter.dart';

typedef VisitReplaySend = Future<Response<dynamic>> Function(
  String path, {
  required Map<String, dynamic> data,
});

typedef VisitBalanceUpdate = Future<void> Function(
  int visitId,
  double newBalance,
);

typedef VisitCommandFinalize = Future<void> Function({
  required int commandRecordId,
  required int visitId,
  required String status,
  required String outcome,
  required double cashCollected,
  required double debtPaid,
  String? cartItemsJson,
  String? returnsJson,
  String? notes,
  required List<dynamic> cartItems,
  List<dynamic>? returnItems,
});

class LocalVisitReplayAdapter implements VisitReplayAdapter {
  LocalVisitReplayAdapter({
    required VisitReplaySend send,
    required VisitBalanceUpdate updateBalance,
    required VisitCommandFinalize finalize,
  })  : _send = send,
        _updateBalance = updateBalance,
        _finalize = finalize;

  factory LocalVisitReplayAdapter.withDependencies({
    ApiClient? api,
    LocalDatabase? database,
  }) {
    final client = api ?? ApiClient.instance;
    final db = database ?? LocalDatabase.instance;
    return LocalVisitReplayAdapter(
      send: (path, {required data}) => client.put(path, data: data),
      updateBalance: db.updateShopBalanceLocally,
      finalize: ({
        required commandRecordId,
        required visitId,
        required status,
        required outcome,
        required cashCollected,
        required debtPaid,
        cartItemsJson,
        returnsJson,
        notes,
        required cartItems,
        returnItems,
      }) =>
          db.finalizeVisitCommandLocalState(
            commandRecordId: commandRecordId,
            visitId: visitId,
            status: status,
            outcome: outcome,
            cashCollected: cashCollected,
            debtPaid: debtPaid,
            cartItemsJson: cartItemsJson,
            returnsJson: returnsJson,
            notes: notes,
            cartItems: cartItems,
            returnItems: returnItems,
          ),
    );
  }

  final VisitReplaySend _send;
  final VisitBalanceUpdate _updateBalance;
  final VisitCommandFinalize _finalize;

  @override
  Future<void> dispatch(Map<String, dynamic> payload) async {
    final visitId =
        int.tryParse(payload['visitId']?.toString() ?? '') ?? 0;
    final body = Map<String, dynamic>.from(payload)
      ..remove('visitId')
      ..remove('idempotency_key')
      ..remove('quarantine_reason');

    final requestId = body['request_id']?.toString().trim() ?? '';
    if (requestId.isEmpty) {
      throw StateError('submit_sale is missing its durable request_id.');
    }

    final response = await _send('/visits/$visitId', data: body);
    if (response.statusCode == null ||
        response.statusCode! < 200 ||
        response.statusCode! >= 300) {
      throw DioException(
        requestOptions: response.requestOptions,
        response: response,
        type: DioExceptionType.badResponse,
      );
    }

    try {
      if (response.data is Map && response.data['new_balance'] != null) {
        final newBalance =
            double.tryParse(response.data['new_balance'].toString()) ?? 0.0;
        await _updateBalance(visitId, newBalance);
      }
    } catch (error) {
      developer.log(
        '[VisitReplayAdapter] Warning: local balance update failed after successful sync: $error',
      );
    }
  }

  @override
  Future<void> finalizeLocalState({
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

    await _finalize(
      commandRecordId: commandRecordId,
      visitId: visitId,
      status: finalStatus,
      outcome: outcome,
      cashCollected: cashCollected,
      debtPaid: debtPaid,
      cartItemsJson: payload['cart_items'] != null
          ? jsonEncode(payload['cart_items'])
          : null,
      returnsJson:
          payload['returns'] != null ? jsonEncode(payload['returns']) : null,
      notes: payload['notes']?.toString(),
      cartItems: cartItems,
      returnItems: returnItems,
    );
  }
}
