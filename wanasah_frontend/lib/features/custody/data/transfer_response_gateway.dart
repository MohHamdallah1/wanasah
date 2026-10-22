import 'package:dio/dio.dart';

import '../application/transfer_dispatch_failure.dart';
import '../domain/transfer_decision.dart';
import 'transfer_decision_store.dart';
import 'transfer_response_client.dart';

enum TransferDispatchDisposition {
  live,
  queued,
  blocked,
}

class TransferDispatchResult {
  const TransferDispatchResult({
    required this.decision,
    required this.disposition,
    this.failureCode,
    this.requestId,
  });

  final TransferDecision decision;
  final TransferDispatchDisposition disposition;
  final String? failureCode;
  final String? requestId;
}

abstract interface class TransferDispatchGateway {
  Future<TransferDispatchResult> respond(TransferDecision decision);

  Future<List<TransferDispatchResult>> respondBatch(
    List<TransferDecision> decisions,
  );
}

class CustodyTransferGateway implements TransferDispatchGateway {
  CustodyTransferGateway({
    TransferResponseClient? client,
    TransferDecisionStore? store,
  }) : _client = client ?? ApiTransferResponseClient(),
       _store = store ?? LocalTransferDecisionStore();

  final TransferResponseClient _client;
  final TransferDecisionStore _store;

  @override
  Future<TransferDispatchResult> respond(
    TransferDecision decision,
  ) async {
    final commands = <StoredTransferDecision>[
      await _store.stageOrReuse(decision),
    ];
    final results = await _dispatch(
      commands,
      () => _client.respondIndividual(decision),
    );
    return results.single;
  }

  @override
  Future<List<TransferDispatchResult>> respondBatch(
    List<TransferDecision> decisions,
  ) async {
    if (decisions.isEmpty ||
        decisions.length > ApiTransferResponseClient.runtimeBatchMaximum) {
      throw ArgumentError.value(
        decisions.length,
        'decisions',
        'Transfer batch must contain 1..'
            '${ApiTransferResponseClient.runtimeBatchMaximum} decisions.',
      );
    }

    final commands = <StoredTransferDecision>[];
    for (final decision in decisions) {
      commands.add(await _store.stageOrReuse(decision));
    }

    return _dispatch(
      commands,
      () => _client.respondBatch(decisions),
    );
  }

  Future<List<TransferDispatchResult>> _dispatch(
    List<StoredTransferDecision> commands,
    Future<void> Function() send,
  ) async {
    for (final command in commands) {
      await _store.markInFlight(command);
    }

    try {
      await send();
      final results = <TransferDispatchResult>[];
      for (final command in commands) {
        await _store.finalizeConfirmedSuccess(command);
        results.add(
          TransferDispatchResult(
            decision: command.decision,
            disposition: TransferDispatchDisposition.live,
          ),
        );
      }
      return results;
    } on DioException catch (error) {
      final failure = TransferDispatchFailure.fromDio(error);
      final disposition =
          failure.kind == TransferDispatchFailureKind.unresolved
              ? TransferDispatchDisposition.queued
              : TransferDispatchDisposition.blocked;

      for (final command in commands) {
        if (failure.kind == TransferDispatchFailureKind.unresolved) {
          await _store.markPending(
            command,
            code: failure.code,
            displayFallback: failure.displayFallback,
            requestId: failure.requestId,
          );
        } else {
          await _store.markBlocked(
            command,
            code: failure.code,
            displayFallback: failure.displayFallback,
            requestId: failure.requestId,
          );
        }
      }

      return commands
          .map(
            (command) => TransferDispatchResult(
              decision: command.decision,
              disposition: disposition,
              failureCode: failure.code,
              requestId: failure.requestId,
            ),
          )
          .toList(growable: false);
    } catch (_) {
      const code = 'TRANSFER_DISPATCH_UNRESOLVED';
      for (final command in commands) {
        await _store.markPending(command, code: code);
      }

      return commands
          .map(
            (command) => TransferDispatchResult(
              decision: command.decision,
              disposition: TransferDispatchDisposition.queued,
              failureCode: code,
            ),
          )
          .toList(growable: false);
    }
  }
}
