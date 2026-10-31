import 'package:wanasah_frontend/core/network/api_client.dart';

import '../data/custody_client.dart';
import '../data/pending_return_custody_source.dart';
import '../data/pending_transfer_source.dart';
import '../data/transfer_response_client.dart';
import '../data/transfer_response_gateway.dart';
import '../domain/non_sellable_custody.dart';
import '../domain/pending_return_custody.dart';
import '../domain/pending_transfer.dart';
import '../domain/transfer_decision.dart';
import 'custody_outcome.dart';

class CustodyCoordinator {
  CustodyCoordinator({
    required PendingTransferSource pendingTransfers,
    required CustodyClient custodyClient,
    required TransferDispatchGateway transferGateway,
    PendingReturnCustodySource? pendingReturnCustody,
  }) : _pendingTransfers = pendingTransfers,
       _custodyClient = custodyClient,
       _transferGateway = transferGateway,
       _pendingReturnCustody =
           pendingReturnCustody ??
           LocalPendingReturnCustodySource.withDatabase();

  factory CustodyCoordinator.defaults() => CustodyCoordinator(
        pendingTransfers: PendingTransferSource.defaults(),
        custodyClient: CustodyClient.withApiClient(ApiClient.instance),
        transferGateway: CustodyTransferGateway(),
        pendingReturnCustody: LocalPendingReturnCustodySource.withDatabase(),
      );

  static const int transferBatchMaximum =
      ApiTransferResponseClient.runtimeBatchMaximum;

  final PendingTransferSource _pendingTransfers;
  final CustodyClient _custodyClient;
  final TransferDispatchGateway _transferGateway;
  final PendingReturnCustodySource _pendingReturnCustody;

  Future<PendingTransferBatch?> loadPendingTransfers() =>
      _pendingTransfers.load();

  Future<List<NonSellableCustodyItem>> loadNonSellableCustody() async {
    // Cursor is opaque and session-bound. Never return partial pages.
    final items = <NonSellableCustodyItem>[];
    final seenCursors = <String>{};
    int? sessionId;
    String? cursor;
    var pages = 0;
    do {
      if (++pages > 10000) {
        throw const FormatException('Custody pagination limit exceeded');
      }
      final page = await _custodyClient.custody(
        query: CustodyQuery(limit: 100, cursor: cursor),
      );
      if (sessionId != null && sessionId != page.sessionId) {
        throw const FormatException('Custody session changed between pages');
      }
      sessionId = page.sessionId;
      items.addAll(page.items);
      cursor = page.nextCursor;
      if (cursor != null && !seenCursors.add(cursor)) {
        throw const FormatException('Repeated custody cursor');
      }
    } while (cursor != null);
    return List.unmodifiable(items);
  }

  Future<List<PendingReturnCustodyItem>> loadPendingReturnCustody() =>
      _pendingReturnCustody.read();

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

    if (decisions.length == 1) {
      return CustodyResponseOutcome(
        <TransferDispatchResult>[
          await _transferGateway.respond(decisions.single),
        ],
      );
    }

    final results = <TransferDispatchResult>[];
    var offset = 0;

    while (offset < decisions.length) {
      final end =
          (offset + transferBatchMaximum < decisions.length)
              ? offset + transferBatchMaximum
              : decisions.length;
      final chunk = decisions.sublist(offset, end);
      final chunkResults = await _transferGateway.respondBatch(chunk);
      results.addAll(chunkResults);

      final unresolved = chunkResults.any(
        (result) =>
            result.disposition != TransferDispatchDisposition.live,
      );
      if (unresolved) {
        return CustodyResponseOutcome(
          results,
          unattemptedDecisions:
              decisions.sublist(end).toList(growable: false),
        );
      }

      offset = end;
    }

    return CustodyResponseOutcome(results);
  }
}
