import 'package:wanasah_frontend/core/network/api_client.dart';

import '../data/custody_client.dart';
import '../data/pending_transfer_source.dart';
import '../data/transfer_response_gateway.dart';
import '../domain/non_sellable_custody.dart';
import '../domain/pending_transfer.dart';
import '../domain/transfer_decision.dart';
import 'custody_outcome.dart';

class CustodyCoordinator {
  CustodyCoordinator({
    required PendingTransferSource pendingTransfers,
    required CustodyClient custodyClient,
    required CustodyTransferGateway transferGateway,
  })  : _pendingTransfers = pendingTransfers,
        _custodyClient = custodyClient,
        _transferGateway = transferGateway;

  factory CustodyCoordinator.defaults() => CustodyCoordinator(
        pendingTransfers: PendingTransferSource.defaults(),
        custodyClient: CustodyClient.withApiClient(ApiClient.instance),
        transferGateway: CustodyTransferGateway(),
      );

  final PendingTransferSource _pendingTransfers;
  final CustodyClient _custodyClient;
  final CustodyTransferGateway _transferGateway;

  Future<PendingTransferBatch?> loadPendingTransfers() =>
      _pendingTransfers.load();

  Future<List<NonSellableCustodyItem>> loadNonSellableCustody() async {
    final page = await _custodyClient.custody();
    return page.items;
  }

  Future<CustodyResponseOutcome> respond(
    List<TransferDecision> decisions,
  ) async {
    if (decisions.isEmpty) {
      return CustodyResponseOutcome(const <TransferDispatchResult>[]);
    }

    final ids = decisions.map((decision) => decision.transferId).toList();
    if (ids.toSet().length != ids.length) {
      throw ArgumentError('Duplicate transfer decision.');
    }

    final results = <TransferDispatchResult>[];
    for (final decision in decisions) {
      results.add(await _transferGateway.respond(decision));
    }
    return CustodyResponseOutcome(results);
  }
}
