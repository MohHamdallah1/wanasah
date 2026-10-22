import 'package:flutter/material.dart';
import '../../../models/cart_item_model.dart';
import '../application/visit_money_input.dart';
import '../application/visit_return_submission.dart';
import '../application/visit_sale_confirmation.dart';
import '../application/commercial/read_commercial_readiness.dart';
import '../application/commercial/commercial_readiness_outcome.dart';
import '../application/returns/return_resolution_coordinator.dart';
import '../application/invoice/preview_visit_invoice.dart';
import 'commercial/visit_commercial_gate.dart';
import 'returns/resolve_visit_returns.dart';
import 'invoice/confirm_visit_invoice.dart';
import 'visit_field_failure.dart';
import 'visit_field_strings.dart';

class VisitFieldConfirmation {
  const VisitFieldConfirmation({required this.outcome, required this.notes,
    required this.cash, required this.debt, required this.returns, this.sale});
  final String outcome;
  final String notes;
  final String cash;
  final String debt;
  final ResolvedVisitReturns returns;
  final VisitSaleConfirmation? sale;
}

/// Presentation sequences operator decisions. The accepted use-cases continue
/// to own all Backend reads; this function never calls transport or persistence.
Future<VisitFieldConfirmation?> confirmVisitFieldSubmission(BuildContext context, {
  required int visitId, required List<CartItemModel> cart,
  required String notes, required String cashText, required String debtText,
  required ReadCommercialReadiness readiness,
  required ReturnResolutionCoordinator returns,
  required PreviewVisitInvoice preview,
}) async {
  final String cash;
  final String debt;
  try {
    cash = canonicalVisitMoney(cashText);
    debt = canonicalVisitMoney(debtText);
  } on FormatException {
    await showVisitFieldFailure(context, issue: 'invalidMoney');
    return null;
  }
  if (cart.any((item) => (item.sampleCartons > 0 || item.samplePacks > 0) &&
      item.sampleReason.trim().isEmpty)) {
    await showVisitFieldFailure(context, issue: 'sampleReason');
    return null;
  }
  final hasSales = cart.any((item) => item.cartons > 0 || item.packs > 0);
  var outcome = hasSales ? 'Sale' : 'NoSale';
  var finalNotes = notes;
  if (cart.isEmpty) {
    if (!context.mounted) return null;
    final selected = await showDialog<String>(context: context,
      builder: (context) => AlertDialog(
        title: Text(VisitFieldStrings.of(context).t('emptyOutcome')),
        content: Text(VisitFieldStrings.of(context).t('chooseOutcome')),
        actions: [
          for (final value in ['NoSale', 'Postponed'])
            TextButton(onPressed: () => Navigator.pop(context, value),
              child: Text(VisitFieldStrings.of(context).t(
                value == 'NoSale' ? 'noSale' : 'postponed'))),
          TextButton(onPressed: () => Navigator.pop(context),
            child: Text(VisitFieldStrings.of(context).t('cancel'))),
        ],
      ));
    if (!context.mounted) return null;
    if (selected == null) return null;
    outcome = selected;
    if (finalNotes.trim().isEmpty) {
      finalNotes = VisitFieldStrings.of(context).t(
        selected == 'NoSale' ? 'noSaleNote' : 'postponedNote');
    }
  }
  CommercialReady? commercial;
  if (hasSales) {
    if (!context.mounted) return null;
    if (cashText.trim().isEmpty) {
      await showVisitFieldFailure(context, issue: 'cashRequired');
      return null;
    }
    if (!context.mounted) return null;
    commercial = await checkVisitCommercialReadiness(context,
      visitId: visitId, read: readiness);
    if (!context.mounted) return null;
    if (commercial == null) return null;
  }
  if (!context.mounted) return null;
  final resolved = await resolveVisitReturns(context,
    visitId: visitId, cart: cart, coordinator: returns);
  if (!context.mounted) return null;
  if (resolved == null) return null;
  VisitSaleConfirmation? sale;
  if (commercial != null) {
    final request = visitInvoiceRequest(cart);
    if (!context.mounted) return null;
    final invoice = await confirmVisitInvoice(context, visitId: visitId,
      request: request, preview: preview);
    if (invoice == null || !context.mounted) return null;
    sale = VisitSaleConfirmation(visitId: visitId, readiness: commercial,
      preview: invoice, request: request);
  }
  return VisitFieldConfirmation(outcome: outcome, notes: finalNotes,
    cash: cash, debt: debt, returns: resolved, sale: sale);
}
