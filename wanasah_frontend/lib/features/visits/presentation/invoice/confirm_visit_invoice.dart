import 'package:flutter/material.dart';
import '../../application/invoice/preview_visit_invoice.dart';
import '../../application/invoice/invoice_preview_outcome.dart';
import '../../domain/invoice/field_invoice.dart';
import '../../domain/invoice/invoice_preview_request.dart';
import '../visit_field_failure.dart';
import '../visit_field_strings.dart';
import 'visit_invoice_panel.dart';

Future<InvoicePreview?> confirmVisitInvoice(BuildContext context, {
  required int visitId, required InvoicePreviewRequest request,
  required PreviewVisitInvoice preview,
}) async {
  final result = await preview.execute(visitId, request);
  if (!context.mounted) return null;
  switch (result) {
    case InvoicePreviewAvailable():
      final confirmed = await showDialog<bool>(
        context: context, barrierDismissible: false,
        builder: (context) => AlertDialog(
          content: SingleChildScrollView(child: VisitInvoicePanel.preview(result.preview)),
          actions: [
            TextButton(onPressed: () => Navigator.pop(context, false),
              child: Text(VisitFieldStrings.of(context).t('cancel'))),
            FilledButton(onPressed: () => Navigator.pop(context, true),
              child: Text(VisitFieldStrings.of(context).t('confirmSale'))),
          ],
        ),
      );
      return confirmed == true ? result.preview : null;
    case InvoicePreviewFailed():
      await showVisitFieldFailure(context, failure: result.failure);
    case InvoicePreviewInvalidResponse():
      await showVisitFieldFailure(context);
  }
  return null;
}
