import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';

import '../../data/visit_field_client.dart';
import '../../domain/invoice/field_invoice.dart';
import 'committed_invoice_outcome.dart';

typedef CommittedInvoiceRead = Future<CommittedInvoiceResult> Function(int visitId);

class ReadCommittedVisitInvoice {
  const ReadCommittedVisitInvoice({required CommittedInvoiceRead read})
    : _read = read;

  factory ReadCommittedVisitInvoice.fromClient(VisitFieldClient client) =>
      ReadCommittedVisitInvoice(read: client.readInvoice);

  final CommittedInvoiceRead _read;

  Future<CommittedInvoiceOutcome> execute(int visitId) async {
    try {
      return CommittedInvoiceAvailable(await _read(visitId));
    } on ApiFailureException catch (error) {
      return CommittedInvoiceFailed(error.apiFailure);
    } on FormatException {
      return const CommittedInvoiceInvalidResponse();
    }
  }
}
