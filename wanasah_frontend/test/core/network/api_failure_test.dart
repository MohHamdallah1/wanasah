import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';

DioException dioFailure({
  required int status,
  required dynamic data,
  Map<String, List<String>> headers = const <String, List<String>>{},
}) {
  final request = RequestOptions(
    path: '/resource',
    method: 'GET',
  );

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
  group('ApiFailure canonical envelope', () {
    test('parses status, code, message, context and nested request id', () {
      final failure = dioFailure(
        status: 409,
        data: <String, dynamic>{
          'request_id': 'top-level-id',
          'error': <String, dynamic>{
            'code': 'VISIT_STATE_CONFLICT',
            'message': 'Safe display reason',
            'context': <String, dynamic>{
              'visit_id': 41,
              'state': 'Completed',
            },
            'request_id': 'nested-id',
          },
        },
        headers: <String, List<String>>{
          'X-Request-Id': <String>['header-id'],
        },
      ).apiFailure;

      expect(failure.kind, ApiFailureKind.serverResponse);
      expect(failure.status, 409);
      expect(failure.code, 'VISIT_STATE_CONFLICT');
      expect(failure.message, 'Safe display reason');
      expect(
        failure.context,
        <String, dynamic>{
          'visit_id': 41,
          'state': 'Completed',
        },
      );
      expect(failure.requestId, 'nested-id');
      expect(failure.hasStructuredCode, isTrue);
    });

    test('falls back from top-level request id to response header', () {
      final topLevel = dioFailure(
        status: 400,
        data: <String, dynamic>{
          'request_id': 'top-level-id',
          'error': <String, dynamic>{
            'code': 'BAD_INPUT',
            'message': 'Bad input',
            'context': <String, dynamic>{},
          },
        },
        headers: <String, List<String>>{
          'X-Request-Id': <String>['header-id'],
        },
      ).apiFailure;

      final headerOnly = dioFailure(
        status: 500,
        data: <String, dynamic>{
          'error': <String, dynamic>{
            'code': 'INTERNAL_SERVER_ERROR',
            'message': 'Unexpected',
            'context': <String, dynamic>{},
          },
        },
        headers: <String, List<String>>{
          'X-Request-Id': <String>['header-only-id'],
        },
      ).apiFailure;

      expect(topLevel.requestId, 'top-level-id');
      expect(headerOnly.requestId, 'header-only-id');
    });

    test('free-text fallback never becomes business classification', () {
      final legacyMap = dioFailure(
        status: 403,
        data: <String, dynamic>{
          'message': 'تمت تسويتها',
        },
      ).apiFailure;

      final rawText = dioFailure(
        status: 500,
        data: 'temporary upstream failure',
      ).apiFailure;

      expect(legacyMap.code, isNull);
      expect(legacyMap.hasStructuredCode, isFalse);
      expect(legacyMap.context, isEmpty);
      expect(legacyMap.displayFallback, 'تمت تسويتها');

      expect(rawText.code, isNull);
      expect(rawText.hasStructuredCode, isFalse);
      expect(
        rawText.displayFallback,
        'temporary upstream failure',
      );
    });

    test('classifies network and timeout failures without server text', () {
      final request = RequestOptions(path: '/resource');

      final network = DioException(
        requestOptions: request,
        type: DioExceptionType.connectionError,
      ).apiFailure;
      final timeout = DioException(
        requestOptions: request,
        type: DioExceptionType.receiveTimeout,
      ).apiFailure;

      expect(network.kind, ApiFailureKind.connection);
      expect(network.status, isNull);
      expect(network.code, isNull);

      expect(timeout.kind, ApiFailureKind.timeout);
      expect(timeout.status, isNull);
      expect(timeout.code, isNull);
    });
  });
}
