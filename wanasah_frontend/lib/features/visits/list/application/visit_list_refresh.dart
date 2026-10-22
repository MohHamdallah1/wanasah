import 'dart:async';

import 'package:dio/dio.dart';

import '../../../../core/network/api_failure.dart';
import '../../../../core/sync/durable_command.dart';
import '../data/visit_list_refresh_source.dart';

enum VisitListRefreshOutcome {
  refreshed,
  alreadySyncing,
  transportAmbiguous,
  blockedByUnresolvedDurableWork,
  deterministicFailure,
}

class VisitListRefreshResult {
  const VisitListRefreshResult({
    required this.outcome,
    this.code,
    this.requestId,
    this.displayFallback,
  });

  final VisitListRefreshOutcome outcome;
  final String? code;
  final String? requestId;

  /// Display-only fallback. It never drives classification.
  final String? displayFallback;
}

class VisitListRefreshCoordinator {
  VisitListRefreshCoordinator({
    required VisitListRefreshSource source,
    Duration waitLimit = const Duration(seconds: 10),
  }) : _source = source,
       _waitLimit = waitLimit;

  final VisitListRefreshSource _source;
  final Duration _waitLimit;

  Future<VisitListRefreshResult> refresh() async {
    try {
      final ran = await _source.syncDown().timeout(_waitLimit);
      if (!ran) {
        return const VisitListRefreshResult(
          outcome: VisitListRefreshOutcome.alreadySyncing,
        );
      }
      return const VisitListRefreshResult(
        outcome: VisitListRefreshOutcome.refreshed,
      );
    } on TimeoutException {
      return const VisitListRefreshResult(
        outcome: VisitListRefreshOutcome.transportAmbiguous,
      );
    } on DioException catch (error) {
      final failure = error.apiFailure;
      if (_isTransportAmbiguous(failure)) {
        return VisitListRefreshResult(
          outcome: VisitListRefreshOutcome.transportAmbiguous,
          code: failure.code,
          requestId: failure.requestId,
          displayFallback: failure.displayFallback,
        );
      }

      return VisitListRefreshResult(
        outcome: VisitListRefreshOutcome.deterministicFailure,
        code: failure.code,
        requestId: failure.requestId,
        displayFallback: failure.displayFallback,
      );
    } catch (_) {
      final unresolved = await _readUnresolvedFailClosed();
      if (unresolved != null && unresolved.isNotEmpty) {
        return const VisitListRefreshResult(
          outcome:
              VisitListRefreshOutcome.blockedByUnresolvedDurableWork,
        );
      }

      return const VisitListRefreshResult(
        outcome: VisitListRefreshOutcome.deterministicFailure,
      );
    }
  }

  Future<List<Map<String, dynamic>>?> _readUnresolvedFailClosed() async {
    try {
      final rows = await _source.readUnresolvedCommands();
      return rows.where(isUnresolvedOfflineCommand).toList();
    } catch (_) {
      return null;
    }
  }

  bool _isTransportAmbiguous(ApiFailure failure) {
    if (failure.kind == ApiFailureKind.connection ||
        failure.kind == ApiFailureKind.timeout ||
        failure.kind == ApiFailureKind.cancelled ||
        failure.kind == ApiFailureKind.unknown) {
      return true;
    }

    final status = failure.status;
    return status == null ||
        status == 408 ||
        status == 429 ||
        status >= 500;
  }
}
