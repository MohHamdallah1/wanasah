Map<String, dynamic> buildCanonicalVisitPayload({
  required String outcome,
  String? notes,
  required String cashCollected,
  required String debtPaid,
  required List<Map<String, dynamic>> cartItems,
  required List<Map<String, dynamic>> returns,
}) {
  if (outcome != 'Sale' && outcome != 'NoSale' && outcome != 'Postponed') {
    throw ArgumentError.value(outcome, 'outcome', 'Unsupported visit outcome');
  }

  final payload = <String, dynamic>{
    'outcome': outcome,
    'notes': notes?.trim() ?? '',
  };

  if (outcome == 'Postponed') {
    return payload;
  }

  payload['cash_collected'] =
      outcome == 'NoSale' ? '0.000' : cashCollected;
  payload['debt_paid'] = debtPaid;

  if (cartItems.isNotEmpty) {
    payload['cart_items'] = cartItems;
  }
  if (returns.isNotEmpty) {
    payload['returns'] = returns;
  }

  return payload;
}
