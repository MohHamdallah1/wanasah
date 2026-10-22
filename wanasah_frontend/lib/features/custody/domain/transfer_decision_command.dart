import 'transfer_decision.dart';

class TransferDecisionCommand {
  const TransferDecisionCommand._();

  static Map<String, dynamic> toPayload(
    TransferDecision decision, {
    String? productName,
    Object? deltaCartons,
    Object? deltaPacks,
  }) {
    return <String, dynamic>{
      'transferId': decision.transferId,
      'response': decision.status.wireValue,
      'reason': decision.reason,
      if (productName != null) 'context_product_name': productName,
      if (deltaCartons != null) 'context_delta_cartons': deltaCartons,
      if (deltaPacks != null) 'context_delta_packs': deltaPacks,
    };
  }

  static TransferDecision fromPayload(Map<String, dynamic> payload) {
    final transferId =
        int.tryParse(payload['transferId']?.toString() ?? '') ?? 0;
    final response = payload['response']?.toString().trim();
    final status = switch (response) {
      'accepted' => TransferDecisionStatus.accepted,
      'rejected' => TransferDecisionStatus.rejected,
      _ => throw const FormatException(
        'Invalid stored transfer decision status.',
      ),
    };

    return TransferDecision(
      transferId: transferId,
      status: status,
      reason: payload['reason']?.toString(),
    );
  }

  static bool sameDecision(
    TransferDecision left,
    TransferDecision right,
  ) {
    return left.transferId == right.transferId &&
        left.status == right.status &&
        left.reason == right.reason;
  }
}
