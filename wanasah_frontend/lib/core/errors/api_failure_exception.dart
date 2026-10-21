import 'package:dio/dio.dart';

import '../network/api_failure.dart';

/// Carries the existing Network authority unchanged; no message-based branching.
/// Malformed successful responses remain FormatException, not server refusals.
class ApiFailureException implements Exception {
  const ApiFailureException(this.apiFailure);

  factory ApiFailureException.fromDioException(DioException error) =>
      ApiFailureException(error.apiFailure);

  final ApiFailure apiFailure;

  String? get code => apiFailure.code;
  Map<String, dynamic> get context => apiFailure.context;
  String? get requestId => apiFailure.requestId;

  @override
  String toString() => 'ApiFailureException(code: $code, requestId: $requestId)';
}
