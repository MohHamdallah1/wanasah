import 'package:dio/dio.dart';

import '../network/api_failure.dart';
import 'return_evidence.dart';

/// Carries the existing Network authority unchanged; no message-based branching.
/// Malformed successful responses remain FormatException, not server refusals.
class FieldSeamFailure implements Exception {
  const FieldSeamFailure(this.apiFailure);

  factory FieldSeamFailure.fromDioException(DioException error) =>
      FieldSeamFailure(error.apiFailure);

  final ApiFailure apiFailure;

  String? get code => apiFailure.code;
  Map<String, dynamic> get context => apiFailure.context;
  String? get requestId => apiFailure.requestId;
  ReturnAmbiguity? get returnAmbiguity =>
      ReturnAmbiguity.fromFailure(apiFailure);

  @override
  String toString() => 'FieldSeamFailure(code: $code, requestId: $requestId)';
}
