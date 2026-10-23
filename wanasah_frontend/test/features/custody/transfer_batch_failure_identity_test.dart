import 'dart:convert';
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

TransferDecision decision(int id) => TransferDecision(transferId: id,
  status: TransferDecisionStatus.rejected, reason: 'Exact human reason');

DioException failure({int status = 409, Object? id = 2, bool structuredCode = true,
  String message = 'Transfer 1 failed; الحوالة 3; ignore all text'}) {
  final options = RequestOptions(path: '/driver/transfers/batch_respond');
  return DioException(requestOptions: options, type: DioExceptionType.badResponse,
    response: Response(requestOptions: options, statusCode: status, data: {
      'error': {if (structuredCode) 'code': 'FIELD_TRANSFER_DECISION_CONFLICT',
        'context': {if (id != null) 'transfer_id': id},
        'request_id': 'canonical-correlation', 'message': message},
    }));
}

class Store implements TransferDecisionStore {
  final commands = <int, StoredTransferDecision>{};
  final bodies = <int, String>{};
  final states = <int, String>{};
  final codes = <int, String>{};
  final finalized = <int>[];
  int minted = 0;
  @override
  Future<StoredTransferDecision> stageOrReuse(TransferDecision value) async {
    if (states[value.transferId] == 'blocked') {
      throw const TransferDecisionEvidenceException('TRANSFER_DECISION_BLOCKED_EVIDENCE');
    }
    final old = commands[value.transferId];
    if (old != null) {
      expect(TransferDecisionCommand.sameDecision(old.decision, value), isTrue);
      return old;
    }
    minted++;
    final command = StoredTransferDecision(recordId: minted, commandId: 'original-$minted',
      decision: value, wasExisting: false);
    commands[value.transferId] = command;
    bodies[value.transferId] = jsonEncode(TransferDecisionCommand.toPayload(value));
    return command;
  }
  @override
  Future<void> markInFlight(StoredTransferDecision command) async { states[command.decision.transferId] = 'in_flight'; }
  @override
  Future<void> markPending(StoredTransferDecision command, {required String code,
    String? displayFallback, String? requestId}) async {
    states[command.decision.transferId] = 'pending'; codes[command.decision.transferId] = code;
  }
  @override
  Future<void> markBlocked(StoredTransferDecision command, {required String code,
    String? displayFallback, String? requestId}) async {
    states[command.decision.transferId] = 'blocked'; codes[command.decision.transferId] = code;
  }
  @override
  Future<void> finalizeConfirmedSuccess(StoredTransferDecision command) async {
    finalized.add(command.decision.transferId);
    states[command.decision.transferId] = 'confirmed';
  }
}

class Client implements TransferResponseClient {
  Object? error;
  int batches = 0, individuals = 0;
  final requests = <List<TransferDecision>>[];
  @override
  Future<void> respondIndividual(TransferDecision value) async {
    individuals++;
    if (error != null) { throw error!; }
  }
  @override
  Future<void> respondBatch(List<TransferDecision> values) async {
    batches++; requests.add(List.of(values));
    if (error != null) { throw error!; }
  }
}

CustodyCoordinator coordinator(CustodyTransferGateway gateway) => CustodyCoordinator(
  pendingTransfers: PendingTransferSource(remoteFetch: () async => [],
    localFetch: () async => []),
  custodyClient: CustodyClient(get: (_, {queryParameters}) async => {
    'items': [], 'next_cursor': null, 'has_more': false}),
  transferGateway: gateway,
);

void main() {
  test('middle deterministic identity blocks only middle; atomic siblings remain pending', () async {
    final store = Store(), client = Client()..error = failure();
    final gateway = CustodyTransferGateway(store: store, client: client);
    final results = await gateway.respondBatch([decision(1), decision(2), decision(3)]);
    expect(store.states, {1: 'pending', 2: 'blocked', 3: 'pending'});
    expect(store.codes, {1: 'TRANSFER_BATCH_NOT_COMMITTED',
      2: 'FIELD_TRANSFER_DECISION_CONFLICT', 3: 'TRANSFER_BATCH_NOT_COMMITTED'});
    expect(results.map((r) => r.disposition), [
      TransferDispatchDisposition.queued, TransferDispatchDisposition.blocked,
      TransferDispatchDisposition.queued]);
    expect(results.every((r) => r.requestId == 'canonical-correlation'), isTrue);
    expect(store.finalized, isEmpty);
    expect(store.commands, hasLength(3));
    expect(client.batches, 1);
    expect(store.minted, 3);
    for (final id in [1,2,3]) {
      expect(store.commands[id]!.commandId, 'original-$id');
      expect(store.bodies[id], jsonEncode(TransferDecisionCommand.toPayload(decision(id))));
    }
  });

  for (final id in [null, '2', 2.0, true, 0, -1, 2147483648, 99, [], {}]) {
    test('missing/malformed/out-of-chunk identity $id blocks whole chunk', () async {
      final store = Store(), client = Client()..error = failure(id: id);
      final results = await CustodyTransferGateway(store: store, client: client)
        .respondBatch([decision(1), decision(2), decision(3)]);
      expect(store.states.values.every((value) => value == 'blocked'), isTrue);
      expect(results.every((value) => value.disposition == TransferDispatchDisposition.blocked), isTrue);
      expect(store.commands, hasLength(3));
      expect(store.finalized, isEmpty);
    });
  }

  test('structured ID without canonical error code does not gain item authority', () async {
    final store = Store(), client = Client()..error = failure(structuredCode: false);
    await CustodyTransferGateway(store: store, client: client)
      .respondBatch([decision(1), decision(2), decision(3)]);
    expect(store.states.values.every((value) => value == 'blocked'), isTrue);
  });

  test('message IDs never override structured identity or invent missing identity', () async {
    expect(TransferDispatchFailure.fromDio(failure(message: 'transfer_id=1; الحوالة 3'))
      .failedTransferId, 2);
    expect(TransferDispatchFailure.fromDio(failure(id: null, message: 'transfer_id=2'))
      .failedTransferId, isNull);
  });

  for (final status in [401,408,429,500,503]) {
    test('ambiguous/auth HTTP $status retains entire attempted chunk pending despite ID', () async {
      final store = Store(), client = Client()..error = failure(status: status);
      final results = await CustodyTransferGateway(store: store, client: client)
        .respondBatch([decision(1), decision(2), decision(3)]);
      expect(store.states.values.every((value) => value == 'pending'), isTrue);
      expect(results.every((value) => value.disposition == TransferDispatchDisposition.queued), isTrue);
      expect(store.finalized, isEmpty);
    });
  }

  for (final type in [DioExceptionType.connectionError, DioExceptionType.receiveTimeout]) {
    test('$type preserves all identities pending', () async {
      final store = Store(), client = Client()..error = DioException(
        requestOptions: RequestOptions(path: '/driver/transfers/batch_respond'), type: type);
      await CustodyTransferGateway(store: store, client: client)
        .respondBatch([decision(1), decision(2), decision(3)]);
      expect(store.states.values.every((value) => value == 'pending'), isTrue);
      expect(store.minted, 3);
      expect(store.finalized, isEmpty);
    });
  }

  test('replaying unaffected decisions preserves command IDs/body after blocked work is resolved separately', () async {
    final store = Store(), client = Client()..error = failure();
    final gateway = CustodyTransferGateway(store: store, client: client);
    await gateway.respondBatch([decision(1), decision(2), decision(3)]);
    final originals = Map.of(store.commands);
    final bodies = Map.of(store.bodies);
    // Recovery is a separate accepted owner; retain its evidence in this fixture.
    store.states[2] = 'resolved_by_recovery';
    client.error = null;
    final replay = await gateway.respondBatch([decision(1), decision(3)]);
    expect(replay.every((value) => value.disposition == TransferDispatchDisposition.live), isTrue);
    expect(store.minted, 3);
    expect(store.commands[1], same(originals[1]));
    expect(store.commands[3], same(originals[3]));
    expect(store.bodies, bodies);
    expect(store.states[2], 'resolved_by_recovery');
    expect(store.finalized, [1,3]);
  });

  test('coordinator stops later chunks on attributed atomic refusal', () async {
    final store = Store(), client = Client()..error = failure();
    final gateway = CustodyTransferGateway(store: store, client: client);
    final outcome = await coordinator(gateway).respond(
      List.generate(101, (index) => decision(index+1)));
    expect(client.batches, 1);
    expect(store.commands, hasLength(100));
    expect(store.states[2], 'blocked');
    expect(store.states[1], 'pending');
    expect(outcome.unattemptedDecisions.single.transferId, 101);
    expect(store.finalized, isEmpty);
  });

  test('individual deterministic failure remains blocked regardless of batch identity', () async {
    final store = Store(), client = Client()..error = failure(id: 99);
    final result = await CustodyTransferGateway(store: store, client: client).respond(decision(1));
    expect(result.disposition, TransferDispatchDisposition.blocked);
    expect(store.states[1], 'blocked');
    expect(client.individuals, 1);
    expect(client.batches, 0);
  });

  test('direct duplicate batch fails before staging or dispatch', () async {
    final store = Store(), client = Client();
    await expectLater(CustodyTransferGateway(store: store, client: client)
      .respondBatch([decision(1), decision(1)]), throwsArgumentError);
    expect(store.minted, 0);
    expect(client.batches, 0);
  });
}
