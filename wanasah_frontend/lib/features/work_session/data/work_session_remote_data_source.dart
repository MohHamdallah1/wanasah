import 'package:dio/dio.dart';

import '../../../core/network/api_client.dart';
import 'work_session_snapshot.dart';

abstract interface class WorkSessionRemoteDataSource {
  Future<void> startSession({
    required double? latitude,
    required double? longitude,
  });

  Future<void> endSession();

  Future<void> toggleBreak({required bool start});

  Future<WorkSessionSnapshot> readActiveSession();

  Future<WorkSessionSnapshot> readRuntimeSession();
}

class ApiWorkSessionRemoteDataSource implements WorkSessionRemoteDataSource {
  ApiWorkSessionRemoteDataSource({ApiClient? apiClient})
      : _apiClient = apiClient ?? ApiClient.instance;

  final ApiClient _apiClient;

  @override
  Future<void> startSession({
    required double? latitude,
    required double? longitude,
  }) async {
    await _apiClient.post(
      '/driver/sessions/start',
      data: <String, dynamic>{
        'latitude': latitude,
        'longitude': longitude,
      },
      options: Options(
        sendTimeout: const Duration(seconds: 20),
        receiveTimeout: const Duration(seconds: 20),
      ),
    );
  }

  @override
  Future<void> endSession() async {
    await _apiClient.put(
      '/driver/sessions/end',
      options: Options(sendTimeout: const Duration(seconds: 15)),
    );
  }

  @override
  Future<void> toggleBreak({required bool start}) async {
    await _apiClient.put(
      '/driver/sessions/break',
      data: <String, dynamic>{'action': start ? 'start' : 'end'},
      options: Options(sendTimeout: const Duration(seconds: 10)),
    );
  }

  @override
  Future<WorkSessionSnapshot> readActiveSession() async {
    final response = await _apiClient.get('/driver/sessions/active');
    return WorkSessionSnapshot.fromActiveResponse(response.data);
  }

  @override
  Future<WorkSessionSnapshot> readRuntimeSession() async {
    final response = await _apiClient.get('/driver/dashboard');
    return WorkSessionSnapshot.fromDashboardResponse(response.data);
  }
}
