import '../domain/non_sellable_custody.dart';
import '../domain/pending_transfer.dart';
import '../data/transfer_response_gateway.dart';

class CustodySnapshot {
  const CustodySnapshot({
    required this.pendingTransfer,
    required this.nonSellableItems,
  });

  final PendingTransferBatch? pendingTransfer;
  final List<NonSellableCustodyItem> nonSellableItems;
}

class CustodyResponseOutcome {
  CustodyResponseOutcome(List<TransferDispatchResult> results)
      : results = List.unmodifiable(results);

  final List<TransferDispatchResult> results;

  bool get anyQueued => results.any(
        (result) =>
            result.disposition == TransferDispatchDisposition.queued,
      );

  bool get allLive => results.isNotEmpty && !anyQueued;
}
