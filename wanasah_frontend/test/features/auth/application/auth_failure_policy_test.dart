import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/auth/application/auth_failure_policy.dart';
import 'package:wanasah_frontend/features/auth/presentation/auth_messages.dart';

DioException responseFailure(
  int status, {
  dynamic data,
  Map<String, List<String>> headers = const <String, List<String>>{},
}) {
  final request = RequestOptions(path: '/driver/login', method: 'POST');
  return DioException(
    requestOptions: request,
    response: Response<dynamic>(
      requestOptions: request,
      statusCode: status,
      data: data,
      headers: Headers.fromMap(headers),
    ),
    type: DioExceptionType.badResponse,
  );
}

void main() {
  group('AuthLoginFailure', () {
    test('401 and 403 are confirmed authentication rejection', () {
      for (final status in <int>[401, 403]) {
        final failure = AuthLoginFailure.fromDioException(
          responseFailure(
            status,
            data: <String, dynamic>{
              'message': 'localized display text must not classify',
            },
          ),
        );

        expect(failure.kind, AuthLoginFailureKind.authRejected);
        expect(
          authLoginFailureMessage(failure),
          isNot(contains('localized display text must not classify')),
        );
      }
    });

    test('429 is rate limit and never bad credentials', () {
      final failure = AuthLoginFailure.fromDioException(
        responseFailure(
          429,
          data: <String, dynamic>{
            'request_id': 'req-rate',
            'error': <String, dynamic>{
              'code': 'RATE_LIMITED',
              'message': 'server localized fallback',
              'context': <String, dynamic>{'retry_after': 7},
              'request_id': 'req-rate',
            },
          },
        ),
      );

      expect(failure.kind, AuthLoginFailureKind.rateLimited);
      expect(failure.code, 'RATE_LIMITED');
      expect(failure.context, <String, dynamic>{'retry_after': 7});
      expect(failure.requestId, 'req-rate');
      expect(
        authLoginFailureMessage(failure),
        contains('حد محاولات تسجيل الدخول'),
      );
    });

    test('network and timeout failures are connectivity failures', () {
      final request = RequestOptions(path: '/driver/login', method: 'POST');

      for (final type in <DioExceptionType>[
        DioExceptionType.connectionError,
        DioExceptionType.connectionTimeout,
        DioExceptionType.sendTimeout,
        DioExceptionType.receiveTimeout,
      ]) {
        final failure = AuthLoginFailure.fromDioException(
          DioException(requestOptions: request, type: type),
        );
        expect(failure.kind, AuthLoginFailureKind.connectivity);
      }
    });

    test('5xx is server failure and keeps correlation id', () {
      final failure = AuthLoginFailure.fromDioException(
        responseFailure(
          503,
          data: <String, dynamic>{
            'error': <String, dynamic>{
              'code': 'SERVICE_UNAVAILABLE',
              'message': 'internal text must stay hidden',
              'context': <String, dynamic>{'component': 'auth'},
            },
          },
          headers: <String, List<String>>{
            'X-Request-Id': <String>['req-server'],
          },
        ),
      );

      expect(failure.kind, AuthLoginFailureKind.serverFailure);
      expect(failure.code, 'SERVICE_UNAVAILABLE');
      expect(failure.context, <String, dynamic>{'component': 'auth'});
      expect(failure.requestId, 'req-server');

      final shown = authLoginFailureMessage(failure);
      expect(shown, contains('req-server'));
      expect(shown, isNot(contains('internal text must stay hidden')));
    });

    test('free text remains display fallback, never business classification', () {
      final failure = AuthLoginFailure.fromDioException(
        responseFailure(
          409,
          data: <String, dynamic>{'message': 'عرض للمستخدم فقط'},
        ),
      );

      expect(failure.kind, AuthLoginFailureKind.requestRejected);
      expect(failure.code, isNull);
      expect(failure.context, isEmpty);
      expect(failure.displayFallback, 'عرض للمستخدم فقط');
      expect(authLoginFailureMessage(failure), 'عرض للمستخدم فقط');
    });
  });
}
