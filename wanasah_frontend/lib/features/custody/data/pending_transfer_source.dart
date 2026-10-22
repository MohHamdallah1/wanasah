import 'package:dio/dio.dart';
import 'package:wanasah_frontend/core/db/local_database.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_client.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';

import '../domain/pending_transfer.dart';

typedef PendingTransferRemoteFetch = Future<Object?> Function();
typedef PendingTransferLocalFetch =
    Future<List<Map<String, dynamic>>> Function();

class PendingTransferSource {
  const PendingTransferSource({
    required PendingTransferRemoteFetch remoteFetch,
    required PendingTransferLocalFetch localFetch,
  })  : _remoteFetch = remoteFetch,
        _localFetch = localFetch;

  factory PendingTransferSource.defaults({
    ApiClient? apiClient,
    LocalDatabase? localDatabase,
  }) {
    final api = apiClient ?? ApiClient.instance;
    final db = localDatabase ?? LocalDatabase.instance;
    return PendingTransferSource(
      remoteFetch: () async =>
          (await api.get<Object?>('/driver/transfers/pending')).data,
      localFetch: db.getIncomingTransfers,
    );
  }

  final PendingTransferRemoteFetch _remoteFetch;
  final PendingTransferLocalFetch _localFetch;

  Future<PendingTransferBatch?> load() async {
    try {
      final raw = await _remoteFetch();
      if (raw is! List) {
        throw const FormatException(
          'Invalid pending transfer response shape.',
        );
      }
      if (raw.isEmpty) return null;
      return PendingTransferBatch.fromServerJson(raw.first);
    } on DioException catch (error) {
      final failure = error.apiFailure;
      if (!_allowsLocalFallback(failure)) {
        throw ApiFailureException(failure);
      }

      final localRows = await _localFetch();
      if (localRows.isEmpty) return null;
      return PendingTransferBatch.fromLocalRows(localRows);
    }
  }

  static bool _allowsLocalFallback(ApiFailure failure) {
    if (failure.kind == ApiFailureKind.connection ||
        failure.kind == ApiFailureKind.timeout) {
      return true;
    }
    final status = failure.status;
    return status == 429 || (status != null && status >= 500);
  }
}
