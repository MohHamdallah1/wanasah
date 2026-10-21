import '../../../models/cart_item_model.dart';

class VisitCartMutationResult {
  const VisitCartMutationResult({
    required this.cart,
    this.errorMessage,
  });

  final List<CartItemModel> cart;
  final String? errorMessage;

  bool get isAccepted => errorMessage == null;
}

VisitCartMutationResult applyVisitCartItem({
  required List<CartItemModel> currentCart,
  required CartItemModel item,
}) {
  final packsPerCarton = item.packsPerCarton > 0 ? item.packsPerCarton : 1;
  final requestedBasePacks =
      (item.cartons * packsPerCarton) +
      item.packs +
      (item.sampleCartons * packsPerCarton) +
      item.samplePacks +
      (item.returnFactoryCartons * packsPerCarton) +
      item.returnFactoryPacks +
      (item.returnExpiredCartons * packsPerCarton) +
      item.returnExpiredPacks;
  final availableBasePacks =
      (item.availableCartons * packsPerCarton) + item.availablePacks;

  if (requestedBasePacks > availableBasePacks) {
    return VisitCartMutationResult(
      cart: List<CartItemModel>.unmodifiable(currentCart),
      errorMessage:
          'عفواً، كمية ${item.name} المطلوبة لا تكفي بالسيارة.',
    );
  }

  final updated = List<CartItemModel>.from(currentCart);
  final index = updated.indexWhere(
    (current) => current.productVariantId == item.productVariantId,
  );

  final hasZeroQuantities =
      item.cartons == 0 &&
      item.packs == 0 &&
      item.sampleCartons == 0 &&
      item.samplePacks == 0 &&
      item.returnFactoryCartons == 0 &&
      item.returnFactoryPacks == 0 &&
      item.returnExpiredCartons == 0 &&
      item.returnExpiredPacks == 0;

  if (hasZeroQuantities) {
    if (index >= 0) updated.removeAt(index);
  } else if (index >= 0) {
    updated[index] = item;
  } else {
    updated.add(item);
  }

  return VisitCartMutationResult(
    cart: List<CartItemModel>.unmodifiable(updated),
  );
}

List<CartItemModel> removeVisitCartItem({
  required List<CartItemModel> currentCart,
  required int productVariantId,
}) {
  return List<CartItemModel>.unmodifiable(
    currentCart.where(
      (item) => item.productVariantId != productVariantId,
    ),
  );
}
