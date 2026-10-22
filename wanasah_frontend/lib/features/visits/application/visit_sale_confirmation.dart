import 'dart:convert';
import '../../../models/cart_item_model.dart';
import 'commercial/commercial_readiness_outcome.dart';
import '../domain/invoice/field_invoice.dart';
import '../domain/invoice/invoice_preview_request.dart';

InvoicePreviewRequest visitInvoiceRequest(List<CartItemModel> cart) =>
    InvoicePreviewRequest([
      for (final item in cart)
        if (item.cartons > 0 || item.packs > 0)
          InvoicePreviewLine(productVariantId: item.productVariantId,
            quantity: item.cartons, packsQuantity: item.packs),
    ]);

/// Presentation confirmation of this exact sold draft, never proof of commit.
class VisitSaleConfirmation {
  VisitSaleConfirmation({required this.visitId, required this.readiness,
    required this.preview, required InvoicePreviewRequest request})
    : _soldDraft = jsonEncode(request.toJson());

  final int visitId;
  final CommercialReady readiness;
  final InvoicePreview preview;
  final String _soldDraft;

  void validate(int id, List<CartItemModel> cart) {
    if (visitId != id || !readiness.taxSetupReady ||
        !readiness.readiness.saleReady ||
        preview.invoice.status != FieldInvoiceStatus.preview ||
        _soldDraft != jsonEncode(visitInvoiceRequest(cart).toJson())) {
      throw const FormatException('Sale confirmation does not match draft');
    }
  }
}
