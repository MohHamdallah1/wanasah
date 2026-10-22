import 'package:flutter/material.dart';
import '../../application/visit_command_evidence.dart';
import '../../application/invoice/committed_invoice_outcome.dart';
import '../../application/invoice/read_committed_visit_invoice.dart';
import '../visit_field_failure.dart';
import '../visit_field_strings.dart';
import 'visit_invoice_panel.dart';

/// Mutation completion and invoice-read availability are separate states.
/// This component can only repeat the read, never resubmit a Visit.
class VisitInvoiceReceipt extends StatefulWidget {
  const VisitInvoiceReceipt({super.key, required this.visitId,
    required this.disposition, required this.initial, required this.read});
  final int visitId;
  final VisitSubmissionDisposition disposition;
  final CommittedInvoiceOutcome? initial;
  final ReadCommittedVisitInvoice read;
  @override
  State<VisitInvoiceReceipt> createState() => _VisitInvoiceReceiptState();
}

class _VisitInvoiceReceiptState extends State<VisitInvoiceReceipt> {
  late CommittedInvoiceOutcome? _outcome = widget.initial;
  bool _reading = false;

  Future<void> _read() async {
    setState(() => _reading = true);
    CommittedInvoiceOutcome result;
    try { result = await widget.read.execute(widget.visitId); }
    catch (_) { result = const CommittedInvoiceInvalidResponse(); }
    if (!mounted) return;
    setState(() { _outcome = result; _reading = false; });
  }

  @override
  Widget build(BuildContext context) {
    final strings = VisitFieldStrings.of(context);
    final pending = widget.disposition == VisitSubmissionDisposition.unresolved;
    return AlertDialog(
      content: SingleChildScrollView(child: Column(mainAxisSize: MainAxisSize.min,
        children: [
          Text(strings.t(pending ? 'pending' : 'confirmed')),
          if (!pending) ...[
            if (_outcome case CommittedInvoiceAvailable(:final result))
              VisitInvoicePanel.committed(result),
            if (_outcome case CommittedInvoiceFailed(:final failure)) ...[
              Text(strings.t('readFailed')), VisitFieldFailurePanel(failure: failure),
            ],
            if (_outcome is CommittedInvoiceInvalidResponse) ...[
              Text(strings.t('readFailed')), const VisitFieldFailurePanel(),
            ],
            if (_reading) const CircularProgressIndicator(),
          ],
        ])),
      actions: [
        if (!pending && _outcome != null && _outcome is! CommittedInvoiceAvailable)
          TextButton(onPressed: _reading ? null : _read,
            child: Text(strings.t('retryRead'))),
        TextButton(onPressed: _reading ? null : () => Navigator.pop(context),
          child: Text(strings.t('close'))),
      ],
    );
  }
}
