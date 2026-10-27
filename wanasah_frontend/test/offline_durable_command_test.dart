import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/sync/durable_command.dart';

void main() {
  group('DurableCommandState', () {
    test('parses persisted lifecycle values and fails legacy rows to pending', () {
      expect(
        DurableCommandState.fromStorage('pending'),
        DurableCommandState.pending,
      );
      expect(
        DurableCommandState.fromStorage('in_flight'),
        DurableCommandState.inFlight,
      );
      expect(
        DurableCommandState.fromStorage('blocked'),
        DurableCommandState.blocked,
      );
      expect(
        DurableCommandState.fromStorage(null),
        DurableCommandState.pending,
      );
    });
  });

  group('DurableCommandType', () {
    test('normalizes legacy quarantine names without inventing replayability', () {
      expect(
        DurableCommandType.normalizeLegacyType('quarantined_draft_sale'),
        DurableCommandType.submitSale,
      );
      expect(
        DurableCommandType.normalizeLegacyType('quarantined_corrupt'),
        DurableCommandType.corrupt,
      );
      expect(
        DurableCommandType.isReplayable('quarantined_submit_sale'),
        isTrue,
      );
      expect(
        DurableCommandType.isReplayable('quarantined_transfer_response'),
        isTrue,
      );
      expect(
        DurableCommandType.isReplayable('quarantined_corrupt'),
        isFalse,
      );
      expect(
        DurableCommandType.isTemporal('toggle_break'),
        isTrue,
      );
    });

    test('blocked and legacy rows remain unresolved owner evidence', () {
      expect(
        isUnresolvedOfflineCommand(<String, dynamic>{
          'type': 'submit_sale',
          'state': 'blocked',
        }),
        isTrue,
      );
      expect(
        isUnresolvedOfflineCommand(<String, dynamic>{
          'type': 'quarantined_submit_sale',
        }),
        isTrue,
      );
      expect(
        isUnresolvedOfflineCommand(<String, dynamic>{
          'type': 'submit_sale',
          'state': 'reconciled',
        }),
        isFalse,
      );
    });
  });

  group('Offline V1 source invariants', () {
    test('database migration preserves command evidence and has no bulk clear', () async {
      final source =
          await File('lib/core/db/local_database.dart').readAsString();

      expect(source, contains('version: 11'));
      expect(source, contains('ALTER TABLE incoming_transfers ADD COLUMN'));
      expect(source, contains("DEFAULT 'pending'"));
      expect(source, contains('owner_company_code'));
      expect(source, contains('attempt_count'));
      expect(
        source,
        contains('Offline command evidence cannot be bulk-deleted'),
      );
      expect(
        source,
        contains("UPDATE pending_sync SET state = ? WHERE type LIKE 'quarantined_%'"),
      );
      expect(
        source,
        contains("SELECT COUNT(*) FROM pending_sync"),
      );
    });

    test('visit identity is durable before first mutation send', () async {
      final source =
          await File('lib/repositories/sync_repository.dart').readAsString();

      final stageIndex = source.indexOf('stageVisitCommandAtomic(');
      final firstDispatchAfterStage =
          source.indexOf('_dispatchPendingRecord(', stageIndex);
      expect(stageIndex, greaterThanOrEqualTo(0));
      expect(firstDispatchAfterStage, greaterThan(stageIndex));
      expect(source, contains('isFirstUnresolvedCommand'));
      expect(source, contains('markPendingSyncInFlight'));
      expect(
        source,
        contains('_visitReplay.finalizeLocalState'),
      );
    });

    test('local visit projection is marked exactly once before command deletion', () async {
      final dbSource =
          await File('lib/core/db/local_database.dart').readAsString();
      final visitPersistence = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();
      final syncSource =
          await File('lib/repositories/sync_repository.dart').readAsString();

      expect(dbSource, contains('local_effect_applied INTEGER NOT NULL DEFAULT 0'));
      expect(visitPersistence, contains("'local_effect_applied': 1"));
      expect(
        dbSource,
        contains('Unresolved visit commands are immutable until reconciliation'),
      );

      final replayDispatch =
          syncSource.indexOf('await _dispatchPendingRecord(type: type, payload: payload);');
      final replayFinalize =
          syncSource.indexOf('_visitReplay.finalizeLocalState(', replayDispatch);
      final replayDelete =
          syncSource.indexOf('await _db.deletePendingSync(recordId);', replayFinalize);
      expect(replayDispatch, greaterThanOrEqualTo(0));
      expect(replayFinalize, greaterThan(replayDispatch));
      expect(replayDelete, greaterThan(replayFinalize));
    });

    test('sync engine never deletes unknown, stale break, or rejected evidence', () async {
      final source =
          await File('lib/repositories/sync_repository.dart').readAsString();

      expect(source, contains('UNKNOWN_OFFLINE_COMMAND'));
      expect(source, contains('STALE_TEMPORAL_COMMAND'));
      expect(source, contains('CORRUPT_OFFLINE_PAYLOAD'));
      expect(source, contains('markPendingSyncBlocked'));
      expect(source, isNot(contains("errorMessage.contains('تم تسويتها')")));
      expect(
        source,
        isNot(contains("statusCode == 400 && type == 'toggle_break'")),
      );
      expect(
        source,
        isNot(contains('Poison Pill detected: Unknown type')),
      );
    });

    test('break repository no longer creates deferred break commands', () async {
      final source =
          await File('lib/repositories/dashboard_repository.dart').readAsString();

      expect(source, contains("'/driver/sessions/break'"));
      expect(source, isNot(contains("type: 'toggle_break'")));
      expect(source, isNot(contains('isQueuedOffline')));
    });

    test('field UI has no quarantine deletion event or destructive action', () async {
      final eventSource =
          await File('lib/blocs/dashboard/dashboard_event.dart').readAsString();
      final screenSource =
          await File('lib/screens/dashboard_screen.dart').readAsString();

      expect(eventSource, isNot(contains('ClearQuarantineEvent')));
      expect(screenSource, isNot(contains('ClearQuarantineEvent')));
      expect(
        screenSource,
        isNot(contains('مسح السجلات')),
      );
      expect(
        screenSource,
        contains('لا يمكن حذفها من تطبيق المندوب'),
      );
    });
  });
}
