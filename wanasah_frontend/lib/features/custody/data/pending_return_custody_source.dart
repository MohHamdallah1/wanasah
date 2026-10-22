import 'dart:convert';

import '../../../core/db/local_database.dart';
import '../../../core/sync/durable_command.dart';
import '../domain/pending_return_custody.dart';

typedef PendingRowsLoader = Future<List<Map<String, dynamic>>> Function();
typedef ProductRowsLoader = Future<List<Map<String, dynamic>>> Function();

abstract interface class PendingReturnCustodySource {
  Future<List<PendingReturnCustodyItem>> read();
}

class LocalPendingReturnCustodySource implements PendingReturnCustodySource {
  LocalPendingReturnCustodySource({
    required PendingRowsLoader pendingRows,
    required ProductRowsLoader productRows,
  })  : _pendingRows = pendingRows,
        _productRows = productRows;

  factory LocalPendingReturnCustodySource.withDatabase([
    LocalDatabase? database,
  ]) {
    final db = database ?? LocalDatabase.instance;
    return LocalPendingReturnCustodySource(
      pendingRows: db.getPendingSyncs,
      productRows: db.getProducts,
    );
  }

  final PendingRowsLoader _pendingRows;
  final ProductRowsLoader _productRows;

  @override
  Future<List<PendingReturnCustodyItem>> read() async {
    final rows = await _pendingRows();
    final products = await _productRows();
    final names = <int, String>{
      for (final row in products)
        if (_positiveInt(row['id']) case final id?)
          id: _nonEmpty(row['name']) ?? 'منتج #$id',
    };

    final projected = <String, PendingReturnCustodyItem>{};

    for (final row in rows) {
      final rawType = row['type']?.toString() ?? '';
      final type = DurableCommandType.normalizeLegacyType(rawType);
      if (type != DurableCommandType.submitSale) continue;

      final localEffectApplied =
          (row['local_effect_applied'] as num?)?.toInt() == 1;
      if (!localEffectApplied) continue;

      final payload = _payload(row['payload']);
      if (payload == null) continue;
      final returns = payload['returns'];
      if (returns is! List) continue;

      final state = _state(row['state']);
      for (final raw in returns) {
        if (raw is! Map) continue;
        if (raw['is_cancelled'] == true || raw['is_cancelled'] == 1) continue;

        final variantId = _positiveInt(raw['product_variant_id']);
        final reason = PendingReturnReason.fromCode(raw['return_type']);
        if (variantId == null || reason == null) continue;

        final cartons =
            (raw['quantity'] as num?)?.toInt() ??
            (raw['cartons'] as num?)?.toInt() ??
            0;
        final packs =
            (raw['packs_quantity'] as num?)?.toInt() ??
            (raw['packs'] as num?)?.toInt() ??
            0;
        if (cartons <= 0 && packs <= 0) continue;

        final key = '$variantId|\${reason.code}|\${state.name}';
        final existing = projected[key];
        if (existing == null) {
          projected[key] = PendingReturnCustodyItem(
            productVariantId: variantId,
            productName: names[variantId] ?? 'منتج #$variantId',
            reason: reason,
            evidenceState: state,
            cartons: cartons,
            packs: packs,
            commandCount: 1,
          );
        } else {
          projected[key] = existing.add(cartons: cartons, packs: packs);
        }
      }
    }

    final result = projected.values.toList()
      ..sort((a, b) {
        final byName = a.productName.compareTo(b.productName);
        if (byName != 0) return byName;
        final byReason = a.reason.code.compareTo(b.reason.code);
        if (byReason != 0) return byReason;
        return a.evidenceState.index.compareTo(b.evidenceState.index);
      });
    return List<PendingReturnCustodyItem>.unmodifiable(result);
  }

  static Map<String, dynamic>? _payload(Object? raw) {
    try {
      final decoded = jsonDecode(raw?.toString() ?? '');
      if (decoded is! Map) return null;
      return <String, dynamic>{
        for (final entry in decoded.entries)
          if (entry.key is String) entry.key as String: entry.value,
      };
    } catch (_) {
      return null;
    }
  }

  static PendingCustodyEvidenceState _state(Object? raw) {
    return switch (DurableCommandState.fromStorage(raw)) {
      DurableCommandState.pending => PendingCustodyEvidenceState.pending,
      DurableCommandState.inFlight => PendingCustodyEvidenceState.inFlight,
      DurableCommandState.blocked => PendingCustodyEvidenceState.blocked,
    };
  }

  static int? _positiveInt(Object? raw) {
    final value = raw is num ? raw.toInt() : int.tryParse(raw?.toString() ?? '');
    return value != null && value > 0 ? value : null;
  }

  static String? _nonEmpty(Object? raw) {
    final value = raw?.toString().trim() ?? '';
    return value.isEmpty ? null : value;
  }
}
