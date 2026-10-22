import 'dart:async';
import 'dart:convert';
import 'dart:typed_data';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/network/auth_interceptor.dart';
import 'package:wanasah_frontend/core/network/auth_token_store.dart';

class _MemoryTokenStore implements AuthTokenStore {
  _MemoryTokenStore({
    String? accessToken,
    String? refreshToken,
  }) : _accessToken = accessToken,
       _refreshToken = refreshToken;

  String? _accessToken;
  String? _refreshToken;
  int persistCalls = 0;

  String? get accessToken => _accessToken;
  String? get refreshToken => _refreshToken;

  @override
  Future<String?> readAccessToken() async => _accessToken;

  @override
  Future<String?> readRefreshToken() async => _refreshToken;

  @override
  Future<void> persistReplacement({
    required String accessToken,
    required String refreshToken,
  }) async {
    persistCalls++;
    _refreshToken = refreshToken;
    _accessToken = accessToken;
  }

  @override
  Future<void> clear() async {
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

ResponseBody jsonResponse(
  int status,
  Map<String, dynamic> data,
) {
  return ResponseBody.fromString(
    jsonEncode(data),
    status,
    headers: <String, List<String>>{
      Headers.contentTypeHeader: <String>[
        Headers.jsonContentType,
      ],
    },
  );
}

Map<String, dynamic> authErrorBody() {
  return <String, dynamic>{
    'request_id': 'req-auth',
    'error': <String, dynamic>{
      'code': 'HTTP_401',
      'message': 'Authentication failed.',
      'context': <String, dynamic>{},
      'request_id': 'req-auth',
    },
  };
}

void main() {
  test('concurrent confirmed 401 responses share one refresh', () async {
    final tokenStore = _MemoryTokenStore(
      accessToken: 'old-access',
      refreshToken: 'old-refresh',
    );

    final refreshStarted = Completer<void>();
    final allowRefresh = Completer<void>();
    int refreshCalls = 0;

    final refreshDio = Dio(
      BaseOptions(baseUrl: 'https://example.test'),
    );
    refreshDio.httpClientAdapter = _CallbackAdapter(
      (options) async {
        refreshCalls++;
        if (!refreshStarted.isCompleted) {
          refreshStarted.complete();
        }
        await allowRefresh.future;
        return jsonResponse(
          200,
          <String, dynamic>{
            'token': 'new-access',
            'refresh_token': 'new-refresh',
          },
        );
      },
    );

    int protectedCalls = 0;
    final dio = Dio(
      BaseOptions(baseUrl: 'https://example.test'),
    );
    dio.httpClientAdapter = _CallbackAdapter(
      (options) async {
        protectedCalls++;
        if (options.headers['Authorization'] ==
            'Bearer new-access') {
          return jsonResponse(
            200,
            <String, dynamic>{'ok': true},
          );
        }
        return jsonResponse(401, authErrorBody());
      },
    );

    bool unauthorizedCalled = false;
    dio.interceptors.add(
      AuthInterceptor(
        onUnauthorized: () {
          unauthorizedCalled = true;
        },
        dio: dio,
        tokenStore: tokenStore,
        refreshDioFactory: () => refreshDio,
      ),
    );

    final first = dio.get<dynamic>('/protected');
    final second = dio.get<dynamic>('/protected');

    await refreshStarted.future;
    allowRefresh.complete();

    final responses = await Future.wait(
      <Future<Response<dynamic>>>[first, second],
    );

    expect(responses.every((response) => response.statusCode == 200), isTrue);
    expect(refreshCalls, 1);
    expect(protectedCalls, 4);
    expect(tokenStore.persistCalls, 1);
    expect(tokenStore.accessToken, 'new-access');
    expect(tokenStore.refreshToken, 'new-refresh');
    expect(unauthorizedCalled, isFalse);
  });

  test('401 on authentication path does not recursively refresh', () async {
    final tokenStore = _MemoryTokenStore(
      accessToken: 'old-access',
      refreshToken: 'old-refresh',
    );

    final dio = Dio(
      BaseOptions(baseUrl: 'https://example.test'),
    );
    dio.httpClientAdapter = _CallbackAdapter(
      (options) async => jsonResponse(
        401,
        authErrorBody(),
      ),
    );

    int refreshFactoryCalls = 0;
    dio.interceptors.add(
      AuthInterceptor(
        onUnauthorized: () {},
        dio: dio,
        tokenStore: tokenStore,
        refreshDioFactory: () {
          refreshFactoryCalls++;
          return Dio(
            BaseOptions(
              baseUrl: 'https://example.test',
            ),
          );
        },
      ),
    );

    await expectLater(
      dio.post<dynamic>(
        '/refresh',
        data: <String, dynamic>{
          'refresh_token': 'old-refresh',
        },
      ),
      throwsA(isA<DioException>()),
    );

    expect(refreshFactoryCalls, 0);
    expect(tokenStore.persistCalls, 0);
  });
}
