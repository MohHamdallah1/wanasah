import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_state.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_action_issue.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_coordinator.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_failure.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_location_source.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_outcome.dart';
import 'package:wanasah_frontend/features/work_session/data/work_session_remote_data_source.dart';
import 'package:wanasah_frontend/features/work_session/data/work_session_snapshot.dart';
import 'package:wanasah_frontend/features/work_session/presentation/work_session_controls.dart';
import 'package:wanasah_frontend/features/work_session/presentation/work_session_issue_message.dart';
import 'package:wanasah_frontend/l10n/generated/app_localizations.dart';

void main() {
  group('verified Backend session authority contract', () {
    test(
      'start location is optional and Backend owns route vehicle custody gates',
      () async {
        final schemas = await File('../wa_backend/schemas.py').readAsString();
        final driver = await File('../wa_backend/api/driver.py').readAsString();

        expect(schemas, contains('class SessionStartRequest(RequestModel):'));
        expect(schemas, contains('latitude: Latitude = None'));
        expect(schemas, contains('longitude: Longitude = None'));

        expect(driver, contains('dispatch_date=company_local_date'));
        expect(driver, contains('status="active"'));
        expect(driver, contains('if active_route.vehicle_id is None:'));
        expect(driver, contains('resolve_vehicle_custody_location_id('));
        expect(driver, contains('read_vehicle_operational_state('));
        expect(driver, contains('require_route_commercial_context('));
        expect(driver, contains('start_latitude=payload.latitude'));
        expect(driver, contains('start_longitude=payload.longitude'));
      },
    );

    test(
      'end authority blocks active break and pending handshake only',
      () async {
        final driver = await File('../wa_backend/api/driver.py').readAsString();

        expect(
          driver,
          contains(
            'if active_session.break_start_time and not active_session.break_end_time:',
          ),
        );
        expect(
          driver,
          contains('InventoryTransferHeader.workflow_type == "HANDSHAKE"'),
        );
        expect(driver, contains('InventoryTransferHeader.status == "PENDING"'));
        expect(driver, contains('active_session.end_time = get_utc_now()'));
        expect(driver, contains('التسوية ليست مسؤولية هذا endpoint'));
      },
    );

    test(
      'restart recovery is canonical Backend read scoped to current actor',
      () async {
        final driver = await File('../wa_backend/api/driver.py').readAsString();

        expect(
          driver,
          contains(
            '@router.get("/driver/sessions/active", response_model=ActiveSessionResponse, status_code=200)',
          ),
        );
        expect(driver, contains('driver_id = legacy_actor.id'));
        expect(driver, contains('company_id=field_context.company_id'));
        expect(driver, contains('active_session_found'));
      },
    );
  });

  group('start-session evidence', () {
    test('valid optional coordinates are forwarded exactly', () async {
      final remote = _FakeRemote();
      final coordinator = WorkSessionCoordinator(
        remote: remote,
        locationSource: const _Location(
          WorkSessionCoordinates(latitude: 31.95, longitude: 35.91),
        ),
      );

      final result = await coordinator.startSession();

      expect(result.disposition, WorkSessionDisposition.success);
      expect(remote.lastLatitude, 31.95);
      expect(remote.lastLongitude, 35.91);
    });

    test(
      'missing optional location does not become a client-side blocker',
      () async {
        final remote = _FakeRemote();
        final coordinator = WorkSessionCoordinator(
          remote: remote,
          locationSource: const _Location(null),
        );

        final result = await coordinator.startSession();

        expect(result.disposition, WorkSessionDisposition.success);
        expect(remote.lastLatitude, isNull);
        expect(remote.lastLongitude, isNull);
      },
    );

    test(
      'invalid optional device coordinates are omitted, not authoritative',
      () async {
        final remote = _FakeRemote();
        final coordinator = WorkSessionCoordinator(
          remote: remote,
          locationSource: const _Location(
            WorkSessionCoordinates(latitude: 95, longitude: 35.91),
          ),
        );

        final result = await coordinator.startSession();

        expect(result.disposition, WorkSessionDisposition.success);
        expect(remote.lastLatitude, isNull);
        expect(remote.lastLongitude, isNull);
      },
    );

    test('remote start transport omits nullable location keys', () async {
      final source =
          await File(
            'lib/features/work_session/data/work_session_remote_data_source.dart',
          ).readAsString();

      expect(source, contains("if (latitude != null) 'latitude': latitude"));
      expect(source, contains("if (longitude != null) 'longitude': longitude"));
      expect(
        source,
        isNot(
          contains("'latitude': latitude,\n        'longitude': longitude"),
        ),
      );
    });
  });

  group('typed authoritative refusal mapping', () {
    test('structured vehicle custody refusal remains authoritative', () {
      final result = WorkSessionOperationResult(
        operation: WorkSessionOperation.start,
        disposition: WorkSessionDisposition.rejected,
        failure: const WorkSessionFailure(
          kind: WorkSessionFailureKind.businessRejected,
          status: 409,
          code: 'VEHICLE_CUSTODY_LOCATION_INACTIVE',
          context: <String, dynamic>{'location_count': 0},
          requestId: 'req-custody',
          displayFallback: 'display only',
        ),
      );

      final issue = WorkSessionActionIssue.fromResult(result);

      expect(issue.kind, WorkSessionActionIssueKind.vehicleCustodyPrerequisite);
      expect(issue.status, 409);
      expect(issue.code, 'VEHICLE_CUSTODY_LOCATION_INACTIVE');
      expect(issue.context, <String, dynamic>{'location_count': 0});
      expect(issue.requestId, 'req-custody');
    });

    test('legacy start HTTP 400 stays broad and never parses message text', () {
      for (final message in <String>[
        'لا يوجد خط سير',
        'completely different display text',
      ]) {
        final issue = WorkSessionActionIssue.fromResult(
          WorkSessionOperationResult(
            operation: WorkSessionOperation.start,
            disposition: WorkSessionDisposition.rejected,
            failure: WorkSessionFailure(
              kind: WorkSessionFailureKind.businessRejected,
              status: 400,
              code: 'HTTP_400',
              context: const <String, dynamic>{},
              requestId: 'req-start',
              displayFallback: message,
            ),
          ),
        );

        expect(issue.kind, WorkSessionActionIssueKind.startPrerequisite);
        expect(issue.code, 'HTTP_400');
      }
    });

    test('end rejection maps to end prerequisite without guessing blocker', () {
      final issue = WorkSessionActionIssue.fromResult(
        const WorkSessionOperationResult(
          operation: WorkSessionOperation.end,
          disposition: WorkSessionDisposition.rejected,
          failure: WorkSessionFailure(
            kind: WorkSessionFailureKind.businessRejected,
            status: 400,
            code: 'HTTP_400',
            context: <String, dynamic>{},
            requestId: 'req-end',
            displayFallback: 'legacy display detail',
          ),
        ),
      );

      expect(issue.kind, WorkSessionActionIssueKind.endPrerequisite);
      expect(issue.requestId, 'req-end');
    });

    test('validation refusal is typed separately', () {
      final issue = WorkSessionActionIssue.fromResult(
        const WorkSessionOperationResult(
          operation: WorkSessionOperation.start,
          disposition: WorkSessionDisposition.rejected,
          failure: WorkSessionFailure(
            kind: WorkSessionFailureKind.businessRejected,
            status: 422,
            code: 'VALIDATION_ERROR',
            context: <String, dynamic>{'field': 'latitude'},
            requestId: 'req-validation',
            displayFallback: 'display only',
          ),
        ),
      );

      expect(issue.kind, WorkSessionActionIssueKind.invalidStartEvidence);
      expect(issue.context['field'], 'latitude');
    });

    test('unresolved server result never exposes internal fallback text', () {
      final issue = WorkSessionActionIssue.fromResult(
        const WorkSessionOperationResult(
          operation: WorkSessionOperation.end,
          disposition: WorkSessionDisposition.unresolved,
          failure: WorkSessionFailure(
            kind: WorkSessionFailureKind.server,
            status: 500,
            code: 'HTTP_500',
            context: <String, dynamic>{},
            requestId: 'req-500',
            displayFallback: 'sensitive server internals',
          ),
        ),
      );

      final message = workSessionIssueMessage(issue);

      expect(issue.kind, WorkSessionActionIssueKind.unresolved);
      expect(issue.displayFallback, isNull);
      expect(message, isNot(contains('sensitive server internals')));
      expect(message, contains('HTTP_500'));
      expect(message, contains('req-500'));
    });
  });

  group('break and end semantics', () {
    test('break transport ambiguity never creates historical queue', () async {
      final remote =
          _FakeRemote()
            ..breakError = _networkError('/driver/sessions/break')
            ..runtimeSnapshot = const WorkSessionSnapshot(
              isActive: true,
              sessionId: 700,
              startTime: '2026-10-22T08:00:00Z',
              isOnBreak: false,
            );

      final result = await _coordinator(remote).toggleBreak(start: true);

      expect(result.disposition, WorkSessionDisposition.unresolved);
      expect(remote.breakCalls, 1);
      expect(remote.runtimeReads, 1);

      final featureSources = await _workSessionSources();
      expect(featureSources, isNot(contains('pending_sync')));
      expect(featureSources, isNot(contains('SyncRepository')));
      expect(featureSources, isNot(contains('toggle_break')));
    });

    test('end rejection never pretends local completion', () async {
      final remote =
          _FakeRemote()
            ..endError = _serverError(
              status: 400,
              code: 'HTTP_400',
              requestId: 'req-blocked-end',
            );

      final result = await _coordinator(remote).endSession();

      expect(result.disposition, WorkSessionDisposition.rejected);
      expect(result.isSuccess, isFalse);
      expect(remote.endCalls, 1);
      expect(remote.activeReads, 0);

      final issue = WorkSessionActionIssue.fromResult(result);
      const active = DashboardLoaded(
        visits: [],
        products: [],
        totalVisits: 0,
        completedVisits: 0,
        pendingVisits: 0,
        offlineVisits: 0,
        isActiveSession: true,
      );
      final preserved = active.copyWith(workSessionIssue: issue);
      expect(preserved.isActiveSession, isTrue);
      expect(
        preserved.workSessionIssue?.kind,
        WorkSessionActionIssueKind.endPrerequisite,
      );
    });

    test(
      'ambiguous end remains unresolved while Backend still reports active',
      () async {
        final remote =
            _FakeRemote()
              ..endError = _networkError('/driver/sessions/end')
              ..activeSnapshot = const WorkSessionSnapshot(
                isActive: true,
                sessionId: 701,
                startTime: '2026-10-22T08:00:00Z',
                isOnBreak: null,
              );

        final result = await _coordinator(remote).endSession();

        expect(result.disposition, WorkSessionDisposition.unresolved);
        expect(result.reconciledSession?.isActive, isTrue);
        expect(result.isSuccess, isFalse);
      },
    );

    test(
      'ambiguous end succeeds only after Backend confirms inactive',
      () async {
        final remote =
            _FakeRemote()
              ..endError = _networkError('/driver/sessions/end')
              ..activeSnapshot = const WorkSessionSnapshot.inactive();

        final result = await _coordinator(remote).endSession();

        expect(result.disposition, WorkSessionDisposition.reconciledSuccess);
        expect(result.isSuccess, isTrue);
        expect(result.reconciledSession?.isActive, isFalse);
      },
    );
  });

  group('restart and authority boundaries', () {
    test('restart recovery reads active session from Backend', () async {
      final remote =
          _FakeRemote()
            ..activeSnapshot = const WorkSessionSnapshot(
              isActive: true,
              sessionId: 702,
              startTime: '2026-10-22T08:00:00Z',
              isOnBreak: null,
            );

      final recovery = await _coordinator(remote).recoverActiveSession();

      expect(recovery.succeeded, isTrue);
      expect(recovery.session?.sessionId, 702);
      expect(remote.activeReads, 1);
    });

    test(
      'Work Session feature has no local role or authorization authority',
      () async {
        final sources = await _workSessionSources();

        expect(sources, isNot(contains('is_authorized')));
        expect(sources, isNot(contains('FlutterSecureStorage')));
        expect(sources, isNot(contains('LocalDatabase')));
        expect(sources, isNot(contains('role')));
      },
    );

    test(
      'machine decisions do not branch on free-text display messages',
      () async {
        final sources = await _workSessionSources();

        expect(sources, isNot(contains('message.contains')));
        expect(sources, isNot(contains('displayFallback.contains')));
        expect(sources, isNot(contains("contains('لا يوجد")));
      },
    );

    test('Dashboard keeps typed session refusal in loaded composition', () async {
      final bloc =
          await File('lib/blocs/dashboard/dashboard_bloc.dart').readAsString();
      final state =
          await File('lib/blocs/dashboard/dashboard_state.dart').readAsString();
      final screen =
          await File('lib/screens/dashboard_screen.dart').readAsString();
      final controls =
          await File(
            'lib/features/work_session/presentation/work_session_controls.dart',
          ).readAsString();

      expect(bloc, contains('WorkSessionActionIssue.fromResult(result)'));
      expect(bloc, contains('workSessionIssue: issue'));
      expect(bloc, contains('clearWorkSessionIssue: true'));
      expect(state, contains('WorkSessionActionIssue? workSessionIssue'));
      expect(screen, contains('issue: state.workSessionIssue'));
      expect(controls, contains('WorkSessionIssuePanel'));
      expect(controls, isNot(contains('يجب إنهاء الاستراحة أولاً!')));
    });
  });

  testWidgets(
    'typed refusal remains visible instead of SnackBar-only handling',
    (tester) async {
      final issue = WorkSessionActionIssue(
        operation: WorkSessionOperation.end,
        kind: WorkSessionActionIssueKind.endPrerequisite,
        status: 400,
        code: 'HTTP_400',
        context: const <String, dynamic>{'blocker': 'server_authority'},
        requestId: 'req-visible',
        displayFallback: 'أكمل المتطلبات التشغيلية أولاً.',
      );

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ar'),
          supportedLocales: AppLocalizations.supportedLocales,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          home: Scaffold(
            body: WorkSessionControls(
              isActiveSession: true,
              activeSessionStartTime: '2026-10-22T08:00:00Z',
              isOnBreak: false,
              isActionInProgress: false,
              onActionStarted: () {},
              onStart: () {},
              onEnd: () {},
              onToggleBreak: (_) {},
              issue: issue,
            ),
          ),
        ),
      );

      expect(
        find.textContaining('أكمل المتطلبات التشغيلية أولاً.'),
        findsOneWidget,
      );
      expect(find.text('إنهاء العمل'), findsOneWidget);
      expect(find.textContaining('HTTP_400'), findsOneWidget);
      expect(find.textContaining('req-visible'), findsOneWidget);
    },
  );
}

WorkSessionCoordinator _coordinator(_FakeRemote remote) {
  return WorkSessionCoordinator(
    remote: remote,
    locationSource: const _Location(null),
  );
}

Future<String> _workSessionSources() async {
  final files = Directory('lib/features/work_session')
      .listSync(recursive: true)
      .whereType<File>()
      .where((file) => file.path.endsWith('.dart'));

  final buffer = StringBuffer();
  for (final file in files) {
    buffer.writeln(await file.readAsString());
  }
  return buffer.toString();
}

class _Location implements WorkSessionLocationSource {
  const _Location(this.coordinates);

  final WorkSessionCoordinates? coordinates;

  @override
  Future<WorkSessionCoordinates?> currentCoordinates() async => coordinates;
}

class _FakeRemote implements WorkSessionRemoteDataSource {
  Object? startError;
  Object? endError;
  Object? breakError;
  Object? activeError;
  Object? runtimeError;

  WorkSessionSnapshot activeSnapshot = const WorkSessionSnapshot.inactive();
  WorkSessionSnapshot runtimeSnapshot = const WorkSessionSnapshot.inactive();

  int startCalls = 0;
  int endCalls = 0;
  int breakCalls = 0;
  int activeReads = 0;
  int runtimeReads = 0;
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
    activeReads += 1;
    if (activeError case final error?) throw error;
    return activeSnapshot;
  }

  @override
  Future<WorkSessionSnapshot> readRuntimeSession() async {
    runtimeReads += 1;
    if (runtimeError case final error?) throw error;
    return runtimeSnapshot;
  }
}

DioException _networkError(String path) {
  return DioException(
    requestOptions: RequestOptions(path: path),
    type: DioExceptionType.connectionError,
    message: 'transport unavailable',
  );
}

DioException _serverError({
  required int status,
  required String code,
  required String requestId,
}) {
  final options = RequestOptions(path: '/driver/sessions/test');
  return DioException(
    requestOptions: options,
    type: DioExceptionType.badResponse,
    response: Response<dynamic>(
      requestOptions: options,
      statusCode: status,
      headers: Headers.fromMap(<String, List<String>>{
        'x-request-id': <String>[requestId],
      }),
      data: <String, dynamic>{
        'request_id': requestId,
        'error': <String, dynamic>{
          'code': code,
          'message': 'display fallback only',
          'context': <String, dynamic>{},
          'request_id': requestId,
        },
      },
    ),
  );
}
