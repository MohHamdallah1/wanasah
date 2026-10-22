import 'dart:convert';
import '../../../core/sync/durable_command.dart';

/// Reads lifecycle evidence only. Never edits, replaces or replays a command.
bool visitHasUnresolvedCommand(int visitId, List<Map<String, dynamic>> rows) {
  for (final row in rows.where(isUnresolvedOfflineCommand)) {
    final type = DurableCommandType.normalizeLegacyType(
      row['type']?.toString() ?? '');
    if (type == DurableCommandType.corrupt) return true;
    if (type != DurableCommandType.submitSale) continue;
    try {
      final payload = jsonDecode(row['payload'] as String);
      if (payload is! Map) return true;
      final id = payload['visitId'] ?? payload['visit_id'];
      if (id == null || id.toString() == visitId.toString()) return true;
    } catch (_) {
      return true;
    }
  }
  return false;
}

class VisitPriorCommandUnresolved implements Exception {
  const VisitPriorCommandUnresolved();
}

enum VisitSubmissionDisposition { confirmed, unresolved }
