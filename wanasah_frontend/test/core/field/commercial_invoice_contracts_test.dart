import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/field/field_contracts.dart';

import 'field_contract_fixtures.dart';

void main() {
  test('canonical READY tax setup parses without a Flutter jurisdiction choice', () {
    final state = CommercialReadiness.fromResponse({
      'commercial_readiness': {
        'status': 'READY', 'sale_ready': true, 'code': null, 'required_action': null,
      },
    });
    expect(state.status, CommercialReadinessStatus.ready);
    expect(state.saleReady, isTrue);
    expect(state.code, isNull);
    expect(state.requiredAction, isNull);
  });

  for (final code in [
    'SHOP_TAX_JURISDICTION_REQUIRED', 'SHOP_TAX_JURISDICTION_REVIEW_REQUIRED',
  ]) {
    test('actionable tax completion preserves code $code', () {
      final state = CommercialReadiness.fromResponse({
        'shop': {'id': 99},
        'commercial_readiness': {
          'status': 'ACTION_REQUIRED', 'sale_ready': false, 'code': code,
          'required_action': 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
        },
      });
      expect(state.saleReady, isFalse);
      expect(state.status, CommercialReadinessStatus.actionRequired);
      expect(state.code, code);
      expect(state.requiredAction, 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION');
    });
  }

  test('contradictory or unknown readiness never becomes a ready sale', () {
    for (final json in [
      {'status': 'READY', 'sale_ready': false},
      {'status': 'ACTION_REQUIRED', 'sale_ready': true, 'code': 'X', 'required_action': 'Y'},
      {'status': 'READY', 'sale_ready': true, 'required_action': 'Y'},
      {'status': 'UNKNOWN', 'sale_ready': true},
      {'status': 'ACTION_REQUIRED', 'sale_ready': false, 'code': 'X'},
    ]) {
      expect(() => CommercialReadiness.fromJson(json), throwsFormatException);
    }
  });

  test('preview preserves every authoritative money string and calculation metadata', () {
    final preview = InvoicePreview.fromJson({
      'invoice': invoiceJson(status: 'PREVIEW', revision: false), 'commit_required': true,
    });
    final invoice = preview.invoice;
    expect(preview.commitRequired, isTrue);
    expect(invoice.status, FieldInvoiceStatus.preview);
    expect(invoice.currencyCode, 'JOD');
    expect(invoice.calculatedAt, '2026-10-22T10:15:30.123456+03:00');
    expect(invoice.rounding.precision, 3);
    expect(invoice.rounding.mode, InvoiceRoundingMode.halfUp);
    expect(invoice.totals.grossAmount, '9007199254740993.123456');
    expect(invoice.totals.discountAmount, '1.000000');
    expect(invoice.totals.postOfferAmount, '9007199254740992.123456');
    expect(invoice.totals.taxableAmount, '9007199254740992.123456');
    expect(invoice.totals.taxAmount, '0.000000');
    expect(invoice.totals.lineTotalAmount, '9007199254740992.123456');
    expect(invoice.totals.roundingAdjustment, '-0.000456');
    expect(invoice.totals.finalAmount, '9007199254740992.123000');
    expect(invoice.lines.single.grossAmount, '9007199254740993.123456');
    expect(invoice.lines.single.discountAmount, '1.000000');
    expect(invoice.lines.single.taxAmount, '0.000000');
    expect(invoice.lines.single.finalAmount, '9007199254740992.123456');
    expect(invoice.rewards.single.baseQuantity, '0.500000');
    expect(() => invoice.lines.clear(), throwsUnsupportedError);
    expect(() => invoice.rewards.clear(), throwsUnsupportedError);
  });

  test('frozen read and immediate committed result model separate revision availability', () {
    final frozen = CommittedInvoiceResult.fromReadResponse({'invoice': invoiceJson()});
    expect(frozen.availability, InvoiceAvailability.available);
    expect(frozen.invoice!.revisionNumber, 2);
    final committed = CommittedInvoiceResult.fromVisitResult({
      'message': 'Visit updated successfully', 'invoice': invoiceJson(revision: false),
    });
    expect(committed.invoice!.status, FieldInvoiceStatus.committed);
    expect(committed.invoice!.revisionNumber, isNull);
    expect(committed.invoice!.totals.finalAmount, frozen.invoice!.totals.finalAmount);
  });

  test('legacy replay missing invoice is distinct from explicit non-sale null', () {
    final legacy = CommittedInvoiceResult.fromVisitResult({'message': 'old response'});
    final none = CommittedInvoiceResult.fromVisitResult({'invoice': null});
    expect(legacy.availability, InvoiceAvailability.legacyResponse);
    expect(none.availability, InvoiceAvailability.none);
    expect(legacy.invoice, isNull);
    expect(none.invoice, isNull);
    expect(CommittedInvoiceResult.fromReadResponse({'invoice': null}).availability,
      InvoiceAvailability.none);
    expect(() => CommittedInvoiceResult.fromReadResponse({}), throwsFormatException);
  });

  test('numeric money, unknown rounding and mismatched invoice states fail closed', () {
    final numeric = invoiceJson();
    (numeric['totals'] as Map<String, dynamic>)['final_amount'] = 10.261;
    expect(() => FieldInvoice.fromJson(numeric), throwsFormatException);
    final badRounding = invoiceJson()..['rounding'] = {'precision': 3, 'mode': 'CEILING'};
    expect(() => FieldInvoice.fromJson(badRounding), throwsFormatException);
    expect(() => InvoicePreview.fromJson({
      'invoice': invoiceJson(), 'commit_required': true,
    }), throwsFormatException);
    expect(() => InvoicePreview.fromJson({
      'invoice': invoiceJson(status: 'PREVIEW'), 'commit_required': false,
    }), throwsFormatException);
    expect(() => CommittedInvoiceResult.fromReadResponse({
      'invoice': invoiceJson(revision: false),
    }), throwsFormatException);
    expect(() => CommittedInvoiceResult.fromVisitResult({
      'invoice': invoiceJson(status: 'PREVIEW'),
    }), throwsFormatException);
  });

  test('preview request is immutable quantity transport with no client price authority', () {
    final lines = [InvoicePreviewLine(productVariantId: 44, quantity: 2, packsQuantity: 3)];
    final request = InvoicePreviewRequest(lines);
    lines.clear();
    expect(request.toJson(), {
      'cart_items': [{'product_variant_id': 44, 'quantity': 2, 'packs_quantity': 3}],
    });
    expect(() => request.cartItems.clear(), throwsUnsupportedError);
    expect(() => InvoicePreviewRequest([]), throwsFormatException);
  });
}
