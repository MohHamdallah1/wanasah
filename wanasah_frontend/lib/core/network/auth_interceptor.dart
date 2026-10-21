import 'dart:async';
import 'dart:developer' as developer;

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../services/api_constants.dart';
import '../db/local_database.dart';
import 'retry_policy.dart';

// -----------------------------------------------------------------------
// AuthInterceptor
// المهمة: قراءة auth_token وحقنه في كل طلب، والتعامل مع 401 عبر التجديد الصامت
// -----------------------------------------------------------------------
class AuthInterceptor extends Interceptor {
  final FlutterSecureStorage _storage;
  final VoidCallback onUnauthorized;
  final Dio _dio;
  final RetryPolicy _retryPolicy;

  // +++ الدرع المعماري: إدارة تزامن التجديد عبر Completer لمنع تضارب الطلبات المتزامنة +++
  Completer<bool>? _refreshCompleter;

  AuthInterceptor({
    required this.onUnauthorized,
    required Dio dio,
    FlutterSecureStorage? storage,
  }) : _storage = storage ?? const FlutterSecureStorage(),
       _dio = dio,
       _retryPolicy = RetryPolicy();

  // --- حقن التوكن في كل طلب ---
  @override
  Future<void> onRequest(
    RequestOptions options,
    RequestInterceptorHandler handler,
  ) async {
    try {
      final String? token = await _storage.read(key: 'auth_token');

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
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    // +++ H-4: درع اللوب اللانهائي (منع إعادة الطلب أكثر من مرة) +++
    if (_retryPolicy.hasRetryAttempt(err.requestOptions)) {
      return handler.next(err);
    }

    // +++ H-1: امتصاص درع الـ 429 + Jitter عشوائي لكسر الهجوم المتزامن +++
    if (_retryPolicy.shouldAutoRetryRateLimit(err)) {
      final delay = _retryPolicy.rateLimitDelay(err);

      developer.log(
        '[AuthInterceptor] 429 Hit. Backing off for ${delay.inSeconds} seconds...',
      );
      await Future.delayed(delay);
      _retryPolicy.markRetryAttempt(err.requestOptions);
      return _retryRequest(err.requestOptions, handler);
    }

    if (err.response?.statusCode == 401) {
      final isAuthPath = err.requestOptions.path.endsWith('/login') ||
          err.requestOptions.path.endsWith('/driver/login') ||
          err.requestOptions.path.endsWith('/refresh');

      if (!isAuthPath) {
        // إذا كان هناك طلب تجديد قيد التنفيذ بالفعل، ننتظر انتهاءه بدقة
        if (_refreshCompleter != null) {
          final success = await _refreshCompleter!.future;
          if (success) {
            return _retryRequest(err.requestOptions, handler);
          } else {
            return handler.next(err);
          }
        }

        _refreshCompleter = Completer<bool>();

        try {
          final refreshToken = await _storage.read(key: 'refresh_token');
          if (refreshToken != null && refreshToken.isNotEmpty) {
            developer.log('[AuthInterceptor] Attempting silent token refresh...');

            // +++ استخدام محرك Dio منفصل لكن بوراثة صارمة للمهلات الزمنية الأساسية لمنع التعليق اللانهائي +++
            final refreshDio = Dio(
              _dio.options.copyWith(baseUrl: ApiConstants.baseUrl),
            );
            final response = await refreshDio.post(
              '/refresh',
              data: {'refresh_token': refreshToken},
              options: Options(
                headers: {'Content-Type': 'application/json'},
              ),
            );

            final newAccessToken = response.data['token'];
            final newRefreshToken = response.data['refresh_token'];

            if (newAccessToken != null) {
              await _storage.write(
                key: 'auth_token',
                value: newAccessToken,
              );
              if (newRefreshToken != null) {
                await _storage.write(
                  key: 'refresh_token',
                  value: newRefreshToken,
                );
              }
              _refreshCompleter!.complete(true);
              _refreshCompleter = null;

              _retryPolicy.markRetryAttempt(err.requestOptions);
              return _retryRequest(err.requestOptions, handler);
            }
          }
        } on DioException catch (e) {
          // +++ حصر الطرد في الرفض الصريح فقط (401/403) +++
          if (e.response?.statusCode == 401 ||
              e.response?.statusCode == 403) {
            developer.log(
              '[AuthInterceptor] Token permanently rejected → Triggering logout',
            );

            // +++ استخدام محرك Dio موحد بمهلات زمنية للحرق الأمني للتوكن (Fire-and-forget) +++
            try {
              final oldRefresh =
                  await _storage.read(key: 'refresh_token');
              if (oldRefresh != null) {
                Dio(
                  _dio.options.copyWith(baseUrl: ApiConstants.baseUrl),
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

            await _storage.delete(key: 'auth_token');
            await _storage.delete(key: 'refresh_token');
            await LocalDatabase.instance.clearSessionData(
              clearPendingSyncs: false,
            );
            onUnauthorized();
            return handler.next(err); // إنهاء الـ Flow
          } else {
            developer.log(
              '[AuthInterceptor] Network/Server Error, avoiding force logout.',
            );
          }
        } catch (e) {
          developer.log(
            '[AuthInterceptor] Unknown error, keeping session intact: $e',
          );
        } finally {
          // إنهاء الـ Completer بأمان تام في كل الحالات
          if (!(_refreshCompleter?.isCompleted ?? true)) {
            _refreshCompleter?.complete(false);
          }
          _refreshCompleter = null;
        }

        // إذا فشلنا بس مش 401/403، منرجع الخطأ زي ما هو عشان الـ UI يتعامل معاه
        return handler.next(err);
      }
    }
    return handler.next(err);
  }

  // إعادة إرسال الطلب بعد تجديد التوكن
  Future<void> _retryRequest(
    RequestOptions requestOptions,
    ErrorInterceptorHandler handler,
  ) async {
    try {
      final token = await _storage.read(key: 'auth_token');
      // +++ استخدام copyWith لنسخ FormData وكل الخصائص المخفية +++
      final newOptions = requestOptions.copyWith(
        headers: Map<String, dynamic>.from(requestOptions.headers)
          ..['Authorization'] = 'Bearer $token',
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
}
