abstract final class LocalInventoryProjectionCode {
  static const invalidPacksPerCarton =
      'LOCAL_PROJECTION_PACKS_PER_CARTON_INVALID';
  static const invalidCurrentState =
      'LOCAL_PROJECTION_CURRENT_STATE_INVALID';
  static const invalidQuantity =
      'LOCAL_PROJECTION_QUANTITY_INVALID';
  static const invalidVariant =
      'LOCAL_PROJECTION_VARIANT_INVALID';
  static const invalidPayload =
      'LOCAL_PROJECTION_PAYLOAD_INVALID';
  static const productMissing =
      'LOCAL_PROJECTION_PRODUCT_MISSING';
  static const underflow =
      'LOCAL_PROJECTION_UNDERFLOW';
  static const updateFailed =
      'LOCAL_PROJECTION_UPDATE_FAILED';
}

class LocalInventoryProjectionException implements Exception {
  const LocalInventoryProjectionException({
    required this.code,
    this.variantId,
    this.details = const <String, Object?>{},
  });

  final String code;
  final int? variantId;
  final Map<String, Object?> details;

  @override
  String toString() {
    return 'LocalInventoryProjectionException('
        'code: $code, variantId: $variantId, details: $details)';
  }
}

class LocalAvailableInventory {
  const LocalAvailableInventory({
    required this.cartons,
    required this.packs,
  });

  final int cartons;
  final int packs;
}

class VisitInventoryQuantity {
  const VisitInventoryQuantity({
    this.cartons = 0,
    this.packs = 0,
  });

  final int cartons;
  final int packs;

  VisitInventoryQuantity add({
    int cartons = 0,
    int packs = 0,
  }) {
    return VisitInventoryQuantity(
      cartons: this.cartons + cartons,
      packs: this.packs + packs,
    );
  }

  int toBasePacks(int packsPerCarton, {int? variantId}) {
    if (packsPerCarton <= 0) {
      throw LocalInventoryProjectionException(
        code: LocalInventoryProjectionCode.invalidPacksPerCarton,
        variantId: variantId,
        details: <String, Object?>{
          'packs_per_carton': packsPerCarton,
        },
      );
    }
    if (cartons < 0 || packs < 0) {
      throw LocalInventoryProjectionException(
        code: LocalInventoryProjectionCode.invalidQuantity,
        variantId: variantId,
        details: <String, Object?>{
          'cartons': cartons,
          'packs': packs,
        },
      );
    }
    return (cartons * packsPerCarton) + packs;
  }
}

Map<int, VisitInventoryQuantity> visitInventoryProjection({
  required List<dynamic> cartItems,
  required List<dynamic> returns,
}) {
  final projected = <int, VisitInventoryQuantity>{};

  void add(int variantId, int cartons, int packs) {
    if (cartons == 0 && packs == 0) return;
    if (variantId <= 0) {
      throw LocalInventoryProjectionException(
        code: LocalInventoryProjectionCode.invalidVariant,
        variantId: variantId,
      );
    }
    if (cartons < 0 || packs < 0) {
      throw LocalInventoryProjectionException(
        code: LocalInventoryProjectionCode.invalidQuantity,
        variantId: variantId,
        details: <String, Object?>{
          'cartons': cartons,
          'packs': packs,
        },
      );
    }
    projected[variantId] =
        (projected[variantId] ?? const VisitInventoryQuantity()).add(
      cartons: cartons,
      packs: packs,
    );
  }

  for (final raw in cartItems) {
    if (raw is! Map) {
      throw const LocalInventoryProjectionException(
        code: LocalInventoryProjectionCode.invalidPayload,
      );
    }
    if (raw['is_cancelled'] == true || raw['is_cancelled'] == 1) continue;

    final variantId =
        int.tryParse(raw['product_variant_id']?.toString() ?? '') ?? 0;
    final cartons = (raw['quantity'] as num?)?.toInt() ?? 0;
    final packs =
        (raw['packs_quantity'] as num?)?.toInt() ??
        (raw['packs'] as num?)?.toInt() ??
        0;
    final sampleCartons =
        (raw['sample_quantity'] as num?)?.toInt() ??
        (raw['sample_cartons'] as num?)?.toInt() ??
        0;
    final samplePacks =
        (raw['sample_packs_quantity'] as num?)?.toInt() ??
        (raw['sample_packs'] as num?)?.toInt() ??
        0;
    final bonusCartons =
        (raw['bonus_quantity'] as num?)?.toInt() ?? 0;

    add(
      variantId,
      cartons + sampleCartons + bonusCartons,
      packs + samplePacks,
    );
  }

  for (final raw in returns) {
    if (raw is! Map) {
      throw const LocalInventoryProjectionException(
        code: LocalInventoryProjectionCode.invalidPayload,
      );
    }
    if (raw['is_cancelled'] == true || raw['is_cancelled'] == 1) continue;

    final variantId =
        int.tryParse(raw['product_variant_id']?.toString() ?? '') ?? 0;
    final cartons =
        (raw['quantity'] as num?)?.toInt() ??
        (raw['cartons'] as num?)?.toInt() ??
        0;
    final packs =
        (raw['packs_quantity'] as num?)?.toInt() ??
        (raw['packs'] as num?)?.toInt() ??
        0;

    // Customer return exchange sends replacement AVAILABLE stock out of the
    // vehicle. Non-sellable returned custody remains a separate projection.
    add(variantId, cartons, packs);
  }

  return projected;
}

int inventoryCorrectionDeltaBasePacks({
  required VisitInventoryQuantity oldProjection,
  required VisitInventoryQuantity newProjection,
  required int packsPerCarton,
  int? variantId,
}) {
  return oldProjection.toBasePacks(
        packsPerCarton,
        variantId: variantId,
      ) -
      newProjection.toBasePacks(
        packsPerCarton,
        variantId: variantId,
      );
}

LocalAvailableInventory applyLocalAvailableInventoryDelta({
  required int variantId,
  required int currentCartons,
  required int currentPacks,
  required int packsPerCarton,
  required int deltaBasePacks,
}) {
  if (packsPerCarton <= 0) {
    throw LocalInventoryProjectionException(
      code: LocalInventoryProjectionCode.invalidPacksPerCarton,
      variantId: variantId,
      details: <String, Object?>{
        'packs_per_carton': packsPerCarton,
      },
    );
  }

  if (currentCartons < 0 ||
      currentPacks < 0 ||
      currentPacks >= packsPerCarton) {
    throw LocalInventoryProjectionException(
      code: LocalInventoryProjectionCode.invalidCurrentState,
      variantId: variantId,
      details: <String, Object?>{
        'current_cartons': currentCartons,
        'current_packs': currentPacks,
        'packs_per_carton': packsPerCarton,
      },
    );
  }

  final currentBasePacks =
      (currentCartons * packsPerCarton) + currentPacks;
  final correctedBasePacks = currentBasePacks + deltaBasePacks;

  if (correctedBasePacks < 0) {
    throw LocalInventoryProjectionException(
      code: LocalInventoryProjectionCode.underflow,
      variantId: variantId,
      details: <String, Object?>{
        'current_base_packs': currentBasePacks,
        'delta_base_packs': deltaBasePacks,
      },
    );
  }

  return LocalAvailableInventory(
    cartons: correctedBasePacks ~/ packsPerCarton,
    packs: correctedBasePacks % packsPerCarton,
  );
}
