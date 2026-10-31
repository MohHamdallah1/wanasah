import 'package:flutter/material.dart';

import '../../../models/product_model.dart';
import '../../../l10n/generated/app_localizations.dart';
import '../domain/stock_disclosure.dart';
import '../domain/non_sellable_custody.dart';
import '../domain/pending_return_custody.dart';

class VehicleInventorySection extends StatelessWidget {
  const VehicleInventorySection({
    required this.products,
    required this.nonSellableCustody,
    this.pendingReturnCustody = const <PendingReturnCustodyItem>[],
    this.sellableDisclosure = StockDisclosure.unavailable,
    this.nonSellableDisclosure = StockDisclosure.unavailable,
    super.key,
  });

  final List<ProductModel> products;
  final List<NonSellableCustodyItem> nonSellableCustody;
  final List<PendingReturnCustodyItem> pendingReturnCustody;
  final StockDisclosure sellableDisclosure;
  final StockDisclosure nonSellableDisclosure;

  @override
  Widget build(BuildContext context) {
    final l10n = AppLocalizations.of(context);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const SizedBox(height: 20),
        const Divider(height: 30, thickness: 1),
        Text(
          l10n.stockVehicleTitle,
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        if (sellableDisclosure != StockDisclosure.verified)
          _disclosureNotice(context, sellableDisclosure, l10n),
        if (products.isEmpty && sellableDisclosure == StockDisclosure.verified)
          Container(
            padding: const EdgeInsets.all(16.0),
            decoration: BoxDecoration(
              color: Colors.red[50],
              borderRadius: BorderRadius.circular(8.0),
              border: Border.all(color: Colors.red.shade200),
            ),
            child: Center(
              child: Text(
                l10n.stockEmptyVerified,
                style: const TextStyle(
                  fontSize: 16,
                  color: Colors.red,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
        if (products.isNotEmpty &&
            (sellableDisclosure == StockDisclosure.verified ||
             sellableDisclosure == StockDisclosure.stale))
          ...products.map(
            (item) => Padding(
              padding: const EdgeInsets.only(bottom: 12.0),
              child: Container(
                padding: const EdgeInsets.all(12.0),
                decoration: BoxDecoration(
                  color: Colors.grey[100],
                  borderRadius: BorderRadius.circular(8.0),
                  border: Border.all(color: Colors.grey.shade300),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      item.name,
                      style: const TextStyle(
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Row(
                      mainAxisAlignment:
                          MainAxisAlignment.spaceBetween,
                      children: [
                        Text(
                          '${l10n.stockReceived}: ${item.startingCartons} ${l10n.stockCarton}'
                           "${item.startingPacks > 0 ? ' + ${item.startingPacks} ${l10n.stockPiece}' : ''}",
                          style: const TextStyle(fontSize: 14),
                        ),
                        Text(
                          '${l10n.stockSold}: ${item.soldCartons} ${l10n.stockCarton}, ${item.soldPacks} ${l10n.stockPiece}',
                          style: TextStyle(
                            fontSize: 14,
                            color: Colors.green[700],
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '${l10n.stockRemaining}: ${item.currentCartons} ${l10n.stockCarton}, ${item.currentPacks} ${l10n.stockPack}',
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.bold,
                        color: Colors.blueAccent,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        if (pendingReturnCustody.isNotEmpty) ...[
          const SizedBox(height: 12),
          Text(
            l10n.stockPendingReturns,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 4),
          Text(
            l10n.stockPendingReturnsHint,
            style: const TextStyle(fontSize: 12, color: Colors.deepOrange),
          ),
          const SizedBox(height: 8),
          ...pendingReturnCustody.map(
            (item) => Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: item.evidenceState == PendingCustodyEvidenceState.blocked
                    ? Colors.red.shade50
                    : Colors.amber.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(
                  color: item.evidenceState == PendingCustodyEvidenceState.blocked
                      ? Colors.red.shade200
                      : Colors.amber.shade200,
                ),
              ),
              child: Row(
                children: [
                  Icon(
                    item.evidenceState == PendingCustodyEvidenceState.blocked
                        ? Icons.report_problem_outlined
                        : Icons.schedule_outlined,
                    color: item.evidenceState == PendingCustodyEvidenceState.blocked
                        ? Colors.red
                        : Colors.amber.shade800,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.productName,
                          style: const TextStyle(fontWeight: FontWeight.bold),
                        ),
                        Text(
                          '${_pendingReasonLabel(item.reason, l10n)} · ${_pendingStateLabel(item.evidenceState, l10n)}',
                          style: const TextStyle(fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                  Text(
                    '${item.cartons} ${l10n.stockCarton}, ${item.packs} ${l10n.stockPack}',
                    style: const TextStyle(fontWeight: FontWeight.bold),
                  ),
                ],
              ),
            ),
          ),
        ],
        if (nonSellableDisclosure != StockDisclosure.verified)
          _disclosureNotice(context, nonSellableDisclosure, l10n),
        if (nonSellableCustody.isNotEmpty &&
            (nonSellableDisclosure == StockDisclosure.verified ||
             nonSellableDisclosure == StockDisclosure.stale)) ...[
          const SizedBox(height: 12),
          Text(
            l10n.stockNonSellableTitle,
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          ...nonSellableCustody.map(
            (item) => Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.all(10),
              decoration: BoxDecoration(
                color: Colors.orange.shade50,
                borderRadius: BorderRadius.circular(8),
                border: Border.all(color: Colors.orange.shade200),
              ),
              child: Row(
                children: [
                  const Icon(
                    Icons.inventory_2_outlined,
                    color: Colors.orange,
                  ),
                  const SizedBox(width: 8),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          item.productName,
                          style: const TextStyle(
                            fontWeight: FontWeight.bold,
                          ),
                        ),
                        Text(
                          _statusLabel(item.status, l10n),
                          style: const TextStyle(fontSize: 12),
                        ),
                      ],
                    ),
                  ),
                  Text(
                    '${item.quantity} ${item.uomCode}',
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
        const SizedBox(height: 20),
      ],
    );
  }

  Widget _disclosureNotice(
    BuildContext context,
    StockDisclosure disclosure,
    AppLocalizations l10n,
  ) {
    final message = switch (disclosure) {
      StockDisclosure.verified => '',
      StockDisclosure.stale => l10n.stockStale,
      StockDisclosure.denied => l10n.stockDenied,
      StockDisclosure.unavailable => l10n.stockUnavailable,
    };
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 8),
      child: Text(
        message,
        style: TextStyle(color: Theme.of(context).colorScheme.error),
      ),
    );
  }

  String _pendingReasonLabel(PendingReturnReason reason, AppLocalizations l10n) {
    return switch (reason) {
      PendingReturnReason.damaged => l10n.stockStatusDamaged,
      PendingReturnReason.expired => l10n.stockReasonExpired,
      PendingReturnReason.factoryDefect => l10n.stockReasonFactory,
    };
  }

  String _pendingStateLabel(PendingCustodyEvidenceState state, AppLocalizations l10n) {
    return switch (state) {
      PendingCustodyEvidenceState.pending => l10n.stockPending,
      PendingCustodyEvidenceState.inFlight => l10n.stockInFlight,
      PendingCustodyEvidenceState.blocked => l10n.stockNeedsAction,
    };
  }

  String _statusLabel(NonSellableCustodyStatus status, AppLocalizations l10n) {
    return switch (status) {
      NonSellableCustodyStatus.damaged => l10n.stockStatusDamaged,
      NonSellableCustodyStatus.quarantined => l10n.stockStatusQuarantined,
      NonSellableCustodyStatus.blocked => l10n.stockStatusBlocked,
      NonSellableCustodyStatus.recalled => l10n.stockStatusRecalled,
      NonSellableCustodyStatus.disposalPending => l10n.stockStatusDisposalPending,
    };
  }
}
