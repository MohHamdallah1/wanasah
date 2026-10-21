import 'package:dio/dio.dart';

enum ApiFailureKind {
  serverResponse,
  connection,
  timeout,
  cancelled,
  unknown,
}

/// Parsed transport failure metadata.
///
/// Stable business classification comes from [code] only. Human-readable
/// message text is retained for display/fallback purposes and must not drive
/// business decisions.
class ApiFailure {
  const ApiFailure({
    required this.kind,
    required this.status,
    required this.code,
    required this.message,
    required this.context,
    required this.requestId,
    required this.displayFallback,
  });

  final ApiFailureKind kind;
  final int? status;
  final String? code;
  final String? message;
  final Map<String, dynamic> context;
  final String? requestId;
  final String? displayFallback;

  bool get hasStructuredCode => code != null && code!.isNotEmpty;

  factory ApiFailure.fromDioException(DioException error) {
    final response = error.response;
    final data = response?.data;
    final root = _asStringKeyedMap(data);
    final structured = _asStringKeyedMap(root?['error']);

    final code = _nonEmptyString(structured?['code']);
    final canonicalMessage = _nonEmptyString(structured?['message']);
    final context =
        _asStringKeyedMap(structured?['context']) ??
        const <String, dynamic>{};

    final requestId =
        _nonEmptyString(structured?['request_id']) ??
        _nonEmptyString(root?['request_id']) ??
        _nonEmptyString(response?.headers.value('x-request-id'));

    return ApiFailure(
      kind: _kindFor(error),
      status: response?.statusCode,
      code: code,
      message: canonicalMessage,
      context: Map<String, dynamic>.unmodifiable(context),
      requestId: requestId,
      displayFallback:
          canonicalMessage ??
          _legacyDisplayFallback(data, root) ??
          _nonEmptyString(error.message),
    );
  }

  static ApiFailureKind _kindFor(DioException error) {
    if (error.response != null) {
      return ApiFailureKind.serverResponse;
    }

    switch (error.type) {
      case DioExceptionType.connectionTimeout:
      case DioExceptionType.sendTimeout:
      case DioExceptionType.receiveTimeout:
        return ApiFailureKind.timeout;
      case DioExceptionType.connectionError:
        return ApiFailureKind.connection;
      case DioExceptionType.cancel:
        return ApiFailureKind.cancelled;
      case DioExceptionType.badCertificate:
      case DioExceptionType.badResponse:
      case DioExceptionType.unknown:
        return ApiFailureKind.unknown;
    }
  }

  static String? _legacyDisplayFallback(
    dynamic data,
    Map<String, dynamic>? root,
  ) {
    if (root != null) {
      final message = _nonEmptyString(root['message']);
      if (message != null) return message;

      final detail = _nonEmptyString(root['detail']);
      if (detail != null) return detail;
    }

    return _nonEmptyString(data);
  }

  static Map<String, dynamic>? _asStringKeyedMap(dynamic value) {
    if (value is! Map) return null;

    final result = <String, dynamic>{};
    for (final entry in value.entries) {
      if (entry.key is String) {
        result[entry.key as String] = entry.value;
      }
    }
    return result;
  }

  static String? _nonEmptyString(dynamic value) {
    if (value is! String) return null;
    final trimmed = value.trim();
    return trimmed.isEmpty ? null : trimmed;
  }
}

extension DioExceptionApiFailure on DioException {
  ApiFailure get apiFailure => ApiFailure.fromDioException(this);
}
