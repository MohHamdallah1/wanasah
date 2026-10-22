import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/sync/durable_command.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_command.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_reader.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_snapshot.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_sync_coordinator.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_data_source.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_sync_executor.dart';
import 'package:wanasah_frontend/features/recovery/presentation/recovery_panel.dart';

void main() {
  group('Recovery read model', () {
    test('pending and blocked durable evidence remain distinct', () async {
      final reader = RecoveryReader(
        dataSource: _FakeRecoveryDataSource(<Map<String, dynamic>>[
          _row(
            id: 1,
            type: DurableCommandType.submitSale,
            state: DurableCommandState.pending.storageValue,
            commandId: 'sale-1',
          ),
          _row(
            id: 2,
            type: DurableCommandType.transferResponse,
            state: DurableCommandState.blocked.storageValue,
            commandId: 'transfer-2',
            errorCode: 'TRANSFER_CONFLICT',
            requestId: 'req-2',
          ),
        ]),
      );

      final snapshot = await reader.read();

      expect(snapshot.pendingCount, 1);
      expect(snapshot.blockedCount, 1);
      expect(snapshot.pending.single.commandId, 'sale-1');
      expect(snapshot.blocked.single.commandId, 'transfer-2');
    });

    test('legacy quarantined type normalizes through durable command contract',
        () async {
      final command = RecoveryCommand.fromRow(
        _row(
          id: 3,
          type: 'quarantined_draft_sale',
          state: null,
          commandId: 'legacy-sale',
        ),
      );

      expect(command.legacyQuarantined, isTrue);
      expect(command.isBlocked, isTrue);
      expect(command.normalizedType, DurableCommandType.submitSale);
      expect(command.isReplayable, isTrue);
    });

    test('stable code request id and payload reference evidence are preserved',
        () {
      final command = RecoveryCommand.fromRow(
        _row(
          id: 4,
          type: DurableCommandType.submitSale,
          state: DurableCommandState.blocked.storageValue,
          commandId: 'cmd-4',
          errorCode: 'VISIT_STATE_CONFLICT',
          requestId: 'trace-4',
          message: 'Safe display fallback',
          payload:
              '{"visitId":77,"context_product_name":"Sample product"}',
          attempts: 3,
        ),
      );

      expect(command.lastErrorCode, 'VISIT_STATE_CONFLICT');
      expect(command.lastRequestId, 'trace-4');
      expect(command.displayFallback, 'Safe display fallback');
      expect(command.visitId, 77);
      expect(command.referenceLabel, 'Sample product');
      expect(command.attemptCount, 3);
    });

    test('free text never drives state type or retry classification', () {
      final first = RecoveryCommand.fromRow(
        _row(
          id: 5,
          type: DurableCommandType.transferResponse,
          state: DurableCommandState.blocked.storageValue,
          message: 'نص عربي مختلف تماماً',
        ),
      );
      final second = RecoveryCommand.fromRow(
        _row(
          id: 6,
          type: DurableCommandType.transferResponse,
          state: DurableCommandState.blocked.storageValue,
          message: 'Completely unrelated English text',
        ),
      );

      expect(first.normalizedType, second.normalizedType);
      expect(first.state, second.state);
      expect(first.isBlocked, second.isBlocked);
      expect(first.canGenericRetry, second.canGenericRetry);
      expect(first.displayFallback, isNot(second.displayFallback));
    });

    test('non-replayable blocked command cannot receive generic retry', () {
      final command = RecoveryCommand.fromRow(
        _row(
          id: 7,
          type: DurableCommandType.legacyToggleBreak,
          state: DurableCommandState.blocked.storageValue,
          errorCode: 'STALE_TEMPORAL_COMMAND',
        ),
      );

      expect(command.isBlocked, isTrue);
      expect(command.isReplayable, isFalse);
      expect(command.canGenericRetry, isFalse);
    });
  });

  group('Recovery sync result classification', () {
    final empty = const RecoverySnapshot.empty();
    final pending = RecoverySnapshot(
      commands: <RecoveryCommand>[
        _command(
          id: 10,
          type: DurableCommandType.submitSale,
          state: DurableCommandState.pending,
        ),
      ],
    );
    final blocked = RecoverySnapshot(
      commands: <RecoveryCommand>[
        _command(
          id: 11,
          type: DurableCommandType.submitSale,
          state: DurableCommandState.blocked,
        ),
      ],
    );

    test('full success requires both pending and blocked to be empty', () {
      expect(
        RecoverySyncResult.classify(
          snapshot: empty,
          execution: RecoverySyncExecution.completed,
        ),
        RecoverySyncDisposition.synced,
      );
    });

    test('pending after sync is incomplete', () {
      expect(
        RecoverySyncResult.classify(
          snapshot: pending,
          execution: RecoverySyncExecution.completed,
        ),
        RecoverySyncDisposition.incomplete,
      );
    });

    test('blocked after sync requires recovery', () {
      expect(
        RecoverySyncResult.classify(
          snapshot: blocked,
          execution: RecoverySyncExecution.completed,
        ),
        RecoverySyncDisposition.recoveryRequired,
      );
    });

    test('timeout and transport ambiguity are unresolved', () {
      expect(
        RecoverySyncResult.classify(
          snapshot: empty,
          execution: RecoverySyncExecution.timedOut,
        ),
        RecoverySyncDisposition.unresolved,
      );
      expect(
        RecoverySyncResult.classify(
          snapshot: empty,
          execution: RecoverySyncExecution.transportAmbiguous,
        ),
        RecoverySyncDisposition.unresolved,
      );
      expect(
        RecoverySyncResult.classify(
          snapshot: pending,
          execution: RecoverySyncExecution.timedOut,
        ),
        RecoverySyncDisposition.unresolved,
      );
    });

    test('blocked durable evidence stays recovery-required even after ambiguity',
        () {
      expect(
        RecoverySyncResult.classify(
          snapshot: blocked,
          execution: RecoverySyncExecution.transportAmbiguous,
        ),
        RecoverySyncDisposition.recoveryRequired,
      );
    });

    test('coordinator marks actual wait timeout unresolved', () async {
      final executor = _CompleterSyncExecutor();
      final coordinator = RecoverySyncCoordinator(
        reader: RecoveryReader(
          dataSource: _FakeRecoveryDataSource(const <Map<String, dynamic>>[]),
        ),
        executor: executor,
      );

      final result = await coordinator.synchronize(
        waitLimit: const Duration(milliseconds: 1),
      );

      expect(result.execution, RecoverySyncExecution.timedOut);
      expect(result.disposition, RecoverySyncDisposition.unresolved);
    });

    test('typed connection failure is transport-ambiguous without text parsing',
        () async {
      final coordinator = RecoverySyncCoordinator(
        reader: RecoveryReader(
          dataSource: _FakeRecoveryDataSource(const <Map<String, dynamic>>[]),
        ),
        executor: _ThrowingSyncExecutor(
          DioException(
            requestOptions: RequestOptions(path: '/driver/visits'),
            type: DioExceptionType.connectionError,
            message: 'arbitrary human text',
          ),
        ),
      );

      final result = await coordinator.synchronize();

      expect(result.execution, RecoverySyncExecution.transportAmbiguous);
      expect(result.disposition, RecoverySyncDisposition.unresolved);
    });
  });

  group('Recovery architecture invariants', () {
    test('dashboard screen does not parse SQLite recovery rows directly',
        () async {
      final screen = await File(
        'lib/screens/dashboard_screen.dart',
      ).readAsString();

      expect(screen, isNot(contains('LocalDatabase')));
      expect(screen, isNot(contains('getPendingSyncs')));
      expect(screen, isNot(contains('getQuarantinedSyncs')));
      expect(screen, isNot(contains('jsonDecode')));
      expect(screen, isNot(contains("startsWith('quarantined_')")));
      expect(screen, contains('RecoveryDashboardScroll('));
    });

    test('recovery UI has no destructive clear-all or evidence delete path',
        () async {
      final paths = <String>[
        'lib/screens/dashboard_screen.dart',
        'lib/features/recovery/presentation/recovery_dashboard_scroll.dart',
        'lib/features/recovery/presentation/recovery_status_banner.dart',
        'lib/features/recovery/presentation/recovery_panel.dart',
        'lib/features/recovery/application/recovery_sync_coordinator.dart',
      ];

      for (final path in paths) {
        final source = await File(path).readAsString();
        expect(
          source,
          isNot(contains('clearAllQuarantinedSyncs')),
          reason: path,
        );
        expect(
          source,
          isNot(contains('deleteQuarantinedSync')),
          reason: path,
        );
        expect(
          source,
          isNot(contains('retryQuarantinedRecord')),
          reason: path,
        );
        expect(
          source,
          isNot(contains('retryBlocked')),
          reason: path,
        );
      }
    });

    test('DashboardBloc delegates recovery row interpretation to feature reader',
        () async {
      final bloc = await File(
        'lib/blocs/dashboard/dashboard_bloc.dart',
      ).readAsString();

      expect(bloc, contains('_recoveryReader.read()'));
      expect(bloc, contains('_recoverySyncCoordinator.synchronize()'));
      expect(bloc, isNot(contains('DurableCommandType.isLegacyQuarantined')));
      expect(bloc, isNot(contains('DurableCommandState.fromStorage')));
    });
  });

  testWidgets(
      'blocked recovery panel displays stable code request id and safe fallback',
      (tester) async {
    final snapshot = RecoverySnapshot(
      commands: <RecoveryCommand>[
        RecoveryCommand.fromRow(
          _row(
            id: 12,
            type: DurableCommandType.submitSale,
            state: DurableCommandState.blocked.storageValue,
            commandId: 'command-12',
            errorCode: 'BLOCKED_CODE',
            requestId: 'request-12',
            message: 'Safe fallback for representative',
          ),
        ),
      ],
    );

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ar'),
        home: Scaffold(
          body: RecoveryPanel(snapshot: snapshot),
        ),
      ),
    );

    expect(find.textContaining('BLOCKED_CODE'), findsOneWidget);
    expect(find.textContaining('request-12'), findsOneWidget);
    expect(
      find.textContaining('Safe fallback for representative'),
      findsOneWidget,
    );
    expect(find.byType(ElevatedButton), findsNothing);
    expect(find.byType(TextButton), findsNothing);
  });
}

Map<String, dynamic> _row({
  required int id,
  required String type,
  required String? state,
  String? commandId,
  String? errorCode,
  String? requestId,
  String? message,
  String payload = '{}',
  int attempts = 0,
}) {
  return <String, dynamic>{
    'id': id,
    'type': type,
    'state': state,
    'command_id': commandId,
    'created_at': '2026-10-22T00:00:00Z',
    'attempt_count': attempts,
    'last_error_code': errorCode,
    'last_request_id': requestId,
    'last_error_message': message,
    'payload': payload,
  };
}

RecoveryCommand _command({
  required int id,
  required String type,
  required DurableCommandState state,
}) {
  return RecoveryCommand(
    recordId: id,
    commandId: 'command-$id',
    normalizedType: type,
    state: state,
    legacyQuarantined: false,
    createdAt: DateTime.utc(2026, 10, 22),
    attemptCount: 0,
    lastErrorCode: null,
    lastRequestId: null,
    displayFallback: null,
    visitId: null,
    transferId: null,
    referenceLabel: null,
  );
}

class _FakeRecoveryDataSource implements RecoveryDataSource {
  _FakeRecoveryDataSource(this.rows);

  final List<Map<String, dynamic>> rows;

  @override
  Future<List<Map<String, dynamic>>> readUnresolvedRows() async => rows;
}

class _CompleterSyncExecutor implements RecoverySyncExecutor {
  final Completer<bool> _completer = Completer<bool>();

  @override
  Future<bool> synchronize() => _completer.future;
}

class _ThrowingSyncExecutor implements RecoverySyncExecutor {
  _ThrowingSyncExecutor(this.error);

  final Object error;

  @override
  Future<bool> synchronize() async {
    throw error;
  }
}
