// File: lib/core/network/api_client.dart

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:developer' as developer;

import '../../services/api_constants.dart';

// -----------------------------------------------------------------------
// AuthInterceptor
// المهمة: قراءة auth_token من FlutterSecureStorage وحقنه في كل طلب،
//         والتقاط خطأ 401 لطرد المستخدم من التطبيق.
// -----------------------------------------------------------------------
class AuthInterceptor extends Interceptor {
  final FlutterSecureStorage _storage;

  /// دالة تُستدعى عند حدوث خطأ 401 لإبلاغ الـ BLoC
  final VoidCallback onUnauthorized;

  AuthInterceptor({required this.onUnauthorized, FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();

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

    // تمرير الطلب بعد إضافة الهيدر
    return handler.next(options);
  }

  // --- التقاط خطأ 401 وإبلاغ العقل المدبر (BLoC) ---
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 401) {
      // +++ درع تسجيل الدخول: تجاهل 401 من مسار الدخول لمنع طرد المستخدم وكاش اللوب +++
      if (!err.requestOptions.path.contains('/login')) {
        developer.log(
          '[AuthInterceptor] 401 Unauthorized → triggering onUnauthorized callback',
        );
        // إطلاق الإشعار للـ BLoC ليتولى هو مسح الذاكرة والتوجيه
        onUnauthorized();
      }
    }

    // تمرير الخطأ للطبقات الأعلى
    return handler.next(err);
  }
}

// -----------------------------------------------------------------------
// ApiClient
// Singleton يوفر instance واحد من Dio مُهيَّأ مع AuthInterceptor.
// -----------------------------------------------------------------------
class ApiClient {
  ApiClient._(); // منع الإنشاء المباشر

  static ApiClient? _instance;
  static Dio? _dio;

  /// الحصول على الـ Instance الوحيد من ApiClient.
  /// يجب استدعاء [init] مرة واحدة قبل الاستخدام.
  static ApiClient get instance {
    assert(
      _instance != null,
      'ApiClient.init() must be called before accessing ApiClient.instance',
    );
    return _instance!;
  }

  /// تهيئة ApiClient.
  /// يجب تمرير دالة onUnauthorized ليتم استدعاء LogoutEvent في الـ AuthBloc
  static void init({required VoidCallback onUnauthorized}) {
    if (_instance != null) return; // تجنب التهيئة المزدوجة

    final dio = Dio(
      BaseOptions(
        baseUrl: ApiConstants.baseUrl,
        // +++ درع الشبكات الضعيفة: رفع المهلة الزمنية لمنع الانقطاع الوهمي في الميدان +++
        connectTimeout: const Duration(seconds: 30),
        receiveTimeout: const Duration(seconds: 60),
        headers: {
          'Content-Type': 'application/json; charset=UTF-8',
          'Accept': 'application/json',
        },
      ),
    );

    // إضافة AuthInterceptor
    dio.interceptors.add(AuthInterceptor(onUnauthorized: onUnauthorized));

    // (اختياري) إضافة LogInterceptor في وضع التطوير
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

  /// GET request
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

  /// POST request
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

  /// PUT request
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

  /// PATCH request
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

  /// DELETE request
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
