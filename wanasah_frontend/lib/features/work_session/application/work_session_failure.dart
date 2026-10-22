import 'package:dio/dio.dart';

import '../../../core/network/api_failure.dart';

enum WorkSessionFailureKind {
  authRejected,
  businessRejected,
  rateLimited,
  network,
  server,
  unknown,
}

class WorkSessionFailure {
  const WorkSessionFailure({
    required this.kind,
    required this.status,
    required this.code,
    required this.context,
    required this.requestId,
    required this.displayFallback,
  });

  final WorkSessionFailureKind kind;
  final int? status;
  final String? code;
  final Map<String, dynamic> context;
  final String? requestId;

  /// Display-only evidence. Never use this value for branching.
  final String? displayFallback;

  bool get isAmbiguousMutation =>
      kind == WorkSessionFailureKind.network ||
      kind == WorkSessionFailureKind.server ||
      kind == WorkSessionFailureKind.unknown;

  factory WorkSessionFailure.fromDioException(DioException error) {
    return WorkSessionFailure.fromApiFailure(error.apiFailure);
  }

  factory WorkSessionFailure.fromApiFailure(ApiFailure failure) {
    final status = failure.status;
    final WorkSessionFailureKind kind;

    if (status == 401 || status == 403) {
      kind = WorkSessionFailureKind.authRejected;
    } else if (status == 429) {
      kind = WorkSessionFailureKind.rateLimited;
    } else if (failure.kind == ApiFailureKind.serverResponse &&
        status != null &&
        status >= 400 &&
        status < 500) {
      kind = WorkSessionFailureKind.businessRejected;
    } else if (failure.kind == ApiFailureKind.serverResponse &&
        status != null &&
        status >= 500) {
      kind = WorkSessionFailureKind.server;
    } else if (failure.kind == ApiFailureKind.connection ||
        failure.kind == ApiFailureKind.timeout ||
        failure.kind == ApiFailureKind.cancelled) {
      kind = WorkSessionFailureKind.network;
    } else {
      kind = WorkSessionFailureKind.unknown;
    }

    return WorkSessionFailure(
      kind: kind,
      status: status,
      code: failure.code,
      context: failure.context,
      requestId: failure.requestId,
      displayFallback: failure.displayFallback,
    );
  }

  const WorkSessionFailure.unknown()
      : kind = WorkSessionFailureKind.unknown,
        status = null,
        code = null,
        context = const <String, dynamic>{},
        requestId = null,
        displayFallback = null;
}
