import 'dart:math';

import 'package:dio/dio.dart';

import 'api_failure.dart';

class RetryPolicy {
  static const String retryAttemptHeader = 'X-Retry-Attempt';
  static const Set<String> _safeReadMethods = <String>{
    'GET',
    'HEAD',
    'OPTIONS',
  };

  final Random _random;

  RetryPolicy({Random? random}) : _random = random ?? Random();

  bool hasRetryAttempt(RequestOptions options) {
    return options.headers.containsKey(retryAttemptHeader);
  }

  bool isSafeRead(RequestOptions options) {
    return _safeReadMethods.contains(options.method.toUpperCase());
  }

  bool shouldAutoRetryRateLimit(DioException error) {
    final failure = error.apiFailure;
    return failure.kind == ApiFailureKind.serverResponse &&
        failure.status == 429 &&
        isSafeRead(error.requestOptions) &&
        !hasRetryAttempt(error.requestOptions);
  }

  bool shouldAttemptAuthRefresh(DioException error) {
    final failure = error.apiFailure;
    return failure.kind == ApiFailureKind.serverResponse &&
        failure.status == 401 &&
        !hasRetryAttempt(error.requestOptions) &&
        !_isAuthenticationPath(error.requestOptions.path);
  }

  Duration rateLimitDelay(DioException error) {
    final retryAfter = error.response?.headers.value('retry-after');
    int baseDelay = num.tryParse(retryAfter ?? '')?.ceil() ?? 2;
    if (baseDelay < 1) baseDelay = 1;
    if (baseDelay > 30) baseDelay = 30;
    final jitter = _random.nextInt(3);
    return Duration(seconds: baseDelay + jitter);
  }

  void markRetryAttempt(RequestOptions options) {
    options.headers[retryAttemptHeader] = 'true';
  }

  bool _isAuthenticationPath(String rawPath) {
    final parsed = Uri.tryParse(rawPath);
    var path = (parsed?.path ?? rawPath).toLowerCase();
    if (path.length > 1 && path.endsWith('/')) {
      path = path.substring(0, path.length - 1);
    }

    return path.endsWith('/login') ||
        path.endsWith('/driver/login') ||
        path.endsWith('/refresh') ||
        path.endsWith('/logout');
  }
}
