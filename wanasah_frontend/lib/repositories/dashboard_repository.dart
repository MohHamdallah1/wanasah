import 'dart:convert';
import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../core/network/api_client.dart';
import '../core/db/local_database.dart';

class DashboardRepository {
  final ApiClient _apiClient;
  final LocalDatabase _db;
  final FlutterSecureStorage _storage;

  DashboardRepository({
    ApiClient? apiClient,
    LocalDatabase? db,
    FlutterSecureStorage? storage,
  })  : _apiClient = apiClient ?? ApiClient.instance,
        _db = db ?? LocalDatabase.instance,
        _storage = storage ?? const FlutterSecureStorage();

  Future<void> startSession(double? lat, double? lng) async {
    await _apiClient.post(
      '/driver/sessions/start',
      data: {'latitude': lat, 'longitude': lng},
      options: Options(sendTimeout: const Duration(seconds: 20), receiveTimeout: const Duration(seconds: 20)),
    );
  }

  Future<void> endSession() async {
    await _apiClient.put(
      '/driver/sessions/end',
      options: Options(sendTimeout: const Duration(seconds: 15)),
    );
  }

  Future<void> toggleBreak(int driverId, String action) async {
    try {
      await _apiClient.put(
        '/driver/sessions/break',
        data: {'action': action},
        options: Options(sendTimeout: const Duration(seconds: 10)),
      );
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) rethrow; // يتم اصطياده في الـ BLoC لتنظيف التطبيق

      // +++ الكي الجراحي لـ Bug 2: إضافة أخطاء اتصال Dio v5 للعمل بشكل صحيح أوفلاين +++
      final isOffline = e.response == null || 
                        e.type == DioExceptionType.connectionTimeout || 
                        e.type == DioExceptionType.receiveTimeout || 
                        e.type == DioExceptionType.sendTimeout || 
                        e.type == DioExceptionType.connectionError || 
                        e.type == DioExceptionType.unknown ||
                        e.error.toString().contains('SocketException');

      if (isOffline) {
        // حماية الأوفلاين: وضع الحركة في الخزنة
        await _db.addPendingSync(
          type: 'toggle_break',
          payload: jsonEncode({'driver_id': driverId, 'action': action}),
        );
      } else {
        rethrow; // خطأ سيرفر حقيقي (400/500)
      }
    }
    
    // توثيق الحركة محلياً سواء نجح النت أو تم التخزين أوفلاين
    await _storage.write(key: 'is_on_break', value: action == 'start' ? 'true' : 'false');
  }

  Future<void> clearSessionLocally() async {
    await _storage.delete(key: 'is_on_break');
    await _db.clearSessionData();
  }

// +++ الدوال الجديدة لعزل الـ BLoC عن السيرفر والخزنة (Clean Architecture) +++
  
  Future<Response> fetchDashboardRaw() async {
    return await _apiClient.get('/driver/dashboard');
  }

  Future<void> cacheDashboardData(Map<String, String> data) async {
    // +++ الكي الجراحي لـ Bug 3: التخزين بشكل متسلسل لحماية الـ KeyStore في أجهزة الأندرويد من الكراش +++
    for (final entry in data.entries) {
      await _storage.write(key: entry.key, value: entry.value);
    }
  }

  Future<Map<String, String>> getAllCachedData() async {
    return await _storage.readAll();
  }

  Future<Response> checkPendingTransfersRaw() async {
    return await _apiClient.get('/driver/transfers/pending');
  }

  Future<void> respondToTransfer(int transferId, String response) async {
    await _apiClient.put('/driver/transfers/$transferId/respond', data: {'response': response});
  }

  Future<void> respondToBatchTransfer(List<Map<String, dynamic>> transfers) async {
    await _apiClient.put('/driver/transfers/batch_respond', data: {'transfers': transfers});
  }

  Future<void> removeLocalTransfer(int transferId) async {
    await _db.removeIncomingTransfer(transferId);
  }

  Future<int?> getDriverId() async {
    final str = await _storage.read(key: 'driver_id');
    return int.tryParse(str ?? '');
  }
}