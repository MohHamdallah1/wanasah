import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_coordinator.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_failure.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_location_source.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_outcome.dart';
import 'package:wanasah_frontend/features/work_session/data/work_session_remote_data_source.dart';
import 'package:wanasah_frontend/features/work_session/data/work_session_snapshot.dart';
import 'package:wanasah_frontend/features/work_session/presentation/work_session_result_message.dart';
import 'package:wanasah_frontend/features/work_session/presentation/work_session_strings.dart';

void main() {
  group('WorkSessionCoordinator', () {
    test('start success sends current coordinates and trusts Backend result', () async {
      final remote = _FakeRemote();
      final coordinator = WorkSessionCoordinator(
        remote: remote,
        locationSource: const _FakeLocation(
          coordinates: WorkSessionCoordinates(
            latitude: 31.95,
            longitude: 35.91,
          ),
        ),
      );

      final result = await coordinator.startSession();

      expect(result.disposition, WorkSessionDisposition.success);
      expect(remote.startCalls, 1);
      expect(remote.lastLatitude, 31.95);
      expect(remote.lastLongitude, 35.91);
      expect(remote.readActiveCalls, 0);
    });

    test('GPS failure is best-effort because Backend accepts nullable coordinates',
        () async {
      final remote = _FakeRemote();
      final coordinator = WorkSessionCoordinator(
        remote: remote,
        locationSource: const _ThrowingLocation(),
      );

      final result = await coordinator.startSession();

      expect(result.disposition, WorkSessionDisposition.success);
      expect(remote.startCalls, 1);
      expect(remote.lastLatitude, isNull);
      expect(remote.lastLongitude, isNull);
    });

    test('structured Backend rejection preserves code context and request id',
        () async {
      final remote = _FakeRemote()
        ..startError = _serverError(
          status: 409,
          code: 'VEHICLE_CUSTODY_LOCATION_INACTIVE',
          message: 'Vehicle custody is not operational.',
          context: const <String, dynamic>{'vehicle_id': 81},
          requestId: 'req-start-409',
        );
      final coordinator = _coordinator(remote);

      final result = await coordinator.startSession();

      expect(result.disposition, WorkSessionDisposition.rejected);
      expect(result.failure!.kind, WorkSessionFailureKind.businessRejected);
      expect(result.failure!.status, 409);
      expect(result.failure!.code, 'VEHICLE_CUSTODY_LOCATION_INACTIVE');
      expect(result.failure!.context, {'vehicle_id': 81});
      expect(result.failure!.requestId, 'req-start-409');
      expect(remote.readActiveCalls, 0);
    });

    test('restart recovery reads canonical active session from Backend', () async {
      final remote = _FakeRemote()
        ..activeSnapshot = const WorkSessionSnapshot(
          isActive: true,
          sessionId: 601,
          startTime: '2026-10-22T07:30:00+00:00',
          isOnBreak: null,
        );
      final coordinator = _coordinator(remote);

      final recovery = await coordinator.recoverActiveSession();

      expect(recovery.succeeded, isTrue);
      expect(recovery.session!.isActive, isTrue);
      expect(recovery.session!.sessionId, 601);
      expect(remote.readActiveCalls, 1);
    });

    test('ambiguous start reconciles active session before declaring success',
        () async {
      final remote = _FakeRemote()
        ..startError = _networkError()
        ..activeSnapshot = const WorkSessionSnapshot(
          isActive: true,
          sessionId: 602,
          startTime: '2026-10-22T08:00:00+00:00',
          isOnBreak: null,
        );
      final coordinator = _coordinator(remote);

      final result = await coordinator.startSession();

      expect(result.disposition, WorkSessionDisposition.reconciledSuccess);
      expect(result.reconciledSession!.sessionId, 602);
      expect(result.failure!.kind, WorkSessionFailureKind.network);
      expect(remote.startCalls, 1);
      expect(remote.readActiveCalls, 1);
    });

    test('break network failure never becomes queued or pretend success',
        () async {
      final remote = _FakeRemote()
        ..breakError = _networkError()
        ..runtimeSnapshot = const WorkSessionSnapshot(
          isActive: true,
          sessionId: 603,
          startTime: '2026-10-22T08:00:00+00:00',
          isOnBreak: false,
        );
      final coordinator = _coordinator(remote);

      final result = await coordinator.toggleBreak(start: true);

      expect(result.disposition, WorkSessionDisposition.unresolved);
      expect(result.isSuccess, isFalse);
      expect(result.failure!.kind, WorkSessionFailureKind.network);
      expect(remote.breakCalls, 1);
      expect(remote.readRuntimeCalls, 1);
    });

    test('ambiguous break succeeds only when Backend read confirms desired state',
        () async {
      final remote = _FakeRemote()
        ..breakError = _timeoutError()
        ..runtimeSnapshot = const WorkSessionSnapshot(
          isActive: true,
          sessionId: 604,
          startTime: '2026-10-22T08:00:00+00:00',
          isOnBreak: true,
        );
      final coordinator = _coordinator(remote);

      final result = await coordinator.toggleBreak(start: true);

      expect(result.disposition, WorkSessionDisposition.reconciledSuccess);
      expect(result.reconciledSession!.isOnBreak, isTrue);
    });

    test('confirmed 401 and 403 are auth rejection and are never reconciled',
        () async {
      for (final status in <int>[401, 403]) {
        final remote = _FakeRemote()
          ..startError = _serverError(
            status: status,
            code: 'HTTP_$status',
            message: 'Authorization rejected.',
            requestId: 'auth-$status',
          );
        final coordinator = _coordinator(remote);

        final result = await coordinator.startSession();

        expect(
          result.failure!.kind,
          WorkSessionFailureKind.authRejected,
          reason: 'status=$status',
        );
        expect(result.disposition, WorkSessionDisposition.rejected);
        expect(remote.readActiveCalls, 0);
      }
    });

    test('409 remains a business-state rejection rather than fake success',
        () async {
      final remote = _FakeRemote()
        ..startError = _serverError(
          status: 409,
          code: 'HTTP_409',
          message: 'An active session already exists.',
          requestId: 'conflict-409',
        );

      final result = await _coordinator(remote).startSession();

      expect(result.disposition, WorkSessionDisposition.rejected);
      expect(result.failure!.kind, WorkSessionFailureKind.businessRejected);
      expect(result.failure!.status, 409);
    });

    test('ambiguous end reconciles inactive Backend state as success', () async {
      final remote = _FakeRemote()
        ..endError = _serverError(
          status: 500,
          code: 'HTTP_500',
          message: 'Internal detail must not drive logic.',
          requestId: 'end-500',
        )
        ..activeSnapshot = const WorkSessionSnapshot.inactive();

      final result = await _coordinator(remote).endSession();

      expect(result.disposition, WorkSessionDisposition.reconciledSuccess);
      expect(result.reconciledSession!.isActive, isFalse);
      expect(result.failure!.kind, WorkSessionFailureKind.server);
      expect(remote.readActiveCalls, 1);
    });

    test('Backend-blocked end preserves deterministic blocker and does not retry',
        () async {
      final remote = _FakeRemote()
        ..endError = _serverError(
          status: 400,
          code: 'HTTP_400',
          message: 'Pending custody transfer must be resolved first.',
          context: const <String, dynamic>{'blocker': 'pending_transfer'},
          requestId: 'end-blocked',
        );

      final result = await _coordinator(remote).endSession();

      expect(result.disposition, WorkSessionDisposition.rejected);
      expect(result.failure!.kind, WorkSessionFailureKind.businessRejected);
      expect(
        result.failure!.displayFallback,
        'Pending custody transfer must be resolved first.',
      );
      expect(result.failure!.context, {'blocker': 'pending_transfer'});
      expect(result.failure!.requestId, 'end-blocked');
      expect(remote.endCalls, 1);
      expect(remote.readActiveCalls, 0);
    });
  });

  group('WorkSessionSnapshot', () {
    test('parses canonical active-session recovery response', () {
      final snapshot = WorkSessionSnapshot.fromActiveResponse(
        <String, dynamic>{
          'active_session_found': true,
          'session_id': 77,
          'start_time': '2026-10-22T08:00:00+00:00',
        },
      );

      expect(snapshot.isActive, isTrue);
      expect(snapshot.sessionId, 77);
      expect(snapshot.startTime, '2026-10-22T08:00:00+00:00');
      expect(snapshot.isOnBreak, isNull);
    });

    test('dashboard runtime parser keeps break state server-authoritative', () {
      final snapshot = WorkSessionSnapshot.fromDashboardResponse(
        <String, dynamic>{
          'active_session': <String, dynamic>{
            'session_id': 78,
            'start_time': '2026-10-22T08:00:00+00:00',
            'break_start_time': '2026-10-22T09:00:00+00:00',
            'break_end_time': null,
          },
        },
      );

      expect(snapshot.isActive, isTrue);
      expect(snapshot.isOnBreak, isTrue);
    });

    test('malformed active session fails closed instead of inventing state', () {
      expect(
        () => WorkSessionSnapshot.fromActiveResponse(
          <String, dynamic>{
            'active_session_found': true,
            'session_id': null,
          },
        ),
        throwsFormatException,
      );
    });
  });

  group('error presentation and architecture invariants', () {
    test('presentation copy resolves through locale resources', () {
      expect(
        workSessionString(
          WorkSessionStringKey.startSuccess,
          localeCode: 'ar-JO',
        ),
        'تم بدء جلسة العمل.',
      );
      expect(
        workSessionString(
          WorkSessionStringKey.startSuccess,
          localeCode: 'en-US',
        ),
        'Work session started.',
      );
    });

    test('unexpected 5xx hides server detail while preserving request id', () {
      const failure = WorkSessionFailure(
        kind: WorkSessionFailureKind.server,
        status: 500,
        code: 'HTTP_500',
        context: <String, dynamic>{},
        requestId: 'trace-500',
        displayFallback: 'sensitive internal stack detail',
      );
      const result = WorkSessionOperationResult(
        operation: WorkSessionOperation.end,
        disposition: WorkSessionDisposition.unresolved,
        failure: failure,
      );

      final message = workSessionResultMessage(result);

      expect(message, isNot(contains('sensitive internal stack detail')));
      expect(message, contains('trace-500'));
    });

    test('deterministic 4xx may display safe fallback but never branch on it',
        () {
      const a = WorkSessionFailure(
        kind: WorkSessionFailureKind.businessRejected,
        status: 400,
        code: 'HTTP_400',
        context: <String, dynamic>{},
        requestId: null,
        displayFallback: 'first safe reason',
      );
      const b = WorkSessionFailure(
        kind: WorkSessionFailureKind.businessRejected,
        status: 400,
        code: 'HTTP_400',
        context: <String, dynamic>{},
        requestId: null,
        displayFallback: 'completely different safe reason',
      );

      expect(a.kind, b.kind);
      expect(a.isAmbiguousMutation, b.isAmbiguousMutation);
    });

    test('work-session mutation path has no offline command queue dependency',
        () async {
      final coordinator = await File(
        'lib/features/work_session/application/work_session_coordinator.dart',
      ).readAsString();
      final remote = await File(
        'lib/features/work_session/data/work_session_remote_data_source.dart',
      ).readAsString();
      final dashboard = await File(
        'lib/blocs/dashboard/dashboard_bloc.dart',
      ).readAsString();

      expect(coordinator, isNot(contains('displayFallback')));
      expect(coordinator, isNot(contains('sync_repository')));
      expect(coordinator, isNot(contains('pending_sync')));
      expect(remote, isNot(contains('sync_repository')));
      expect(remote, isNot(contains('local_database')));
      expect(remote, contains("'/driver/sessions/active'"));
      expect(remote, contains("'/driver/sessions/break'"));
      expect(dashboard, isNot(contains('work_session_handlers.dart')));
      expect(dashboard, contains('recoverActiveSession()'));
      expect(dashboard, isNot(contains('clearSessionLocally()')));
    });
  });
}

WorkSessionCoordinator _coordinator(_FakeRemote remote) {
  return WorkSessionCoordinator(
    remote: remote,
    locationSource: const _FakeLocation(coordinates: null),
  );
}

class _FakeRemote implements WorkSessionRemoteDataSource {
  Object? startError;
  Object? endError;
  Object? breakError;
  Object? activeError;
  Object? runtimeError;

  WorkSessionSnapshot activeSnapshot =
      const WorkSessionSnapshot.inactive();
  WorkSessionSnapshot runtimeSnapshot =
      const WorkSessionSnapshot.inactive();

  int startCalls = 0;
  int endCalls = 0;
  int breakCalls = 0;
  int readActiveCalls = 0;
  int readRuntimeCalls = 0;

  double? lastLatitude;
  double? lastLongitude;

  @override
  Future<void> startSession({
    required double? latitude,
    required double? longitude,
  }) async {
    startCalls += 1;
    lastLatitude = latitude;
    lastLongitude = longitude;
    if (startError case final error?) throw error;
  }

  @override
  Future<void> endSession() async {
    endCalls += 1;
    if (endError case final error?) throw error;
  }

  @override
  Future<void> toggleBreak({required bool start}) async {
    breakCalls += 1;
    if (breakError case final error?) throw error;
  }

  @override
  Future<WorkSessionSnapshot> readActiveSession() async {
    readActiveCalls += 1;
    if (activeError case final error?) throw error;
    return activeSnapshot;
  }

  @override
  Future<WorkSessionSnapshot> readRuntimeSession() async {
    readRuntimeCalls += 1;
    if (runtimeError case final error?) throw error;
    return runtimeSnapshot;
  }
}

class _FakeLocation implements WorkSessionLocationSource {
  const _FakeLocation({required this.coordinates});

  final WorkSessionCoordinates? coordinates;

  @override
  Future<WorkSessionCoordinates?> currentCoordinates() async => coordinates;
}

class _ThrowingLocation implements WorkSessionLocationSource {
  const _ThrowingLocation();

  @override
  Future<WorkSessionCoordinates?> currentCoordinates() async {
    throw StateError('device location unavailable');
  }
}

DioException _networkError() {
  return DioException(
    requestOptions: RequestOptions(path: '/driver/sessions/start'),
    type: DioExceptionType.connectionError,
    message: 'offline',
  );
}

DioException _timeoutError() {
  return DioException(
    requestOptions: RequestOptions(path: '/driver/sessions/break'),
    type: DioExceptionType.receiveTimeout,
    message: 'timeout',
  );
}

DioException _serverError({
  required int status,
  required String code,
  required String message,
  Map<String, dynamic> context = const <String, dynamic>{},
  required String requestId,
}) {
  final options = RequestOptions(path: '/driver/sessions/test');
  return DioException(
    requestOptions: options,
    type: DioExceptionType.badResponse,
    response: Response<dynamic>(
      requestOptions: options,
      statusCode: status,
      headers: Headers.fromMap(
        <String, List<String>>{
          'x-request-id': <String>[requestId],
        },
      ),
      data: <String, dynamic>{
        'request_id': requestId,
        'error': <String, dynamic>{
          'code': code,
          'message': message,
          'context': context,
          'request_id': requestId,
        },
      },
    ),
  );
}
