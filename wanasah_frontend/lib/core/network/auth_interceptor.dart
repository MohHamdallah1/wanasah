import 'dart:async';
import 'dart:developer' as developer;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../services/api_constants.dart';
import '../db/local_database.dart';
import 'api_failure.dart';
import 'auth_token_store.dart';
import 'retry_policy.dart';

// -----------------------------------------------------------------------
// AuthInterceptor
// Injects bearer credentials and performs the narrowly-scoped network retries
// owned by transport: safe-read 429 retry and confirmed pre-handler 401 refresh.
// -----------------------------------------------------------------------
class AuthInterceptor extends Interceptor {
  AuthInterceptor({
    required this.onUnauthorized,
    required Dio dio,
    FlutterSecureStorage? storage,
    AuthTokenStore? tokenStore,
    Dio Function()? refreshDioFactory,
    RetryPolicy? retryPolicy,
    Future<void> Function()? clearRejectedSessionData,
  }) : _tokenStore =
           tokenStore ?? SecureAuthTokenStore(storage: storage),
       _dio = dio,
       _refreshDioFactory = refreshDioFactory,
       _retryPolicy = retryPolicy ?? RetryPolicy(),
       _clearRejectedSessionData = clearRejectedSessionData ??
         (() => LocalDatabase.instance.clearSessionData(clearPendingSyncs: false));

  final AuthTokenStore _tokenStore;
  final VoidCallback onUnauthorized;
  final Dio _dio;
  final Dio Function()? _refreshDioFactory;
  final RetryPolicy _retryPolicy;
  final Future<void> Function() _clearRejectedSessionData;

  Completer<bool>? _refreshCompleter;

  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    try {
      final token = await _tokenStore.readAccessToken();

      if (token != null && token.isNotEmpty) {
        options.headers['Authorization'] = 'Bearer $token';
        developer.log(
          '[AuthInterceptor] Token injected → ${options.method} ${options.path}',
        );
      } else {
        developer.log(
          '[AuthInterceptor] No token found → ${options.method} ${options.path}',
        );
      }
    } catch (e) {
      developer.log('[AuthInterceptor] Error reading token: $e');
    }

    return handler.next(options);
  }

  @override
  void onError(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    if (_retryPolicy.hasRetryAttempt(err.requestOptions)) {
      return handler.next(err);
    }

    if (_retryPolicy.shouldAutoRetryRateLimit(err)) {
      final delay = _retryPolicy.rateLimitDelay(err);
      developer.log(
        '[AuthInterceptor] Safe-read 429. Backing off for '
        '${delay.inSeconds} seconds...',
      );
      await Future.delayed(delay);
      _retryPolicy.markRetryAttempt(err.requestOptions);
      return _retryRequest(err.requestOptions, handler);
    }

    if (_retryPolicy.shouldAttemptAuthRefresh(err)) {
      return _handleConfirmedUnauthorized(err, handler);
    }

    return handler.next(err);
  }

  Future<void> _handleConfirmedUnauthorized(
    DioException err,
    ErrorInterceptorHandler handler,
  ) async {
    // A concurrent request can receive its old-token 401 just after another
    // request has already rotated credentials. In that case reuse the freshly
    // persisted access token instead of rotating the refresh token again.
    final currentAccessToken = await _tokenStore.readAccessToken();
    final requestAuthorization =
        err.requestOptions.headers['Authorization']?.toString();
    if (currentAccessToken != null &&
        currentAccessToken.isNotEmpty &&
        requestAuthorization != null &&
        requestAuthorization != 'Bearer $currentAccessToken') {
      _retryPolicy.markRetryAttempt(err.requestOptions);
      return _retryRequest(err.requestOptions, handler);
    }

    final existingRefresh = _refreshCompleter;
    if (existingRefresh != null) {
      final success = await existingRefresh.future;
      if (success) {
        _retryPolicy.markRetryAttempt(err.requestOptions);
        return _retryRequest(err.requestOptions, handler);
      }
      return handler.next(err);
    }

    final refreshCompleter = Completer<bool>();
    _refreshCompleter = refreshCompleter;

    String? attemptedRefreshToken;
    try {
      final refreshToken = await _tokenStore.readRefreshToken();
      attemptedRefreshToken = refreshToken;
      if (refreshToken == null || refreshToken.isEmpty) {
        return handler.next(err);
      }

      developer.log('[AuthInterceptor] Attempting single-flight token refresh...');

      final refreshDio = _refreshDioFactory?.call() ??
          Dio(
            _dio.options.copyWith(
              baseUrl: ApiConstants.baseUrl,
            ),
          );

      final response = await refreshDio.post(
        '/refresh',
        data: {'refresh_token': refreshToken},
        options: Options(
          headers: {'Content-Type': 'application/json'},
        ),
      );

      final data = response.data;
      final newAccessToken =
          data is Map ? _nonEmptyToken(data['token']) : null;
      final newRefreshToken =
          data is Map ? _nonEmptyToken(data['refresh_token']) : null;

      if (newAccessToken == null || newRefreshToken == null) {
        developer.log(
          '[AuthInterceptor] Refresh response missing replacement token pair.',
        );
        return handler.next(err);
      }

      final persisted = await _tokenStore.persistReplacementIfCurrent(
        expectedRefreshToken: refreshToken,
        accessToken: newAccessToken,
        refreshToken: newRefreshToken,
      );
      if (!persisted) return handler.next(err);

      refreshCompleter.complete(true);
      _retryPolicy.markRetryAttempt(err.requestOptions);
      return _retryRequest(err.requestOptions, handler);
    } on DioException catch (refreshError) {
      final refreshFailure = refreshError.apiFailure;

      // A server-confirmed 401/403 from the refresh endpoint is an
      // authentication rejection. Network, timeout and 5xx outcomes are not
      // proof that the local session should be destroyed.
      if (refreshFailure.kind == ApiFailureKind.serverResponse &&
          (refreshFailure.status == 401 ||
              refreshFailure.status == 403)) {
        if (attemptedRefreshToken == null ||
            await _tokenStore.readRefreshToken() != attemptedRefreshToken) {
          return handler.next(err);
        }
        developer.log(
          '[AuthInterceptor] Refresh credential rejected → logging out.',
        );

        try {
          final oldRefresh = attemptedRefreshToken;
          if (oldRefresh.isNotEmpty) {
            Dio(
              _dio.options.copyWith(
                baseUrl: ApiConstants.baseUrl,
              ),
            )
                .post(
                  '/logout',
                  options: Options(
                    headers: {'X-Refresh-Token': oldRefresh},
                  ),
                )
                .ignore();
          }
        } catch (_) {}

        // Rejection is confirmed even if local cleanup refuses to clear caches
        // protected by pending evidence. Neither failure permits evidence loss.
        try {
          if (!await _tokenStore.clearIfCurrent(attemptedRefreshToken)) {
            return handler.next(err);
          }
        } catch (_) { developer.log('[AuthInterceptor] Rejected credential cleanup failed.'); }
        try { await _clearRejectedSessionData(); }
        catch (_) { developer.log('[AuthInterceptor] Protected session cache retained.'); }
        final activeRefresh = await _tokenStore.readRefreshToken();
        if (activeRefresh != null && activeRefresh != attemptedRefreshToken) {
          return handler.next(err);
        }
        onUnauthorized();
      } else {
        developer.log(
          '[AuthInterceptor] Refresh result ambiguous/transient; '
          'keeping local session intact.',
        );
      }

      return handler.next(err);
    } catch (e) {
      developer.log(
        '[AuthInterceptor] Refresh failed unexpectedly; '
        'keeping local session intact: $e',
      );
      return handler.next(err);
    } finally {
      if (!refreshCompleter.isCompleted) {
        refreshCompleter.complete(false);
      }
      if (identical(_refreshCompleter, refreshCompleter)) {
        _refreshCompleter = null;
      }
    }
  }

  Future<void> _retryRequest(
    RequestOptions requestOptions,
    ErrorInterceptorHandler handler,
  ) async {
    try {
      final token = await _tokenStore.readAccessToken();
      final newOptions = requestOptions.copyWith(
        headers: Map<String, dynamic>.from(
          requestOptions.headers,
        )..['Authorization'] = 'Bearer $token',
      );

      final response = await _dio.fetch(newOptions);
      return handler.resolve(response);
    } catch (e) {
      return handler.next(
        e is DioException
            ? e
            : DioException(
                requestOptions: requestOptions,
                error: e,
              ),
      );
    }
  }

  String? _nonEmptyToken(dynamic value) {
    if (value is! String) return null;
    final trimmed = value.trim();
    return trimmed.isEmpty ? null : trimmed;
  }
}
