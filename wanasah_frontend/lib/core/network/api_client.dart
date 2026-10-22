// File: lib/core/network/api_client.dart

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'dart:developer' as developer;

import '../../services/api_constants.dart';
import 'auth_interceptor.dart';

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
