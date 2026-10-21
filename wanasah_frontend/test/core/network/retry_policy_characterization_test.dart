import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/network/retry_policy.dart';

DioException responseError(
  String method,
  int statusCode, {
  String path = '/resource',
  bool alreadyRetried = false,
  String? retryAfter,
}) {
  final request = RequestOptions(
    path: path,
    method: method,
    headers: {
      if (alreadyRetried) RetryPolicy.retryAttemptHeader: 'true',
    },
  );

  return DioException(
    requestOptions: request,
    response: Response<dynamic>(
      requestOptions: request,
      statusCode: statusCode,
      headers: Headers.fromMap({
        if (retryAfter != null) 'retry-after': [retryAfter],
      }),
    ),
    type: DioExceptionType.badResponse,
  );
}

void main() {
  group('RetryPolicy V1 behavior', () {
    test('429 auto retry is limited to safe reads', () {
      final policy = RetryPolicy();

      for (final method in <String>['GET', 'HEAD', 'OPTIONS']) {
        expect(
          policy.shouldAutoRetryRateLimit(
            responseError(method, 429),
          ),
          isTrue,
          reason: '$method should be safe for bounded transport retry',
        );
      }

      for (final method in <String>[
        'POST',
        'PUT',
        'PATCH',
        'DELETE',
      ]) {
        expect(
          policy.shouldAutoRetryRateLimit(
            responseError(method, 429),
          ),
          isFalse,
          reason: '$method must be reconciled by its operation layer',
        );
      }
    });

    test('retry marker prevents a second automatic retry', () {
      final policy = RetryPolicy();

      expect(
        policy.shouldAutoRetryRateLimit(
          responseError(
            'GET',
            429,
            alreadyRetried: true,
          ),
        ),
        isFalse,
      );
      expect(
        policy.shouldAttemptAuthRefresh(
          responseError(
            'GET',
            401,
            alreadyRetried: true,
          ),
        ),
        isFalse,
      );
    });

    test('401 auth endpoints never recursively refresh', () {
      final policy = RetryPolicy();

      for (final path in <String>[
        '/login',
        '/driver/login',
        '/refresh',
        '/logout',
      ]) {
        expect(
          policy.shouldAttemptAuthRefresh(
            responseError('POST', 401, path: path),
          ),
          isFalse,
          reason: '$path must not recurse into refresh',
        );
      }

      expect(
        policy.shouldAttemptAuthRefresh(
          responseError(
            'PUT',
            401,
            path: '/visits/123',
          ),
        ),
        isTrue,
      );
    });

    test('retry-after remains bounded before jitter is applied', () {
      final policy = RetryPolicy();

      final low = policy.rateLimitDelay(
        responseError(
          'GET',
          429,
          retryAfter: '0',
        ),
      );
      final high = policy.rateLimitDelay(
        responseError(
          'GET',
          429,
          retryAfter: '120',
        ),
      );

      expect(low.inSeconds, inInclusiveRange(1, 3));
      expect(high.inSeconds, inInclusiveRange(30, 32));
    });
  });
}
