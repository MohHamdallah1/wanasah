import 'transfer_decision.dart';
import 'pending_transfer_quantity.dart';

class TransferDecisionCommand {
  const TransferDecisionCommand._();

  static Map<String, dynamic> toPayload(
    TransferDecision decision, {
    String? productName,
    Object? deltaCartons,
    Object? deltaPacks,
    PendingTransferQuantity? canonicalQuantity,
  }) {
    return <String, dynamic>{
      'transferId': decision.transferId,
      'response': decision.status.wireValue,
      'reason': decision.reason,
      if (productName != null) 'context_product_name': productName,
      if (canonicalQuantity == null && deltaCartons != null)
        'context_delta_cartons': deltaCartons,
      if (canonicalQuantity == null && deltaPacks != null)
        'context_delta_packs': deltaPacks,
      if (canonicalQuantity != null)
        for (final entry in canonicalQuantity.toEvidence().entries)
          'context_${entry.key}': entry.value,
    };
  }

  static Map<String, dynamic> canonicalContext(Map<String, dynamic> row) {
    final quantity = PendingTransferQuantity.fromEvidence(row);
    return quantity == null
        ? {}
        : {
          for (final entry in quantity.toEvidence().entries)
            'context_${entry.key}': entry.value,
        };
  }

  static TransferDecision fromPayload(Map<String, dynamic> payload) {
    final transferId =
        int.tryParse(payload['transferId']?.toString() ?? '') ?? 0;
    final response = payload['response']?.toString().trim();
    final status = switch (response) {
      'accepted' => TransferDecisionStatus.accepted,
      'rejected' => TransferDecisionStatus.rejected,
      _ =>
        throw const FormatException('Invalid stored transfer decision status.'),
    };

    return TransferDecision(
      transferId: transferId,
      status: status,
      reason: payload['reason']?.toString(),
    );
  }

  static bool sameDecision(TransferDecision left, TransferDecision right) {
    return left.transferId == right.transferId &&
        left.status == right.status &&
        left.reason == right.reason;
  }
}
