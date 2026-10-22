enum TransferDecisionStatus {
  accepted('accepted'),
  rejected('rejected');

  const TransferDecisionStatus(this.wireValue);
  final String wireValue;
}

class TransferDecision {
  TransferDecision({
    required this.transferId,
    required this.status,
    String? reason,
  }) : reason = _normalizeReason(status, reason) {
    if (transferId <= 0) {
      throw ArgumentError.value(
        transferId,
        'transferId',
        'Transfer ID must be positive.',
      );
    }
  }

  final int transferId;
  final TransferDecisionStatus status;
  final String? reason;

  static String? _normalizeReason(
    TransferDecisionStatus status,
    String? reason,
  ) {
    final normalized = reason?.trim();
    if (status == TransferDecisionStatus.rejected) {
      if (normalized == null || normalized.isEmpty) {
        throw ArgumentError(
          'Rejected transfer requires a non-empty reason.',
        );
      }
      if (normalized.length > 1000) {
        throw ArgumentError(
          'Transfer rejection reason exceeds 1000 characters.',
        );
      }
      return normalized;
    }
    return null;
  }
}
