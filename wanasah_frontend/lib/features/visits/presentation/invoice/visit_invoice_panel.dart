import 'package:flutter/material.dart';
import 'package:intl/intl.dart';
import '../../domain/invoice/field_invoice.dart';
import '../visit_field_strings.dart';

/// Localizes separators without converting authoritative decimals to a number.
String formatVisitExactMoney(String amount, Locale locale) {
  final symbols = NumberFormat.decimalPattern(locale.toLanguageTag()).symbols;
  final parts = amount.split('.');
  final integer = parts.first.replaceAllMapped(
    RegExp(r'(\d)(?=(\d{3})+(?!\d))'),
    (match) => '${match[1]}${symbols.GROUP_SEP}');
  return parts.length == 1 ? integer : '$integer${symbols.DECIMAL_SEP}${parts[1]}';
}

class VisitInvoicePanel extends StatelessWidget {
  const VisitInvoicePanel.preview(this.preview, {super.key}) : committed = null;
  const VisitInvoicePanel.committed(this.committed, {super.key}) : preview = null;
  final InvoicePreview? preview;
  final CommittedInvoiceResult? committed;

  @override
  Widget build(BuildContext context) {
    final strings = VisitFieldStrings.of(context);
    final invoice = preview?.invoice ?? committed?.invoice;
    if (invoice == null) return Text(strings.t('noInvoice'));
    final locale = Localizations.localeOf(context);
    Widget row(String key, String amount) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
        Flexible(child: Text(strings.t(key))),
        const SizedBox(width: 12),
        Flexible(child: Text(formatVisitExactMoney(amount, locale))),
      ]));
    final totals = invoice.totals;
    final date = DateTime.parse(invoice.calculatedAt).toLocal();
    final material = MaterialLocalizations.of(context);
    return Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(strings.t(preview != null ? 'preview' : 'committed'),
          style: Theme.of(context).textTheme.titleMedium),
        Text('${strings.t('currency')}: ${invoice.currencyCode}'),
        row('gross', totals.grossAmount), row('discount', totals.discountAmount),
        row('postOffer', totals.postOfferAmount), row('taxable', totals.taxableAmount),
        row('tax', totals.taxAmount), row('lineTotal', totals.lineTotalAmount),
        row('adjustment', totals.roundingAdjustment), row('payable', totals.finalAmount),
        Text('${strings.t('rounding')}: ${strings.t(invoice.rounding.mode == InvoiceRoundingMode.halfUp ? 'halfUp' : 'halfEven')}'),
        Text('${strings.t('precision')}: ${NumberFormat.decimalPattern(locale.toLanguageTag()).format(invoice.rounding.precision)}'),
        Text('${strings.t('calculated')}: ${material.formatFullDate(date)} ${material.formatTimeOfDay(TimeOfDay.fromDateTime(date))}'),
        if (invoice.revisionNumber != null)
          Text('${strings.t('revision')}: ${NumberFormat.decimalPattern(locale.toLanguageTag()).format(invoice.revisionNumber)}'),
      ]);
  }
}
