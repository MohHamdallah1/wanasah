import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';

import '../../data/visit_field_client.dart';
import '../../domain/invoice/field_invoice.dart';
import '../../domain/invoice/invoice_preview_request.dart';
import 'invoice_preview_outcome.dart';

typedef InvoicePreviewRead = Future<InvoicePreview> Function(
  int visitId, InvoicePreviewRequest request,
);

/// Delegates all amounts, offers, tax, rounding and currency to Backend.
class PreviewVisitInvoice {
  const PreviewVisitInvoice({required InvoicePreviewRead preview})
    : _preview = preview;

  factory PreviewVisitInvoice.fromClient(VisitFieldClient client) =>
      PreviewVisitInvoice(preview: client.previewInvoice);

  final InvoicePreviewRead _preview;

  Future<InvoicePreviewOutcome> execute(
    int visitId, InvoicePreviewRequest request,
  ) async {
    try {
      return InvoicePreviewAvailable(await _preview(visitId, request));
    } on ApiFailureException catch (error) {
      return InvoicePreviewFailed(error.apiFailure);
    } on FormatException {
      return const InvoicePreviewInvalidResponse();
    }
  }
}
