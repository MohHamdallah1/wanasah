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

  // +++ إرجاع bool للإبلاغ عن حالة الرفع الفعلية (true = نجح, false = طابور أوفلاين) +++
  Future<bool> toggleBreak(int driverId, String action) async {
    bool isQueuedOffline = false;
    try {
      await _apiClient.put(
        '/driver/sessions/break',
        data: {'action': action},
        options: Options(sendTimeout: const Duration(seconds: 10)),
      );
    } on DioException catch (e) {
      if (e.response?.statusCode == 404) rethrow; 

      // +++ تقييد شرط الأوفلاين: يجب أن يكون الرد null مع خطأ شبكي حقيقي لمنع ابتلاع أخطاء السيرفر +++
      final isOffline = e.response == null && (
                        e.type == DioExceptionType.connectionTimeout || 
                        e.type == DioExceptionType.receiveTimeout || 
                        e.type == DioExceptionType.sendTimeout || 
                        e.type == DioExceptionType.connectionError || 
                        e.type == DioExceptionType.unknown ||
                        e.error.toString().contains('SocketException'));

      if (isOffline) {
        await _db.addPendingSync(
          type: 'toggle_break',
          payload: jsonEncode({'driver_id': driverId, 'action': action}),
        );
        isQueuedOffline = true;
      } else {
        rethrow; 
      }
    }
    
    await _storage.write(key: 'is_on_break', value: action == 'start' ? 'true' : 'false');
    return !isQueuedOffline; // نعيد true إذا لم يتم وضعه في الطابور
  }

  Future<void> clearSessionLocally() async {
    // +++ مسح كامل لبصمات الجلسة لمنع تلوث بيانات المندوب القادم (State Corruption) +++
    await _storage.delete(key: 'is_on_break');
    await _storage.delete(key: 'is_authorized');
    await _storage.delete(key: 'cached_is_active_session');
    await _storage.delete(key: 'cached_session_start_time');
    // تنظيف قاعدة البيانات المحلية
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
    final allData = await _storage.readAll();
    // +++ فلترة أمنية: منع تسريب الـ Tokens لمعالجات الداشبورد +++
    allData.removeWhere((key, value) => key == 'auth_token' || key == 'refresh_token');
    return allData;
  }

  Future<Response> checkPendingTransfersRaw() async {
    return await _apiClient.get('/driver/transfers/pending');
  }

  // +++ تم حذف دوال respondToTransfer لأنها أصبحت من مسؤولية SyncRepository لدعم الأوفلاين +++

  Future<int?> getDriverId() async {
    final str = await _storage.read(key: 'driver_id');
    return int.tryParse(str ?? '');
  }
}