import '../../../models/cart_item_model.dart';

enum VisitActionIssue {
  invalidOutcome, invalidQuantity, invalidNotes, sampleReason,
  saleQuantityRequired, noSaleSoldQuantity, noSaleCash, noSaleReason,
  postponedActions,
}

/// Local shape errors only. Stock, credit, pricing, rewards and tax remain
/// Backend decisions; no cached financial or inventory value is read here.
class VisitActionViolation extends FormatException {
  const VisitActionViolation(this.issue) : super('Invalid Visit action');
  final VisitActionIssue issue;
}

void validateVisitActions({
  required String outcome,
  required List<CartItemModel> cart,
  required String cash,
  required String debt,
  String? notes,
}) {
  if (!['Sale', 'NoSale', 'Postponed'].contains(outcome)) {
    throw const VisitActionViolation(VisitActionIssue.invalidOutcome);
  }
  final text = notes?.trim() ?? '';
  if (text.contains('\u0000') ||
      text.runes.length > (outcome == 'Sale' ? 4000 : 200)) {
    throw const VisitActionViolation(VisitActionIssue.invalidNotes);
  }
  final products = <int>{};
  var sold = false;
  var samples = false;
  var returned = false;
  var cartLines = 0;
  var returnLines = 0;
  for (final item in cart) {
    final quantities = [
      item.cartons, item.packs, item.sampleCartons, item.samplePacks,
      item.returnDamagedCartons, item.returnDamagedPacks,
      item.returnExpiredCartons, item.returnExpiredPacks,
      item.returnFactoryCartons, item.returnFactoryPacks,
    ];
    if (item.productVariantId <= 0 || item.productVariantId > 2147483647 ||
        !products.add(item.productVariantId) ||
        quantities.any((quantity) => quantity < 0 || quantity > 2147483647)) {
      throw const VisitActionViolation(VisitActionIssue.invalidQuantity);
    }
    final hasSale = item.cartons > 0 || item.packs > 0;
    final hasSample = item.sampleCartons > 0 || item.samplePacks > 0;
    sold = sold || hasSale;
    samples = samples || hasSample;
    if (hasSale || hasSample) {
      cartLines++;
    }
    if (((hasSale || hasSample) &&
        (item.sampleReason.contains('\u0000') ||
         item.sampleReason.trim().runes.length > 255)) ||
        (hasSample && item.sampleReason.trim().isEmpty)) {
      throw const VisitActionViolation(VisitActionIssue.sampleReason);
    }
    returnLines += item.returns.length;
    returned = returned || item.returns.isNotEmpty;
  }
  if (cartLines > 500 || returnLines > 500) {
    throw const VisitActionViolation(VisitActionIssue.invalidQuantity);
  }
  // canonicalVisitMoney has already checked syntax. Digit presence is an
  // exact positivity check, independent of decimal scale and binary floats.
  final hasCash = RegExp(r'[1-9]').hasMatch(cash);
  final hasDebt = RegExp(r'[1-9]').hasMatch(debt);
  if (outcome == 'Sale' && !sold) {
    throw const VisitActionViolation(VisitActionIssue.saleQuantityRequired);
  }
  if (outcome == 'NoSale') {
    if (sold) {
      throw const VisitActionViolation(VisitActionIssue.noSaleSoldQuantity);
    }
    if (hasCash) {
      throw const VisitActionViolation(VisitActionIssue.noSaleCash);
    }
    // The schema also requires notes for collection-only NoSale.
    if (!samples && !returned && text.isEmpty) {
      throw const VisitActionViolation(VisitActionIssue.noSaleReason);
    }
  }
  if (outcome == 'Postponed' &&
      (sold || samples || returned || hasCash || hasDebt)) {
    throw const VisitActionViolation(VisitActionIssue.postponedActions);
  }
}
