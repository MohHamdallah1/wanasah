import '../../../models/cart_item_model.dart';
import '../domain/returns/return_resolution.dart';

/// Business quantities only; no provenance is inferred from cached stock.
List<ReturnResolutionRequest> visitReturnRequests(List<CartItemModel> cart) => [
  for (final item in cart) ...[
    if (item.returnFactoryCartons > 0 || item.returnFactoryPacks > 0)
      ReturnResolutionRequest(productVariantId: item.productVariantId,
        quantity: item.returnFactoryCartons, packsQuantity: item.returnFactoryPacks,
        returnType: FieldReturnType.factoryDefect),
    if (item.returnExpiredCartons > 0 || item.returnExpiredPacks > 0)
      ReturnResolutionRequest(productVariantId: item.productVariantId,
        quantity: item.returnExpiredCartons, packsQuantity: item.returnExpiredPacks,
        returnType: FieldReturnType.expired),
    if (item.returnDamagedCartons > 0 || item.returnDamagedPacks > 0)
      ReturnResolutionRequest(productVariantId: item.productVariantId,
        quantity: item.returnDamagedCartons, packsQuantity: item.returnDamagedPacks,
        returnType: FieldReturnType.damaged),
  ],
];

class ResolvedVisitReturns {
  ResolvedVisitReturns({required this.visitId,
    required List<FieldReturnResolution> resolutions})
    : resolutions = List.unmodifiable(resolutions);

  final int visitId;
  final List<FieldReturnResolution> resolutions;

  /// Reject missing, duplicate or stale evidence before entering durable storage.
  List<Map<String, dynamic>> forSubmission(int id, List<CartItemModel> cart) {
    final expected = visitReturnRequests(cart);
    if (id != visitId || resolutions.length != expected.length) {
      throw const FormatException('Return evidence does not match visit draft');
    }
    final remaining = [...resolutions];
    return [
      for (final request in expected) _takeMatching(remaining, request),
    ];
  }

  static Map<String, dynamic> _takeMatching(
    List<FieldReturnResolution> remaining, ReturnResolutionRequest request,
  ) {
    final index = remaining.indexWhere((value) =>
      value.request.productVariantId == request.productVariantId &&
      value.request.returnType == request.returnType &&
      value.request.quantity == request.quantity &&
      value.request.packsQuantity == request.packsQuantity);
    if (index < 0) {
      throw const FormatException('Return evidence does not match quantities');
    }
    return remaining.removeAt(index).toVisitReturnJson();
  }
}
