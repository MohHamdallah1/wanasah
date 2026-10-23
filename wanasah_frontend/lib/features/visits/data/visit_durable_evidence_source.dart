import 'dart:convert';

import '../../../core/db/local_database.dart';
import '../../../core/sync/durable_command.dart';
import '../application/visit_durable_read_model.dart';

typedef VisitPendingRowsLoader =
    Future<List<Map<String, dynamic>>> Function();

abstract interface class VisitDurableEvidenceSource {
  Future<VisitDurableReadModel> readForVisit(int visitId);
}

class LocalVisitDurableEvidenceSource implements VisitDurableEvidenceSource {
  LocalVisitDurableEvidenceSource({
    required VisitPendingRowsLoader pendingRows,
  }) : _pendingRows = pendingRows;

  factory LocalVisitDurableEvidenceSource.withDatabase([
    LocalDatabase? database,
  ]) {
    final db = database ?? LocalDatabase.instance;
    return LocalVisitDurableEvidenceSource(
      pendingRows: db.getPendingSyncs,
    );
  }

  final VisitPendingRowsLoader _pendingRows;

  @override
  Future<VisitDurableReadModel> readForVisit(int visitId) async {
    final rows = await _pendingRows();

    for (final row in rows.reversed) {
      if (row['type']?.toString() != DurableCommandType.submitSale) {
        continue;
      }

      final payload = _payload(row['payload']);
      if (payload == null || !_belongsToVisit(payload, visitId)) {
        continue;
      }

      return VisitDurableReadModel(
        latestDraft: VisitDurableDraftEvidence(
          cashCollected: payload['cash_collected']?.toString() ?? '0',
          debtPaid: payload['debt_paid']?.toString() ?? '0',
          notes:
              (payload['notes'] ?? payload['no_sale_reason'] ?? '').toString(),
          cartItemsJson: _jsonField(payload, 'cart_items'),
          returnsJson: _jsonField(payload, 'returns'),
        ),
      );
    }

    return const VisitDurableReadModel();
  }

  static bool _belongsToVisit(Map<String, dynamic> payload, int visitId) {
    // Preserve the previous VisitScreen contract: either legacy identifier
    // may independently match. Do not silently prioritize one when both exist.
    final target = visitId.toString();
    return payload['visitId']?.toString() == target ||
        payload['visit_id']?.toString() == target;
  }

  static Map<String, dynamic>? _payload(Object? raw) {
    if (raw is! String) return null;
    try {
      final decoded = jsonDecode(raw);
      if (decoded is! Map) return null;
      return <String, dynamic>{
        for (final entry in decoded.entries)
          if (entry.key is String) entry.key as String: entry.value,
      };
    } catch (_) {
      return null;
    }
  }

  static String? _jsonField(Map<String, dynamic> payload, String key) {
    final value = payload[key];
    return value == null ? null : jsonEncode(value);
  }
}
