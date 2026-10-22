import 'package:wanasah_frontend/core/network/api_failure.dart';

import '../../domain/invoice/field_invoice.dart';

sealed class CommittedInvoiceOutcome {
  const CommittedInvoiceOutcome();
}

final class CommittedInvoiceAvailable extends CommittedInvoiceOutcome {
  const CommittedInvoiceAvailable(this.result);
  /// Preserves authoritative non-sale/null and committed evidence separately.
  final CommittedInvoiceResult result;
}

final class CommittedInvoiceFailed extends CommittedInvoiceOutcome {
  const CommittedInvoiceFailed(this.failure);
  final ApiFailure failure;
}

final class CommittedInvoiceInvalidResponse extends CommittedInvoiceOutcome {
  const CommittedInvoiceInvalidResponse();
}
