import 'package:dio/dio.dart';
import 'package:uuid/uuid.dart';
import 'signed_field_execution_authority.dart';

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
    // Canonical M03 PLANNED -> ACTIVE and signed S2 require a real, unique
    // idempotency identity. A lost response is reconciled by the existing
    // WorkSessionCoordinator via GET, NEVER by a second POST/new UUID.
    final startRequestId = const Uuid().v4();
    final response = await _apiClient.post(
      '/driver/sessions/start',
      data: <String, dynamic>{
        if (latitude != null) 'latitude': latitude,
        if (longitude != null) 'longitude': longitude,
      },
      options: Options(
        headers: <String, String>{'Idempotency-Key': startRequestId},
        sendTimeout: const Duration(seconds: 20),
        receiveTimeout: const Duration(seconds: 20),
      ),
    );
    // Response already committed. Failed local caching must NOT turn 201
    // into an ambiguous retry with a NEW UUID (or invent another S2).
    try {
      await SignedFieldExecutionAuthority.withApiClient(_apiClient)
          .captureSuccessfulStart(response.data);
    } catch (_) {
      // Next online signed GET can safely populate the cache.
    }
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
