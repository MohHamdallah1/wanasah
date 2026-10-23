import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../../visit/local_inventory_projection.dart';

class VisitInventoryProjectionPersistence {
  const VisitInventoryProjectionPersistence();

  List<dynamic> decodeStoredVisitList(Object? raw) {
    if (raw == null) return const <dynamic>[];
    if (raw is List) return List<dynamic>.from(raw);
    if (raw is! String || raw.trim().isEmpty || raw == 'null') {
      return const <dynamic>[];
    }

    final decoded = jsonDecode(raw);
    if (decoded is! List) {
      throw StateError('Stored visit projection is not a list.');
    }
    return List<dynamic>.from(decoded);
  }

  Future<void> applyInitial({
    required Transaction txn,
    required List<dynamic> cartItems,
    required List<dynamic> returnItems,
  }) {
    final projection = visitInventoryProjection(
      cartItems: cartItems,
      returns: returnItems,
    );
    return applyDelta(
      txn: txn,
      oldProjection: const <int, VisitInventoryQuantity>{},
      newProjection: projection,
    );
  }

  Future<void> applyCorrection({
    required Transaction txn,
    required List<dynamic> oldCartItems,
    required List<dynamic> oldReturns,
    required List<dynamic> newCartItems,
    required List<dynamic> newReturns,
  }) {
    final oldProjection = visitInventoryProjection(
      cartItems: oldCartItems,
      returns: oldReturns,
    );
    final newProjection = visitInventoryProjection(
      cartItems: newCartItems,
      returns: newReturns,
    );

    return applyDelta(
      txn: txn,
      oldProjection: oldProjection,
      newProjection: newProjection,
    );
  }

  Future<void> applyDelta({
    required Transaction txn,
    required Map<int, VisitInventoryQuantity> oldProjection,
    required Map<int, VisitInventoryQuantity> newProjection,
  }) async {
    final variantIds = <int>{
      ...oldProjection.keys,
      ...newProjection.keys,
    }.toList()
      ..sort();

    for (final variantId in variantIds) {
      final rows = await txn.query(
        'products',
        columns: <String>[
          'packs_per_carton',
          'current_cartons',
          'current_packs',
        ],
        where: 'id = ?',
        whereArgs: <Object?>[variantId],
        limit: 1,
      );
      if (rows.isEmpty) {
        throw LocalInventoryProjectionException(
          code: LocalInventoryProjectionCode.productMissing,
          variantId: variantId,
        );
      }

      final row = rows.first;
      final packsPerCarton =
          (row['packs_per_carton'] as num?)?.toInt() ?? 0;
      final currentCartons =
          (row['current_cartons'] as num?)?.toInt();
      final currentPacks =
          (row['current_packs'] as num?)?.toInt();

      if (currentCartons == null || currentPacks == null) {
        throw LocalInventoryProjectionException(
          code: LocalInventoryProjectionCode.invalidCurrentState,
          variantId: variantId,
          details: <String, Object?>{
            'current_cartons': row['current_cartons'],
            'current_packs': row['current_packs'],
          },
        );
      }

      final deltaBasePacks = inventoryCorrectionDeltaBasePacks(
        oldProjection:
            oldProjection[variantId] ?? const VisitInventoryQuantity(),
        newProjection:
            newProjection[variantId] ?? const VisitInventoryQuantity(),
        packsPerCarton: packsPerCarton,
        variantId: variantId,
      );

      final next = applyLocalAvailableInventoryDelta(
        variantId: variantId,
        currentCartons: currentCartons,
        currentPacks: currentPacks,
        packsPerCarton: packsPerCarton,
        deltaBasePacks: deltaBasePacks,
      );

      final updated = await txn.update(
        'products',
        <String, Object?>{
          'current_cartons': next.cartons,
          'current_packs': next.packs,
        },
        where: 'id = ?',
        whereArgs: <Object?>[variantId],
      );
      if (updated != 1) {
        throw LocalInventoryProjectionException(
          code: LocalInventoryProjectionCode.updateFailed,
          variantId: variantId,
        );
      }
    }
  }
}
