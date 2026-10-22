import 'dart:async';

import 'package:dio/dio.dart';

import '../../../core/network/api_failure.dart';
import '../../../core/sync/sync_reconciliation_failure.dart';
import '../data/recovery_sync_executor.dart';
import 'recovery_reader.dart';
import 'recovery_snapshot.dart';

enum RecoverySyncExecution {
  completed,
  skipped,
  timedOut,
  transportAmbiguous,
  failed,
}

enum RecoverySyncDisposition {
  synced,
  incomplete,
  recoveryRequired,
  unresolved,
}

class RecoverySyncResult {
  const RecoverySyncResult({
    required this.disposition,
    required this.execution,
    required this.snapshot,
  });

  final RecoverySyncDisposition disposition;
  final RecoverySyncExecution execution;
  final RecoverySnapshot? snapshot;

  static RecoverySyncDisposition classify({
    required RecoverySnapshot snapshot,
    required RecoverySyncExecution execution,
  }) {
    if (snapshot.hasBlocked) {
      return RecoverySyncDisposition.recoveryRequired;
    }

    if (execution == RecoverySyncExecution.timedOut ||
        execution == RecoverySyncExecution.transportAmbiguous) {
      return RecoverySyncDisposition.unresolved;
    }

    if (snapshot.hasPending) {
      return RecoverySyncDisposition.incomplete;
    }

    if (execution != RecoverySyncExecution.completed) {
      return RecoverySyncDisposition.unresolved;
    }

    return RecoverySyncDisposition.synced;
  }
}

class RecoverySyncCoordinator {
  RecoverySyncCoordinator({
    required RecoveryReader reader,
    required RecoverySyncExecutor executor,
  }) : _reader = reader,
       _executor = executor;

  final RecoveryReader _reader;
  final RecoverySyncExecutor _executor;

  Future<RecoverySnapshot> readSnapshot() => _reader.read();

  Future<RecoverySyncResult> synchronize({
    Duration waitLimit = const Duration(seconds: 8),
  }) async {
    RecoverySyncExecution execution;

    try {
      final ran = await _executor.synchronize().timeout(waitLimit);
      execution =
          ran
              ? RecoverySyncExecution.completed
              : RecoverySyncExecution.skipped;
    } on TimeoutException {
      execution = RecoverySyncExecution.timedOut;
    } on DioException catch (error) {
      final failure = error.apiFailure;
      final status = failure.status;
      final isAmbiguous =
          failure.kind == ApiFailureKind.connection ||
          failure.kind == ApiFailureKind.timeout ||
          failure.kind == ApiFailureKind.cancelled ||
          failure.kind == ApiFailureKind.unknown ||
          status == null ||
          status == 408 ||
          status == 429 ||
          status >= 500;
      execution =
          isAmbiguous
              ? RecoverySyncExecution.transportAmbiguous
              : RecoverySyncExecution.failed;
    } on SyncReconciliationException {
      execution = RecoverySyncExecution.failed;
    } catch (_) {
      execution = RecoverySyncExecution.failed;
    }

    RecoverySnapshot? snapshot;
    try {
      snapshot = await _reader.read();
    } catch (_) {
      snapshot = null;
    }

    if (snapshot == null) {
      return RecoverySyncResult(
        disposition: RecoverySyncDisposition.unresolved,
        execution: execution,
        snapshot: null,
      );
    }

    return RecoverySyncResult(
      disposition: RecoverySyncResult.classify(
        snapshot: snapshot,
        execution: execution,
      ),
      execution: execution,
      snapshot: snapshot,
    );
  }
}
