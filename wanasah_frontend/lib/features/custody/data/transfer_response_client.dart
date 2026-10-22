import 'package:wanasah_frontend/core/network/api_client.dart';

import '../domain/transfer_decision.dart';

abstract interface class TransferResponseClient {
  Future<void> respondIndividual(TransferDecision decision);

  Future<void> respondBatch(List<TransferDecision> decisions);
}

class ApiTransferResponseClient implements TransferResponseClient {
  ApiTransferResponseClient({ApiClient? apiClient})
      : _apiClient = apiClient ?? ApiClient.instance;

  static const int runtimeBatchMaximum = 100;

  final ApiClient _apiClient;

  @override
  Future<void> respondIndividual(TransferDecision decision) async {
    await _apiClient.put<Object?>(
      '/driver/transfers/${decision.transferId}/respond',
      data: <String, dynamic>{
        'response': decision.status.wireValue,
        'reason': decision.reason,
      },
    );
  }

  @override
  Future<void> respondBatch(List<TransferDecision> decisions) async {
    if (decisions.isEmpty || decisions.length > runtimeBatchMaximum) {
      throw ArgumentError.value(
        decisions.length,
        'decisions',
        'Transfer batch must contain 1..$runtimeBatchMaximum decisions.',
      );
    }

    await _apiClient.put<Object?>(
      '/driver/transfers/batch_respond',
      data: <String, dynamic>{
        'transfers':
            decisions
                .map(
                  (decision) => <String, dynamic>{
                    'transfer_id': decision.transferId,
                    'status': decision.status.wireValue,
                    'reason': decision.reason,
                  },
                )
                .toList(growable: false),
      },
    );
  }
}
