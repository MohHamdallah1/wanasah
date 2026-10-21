import 'package:dio/dio.dart';

import '../../../core/network/api_failure.dart';

enum AuthLoginFailureKind {
  authRejected,
  rateLimited,
  connectivity,
  serverFailure,
  requestRejected,
  cancelled,
  unexpected,
}

class AuthLoginFailure {
  const AuthLoginFailure({
    required this.kind,
    required this.status,
    required this.code,
    required this.context,
    required this.requestId,
    required this.displayFallback,
  });

  final AuthLoginFailureKind kind;
  final int? status;
  final String? code;
  final Map<String, dynamic> context;
  final String? requestId;
  final String? displayFallback;

  factory AuthLoginFailure.fromDioException(DioException error) {
    final failure = error.apiFailure;
    final status = failure.status;

    AuthLoginFailureKind kind;
    if (failure.kind == ApiFailureKind.connection ||
        failure.kind == ApiFailureKind.timeout) {
      kind = AuthLoginFailureKind.connectivity;
    } else if (failure.kind == ApiFailureKind.cancelled) {
      kind = AuthLoginFailureKind.cancelled;
    } else if (failure.kind == ApiFailureKind.serverResponse) {
      if (status == 401 || status == 403) {
        kind = AuthLoginFailureKind.authRejected;
      } else if (status == 429) {
        kind = AuthLoginFailureKind.rateLimited;
      } else if (status != null && status >= 500) {
        kind = AuthLoginFailureKind.serverFailure;
      } else if (status != null && status >= 400) {
        kind = AuthLoginFailureKind.requestRejected;
      } else {
        kind = AuthLoginFailureKind.unexpected;
      }
    } else {
      kind = AuthLoginFailureKind.unexpected;
    }

    return AuthLoginFailure(
      kind: kind,
      status: status,
      code: failure.code,
      context: failure.context,
      requestId: failure.requestId,
      displayFallback: failure.displayFallback,
    );
  }
}
