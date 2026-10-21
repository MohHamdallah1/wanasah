import 'dart:convert';
import 'dart:io';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/network/auth_interceptor.dart';
import 'package:wanasah_frontend/core/network/auth_token_store.dart';

class _MemoryTokenStore implements AuthTokenStore {
  _MemoryTokenStore({
    required String accessToken,
    required String refreshToken,
  }) : _accessToken = accessToken,
       _refreshToken = refreshToken;

  String? _accessToken;
  String? _refreshToken;
  int clearCalls = 0;

  @override
  Future<String?> readAccessToken() async => _accessToken;

  @override
  Future<String?> readRefreshToken() async => _refreshToken;

  @override
  Future<void> persistReplacement({
    required String accessToken,
    required String refreshToken,
  }) async {
    _refreshToken = refreshToken;
    _accessToken = accessToken;
  }

  @override
  Future<void> clear() async {
    clearCalls++;
    _accessToken = null;
    _refreshToken = null;
  }
}

class _CallbackAdapter implements HttpClientAdapter {
  _CallbackAdapter(this.callback);

  final Future<ResponseBody> Function(RequestOptions options) callback;

  @override
  Future<ResponseBody> fetch(
    RequestOptions options,
    Stream<Uint8List>? requestStream,
    Future<void>? cancelFuture,
  ) {
    return callback(options);
  }

  @override
  void close({bool force = false}) {}
}

ResponseBody jsonResponse(int status, Map<String, dynamic> data) {
  return ResponseBody.fromString(
    jsonEncode(data),
    status,
    headers: <String, List<String>>{
      Headers.contentTypeHeader: <String>[Headers.jsonContentType],
    },
  );
}

Map<String, dynamic> canonicalError(
  int status, {
  String code = 'HTTP_ERROR',
}) {
  return <String, dynamic>{
    'request_id': 'req-$status',
    'error': <String, dynamic>{
      'code': code,
      'message': 'display fallback only',
      'context': <String, dynamic>{},
      'request_id': 'req-$status',
    },
  };
}

Dio protectedDio({
  required _MemoryTokenStore tokenStore,
  required Dio refreshDio,
  required void Function() onUnauthorized,
}) {
  final dio = Dio(BaseOptions(baseUrl: 'https://example.test'));
  dio.httpClientAdapter = _CallbackAdapter(
    (options) async => jsonResponse(401, canonicalError(401)),
  );
  dio.interceptors.add(
    AuthInterceptor(
      onUnauthorized: onUnauthorized,
      dio: dio,
      tokenStore: tokenStore,
      refreshDioFactory: () => refreshDio,
    ),
  );
  return dio;
}

void main() {
  test('ambiguous refresh 5xx does not force logout', () async {
    final tokenStore = _MemoryTokenStore(
      accessToken: 'old-access',
      refreshToken: 'old-refresh',
    );
    final refreshDio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    refreshDio.httpClientAdapter = _CallbackAdapter(
      (options) async => jsonResponse(
        503,
        canonicalError(503, code: 'SERVICE_UNAVAILABLE'),
      ),
    );

    var unauthorizedCalls = 0;
    final dio = protectedDio(
      tokenStore: tokenStore,
      refreshDio: refreshDio,
      onUnauthorized: () {
        unauthorizedCalls++;
      },
    );

    await expectLater(
      dio.get<dynamic>('/protected'),
      throwsA(
        isA<DioException>().having(
          (error) => error.response?.statusCode,
          'original status',
          401,
        ),
      ),
    );

    expect(unauthorizedCalls, 0);
    expect(tokenStore.clearCalls, 0);
    expect(await tokenStore.readAccessToken(), 'old-access');
    expect(await tokenStore.readRefreshToken(), 'old-refresh');
  });

  test('ambiguous refresh transport failure does not force logout', () async {
    final tokenStore = _MemoryTokenStore(
      accessToken: 'old-access',
      refreshToken: 'old-refresh',
    );
    final refreshDio = Dio(BaseOptions(baseUrl: 'https://example.test'));
    refreshDio.httpClientAdapter = _CallbackAdapter(
      (options) async => throw DioException(
        requestOptions: options,
        type: DioExceptionType.connectionError,
        error: 'offline',
      ),
    );

    var unauthorizedCalls = 0;
    final dio = protectedDio(
      tokenStore: tokenStore,
      refreshDio: refreshDio,
      onUnauthorized: () {
        unauthorizedCalls++;
      },
    );

    await expectLater(
      dio.get<dynamic>('/protected'),
      throwsA(isA<DioException>()),
    );

    expect(unauthorizedCalls, 0);
    expect(tokenStore.clearCalls, 0);
    expect(await tokenStore.readRefreshToken(), 'old-refresh');
  });

  test('network boundary reserves unauthorized logout for confirmed refresh rejection', () async {
    final source = await File(
      'lib/core/network/auth_interceptor.dart',
    ).readAsString();

    expect(
      source,
      contains('refreshFailure.kind == ApiFailureKind.serverResponse'),
    );
    expect(source, contains('refreshFailure.status == 401'));
    expect(source, contains('refreshFailure.status == 403'));
    expect(source, contains('onUnauthorized();'));
    expect(RegExp(r'onUnauthorized\(\);').allMatches(source).length, 1);
  });

  test('CheckAuth validates identity without destructive cleanup', () async {
    final source = await File('lib/blocs/auth/auth_bloc.dart').readAsString();
    final start = source.indexOf('Future<void> _onCheckAuth(');
    final end = source.indexOf('Future<void> _onLogin(');

    expect(start, greaterThanOrEqualTo(0));
    expect(end, greaterThan(start));

    final checkAuthSource = source.substring(start, end);
    expect(checkAuthSource, contains('StoredAuthIdentity.tryParse'));
    expect(checkAuthSource, isNot(contains('clearSessionData')));
    expect(checkAuthSource, isNot(contains('_storage.delete')));
  });

  test('user logout preserves unresolved offline evidence', () async {
    final source = await File('lib/blocs/auth/auth_bloc.dart').readAsString();
    final logoutStart = source.indexOf('Future<void> _onLogout(');
    expect(logoutStart, greaterThanOrEqualTo(0));

    final logoutSource = source.substring(logoutStart);
    expect(logoutSource, contains('await _captureOfflineOwnerBeforeLogout();'));
    expect(
      logoutSource,
      contains('clearSessionData(clearPendingSyncs: false)'),
    );
    expect(logoutSource, isNot(contains('clearPendingSyncs: true')));

    final captureIndex = logoutSource.indexOf(
      'await _captureOfflineOwnerBeforeLogout();',
    );
    final tokenDeleteIndex = logoutSource.indexOf(
      "await _storage.delete(key: 'auth_token');",
    );
    expect(tokenDeleteIndex, greaterThan(captureIndex));
  });
}
