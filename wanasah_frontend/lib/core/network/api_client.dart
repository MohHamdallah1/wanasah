// File: lib/core/network/api_client.dart

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'dart:developer' as developer;

import '../../services/api_constants.dart';
import '../db/local_database.dart'; // +++ F-11: استيراد الداتابيز لتنظيفها +++

// -----------------------------------------------------------------------
// AuthInterceptor
// المهمة: قراءة auth_token من FlutterSecureStorage وحقنه في كل طلب،
//         والتقاط خطأ 401 لطرد المستخدم من التطبيق.
// -----------------------------------------------------------------------
class AuthInterceptor extends Interceptor {
  final FlutterSecureStorage _storage;
  final VoidCallback onUnauthorized;
  final Dio _dio; // +++ لاستخدامها في إرسال طلب הـ Refresh +++
  
  bool _isRefreshing = false; // +++ درع הـ Mutex لمنع إرسال 100 طلب Refresh بنفس اللحظة +++

  AuthInterceptor({
    required this.onUnauthorized, 
    required Dio dio, 
    FlutterSecureStorage? storage
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

    // تمرير الطلب بعد إضافة الهيدر
    return handler.next(options);
  }

  @override
  void onError(DioException err, ErrorInterceptorHandler handler) async {
    if (err.response?.statusCode == 401) {
      final isAuthPath = err.requestOptions.path.endsWith('/login') || err.requestOptions.path.endsWith('/refresh');
      
      if (!isAuthPath) {
        if (_isRefreshing) {
          // +++ حماية הـ Mutex: إذا كان في طلب تجديد شغال، بنستنى شوي وبنعيد إرسال الطلب الأصلي +++
          await Future.delayed(const Duration(seconds: 2));
          return _retryRequest(err.requestOptions, handler);
        }

        _isRefreshing = true;
        try {
          final refreshToken = await _storage.read(key: 'refresh_token');
          if (refreshToken != null && refreshToken.isNotEmpty) {
            developer.log('[AuthInterceptor] Attempting silent token refresh...');
            
            // طلب التجديد
            final response = await _dio.post(
              '/refresh', // مسار التجديد بالسيرفر
              options: Options(
                headers: {'Authorization': 'Bearer $refreshToken'}
              ),
            );

            final newAccessToken = response.data['access_token'];
            await _storage.write(key: 'auth_token', value: newAccessToken);
            
            developer.log('[AuthInterceptor] Silent refresh successful!');
            
            // إعادة إرسال الطلب اللي فشل بالتوكن الجديد
            _isRefreshing = false;
            return _retryRequest(err.requestOptions, handler);
          }
        } catch (e) {
          developer.log('[AuthInterceptor] Silent refresh failed: $e');
        } finally {
          _isRefreshing = false;
        }

        // +++ الكارثة: إذا فشل التجديد نهائياً، بنطرد المندوب، لكن بنحمي الخزنة الأوفلاين! +++
        developer.log('[AuthInterceptor] 401 Unauthorized (Refresh Failed) → Triggering logout');
        await _storage.deleteAll();
        // +++ الكي الجراحي 2: FALSE لمنع إحراق مبيعات المندوب الأوفلاين! +++
        await LocalDatabase.instance.clearSessionData(clearPendingSyncs: false); 
        onUnauthorized();
      }
    }
    return handler.next(err);
  }

  // +++ دالة مساعدة لإعادة إرسال الطلب بعد تجديد التوكن +++
  Future<void> _retryRequest(RequestOptions requestOptions, ErrorInterceptorHandler handler) async {
    try {
      final token = await _storage.read(key: 'auth_token');
      requestOptions.headers['Authorization'] = 'Bearer $token';
      
      final response = await _dio.fetch(requestOptions);
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
  ApiClient._(); // منع الإنشاء المباشر

  static ApiClient? _instance;
  static Dio? _dio;

  /// الحصول على الـ Instance الوحيد من ApiClient.
  /// يجب استدعاء [init] مرة واحدة قبل الاستخدام.
  static ApiClient get instance {
    // +++ الكي الجراحي (F-02): استبدال assert بـ StateError لمنع الانهيار في بيئة الإنتاج (Release) +++
    if (_instance == null) {
      throw StateError('ApiClient.init() must be called before accessing ApiClient.instance');
    }
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
        sendTimeout: const Duration(seconds: 30), // +++ الكي الجراحي (F-06): إضافة مهلة الإرسال لمنع اختناق السيرفر +++
        headers: {
          'Content-Type': 'application/json; charset=UTF-8',
          'Accept': 'application/json',
        },
      ),
    );

    // إضافة AuthInterceptor
    dio.interceptors.add(AuthInterceptor(onUnauthorized: onUnauthorized, dio: dio));

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
