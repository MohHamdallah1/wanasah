import 'dart:math';

import 'package:dio/dio.dart';

class RetryPolicy {
  static const String retryAttemptHeader = 'X-Retry-Attempt';

  final Random _random;

  RetryPolicy({Random? random}) : _random = random ?? Random();

  bool hasRetryAttempt(RequestOptions options) {
    return options.headers.containsKey(retryAttemptHeader);
  }

  bool shouldAutoRetryRateLimit(DioException error) {
    return error.response?.statusCode == 429 &&
        !hasRetryAttempt(error.requestOptions);
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
}
