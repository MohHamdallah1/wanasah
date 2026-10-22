enum PendingReturnReason {
  damaged('Damaged'),
  expired('Expired'),
  factoryDefect('Factory_Defect');

  const PendingReturnReason(this.code);
  final String code;

  static PendingReturnReason? fromCode(Object? raw) {
    final value = raw?.toString();
    for (final reason in values) {
      if (reason.code == value) return reason;
    }
    return null;
  }
}

enum PendingCustodyEvidenceState {
  pending,
  inFlight,
  blocked,
}

class PendingReturnCustodyItem {
  const PendingReturnCustodyItem({
    required this.productVariantId,
    required this.productName,
    required this.reason,
    required this.evidenceState,
    required this.cartons,
    required this.packs,
    required this.commandCount,
  });

  final int productVariantId;
  final String productName;
  final PendingReturnReason reason;
  final PendingCustodyEvidenceState evidenceState;
  final int cartons;
  final int packs;
  final int commandCount;

  String get stockStatus => 'DAMAGED';

  PendingReturnCustodyItem add({
    required int cartons,
    required int packs,
  }) {
    return PendingReturnCustodyItem(
      productVariantId: productVariantId,
      productName: productName,
      reason: reason,
      evidenceState: evidenceState,
      cartons: this.cartons + cartons,
      packs: this.packs + packs,
      commandCount: commandCount + 1,
    );
  }
}
