import 'package:wanasah_frontend/core/serialization/json_contract.dart';

/// Only sold quantities; price, tax, reward and totals are never request inputs.
class InvoicePreviewLine {
  InvoicePreviewLine({
    required this.productVariantId, this.quantity = 0, this.packsQuantity = 0,
  }) {
    JsonContract.integer(productVariantId, 'product_variant_id', minimum: 1);
    JsonContract.integer(quantity, 'quantity');
    JsonContract.integer(packsQuantity, 'packs_quantity');
    if (quantity == 0 && packsQuantity == 0) JsonContract.invalid('sale.quantity');
  }

  final int productVariantId;
  final int quantity;
  final int packsQuantity;

  Map<String, dynamic> toJson() => {
    'product_variant_id': productVariantId,
    'quantity': quantity,
    'packs_quantity': packsQuantity,
  };
}

class InvoicePreviewRequest {
  InvoicePreviewRequest(List<InvoicePreviewLine> items)
    : cartItems = List.unmodifiable(items) {
    if (cartItems.isEmpty || cartItems.length > 500) {
      JsonContract.invalid('cart_items');
    }
  }

  final List<InvoicePreviewLine> cartItems;
  Map<String, dynamic> toJson() => {
    'cart_items': cartItems.map((item) => item.toJson()).toList(),
  };
}
