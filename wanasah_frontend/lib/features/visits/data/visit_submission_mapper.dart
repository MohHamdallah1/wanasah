import '../../../models/cart_item_model.dart';

class VisitSubmissionLines {
  const VisitSubmissionLines({
    required this.cartItems,
    required this.returns,
  });

  final List<Map<String, dynamic>> cartItems;
  final List<Map<String, dynamic>> returns;
}

VisitSubmissionLines mapVisitSubmissionLines(
  List<CartItemModel> cart,
) {
  final cartItems = cart
      .where(
        (item) =>
            item.cartons > 0 ||
            item.packs > 0 ||
            item.sampleCartons > 0 ||
            item.samplePacks > 0,
      )
      .map(
        (item) => <String, dynamic>{
          'product_variant_id': item.productVariantId,
          'quantity': item.cartons,
          'packs_quantity': item.packs,
          'sample_quantity': item.sampleCartons,
          'sample_packs_quantity': item.samplePacks,
          'sample_reason': item.sampleReason,
        },
      )
      .toList(growable: false);

  final returns = <Map<String, dynamic>>[];
  for (final item in cart) {
    for (final ret in item.returns) {
      returns.add(
        <String, dynamic>{
          'product_variant_id': item.productVariantId,
          'quantity': ret['cartons'] ?? 0,
          'packs_quantity': ret['packs'] ?? 0,
          'return_type': ret['type'] ?? '',
        },
      );
    }
  }

  return VisitSubmissionLines(
    cartItems: List<Map<String, dynamic>>.unmodifiable(cartItems),
    returns: List<Map<String, dynamic>>.unmodifiable(returns),
  );
}
