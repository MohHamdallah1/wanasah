import '../data/transfer_response_gateway.dart';
import '../domain/non_sellable_custody.dart';
import '../domain/pending_transfer.dart';
import '../domain/transfer_decision.dart';

class CustodySnapshot {
  const CustodySnapshot({
    required this.pendingTransfer,
    required this.nonSellableItems,
  });

  final PendingTransferBatch? pendingTransfer;
  final List<NonSellableCustodyItem> nonSellableItems;
}

class CustodyResponseOutcome {
  CustodyResponseOutcome(
    List<TransferDispatchResult> results, {
    List<TransferDecision> unattemptedDecisions =
        const <TransferDecision>[],
  }) : results = List.unmodifiable(results),
       unattemptedDecisions = List.unmodifiable(unattemptedDecisions);

  final List<TransferDispatchResult> results;
  final List<TransferDecision> unattemptedDecisions;

  bool get anyQueued => results.any(
        (result) =>
            result.disposition == TransferDispatchDisposition.queued,
      );

  bool get anyBlocked => results.any(
        (result) =>
            result.disposition == TransferDispatchDisposition.blocked,
      );

  bool get hasUnattempted => unattemptedDecisions.isNotEmpty;

  bool get allConfirmed =>
      results.isNotEmpty && !anyQueued && !anyBlocked && !hasUnattempted;

  bool get allLive => allConfirmed;
}
