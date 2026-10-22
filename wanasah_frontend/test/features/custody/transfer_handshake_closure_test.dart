import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/application/custody_coordinator.dart';
import 'package:wanasah_frontend/features/custody/application/transfer_dispatch_failure.dart';
import 'package:wanasah_frontend/features/custody/data/custody_client.dart';
import 'package:wanasah_frontend/features/custody/data/pending_transfer_source.dart';
import 'package:wanasah_frontend/features/custody/data/transfer_decision_store.dart';
import 'package:wanasah_frontend/features/custody/data/transfer_response_client.dart';
import 'package:wanasah_frontend/features/custody/data/transfer_response_gateway.dart';
import 'package:wanasah_frontend/features/custody/domain/transfer_decision.dart';
import 'package:wanasah_frontend/features/custody/domain/transfer_decision_command.dart';

void main() {
  group('live Backend transfer contract characterization', () {
    test('Flutter runtime batch cap matches live Backend runtime cap', () async {
      final backend = await File('../wa_backend/api/driver.py').readAsString();
      final schemas = await File('../wa_backend/schemas.py').readAsString();

      expect(
        ApiTransferResponseClient.runtimeBatchMaximum,
        100,
      );
      expect(
        backend,
        contains('if len(payload.transfers) > 100:'),
      );
      expect(
        backend,
        contains('status_code=413'),
      );
      expect(
        schemas,
        contains(
          'transfers: List[BatchTransferItem] = '
          'Field(..., min_length=1, max_length=200)',
        ),
      );
    });

    test('Backend state-idempotency protects exact accepted/rejected replay',
        () async {
      final backend = await File('../wa_backend/api/driver.py').readAsString();

      expect(
        backend,
        contains(
          'response == "accepted" and header.status == "POSTED"',
        ),
      );
      expect(
        backend,
        contains(
          'response == "rejected" and header.status == "REJECTED"',
        ),
      );
      expect(
        backend,
        contains('reason == (header.decision_reason or "").strip()'),
      );
      expect(
        backend,
        contains('request_item.status == "rejected" and not reason'),
      );
    });

    test('pending response exposes real transfer ID per item', () async {
      final backend = await File('../wa_backend/api/driver.py').readAsString();

      expect(
        backend,
        contains('"real_transfer_id": int(header.id)'),
      );
    });
  });

  group('exact transfer identity and decision payload', () {
    test('accepted decision uses real positive ID and carries no reason', () {
      final decision = TransferDecision(
        transferId: 41,
        status: TransferDecisionStatus.accepted,
        reason: 'ignored',
      );
      final payload = TransferDecisionCommand.toPayload(decision);

      expect(payload['transferId'], 41);
      expect(payload['response'], 'accepted');
      expect(payload['reason'], isNull);
    });

    test('rejected decision preserves exact normalized reason', () {
      final decision = TransferDecision(
        transferId: 42,
        status: TransferDecisionStatus.rejected,
        reason: '  الكمية غير مطابقة  ',
      );
      final payload = TransferDecisionCommand.toPayload(decision);
      final replay = TransferDecisionCommand.fromPayload(payload);

      expect(decision.reason, 'الكمية غير مطابقة');
      expect(replay.transferId, 42);
      expect(replay.status, TransferDecisionStatus.rejected);
      expect(replay.reason, 'الكمية غير مطابقة');
    });

    test('invalid zero transfer ID fails closed', () {
      expect(
        () => TransferDecision(
          transferId: 0,
          status: TransferDecisionStatus.accepted,
        ),
        throwsArgumentError,
      );
    });
  });

  group('individual durable dispatch', () {
    test('accepted individual transfer live success finalizes once', () async {
      final store = _MemoryTransferDecisionStore();
      final client = _ScriptedTransferResponseClient();
      final gateway = CustodyTransferGateway(
        store: store,
        client: client,
      );
      final decision = TransferDecision(
        transferId: 51,
        status: TransferDecisionStatus.accepted,
      );

      final result = await gateway.respond(decision);

      expect(result.disposition, TransferDispatchDisposition.live);
      expect(client.individualCalls, <TransferDecision>[decision]);
      expect(store.createdCount, 1);
      expect(store.finalizedIds, <int>[51]);
      expect(store.pendingIds, isEmpty);
      expect(store.blockedIds, isEmpty);
    });

    test('rejected individual sends exact normalized reason', () async {
      final store = _MemoryTransferDecisionStore();
      final client = _ScriptedTransferResponseClient();
      final gateway = CustodyTransferGateway(
        store: store,
        client: client,
      );
      final decision = TransferDecision(
        transferId: 52,
        status: TransferDecisionStatus.rejected,
        reason: '  العبوة تالفة  ',
      );

      final result = await gateway.respond(decision);

      expect(result.disposition, TransferDispatchDisposition.live);
      expect(client.individualCalls.single.transferId, 52);
      expect(
        client.individualCalls.single.status,
        TransferDecisionStatus.rejected,
      );
      expect(client.individualCalls.single.reason, 'العبوة تالفة');
    });

    test('ambiguous individual response keeps exact decision queued', () async {
      final store = _MemoryTransferDecisionStore();
      final client = _ScriptedTransferResponseClient(
        individualErrors: <Object?>[
          DioException(
            requestOptions: RequestOptions(
              path: '/driver/transfers/53/respond',
            ),
            type: DioExceptionType.connectionError,
            message: 'human text does not classify',
          ),
        ],
      );
      final gateway = CustodyTransferGateway(
        store: store,
        client: client,
      );
      final decision = TransferDecision(
        transferId: 53,
        status: TransferDecisionStatus.rejected,
        reason: 'نقص فعلي',
      );

      final result = await gateway.respond(decision);

      expect(result.disposition, TransferDispatchDisposition.queued);
      expect(store.createdCount, 1);
      expect(store.pendingIds, <int>[53]);
      expect(store.finalizedIds, isEmpty);
      final stored = store.byTransferId[53]!.decision;
      expect(stored.transferId, 53);
      expect(stored.status, TransferDecisionStatus.rejected);
      expect(stored.reason, 'نقص فعلي');
    });

    test('accepted state-idempotent replay reuses evidence and finalizes once',
        () async {
      final store = _MemoryTransferDecisionStore();
      final client = _ScriptedTransferResponseClient(
        individualErrors: <Object?>[
          DioException(
            requestOptions: RequestOptions(
              path: '/driver/transfers/54/respond',
            ),
            type: DioExceptionType.receiveTimeout,
          ),
          null,
        ],
      );
      final gateway = CustodyTransferGateway(
        store: store,
        client: client,
      );
      final decision = TransferDecision(
        transferId: 54,
        status: TransferDecisionStatus.accepted,
      );

      final first = await gateway.respond(decision);
      final second = await gateway.respond(decision);

      expect(first.disposition, TransferDispatchDisposition.queued);
      expect(second.disposition, TransferDispatchDisposition.live);
      expect(store.createdCount, 1);
      expect(store.finalizedIds, <int>[54]);
      expect(client.individualCalls, hasLength(2));
      for (final replayed in client.individualCalls) {
        expect(replayed.transferId, 54);
        expect(replayed.status, TransferDecisionStatus.accepted);
        expect(replayed.reason, isNull);
      }
    });

    test('rejected state-idempotent replay preserves exact reason', () async {
      final store = _MemoryTransferDecisionStore();
      final client = _ScriptedTransferResponseClient(
        individualErrors: <Object?>[
          DioException(
            requestOptions: RequestOptions(
              path: '/driver/transfers/55/respond',
            ),
            type: DioExceptionType.sendTimeout,
          ),
          null,
        ],
      );
      final gateway = CustodyTransferGateway(
        store: store,
        client: client,
      );
      final decision = TransferDecision(
        transferId: 55,
        status: TransferDecisionStatus.rejected,
        reason: '  اختلاف الكمية  ',
      );

      final first = await gateway.respond(decision);
      final second = await gateway.respond(decision);

      expect(first.disposition, TransferDispatchDisposition.queued);
      expect(second.disposition, TransferDispatchDisposition.live);
      expect(store.createdCount, 1);
      expect(store.finalizedIds, <int>[55]);
      expect(
        client.individualCalls.map((item) => item.reason).toList(),
        <String?>['اختلاف الكمية', 'اختلاف الكمية'],
      );
    });

    test('conflicting replay decision fails closed before a second command',
        () async {
      final store = _MemoryTransferDecisionStore();
      final client = _ScriptedTransferResponseClient(
        individualErrors: <Object?>[
          DioException(
            requestOptions: RequestOptions(
              path: '/driver/transfers/56/respond',
            ),
            type: DioExceptionType.connectionError,
          ),
        ],
      );
      final gateway = CustodyTransferGateway(
        store: store,
        client: client,
      );

      await gateway.respond(
        TransferDecision(
          transferId: 56,
          status: TransferDecisionStatus.accepted,
        ),
      );

      await expectLater(
        gateway.respond(
          TransferDecision(
            transferId: 56,
            status: TransferDecisionStatus.rejected,
            reason: 'قرار مختلف',
          ),
        ),
        throwsA(isA<TransferDecisionEvidenceException>()),
      );
      expect(store.createdCount, 1);
    });
  });

  group('typed failures never inspect localized text', () {
    test('different 409 human messages produce the same blocked classification',
        () {
      final first = TransferDispatchFailure.fromDio(
        _responseError(409, 'رسالة عربية'),
      );
      final second = TransferDispatchFailure.fromDio(
        _responseError(409, 'Completely different English message'),
      );

      expect(first.kind, TransferDispatchFailureKind.blocked);
      expect(second.kind, TransferDispatchFailureKind.blocked);
      expect(first.code, 'HTTP_409');
      expect(second.code, 'HTTP_409');
    });

    test('5xx stays unresolved regardless of free text', () {
      final failure = TransferDispatchFailure.fromDio(
        _responseError(500, 'تم اعتماد القرار بنجاح'),
      );

      expect(failure.kind, TransferDispatchFailureKind.unresolved);
      expect(failure.code, 'HTTP_500');
    });

    test('401 stays unresolved for authenticated replay rather than blocked',
        () {
      final failure = TransferDispatchFailure.fromDio(
        _responseError(401, 'anything'),
      );

      expect(failure.kind, TransferDispatchFailureKind.unresolved);
      expect(failure.code, 'AUTH_REQUIRED');
    });
  });

  group('batch limit, chunking and ordering', () {
    test('exactly server maximum is one ordered batch of 100', () async {
      final gateway = _RecordingDispatchGateway();
      final coordinator = _coordinator(gateway);
      final decisions = _decisions(1, 100);

      final outcome = await coordinator.respond(decisions);

      expect(gateway.batchCalls, hasLength(1));
      expect(
        gateway.batchCalls.single.map((d) => d.transferId).toList(),
        List<int>.generate(100, (index) => index + 1),
      );
      expect(outcome.allConfirmed, isTrue);
    });

    test('more than maximum splits into deterministic bounded chunks',
        () async {
      final gateway = _RecordingDispatchGateway();
      final coordinator = _coordinator(gateway);
      final decisions = _decisions(1, 205);

      final outcome = await coordinator.respond(decisions);

      expect(
        gateway.batchCalls.map((chunk) => chunk.length).toList(),
        <int>[100, 100, 5],
      );
      expect(
        gateway.batchCalls.expand((chunk) => chunk).map((d) => d.transferId),
        List<int>.generate(205, (index) => index + 1),
      );
      expect(outcome.allConfirmed, isTrue);
    });

    test('ambiguous middle chunk stops and leaves later decisions unattempted',
        () async {
      final gateway = _RecordingDispatchGateway(
        batchDispositions: <TransferDispatchDisposition>[
          TransferDispatchDisposition.live,
          TransferDispatchDisposition.queued,
        ],
      );
      final coordinator = _coordinator(gateway);

      final outcome = await coordinator.respond(_decisions(1, 250));

      expect(
        gateway.batchCalls.map((chunk) => chunk.length).toList(),
        <int>[100, 100],
      );
      expect(outcome.anyQueued, isTrue);
      expect(outcome.allConfirmed, isFalse);
      expect(outcome.unattemptedDecisions, hasLength(50));
      expect(
        outcome.unattemptedDecisions.first.transferId,
        201,
      );
      expect(
        outcome.unattemptedDecisions.last.transferId,
        250,
      );
    });

    test('duplicate transfer decisions are rejected before dispatch', () async {
      final gateway = _RecordingDispatchGateway();
      final coordinator = _coordinator(gateway);

      await expectLater(
        coordinator.respond(
          <TransferDecision>[
            TransferDecision(
              transferId: 77,
              status: TransferDecisionStatus.accepted,
            ),
            TransferDecision(
              transferId: 77,
              status: TransferDecisionStatus.accepted,
            ),
          ],
        ),
        throwsArgumentError,
      );
      expect(gateway.batchCalls, isEmpty);
      expect(gateway.individualCalls, isEmpty);
    });
  });

  group('architecture and durable evidence invariants', () {
    test('Custody gateway stages before send and never imports SyncRepository',
        () async {
      final source = await File(
        'lib/features/custody/data/transfer_response_gateway.dart',
      ).readAsString();

      expect(source, contains('stageOrReuse(decision)'));
      expect(source, contains('markInFlight'));
      expect(source, contains('finalizeConfirmedSuccess'));
      expect(source, isNot(contains('SyncRepository')));
      expect(source, isNot(contains('message.contains')));
    });

    test('Dashboard does not hide queued transfer evidence as completed',
        () async {
      final source = await File(
        'lib/blocs/dashboard/dashboard_bloc.dart',
      ).readAsString();

      expect(source, contains('outcome.anyQueued || outcome.hasUnattempted'));
      expect(source, contains('add(const CheckPendingTransfers())'));
      expect(
        source,
        contains('بقي القرار محفوظاً للاسترداد'),
      );
    });

    test('legacy SyncRepository remains the single replay engine', () async {
      final source = await File(
        'lib/repositories/sync_repository.dart',
      ).readAsString();

      expect(
        source,
        contains('case DurableCommandType.transferResponse:'),
      );
      expect(
        source,
        contains("'/driver/transfers/$tId/respond'"),
      );
      expect(
        source,
        contains('await _db.deletePendingSync(recordId)'),
      );
    });
  });
}

CustodyCoordinator _coordinator(TransferDispatchGateway gateway) {
  return CustodyCoordinator(
    pendingTransfers: PendingTransferSource(
      remoteFetch: () async => const <Object?>[],
      localFetch: () async => const <Map<String, dynamic>>[],
    ),
    custodyClient: CustodyClient(
      get: (path, {queryParameters}) async => <String, dynamic>{
        'items': <Object?>[],
        'next_cursor': null,
        'has_more': false,
      },
    ),
    transferGateway: gateway,
  );
}

List<TransferDecision> _decisions(int startId, int count) {
  return List<TransferDecision>.generate(
    count,
    (index) => TransferDecision(
      transferId: startId + index,
      status:
          index.isEven
              ? TransferDecisionStatus.accepted
              : TransferDecisionStatus.rejected,
      reason: index.isEven ? null : 'reason-${startId + index}',
    ),
  );
}

DioException _responseError(int status, String message) {
  final options = RequestOptions(path: '/driver/transfers/1/respond');
  return DioException(
    requestOptions: options,
    response: Response<Object?>(
      requestOptions: options,
      statusCode: status,
      data: <String, dynamic>{'detail': message},
    ),
    type: DioExceptionType.badResponse,
  );
}

class _MemoryTransferDecisionStore implements TransferDecisionStore {
  final Map<int, StoredTransferDecision> byTransferId =
      <int, StoredTransferDecision>{};
  final List<int> pendingIds = <int>[];
  final List<int> blockedIds = <int>[];
  final List<int> finalizedIds = <int>[];
  int createdCount = 0;

  @override
  Future<StoredTransferDecision> stageOrReuse(
    TransferDecision decision,
  ) async {
    final existing = byTransferId[decision.transferId];
    if (existing != null) {
      if (!TransferDecisionCommand.sameDecision(
        existing.decision,
        decision,
      )) {
        throw const TransferDecisionEvidenceException(
          'TRANSFER_DECISION_CONFLICT',
        );
      }
      return StoredTransferDecision(
        recordId: existing.recordId,
        commandId: existing.commandId,
        decision: existing.decision,
        wasExisting: true,
      );
    }

    createdCount += 1;
    final command = StoredTransferDecision(
      recordId: createdCount,
      commandId: 'command-$createdCount',
      decision: decision,
      wasExisting: false,
    );
    byTransferId[decision.transferId] = command;
    return command;
  }

  @override
  Future<void> markInFlight(StoredTransferDecision command) async {
    pendingIds.remove(command.decision.transferId);
  }

  @override
  Future<void> markPending(
    StoredTransferDecision command, {
    required String code,
    String? displayFallback,
    String? requestId,
  }) async {
    if (!pendingIds.contains(command.decision.transferId)) {
      pendingIds.add(command.decision.transferId);
    }
  }

  @override
  Future<void> markBlocked(
    StoredTransferDecision command, {
    required String code,
    String? displayFallback,
    String? requestId,
  }) async {
    if (!blockedIds.contains(command.decision.transferId)) {
      blockedIds.add(command.decision.transferId);
    }
  }

  @override
  Future<void> finalizeConfirmedSuccess(
    StoredTransferDecision command,
  ) async {
    pendingIds.remove(command.decision.transferId);
    blockedIds.remove(command.decision.transferId);
    finalizedIds.add(command.decision.transferId);
    byTransferId.remove(command.decision.transferId);
  }
}

class _ScriptedTransferResponseClient implements TransferResponseClient {
  _ScriptedTransferResponseClient({
    List<Object?> individualErrors = const <Object?>[],
  }) : _individualErrors = List<Object?>.from(individualErrors);

  final List<Object?> _individualErrors;
  final List<TransferDecision> individualCalls = <TransferDecision>[];
  final List<List<TransferDecision>> batchCalls =
      <List<TransferDecision>>[];

  @override
  Future<void> respondIndividual(TransferDecision decision) async {
    individualCalls.add(decision);
    if (_individualErrors.isNotEmpty) {
      final error = _individualErrors.removeAt(0);
      if (error != null) throw error;
    }
  }

  @override
  Future<void> respondBatch(List<TransferDecision> decisions) async {
    batchCalls.add(List<TransferDecision>.from(decisions));
  }
}

class _RecordingDispatchGateway implements TransferDispatchGateway {
  _RecordingDispatchGateway({
    List<TransferDispatchDisposition> batchDispositions =
        const <TransferDispatchDisposition>[],
  }) : _batchDispositions =
           List<TransferDispatchDisposition>.from(batchDispositions);

  final List<TransferDispatchDisposition> _batchDispositions;
  final List<TransferDecision> individualCalls = <TransferDecision>[];
  final List<List<TransferDecision>> batchCalls =
      <List<TransferDecision>>[];

  @override
  Future<TransferDispatchResult> respond(
    TransferDecision decision,
  ) async {
    individualCalls.add(decision);
    return TransferDispatchResult(
      decision: decision,
      disposition: TransferDispatchDisposition.live,
    );
  }

  @override
  Future<List<TransferDispatchResult>> respondBatch(
    List<TransferDecision> decisions,
  ) async {
    batchCalls.add(List<TransferDecision>.from(decisions));
    final disposition =
        _batchDispositions.isEmpty
            ? TransferDispatchDisposition.live
            : _batchDispositions.removeAt(0);

    return decisions
        .map(
          (decision) => TransferDispatchResult(
            decision: decision,
            disposition: disposition,
          ),
        )
        .toList(growable: false);
  }
}
