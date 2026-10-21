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

  // Break timestamps are server-execution truth. A delayed offline
  // start/end would record the wrong real-world time and may hit a later session.
  Future<bool> toggleBreak(int driverId, String action) async {
    await _apiClient.put(
      '/driver/sessions/break',
      data: {'action': action},
      options: Options(sendTimeout: const Duration(seconds: 10)),
    );

    await _storage.write(
      key: 'is_on_break',
      value: action == 'start' ? 'true' : 'false',
    );
    return true;
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
    // +++  لـ Bug 3: التخزين بشكل متسلسل لحماية الـ KeyStore في أجهزة الأندرويد من الكراش +++
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