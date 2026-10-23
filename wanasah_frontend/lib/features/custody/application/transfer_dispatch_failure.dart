import 'package:dio/dio.dart';

import '../../../core/network/api_failure.dart';

enum TransferDispatchFailureKind {
  unresolved,
  blocked,
}

class TransferDispatchFailure {
  const TransferDispatchFailure({
    required this.kind,
    required this.code,
    required this.requestId,
    required this.displayFallback,
    this.failedTransferId,
  });

  final TransferDispatchFailureKind kind;
  final String code;
  final String? requestId;

  /// Only structured public transfer identity; validated again against the chunk.
  final int? failedTransferId;

  /// Human-readable fallback only. Never drives machine classification.
  final String? displayFallback;

  factory TransferDispatchFailure.fromDio(DioException error) {
    final failure = error.apiFailure;
    final status = failure.status;

    if (status == 401) {
      return TransferDispatchFailure(
        kind: TransferDispatchFailureKind.unresolved,
        code: failure.code ?? 'AUTH_REQUIRED',
        requestId: failure.requestId,
        displayFallback: failure.displayFallback,
      );
    }

    final ambiguous =
        failure.kind == ApiFailureKind.connection ||
        failure.kind == ApiFailureKind.timeout ||
        failure.kind == ApiFailureKind.cancelled ||
        failure.kind == ApiFailureKind.unknown ||
        status == null ||
        status == 408 ||
        status == 429 ||
        status >= 500;

    final rawId = failure.context['transfer_id'];
    final itemId = !ambiguous && status != null && status >= 400 && status < 500 &&
        failure.hasStructuredCode &&
        rawId is int && rawId > 0 && rawId <= 2147483647 ? rawId : null;

    return TransferDispatchFailure(
      failedTransferId: itemId,
      kind:
          ambiguous
              ? TransferDispatchFailureKind.unresolved
              : TransferDispatchFailureKind.blocked,
      code:
          failure.code ??
          (status == null ? 'NETWORK_AMBIGUOUS' : 'HTTP_$status'),
      requestId: failure.requestId,
      displayFallback: failure.displayFallback,
    );
  }
}
