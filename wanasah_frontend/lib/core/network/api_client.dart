// File: lib/core/network/api_client.dart

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:developer' as developer;

import '../../screens/login_screen.dart';
import '../../services/api_constants.dart';

// -----------------------------------------------------------------------
// AuthInterceptor
// المهمة: قراءة auth_token من FlutterSecureStorage وحقنه في كل طلب،
//         والتقاط خطأ 401 لطرد المستخدم من التطبيق.
// -----------------------------------------------------------------------
class AuthInterceptor extends Interceptor {
  final FlutterSecureStorage _storage;

  /// [navigatorKey] يُستخدم للوصول إلى NavigationContext بدون BuildContext.
  final GlobalKey<NavigatorState> navigatorKey;

  AuthInterceptor({
    required this.navigatorKey,
    FlutterSecureStorage? storage,
  }) : _storage = storage ?? const FlutterSecureStorage();

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

  // --- التقاط خطأ 401 وطرد المستخدم ---
  @override
  void onError(DioException err, ErrorInterceptorHandler handler) {
    if (err.response?.statusCode == 401) {
      developer.log(
        '[AuthInterceptor] 401 Unauthorized → triggering handleUnauthorized',
      );
      handleUnauthorized();
    }

    // تمرير الخطأ للطبقات الأعلى (لا نبتلعه)
    return handler.next(err);
  }

  // -----------------------------------------------------------------------
  // handleUnauthorized
  // حذف بيانات الجلسة والتوجيه إلى شاشة تسجيل الدخول.
  // -----------------------------------------------------------------------
  Future<void> handleUnauthorized() async {
    try {
      await _storage.delete(key: 'auth_token');
      await _storage.delete(key: 'driver_id');
      developer.log('[AuthInterceptor] Session cleared due to 401.');
    } catch (e) {
      developer.log('[AuthInterceptor] Error clearing storage: $e');
    }

    // استخدام navigatorKey للوصول إلى NavigationContext بأمان
    final NavigatorState? navigator = navigatorKey.currentState;
    if (navigator != null) {
      navigator.pushAndRemoveUntil(
        MaterialPageRoute(builder: (_) => const LoginScreen()),
        (Route<dynamic> route) => false,
      );
    } else {
      developer.log(
        '[AuthInterceptor] NavigatorState is null — cannot navigate to Login.',
      );
    }
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

  /// تهيئة ApiClient مع الـ navigatorKey من MaterialApp.
  /// استدعِ هذه الدالة مرة واحدة في main() أو في بداية التطبيق.
  static void init({required GlobalKey<NavigatorState> navigatorKey}) {
    if (_instance != null) return; // تجنب التهيئة المزدوجة

    final dio = Dio(
      BaseOptions(
        baseUrl: ApiConstants.baseUrl,
        connectTimeout: const Duration(seconds: 15),
        receiveTimeout: const Duration(seconds: 30),
        headers: {
          'Content-Type': 'application/json; charset=UTF-8',
          'Accept': 'application/json',
        },
      ),
    );

    // إضافة AuthInterceptor
    dio.interceptors.add(
      AuthInterceptor(navigatorKey: navigatorKey),
    );

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

    developer.log('[ApiClient] Initialized with baseUrl: ${ApiConstants.baseUrl}');
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
