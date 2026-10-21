import 'dart:convert';

import '../../../models/cart_item_model.dart';
import '../../../models/product_model.dart';

List<CartItemModel> restoreCompletedVisitCart({
  required List<ProductModel> catalog,
  String? cartItemsJson,
  String? returnsJson,
}) {
  final restoredCart = <CartItemModel>[];

  if (cartItemsJson != null &&
      cartItemsJson.isNotEmpty &&
      cartItemsJson != 'null') {
    final decodedCart = jsonDecode(cartItemsJson);
    if (decodedCart is List) {
      for (final raw in decodedCart) {
        if (raw is! Map) continue;

        final productVariantId =
            int.tryParse(raw['product_variant_id']?.toString() ?? '') ?? 0;
        if (productVariantId == 0) continue;

        final productIndex =
            catalog.indexWhere((product) => product.id == productVariantId);
        if (productIndex < 0) continue;
        final product = catalog[productIndex];

        final packsPerCarton =
            product.packsPerCarton > 0 ? product.packsPerCarton : 1;
        final savedCartons = (raw['quantity'] as num?)?.toInt() ?? 0;
        final savedPacks = (raw['packs_quantity'] as num?)?.toInt() ?? 0;
        final savedSampleCartons =
            (raw['sample_quantity'] as num?)?.toInt() ?? 0;
        final savedSamplePacks =
            (raw['sample_packs_quantity'] as num?)?.toInt() ?? 0;

        final savedBasePacks =
            ((savedCartons + savedSampleCartons) * packsPerCarton) +
                savedPacks +
                savedSamplePacks;
        final currentBasePacks =
            (product.currentCartons * packsPerCarton) + product.currentPacks;
        final combinedBasePacks = currentBasePacks + savedBasePacks;

        restoredCart.add(
          CartItemModel(
            productVariantId: productVariantId,
            name: product.name,
            pricePerCarton: product.pricePerCarton,
            pricePerPack: product.pricePerPack,
            packsPerCarton: product.packsPerCarton,
            availableCartons: combinedBasePacks ~/ packsPerCarton,
            availablePacks: combinedBasePacks % packsPerCarton,
            cartons: savedCartons,
            packs: savedPacks,
            sampleCartons: savedSampleCartons,
            samplePacks: savedSamplePacks,
            sampleReason: raw['sample_reason']?.toString() ?? '',
          ),
        );
      }
    }
  }

  if (returnsJson != null &&
      returnsJson.isNotEmpty &&
      returnsJson != 'null') {
    final decodedReturns = jsonDecode(returnsJson);
    if (decodedReturns is List) {
      for (final raw in decodedReturns) {
        if (raw is! Map) continue;

        final productVariantId =
            int.tryParse(raw['product_variant_id']?.toString() ?? '') ?? 0;
        if (productVariantId == 0) continue;

        final type = raw['return_type']?.toString() ?? '';
        final cartons = (raw['quantity'] as num?)?.toInt() ?? 0;
        final packs = (raw['packs_quantity'] as num?)?.toInt() ?? 0;

        final factoryCartons = type == 'Factory_Defect' ? cartons : 0;
        final factoryPacks = type == 'Factory_Defect' ? packs : 0;
        final expiredCartons = type == 'Expired' ? cartons : 0;
        final expiredPacks = type == 'Expired' ? packs : 0;

        final existingIndex = restoredCart.indexWhere(
          (item) => item.productVariantId == productVariantId,
        );

        if (existingIndex >= 0) {
          final current = restoredCart[existingIndex];
          final packsPerCarton =
              current.packsPerCarton > 0 ? current.packsPerCarton : 1;
          final returnBasePacks =
              ((factoryCartons + expiredCartons) * packsPerCarton) +
                  factoryPacks +
                  expiredPacks;
          final currentAvailableBasePacks =
              (current.availableCartons * packsPerCarton) +
                  current.availablePacks;
          final combinedBasePacks =
              currentAvailableBasePacks + returnBasePacks;

          restoredCart[existingIndex] = current.copyWith(
            availableCartons: combinedBasePacks ~/ packsPerCarton,
            availablePacks: combinedBasePacks % packsPerCarton,
            returnFactoryCartons:
                current.returnFactoryCartons + factoryCartons,
            returnFactoryPacks: current.returnFactoryPacks + factoryPacks,
            returnExpiredCartons:
                current.returnExpiredCartons + expiredCartons,
            returnExpiredPacks: current.returnExpiredPacks + expiredPacks,
          );
          continue;
        }

        final productIndex =
            catalog.indexWhere((product) => product.id == productVariantId);
        if (productIndex < 0) continue;
        final product = catalog[productIndex];
        final packsPerCarton =
            product.packsPerCarton > 0 ? product.packsPerCarton : 1;
        final returnBasePacks =
            ((factoryCartons + expiredCartons) * packsPerCarton) +
                factoryPacks +
                expiredPacks;
        final currentBasePacks =
            (product.currentCartons * packsPerCarton) + product.currentPacks;
        final combinedBasePacks = currentBasePacks + returnBasePacks;

        restoredCart.add(
          CartItemModel(
            productVariantId: productVariantId,
            name: product.name,
            pricePerCarton: product.pricePerCarton,
            pricePerPack: product.pricePerPack,
            packsPerCarton: product.packsPerCarton,
            availableCartons: combinedBasePacks ~/ packsPerCarton,
            availablePacks: combinedBasePacks % packsPerCarton,
            returnFactoryCartons: factoryCartons,
            returnFactoryPacks: factoryPacks,
            returnExpiredCartons: expiredCartons,
            returnExpiredPacks: expiredPacks,
          ),
        );
      }
    }
  }

  return restoredCart;
}
