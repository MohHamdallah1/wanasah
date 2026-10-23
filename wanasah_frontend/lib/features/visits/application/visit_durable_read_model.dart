class VisitDurableDraftEvidence {
  const VisitDurableDraftEvidence({
    required this.cashCollected,
    required this.debtPaid,
    required this.notes,
    this.cartItemsJson,
    this.returnsJson,
  });

  final String cashCollected;
  final String debtPaid;
  final String notes;
  final String? cartItemsJson;
  final String? returnsJson;

  bool get hasCartOrReturnEvidence =>
      cartItemsJson != null || returnsJson != null;
}

class VisitDurableReadModel {
  const VisitDurableReadModel({this.latestDraft});

  final VisitDurableDraftEvidence? latestDraft;

  bool get hasUnresolvedDraft => latestDraft != null;
}
