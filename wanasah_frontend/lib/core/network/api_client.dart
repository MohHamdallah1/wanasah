// File: lib/core/network/api_client.dart

import 'dart:async';
import 'dart:math';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:developer' as developer;

import '../../services/api_constants.dart';
import '../db/local_database.dart';

// -----------------------------------------------------------------------
// AuthInterceptor
// المهمة: قراءة auth_token وحقنه في كل طلب، والتعامل مع 401 عبر التجديد الصامت
// -----------------------------------------------------------------------
class AuthInterceptor extends Interceptor {
  final FlutterSecureStorage _storage;
  final VoidCallback onUnauthorized;
  final Dio _dio;

  // +++ الدرع المعماري: إدارة تزامن التجديد عبر Completer لمنع تضارب الطلبات المتزامنة +++
  Completer<bool>? _refreshCompleter;

  AuthInterceptor({
    required this.onUnauthorized, 
    required Dio dio, 
    FlutterSecureStorage? storage,
  }) : _storage = storage ?? const FlutterSecureStorage(),
       _dio = dio;

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
    if (err.requestOptions.headers.containsKey('X-Retry-Attempt')) {
      return handler.next(err);
    }

    // +++ H-1: امتصاص درع الـ 429 + Jitter عشوائي لكسر الهجوم المتزامن +++
    if (err.response?.statusCode == 429) {
      final retryStr = err.response?.headers.value('retry-after');
      int baseDelay = num.tryParse(retryStr ?? '')?.ceil() ?? 2;
      if (baseDelay < 1) baseDelay = 1;
      if (baseDelay > 30) baseDelay = 30;
      final jitter = Random().nextInt(3); // عشوائية بين 0 و 2
      
      developer.log('[AuthInterceptor] 429 Hit. Backing off for ${baseDelay + jitter} seconds...');
      await Future.delayed(Duration(seconds: baseDelay + jitter));
      err.requestOptions.headers['X-Retry-Attempt'] = 'true';
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
            
            // +++ الكي الجراحي: استخدام محرك Dio منفصل لكن بوراثة صارمة للمهلات الزمنية الأساسية لمنع التعليق اللانهائي +++
            final refreshDio = Dio(_dio.options.copyWith(baseUrl: ApiConstants.baseUrl));
            final response = await refreshDio.post(
              '/refresh',
              data: {'refresh_token': refreshToken},
              options: Options(headers: {'Content-Type': 'application/json'}),
            );

            final newAccessToken = response.data['token'];
            final newRefreshToken = response.data['refresh_token'];

            if (newAccessToken != null) {
              await _storage.write(key: 'auth_token', value: newAccessToken);
              if (newRefreshToken != null) {
                await _storage.write(key: 'refresh_token', value: newRefreshToken);
              }
              _refreshCompleter!.complete(true);
              _refreshCompleter = null;
              
              err.requestOptions.headers['X-Retry-Attempt'] = 'true'; // لمنع اللوب
              return _retryRequest(err.requestOptions, handler);
            }
          }
        } on DioException catch (e) {
          // +++ حصر الطرد في الرفض الصريح فقط (401/403) +++
          if (e.response?.statusCode == 401 || e.response?.statusCode == 403) {
            developer.log('[AuthInterceptor] Token permanently rejected → Triggering logout');
            
            // +++ الكي الجراحي: استخدام محرك Dio موحد بمهلات زمنية للحرق الأمني للتوكن (Fire-and-forget) +++
            try {
              final oldRefresh = await _storage.read(key: 'refresh_token');
              if (oldRefresh != null) {
                Dio(_dio.options.copyWith(baseUrl: ApiConstants.baseUrl))
                    .post('/logout', options: Options(headers: {'X-Refresh-Token': oldRefresh})).ignore();
              }
            } catch (_) {}

            await _storage.delete(key: 'auth_token');
            await _storage.delete(key: 'refresh_token');
            await LocalDatabase.instance.clearSessionData(clearPendingSyncs: false); 
            onUnauthorized();
            return handler.next(err); // إنهاء الـ Flow
          } else {
            developer.log('[AuthInterceptor] Network/Server Error, avoiding force logout.');
          }
        } catch (e) {
          developer.log('[AuthInterceptor] Unknown error, keeping session intact: $e');
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
  Future<void> _retryRequest(RequestOptions requestOptions, ErrorInterceptorHandler handler) async {
    try {
      final token = await _storage.read(key: 'auth_token');
      // +++ النسف المعماري: استخدام copyWith لنسخ FormData وكل الخصائص المخفية +++
      final newOptions = requestOptions.copyWith(
        headers: Map<String, dynamic>.from(requestOptions.headers)..['Authorization'] = 'Bearer $token',
      );

      final response = await _dio.fetch(newOptions);
      return handler.resolve(response);
    } catch (e) {
      return handler.next(e is DioException ? e : DioException(requestOptions: requestOptions, error: e));
    }
  }
}

// -----------------------------------------------------------------------
// ApiClient
// Singleton يوفر instance واحد من Dio مُهيَّأ مع AuthInterceptor.
// -----------------------------------------------------------------------
class ApiClient {
  ApiClient._();

  static ApiClient? _instance;
  static Dio? _dio;

  static ApiClient get instance {
    if (_instance == null) {
      throw StateError('ApiClient.init() must be called before accessing ApiClient.instance');
    }
    return _instance!;
  }

  static void init({required VoidCallback onUnauthorized}) {
    if (_instance != null) return;

    final dio = Dio(
      BaseOptions(
        baseUrl: ApiConstants.baseUrl,
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 60),
        sendTimeout: const Duration(seconds: 30),
        headers: {
          'Content-Type': 'application/json; charset=UTF-8',
          'Accept': 'application/json',
        },
      ),
    );

    dio.interceptors.add(AuthInterceptor(onUnauthorized: onUnauthorized, dio: dio));

    assert(() {
      dio.interceptors.add(
        LogInterceptor(
          requestBody: true,
          responseBody: true,
          logPrint: (obj) => developer.log(obj.toString(), name: 'Dio'),
        ),
      );
      return true;
    }());

    _dio = dio;
    _instance = ApiClient._();

    developer.log(
      '[ApiClient] Initialized with baseUrl: ${ApiConstants.baseUrl}',
    );
  }

  // -----------------------------------------------------------------------
  // Public HTTP methods
  // -----------------------------------------------------------------------

  Future<Response<T>> get<T>(
    String path, {
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio!.get<T>(
      path,
      queryParameters: queryParameters,
      options: options,
    );
  }

  Future<Response<T>> post<T>(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio!.post<T>(
      path,
      data: data,
      queryParameters: queryParameters,
      options: options,
    );
  }

  Future<Response<T>> put<T>(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio!.put<T>(
      path,
      data: data,
      queryParameters: queryParameters,
      options: options,
    );
  }

  Future<Response<T>> patch<T>(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio!.patch<T>(
      path,
      data: data,
      queryParameters: queryParameters,
      options: options,
    );
  }

  Future<Response<T>> delete<T>(
    String path, {
    dynamic data,
    Map<String, dynamic>? queryParameters,
    Options? options,
  }) {
    return _dio!.delete<T>(
      path,
      data: data,
      queryParameters: queryParameters,
      options: options,
    );
  }
}