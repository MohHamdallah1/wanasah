enum DurableCommandState {
  pending('pending'),
  inFlight('in_flight'),
  blocked('blocked');

  const DurableCommandState(this.storageValue);
  final String storageValue;

  static DurableCommandState fromStorage(Object? raw) {
    final value = raw?.toString();
    return DurableCommandState.values.firstWhere(
      (state) => state.storageValue == value,
      orElse: () => DurableCommandState.pending,
    );
  }
}

abstract final class DurableCommandType {
  static const submitSale = 'submit_sale';
  static const transferResponse = 'transfer_response';
  static const legacyToggleBreak = 'toggle_break';
  static const corrupt = 'corrupt';

  static bool isLegacyQuarantined(String type) =>
      type.startsWith('quarantined_');

  static String normalizeLegacyType(String type) {
    if (!isLegacyQuarantined(type)) return type;
    final normalized = type.substring('quarantined_'.length);
    if (normalized == 'draft_sale') return submitSale;
    return normalized;
  }

  static bool isReplayable(String type) {
    final normalized = normalizeLegacyType(type);
    return normalized == submitSale || normalized == transferResponse;
  }

  static bool isTemporal(String type) =>
      normalizeLegacyType(type) == legacyToggleBreak;
}

bool isUnresolvedOfflineCommand(Map<String, dynamic> row) {
  // Rows are physically removed only after a confirmed successful finalize.
  // Legacy databases have no state column, so their existence is unresolved.
  final state = row['state']?.toString();
  if (state == null || state.isEmpty) return true;
  return state != 'reconciled';
}
