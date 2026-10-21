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

  int toBasePacks(int packsPerCarton) {
    final safePpc = packsPerCarton > 0 ? packsPerCarton : 1;
    return (cartons * safePpc) + packs;
  }
}

Map<int, VisitInventoryQuantity> visitInventoryProjection({
  required List<dynamic> cartItems,
  required List<dynamic> returns,
}) {
  final projected = <int, VisitInventoryQuantity>{};

  void add(int variantId, int cartons, int packs) {
    if (variantId <= 0 || (cartons == 0 && packs == 0)) return;
    projected[variantId] = (projected[variantId] ??
            const VisitInventoryQuantity())
        .add(cartons: cartons, packs: packs);
  }

  for (final raw in cartItems) {
    if (raw is! Map) continue;
    if (raw['is_cancelled'] == true || raw['is_cancelled'] == 1) continue;

    final variantId =
        int.tryParse(raw['product_variant_id']?.toString() ?? '') ?? 0;
    final cartons =
        (raw['quantity'] as num?)?.toInt() ?? 0;
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
    if (raw is! Map) continue;
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
    // vehicle. Non-sellable custody is tracked separately in its own V1 wave.
    add(variantId, cartons, packs);
  }

  return projected;
}

int inventoryCorrectionDeltaBasePacks({
  required VisitInventoryQuantity oldProjection,
  required VisitInventoryQuantity newProjection,
  required int packsPerCarton,
}) {
  return oldProjection.toBasePacks(packsPerCarton) -
      newProjection.toBasePacks(packsPerCarton);
}
