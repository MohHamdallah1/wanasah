import 'package:wanasah_frontend/core/network/api_failure.dart';

import '../../domain/invoice/field_invoice.dart';

sealed class InvoicePreviewOutcome {
  const InvoicePreviewOutcome();
}

final class InvoicePreviewAvailable extends InvoicePreviewOutcome {
  const InvoicePreviewAvailable(this.preview);
  final InvoicePreview preview;
}

final class InvoicePreviewFailed extends InvoicePreviewOutcome {
  const InvoicePreviewFailed(this.failure);
  final ApiFailure failure;
}

final class InvoicePreviewInvalidResponse extends InvoicePreviewOutcome {
  const InvoicePreviewInvalidResponse();
}
