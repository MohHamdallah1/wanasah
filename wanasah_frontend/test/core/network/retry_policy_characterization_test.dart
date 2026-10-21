import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/network/retry_policy.dart';

DioException rateLimitError(
  String method, {
  bool alreadyRetried = false,
  String? retryAfter,
}) {
  final request = RequestOptions(
    path: '/resource',
    method: method,
    headers: {
      if (alreadyRetried) RetryPolicy.retryAttemptHeader: 'true',
    },
  );

  return DioException(
    requestOptions: request,
    response: Response<dynamic>(
      requestOptions: request,
      statusCode: 429,
      headers: Headers.fromMap({
        if (retryAfter != null) 'retry-after': [retryAfter],
      }),
    ),
    type: DioExceptionType.badResponse,
  );
}

void main() {
  group('RetryPolicy current behavior characterization', () {
    test('429 auto retry currently applies to reads and mutations', () {
      final policy = RetryPolicy();

      expect(
        policy.shouldAutoRetryRateLimit(rateLimitError('GET')),
        isTrue,
      );
      expect(
        policy.shouldAutoRetryRateLimit(rateLimitError('POST')),
        isTrue,
      );
      expect(
        policy.shouldAutoRetryRateLimit(rateLimitError('PUT')),
        isTrue,
      );
    });

    test('retry marker prevents a second automatic retry', () {
      final policy = RetryPolicy();

      expect(
        policy.shouldAutoRetryRateLimit(
          rateLimitError('GET', alreadyRetried: true),
        ),
        isFalse,
      );
    });

    test('retry-after is bounded before jitter is applied', () {
      final policy = RetryPolicy();

      final low = policy.rateLimitDelay(
        rateLimitError('GET', retryAfter: '0'),
      );
      final high = policy.rateLimitDelay(
        rateLimitError('GET', retryAfter: '120'),
      );

      expect(low.inSeconds, inInclusiveRange(1, 3));
      expect(high.inSeconds, inInclusiveRange(30, 32));
    });
  });
}
