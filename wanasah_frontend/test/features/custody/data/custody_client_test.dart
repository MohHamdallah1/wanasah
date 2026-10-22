import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/features/custody/custody_contracts.dart';

import '../domain/custody_fixtures.dart';

void main() {
  test('custody-only client sends exact GET, page limit and opaque cursor', () async {
    final calls = <Map<String, dynamic>>[];
    final client = CustodyClient(get: (path, {queryParameters}) async {
      calls.add({'path': path, 'query': queryParameters});
      return {
        'session_id': 33,
        'items': [custodyItemJson()],
        'next_cursor': 'opaque-next+/=',
      };
    });
    final page = await client.custody(
      query: CustodyQuery(limit: 1, cursor: 'opaque-page'),
    );
    expect(calls, [{
      'path': '/driver/custody',
      'query': {'limit': 1, 'cursor': 'opaque-page'},
    }]);
    expect(page.items.single.status, NonSellableCustodyStatus.damaged);
    expect(page.items.single.quantity, '9007199254740993.125000');
    expect(page.nextCursor, 'opaque-next+/=');
  });

  test('custody default page size stays 100 with no invented cursor', () async {
    final client = CustodyClient(get: (path, {queryParameters}) async {
      expect(path, '/driver/custody');
      expect(queryParameters, {'limit': 100});
      return {'session_id': 33, 'items': [], 'next_cursor': null};
    });
    expect((await client.custody()).items, isEmpty);
  });

  test('custody failure keeps canonical ApiFailure status, code, context and ID', () async {
    final client = CustodyClient(get: (path, {queryParameters}) async {
      final request = RequestOptions(path: path);
      throw DioException(
        requestOptions: request,
        type: DioExceptionType.badResponse,
        response: Response(
          requestOptions: request,
          statusCode: 409,
          headers: Headers.fromMap({'x-request-id': ['header-id']}),
          data: {
            'request_id': 'root-id',
            'error': {
              'code': 'FIELD_SESSION_SEALED',
              'message': 'Human display text only',
              'context': {'sealed': true, 'evidence': {'reason': 'CLOSED'}},
              'request_id': 'canonical-id',
            },
          },
        ),
      );
    });
    await expectLater(client.custody(), throwsA(isA<ApiFailureException>()
      .having((failure) => failure.apiFailure.kind, 'kind', ApiFailureKind.serverResponse)
      .having((failure) => failure.apiFailure.status, 'status', 409)
      .having((failure) => failure.code, 'code', 'FIELD_SESSION_SEALED')
      .having((failure) => failure.requestId, 'requestId', 'canonical-id')
      .having((failure) => failure.context, 'context',
        {'sealed': true, 'evidence': {'reason': 'CLOSED'}})));
  });

  test('custody preserves the existing correlation-header fallback', () async {
    final client = CustodyClient(get: (path, {queryParameters}) async {
      final request = RequestOptions(path: path);
      throw DioException(
        requestOptions: request,
        type: DioExceptionType.badResponse,
        response: Response(
          requestOptions: request,
          statusCode: 503,
          headers: Headers.fromMap({'x-request-id': ['only-header-id']}),
          data: {'error': {'code': 'TEMPORARY', 'context': {'retry': true}}},
        ),
      );
    });
    await expectLater(client.custody(), throwsA(isA<ApiFailureException>()
      .having((failure) => failure.requestId, 'requestId', 'only-header-id')
      .having((failure) => failure.code, 'code', 'TEMPORARY')
      .having((failure) => failure.context, 'context', {'retry': true})));
  });

  test('custody timeout is surfaced once without introducing a retry policy', () async {
    var sends = 0;
    final client = CustodyClient(get: (path, {queryParameters}) async {
      sends++;
      throw DioException(
        requestOptions: RequestOptions(path: path),
        type: DioExceptionType.receiveTimeout,
      );
    });
    await expectLater(client.custody(), throwsA(isA<ApiFailureException>()
      .having((failure) => failure.apiFailure.kind, 'kind', ApiFailureKind.timeout)));
    expect(sends, 1);
  });

  test('malformed custody success remains a contract failure', () async {
    final client = CustodyClient(get: (path, {queryParameters}) async => {});
    await expectLater(client.custody(), throwsFormatException);
  });
}
