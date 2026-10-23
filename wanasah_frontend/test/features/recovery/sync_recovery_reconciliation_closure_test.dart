import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:sqflite/sqflite.dart';
import 'package:wanasah_frontend/core/sync/durable_command.dart';
import 'package:wanasah_frontend/core/sync/sync_reconciliation_failure.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_command.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_reader.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_snapshot.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_sync_coordinator.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_data_source.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_sync_executor.dart';

void main() {
  group('typed local replay failure classification', () {
    test('real typed DatabaseException maps to transient pending handling', () {
      final failure = SyncLocalFailure.from(
        _TypedDatabaseException(),
      );

      expect(
        failure.disposition,
        SyncLocalFailureDisposition.pending,
      );
      expect(failure.code, 'LOCAL_DATABASE_TRANSIENT');
    });

    test('arbitrary exception maps to stable local blocked failure', () {
      final failure = SyncLocalFailure.from(
        StateError('arbitrary local failure'),
      );

      expect(
        failure.disposition,
        SyncLocalFailureDisposition.blocked,
      );
      expect(failure.code, 'LOCAL_COMMAND_ERROR');
    });

    test('text that says DatabaseException cannot change machine result', () {
      final failure = SyncLocalFailure.from(
        StateError('DatabaseException: fake text only'),
      );

      expect(
        failure.disposition,
        SyncLocalFailureDisposition.blocked,
      );
      expect(failure.code, 'LOCAL_COMMAND_ERROR');
    });
  });

  group('Recovery typed reconciliation classification', () {
    test('typed reconciliation blocker remains recovery-required', () async {
      final coordinator = RecoverySyncCoordinator(
        reader: RecoveryReader(
          dataSource: _Rows(<Map<String, dynamic>>[
            _row(
              id: 1,
              type: DurableCommandType.submitSale,
              state: DurableCommandState.blocked.storageValue,
              errorCode: 'LOCAL_COMMAND_ERROR',
            ),
          ]),
        ),
        executor: const _ThrowingExecutor(
          SyncReconciliationException(
            SyncReconciliationCode.blockedEvidence,
          ),
        ),
      );

      final result = await coordinator.synchronize();

      expect(result.execution, RecoverySyncExecution.failed);
      expect(result.disposition, RecoverySyncDisposition.recoveryRequired);
      expect(result.snapshot?.blockedCount, 1);
    });

    test('typed refresh refusal with no evidence is unresolved, not success',
        () async {
      final coordinator = RecoverySyncCoordinator(
        reader: RecoveryReader(dataSource: _Rows(const <Map<String, dynamic>>[])),
        executor: const _ThrowingExecutor(
          SyncReconciliationException(
            SyncReconciliationCode.invalidAuthoritativeProjection,
          ),
        ),
      );

      final result = await coordinator.synchronize();

      expect(result.execution, RecoverySyncExecution.failed);
      expect(result.disposition, RecoverySyncDisposition.unresolved);
      expect(result.snapshot?.isEmpty, isTrue);
    });
  });

  group('SyncRepository replay ordering source invariants', () {
    test('confirmed Visit replay dispatches then finalizes then deletes', () async {
      final source = await _syncSource();
      final syncUpStart = source.indexOf('Future<int> syncUp()');
      final dispatch = source.indexOf(
        'await _dispatchPendingRecord(type: type, payload: payload);',
        syncUpStart,
      );
      final finalize = source.indexOf(
        'await _visitReplay.finalizeLocalState(',
        dispatch,
      );
      final delete = source.indexOf(
        'await _db.deletePendingSync(recordId);',
        finalize,
      );

      expect(syncUpStart, greaterThanOrEqualTo(0));
      expect(dispatch, greaterThan(syncUpStart));
      expect(finalize, greaterThan(dispatch));
      expect(delete, greaterThan(finalize));
    });

    test('failed direct Visit local finalize cannot delete durable evidence',
        () async {
      final source = await _syncSource();
      final helperStart = source.indexOf(
        'Future<void> _finalizeDirectVisitLocalState({',
      );
      final helperEnd = source.indexOf(
        'Future<void> _refreshAuthoritativeProjectionAfterConfirmedMutation()',
        helperStart,
      );
      final helper = source.substring(helperStart, helperEnd);

      expect(helper, contains('on LocalInventoryProjectionException'));
      expect(helper, contains('errorCode: error.code'));
      expect(helper, contains('_recordLocalReplayFailure'));
      expect(helper, isNot(contains('deletePendingSync')));
    });

    test('direct confirmed Visit refresh starts only after finalize and delete',
        () async {
      final source = await _syncSource();
      final logIndex = source.indexOf(
        'committed and locally finalized with durable request',
      );
      final finalize = source.lastIndexOf(
        'await _finalizeDirectVisitLocalState(',
        logIndex,
      );
      final delete = source.lastIndexOf(
        'await _db.deletePendingSync(commandRecordId);',
        logIndex,
      );
      final refresh = source.indexOf(
        'await _refreshAuthoritativeProjectionAfterConfirmedMutation();',
        logIndex,
      );

      expect(finalize, greaterThanOrEqualTo(0));
      expect(delete, greaterThan(finalize));
      expect(logIndex, greaterThan(delete));
      expect(refresh, greaterThan(logIndex));
    });

    test('post-confirmation refresh failure cannot undo confirmed submission',
        () async {
      final source = await _syncSource();
      final start = source.indexOf(
        'Future<void> _refreshAuthoritativeProjectionAfterConfirmedMutation()',
      );
      final end = source.indexOf(
        'Future<void> _recordLocalReplayFailure(',
        start,
      );
      final helper = source.substring(start, end);

      expect(helper, contains('await syncDown()'));
      expect(helper, contains('catch (error)'));
      expect(helper, isNot(contains('rethrow')));
      expect(helper, isNot(contains('deletePendingSync')));
    });

    test('ambiguous Visit mutation stays pending and is not deleted', () async {
      final source = await _syncSource();
      final saveStart = source.indexOf('Future<void> saveInvoice({');
      final dioCatch = source.indexOf('on DioException catch (e)', saveStart);
      final genericCatch = source.indexOf('} catch (error)', dioCatch);
      final block = source.substring(dioCatch, genericCatch);

      expect(block, contains('markPendingSyncPending'));
      expect(block, contains('NETWORK_AMBIGUOUS'));
      expect(block, contains('_finalizeDirectVisitLocalState'));
      expect(block, isNot(contains('deletePendingSync')));
    });

    test('LocalInventoryProjectionException preserves exact stable code',
        () async {
      final source = await _syncSource();
      final projectionCatch = source.indexOf(
        'on LocalInventoryProjectionException catch (error)',
      );

      expect(projectionCatch, greaterThanOrEqualTo(0));
      expect(
        source.indexOf('errorCode: error.code', projectionCatch),
        greaterThan(projectionCatch),
      );
    });
  });

  group('FIFO and owner safety source invariants', () {
    test('owner evidence is validated before UUID or request repair', () async {
      final source = await _syncSource();
      final syncUpStart = source.indexOf('Future<int> syncUp()');
      final requireRows = source.indexOf('owner.requireRows(pending);', syncUpStart);
      final requestRepair = source.indexOf(
        "payload['request_id'] = _uuid.v4();",
        syncUpStart,
      );
      final commandRepair = source.indexOf(
        'await _db.updatePendingSyncCommandId(recordId, commandId);',
        syncUpStart,
      );

      expect(requireRows, greaterThan(syncUpStart));
      expect(requestRepair, greaterThan(requireRows));
      expect(commandRepair, greaterThan(requireRows));
    });

    test('blocked FIFO head stops before dispatching later evidence', () async {
      final source = await _syncSource();
      final syncUpStart = source.indexOf('Future<int> syncUp()');
      final blockedCheck = source.indexOf(
        'state == DurableCommandState.blocked',
        syncUpStart,
      );
      final blockedBreak = source.indexOf('break;', blockedCheck);
      final dispatch = source.indexOf(
        'await _dispatchPendingRecord(type: type, payload: payload);',
        syncUpStart,
      );

      expect(blockedCheck, greaterThan(syncUpStart));
      expect(blockedBreak, greaterThan(blockedCheck));
      expect(dispatch, greaterThan(blockedBreak));
    });

    test('syncDown refuses refresh while any unresolved evidence remains',
        () async {
      final source = await _syncSource();
      final syncDownStart = source.indexOf('Future<bool> syncDown()');
      final upload = source.indexOf('await syncUp();', syncDownStart);
      final pendingCheck = source.indexOf(
        'final pendingCheck = await _db.getPendingSyncs();',
        upload,
      );
      final fetch = source.indexOf(
        "final response = await _api.get('/driver/visits');",
        pendingCheck,
      );
      final postCheck = source.indexOf(
        'final postCheck = await _db.getPendingSyncs();',
        fetch,
      );
      final refresh = source.indexOf(
        'await _db.refreshSessionData(',
        postCheck,
      );

      expect(upload, greaterThan(syncDownStart));
      expect(pendingCheck, greaterThan(upload));
      expect(fetch, greaterThan(pendingCheck));
      expect(postCheck, greaterThan(fetch));
      expect(refresh, greaterThan(postCheck));
    });
  });

  group('Transfer and Recovery reconciliation integration', () {
    test('transfer replay uses exact id decision reason and finalizes before delete',
        () async {
      final source = await _syncSource();
      final dispatchStart = source.indexOf(
        'case DurableCommandType.transferResponse:',
      );
      final transferId = source.indexOf(
        "payload['transferId']",
        dispatchStart,
      );
      final response = source.indexOf(
        "'response': payload['response']",
        dispatchStart,
      );
      final reason = source.indexOf(
        "'reason': payload['reason']",
        dispatchStart,
      );

      expect(transferId, greaterThan(dispatchStart));
      expect(response, greaterThan(transferId));
      expect(reason, greaterThan(response));

      final syncUpStart = source.indexOf('Future<int> syncUp()');
      final remove = source.indexOf(
        'await _db.removeIncomingTransfer(transferId);',
        syncUpStart,
      );
      final delete = source.indexOf(
        'await _db.deletePendingSync(recordId);',
        remove,
      );
      expect(remove, greaterThan(syncUpStart));
      expect(delete, greaterThan(remove));
    });

    test('accepted live Transfer triggers Dashboard authoritative fetch path',
        () async {
      final dashboard =
          await File('lib/blocs/dashboard/dashboard_bloc.dart').readAsString();
      final responseStart = dashboard.indexOf(
        'Future<void> _onRespondToTransfer(',
      );
      final responseEnd = dashboard.indexOf(
        'Future<void> _onRespondToBatchTransfer(',
        responseStart,
      );
      final responseHandler = dashboard.substring(responseStart, responseEnd);

      expect(responseHandler, contains('FetchDashboardData('));

      final fetchStart = dashboard.indexOf(
        'Future<void> _onFetchDashboardData(',
      );
      final fetchEnd = dashboard.indexOf(
        'Future<void> _onCheckPendingTransfers(',
        fetchStart,
      );
      final fetchHandler = dashboard.substring(fetchStart, fetchEnd);
      expect(fetchHandler, contains('await _syncRepository.syncDown()'));
    });

    test('Recovery executor reuses the single sync engine and authoritative refresh',
        () async {
      final executor = await File(
        'lib/features/recovery/data/recovery_sync_executor.dart',
      ).readAsString();

      expect(executor, contains('Future<bool> synchronize() => _repository.syncDown()'));
      expect(executor, isNot(contains('pending_sync')));
      expect(executor, isNot(contains('ApiClient')));
    });

    test('Recovery never calls blocked evidence synced', () {
      final snapshot = RecoverySnapshot(
        commands: <RecoveryCommand>[
          _command(
            id: 9,
            state: DurableCommandState.blocked,
          ),
        ],
      );

      expect(
        RecoverySyncResult.classify(
          snapshot: snapshot,
          execution: RecoverySyncExecution.completed,
        ),
        RecoverySyncDisposition.recoveryRequired,
      );
    });
  });

  test('owned replay/recovery paths contain no free-text machine classification',
      () async {
    final paths = <String>[
      'lib/repositories/sync_repository.dart',
      'lib/features/recovery/application/recovery_sync_coordinator.dart',
      'lib/features/recovery/application/recovery_reader.dart',
      'lib/features/recovery/application/recovery_command.dart',
      'lib/features/recovery/data/recovery_sync_executor.dart',
      'lib/core/sync/sync_reconciliation_failure.dart',
    ];

    for (final path in paths) {
      final source = await File(path).readAsString();
      expect(source, isNot(contains('message.contains')), reason: path);
      expect(source, isNot(contains('toString().contains')), reason: path);
      expect(source, isNot(contains("contains('DatabaseException")), reason: path);
    }
  });

  test('syncDown blockers now use stable typed reconciliation codes', () async {
    final source = await _syncSource();

    expect(source, contains('SyncReconciliationCode.blockedEvidence'));
    expect(source, contains('SyncReconciliationCode.pendingSensitiveEvidence'));
    expect(source, contains('SyncReconciliationCode.pendingVisitEvidence'));
    expect(
      source,
      contains('SyncReconciliationCode.invalidAuthoritativeProjection'),
    );
    expect(
      source,
      contains('SyncReconciliationCode.commandAppearedDuringRefresh'),
    );
  });
}

Future<String> _syncSource() {
  return File('lib/repositories/sync_repository.dart').readAsString();
}

Map<String, dynamic> _row({
  required int id,
  required String type,
  required String state,
  String? errorCode,
}) {
  return <String, dynamic>{
    'id': id,
    'type': type,
    'state': state,
    'command_id': 'command-$id',
    'created_at': '2026-10-23T00:00:00Z',
    'attempt_count': 0,
    'last_error_code': errorCode,
    'last_request_id': null,
    'last_error_message': null,
    'payload': '{"visitId":1}',
  };
}

RecoveryCommand _command({
  required int id,
  required DurableCommandState state,
}) {
  return RecoveryCommand(
    recordId: id,
    commandId: 'command-$id',
    normalizedType: DurableCommandType.submitSale,
    state: state,
    legacyQuarantined: false,
    createdAt: DateTime.utc(2026, 10, 23),
    attemptCount: 0,
    lastErrorCode: null,
    lastRequestId: null,
    displayFallback: null,
    visitId: 1,
    transferId: null,
    referenceLabel: null,
  );
}

class _Rows implements RecoveryDataSource {
  const _Rows(this.rows);

  final List<Map<String, dynamic>> rows;

  @override
  Future<List<Map<String, dynamic>>> readUnresolvedRows() async => rows;
}

class _ThrowingExecutor implements RecoverySyncExecutor {
  const _ThrowingExecutor(this.error);

  final Object error;

  @override
  Future<bool> synchronize() async {
    throw error;
  }
}


class _TypedDatabaseException extends DatabaseException {
  _TypedDatabaseException() : super('typed sqlite failure');

  @override
  Object? get result => null;

  @override
  int? getResultCode() => null;

  @override
  bool isDatabaseClosedError() => false;

  @override
  bool isDuplicateColumnError([String? column]) => false;

  @override
  bool isNoSuchTableError([String? table]) => false;

  @override
  bool isNotNullConstraintError([String? field]) => false;

  @override
  bool isOpenFailedError() => false;

  @override
  bool isReadOnlyError() => false;

  @override
  bool isSyntaxError() => false;

  @override
  bool isUniqueConstraintError([String? field]) => false;
}
