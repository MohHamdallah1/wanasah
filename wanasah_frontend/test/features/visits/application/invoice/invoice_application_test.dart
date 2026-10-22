import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/committed_invoice_outcome.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/invoice_preview_outcome.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/preview_visit_invoice.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/read_committed_visit_invoice.dart';
import 'package:wanasah_frontend/features/visits/data/visit_field_client.dart';
import 'package:wanasah_frontend/features/visits/domain/invoice/field_invoice.dart';
import 'package:wanasah_frontend/features/visits/domain/invoice/invoice_preview_request.dart';

import '../../domain/invoice/invoice_fixtures.dart';
import '../../domain/returns/return_fixtures.dart';

InvoicePreviewRequest soldItems() =>
    InvoicePreviewRequest([InvoicePreviewLine(productVariantId: 44, packsQuantity: 3)]);

Map<String, dynamic> authoritativeInvoice({required String status, required bool revision}) {
  final json = invoiceJson(status: status, revision: revision);
  final totals = json['totals'] as Map<String, dynamic>;
  totals['tax_amount'] = '0.160000';
  totals['line_total_amount'] = '9007199254740992.283456';
  totals['final_amount'] = '9007199254740992.283000';
  final line = (json['lines'] as List).single as Map<String, dynamic>;
  line['tax_amount'] = '0.160000';
  line['final_amount'] = '9007199254740992.283456';
  return json;
}

void main() {
  test('preview delegates quantity-only business input and preserves exact financial evidence', () async {
    var calls = 0;
    final request = soldItems();
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async => throw StateError('Unexpected GET'),
      post: (path, {required data}) async {
        calls++;
        expect(path, '/visits/11/invoice-preview');
        expect(data, request.toJson());
        return {
          'invoice': authoritativeInvoice(status: 'PREVIEW', revision: false),
          'commit_required': true,
        };
      },
    );
    final outcome = await PreviewVisitInvoice.fromClient(client).execute(11, request)
      as InvoicePreviewAvailable;
    final invoice = outcome.preview.invoice;
    expect(calls, 1);
    expect(outcome.preview.commitRequired, isTrue);
    expect(invoice.status, FieldInvoiceStatus.preview);
    expect(invoice.revisionNumber, isNull);
    expect(invoice.currencyCode, 'JOD');
    expect(invoice.rounding.precision, 3);
    expect(invoice.rounding.mode, InvoiceRoundingMode.halfUp);
    expect(invoice.calculatedAt, '2026-10-22T10:15:30.123456+03:00');
    expect(invoice.totals.grossAmount, '9007199254740993.123456');
    expect(invoice.totals.discountAmount, '1.000000');
    expect(invoice.totals.postOfferAmount, '9007199254740992.123456');
    expect(invoice.totals.taxableAmount, '9007199254740992.123456');
    expect(invoice.totals.taxAmount, '0.160000');
    expect(invoice.totals.lineTotalAmount, '9007199254740992.283456');
    expect(invoice.totals.roundingAdjustment, '-0.000456');
    expect(invoice.totals.finalAmount, '9007199254740992.283000');
    expect(invoice.lines.single.taxAmount, '0.160000');
    expect(invoice.lines.single.finalAmount, '9007199254740992.283456');
    expect(invoice.rewards.single.baseQuantity, '0.500000');
  });

  test('preview outcome preserves the typed Backend object without recalculation', () async {
    final preview = InvoicePreview.fromJson({
      'invoice': authoritativeInvoice(status: 'PREVIEW', revision: false),
      'commit_required': true,
    });
    final useCase = PreviewVisitInvoice(preview: (id, request) async => preview);
    final outcome = await useCase.execute(11, soldItems()) as InvoicePreviewAvailable;
    expect(outcome.preview, same(preview));
  });

  test('frozen read remains committed and retains immutable revision/currency/rounding/tax', () async {
    var calls = 0;
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async {
        calls++;
        expect(path, '/visits/11/invoice');
        return {'invoice': authoritativeInvoice(status: 'COMMITTED', revision: true)};
      },
      post: (path, {required data}) async => throw StateError('Unexpected POST'),
    );
    final outcome = await ReadCommittedVisitInvoice.fromClient(client).execute(11)
      as CommittedInvoiceAvailable;
    final invoice = outcome.result.invoice!;
    expect(calls, 1);
    expect(outcome.result.availability, InvoiceAvailability.available);
    expect(invoice.status, FieldInvoiceStatus.committed);
    expect(invoice.revisionNumber, 2);
    expect(invoice.currencyCode, 'JOD');
    expect(invoice.rounding.precision, 3);
    expect(invoice.rounding.mode, InvoiceRoundingMode.halfUp);
    expect(invoice.totals.taxAmount, '0.160000');
    expect(invoice.totals.finalAmount, '9007199254740992.283000');
  });

  test('an authoritative non-sale read stays explicit and distinct from an invoice', () async {
    final expected = CommittedInvoiceResult.fromReadResponse({'invoice': null});
    final useCase = ReadCommittedVisitInvoice(read: (id) async => expected);
    final outcome = await useCase.execute(11) as CommittedInvoiceAvailable;
    expect(outcome.result, same(expected));
    expect(outcome.result.availability, InvoiceAvailability.none);
    expect(outcome.result.invoice, isNull);
  });

  test('preview rejects committed evidence and numeric money instead of converting it', () async {
    for (final body in [
      {'invoice': invoiceJson(), 'commit_required': true},
      {'invoice': <String, dynamic>{
        ...invoiceJson(status: 'PREVIEW', revision: false),
        'totals': {...(invoiceJson()['totals'] as Map<String, dynamic>), 'final_amount': 1.125},
      }, 'commit_required': true},
      <String, dynamic>{},
    ]) {
      final client = VisitFieldClient(
        get: (path, {queryParameters}) async => throw StateError('Unexpected GET'),
        post: (path, {required data}) async => body,
      );
      expect(await PreviewVisitInvoice.fromClient(client).execute(11, soldItems()),
        isA<InvoicePreviewInvalidResponse>());
    }
  });

  test('frozen read rejects preview, missing invoice and missing frozen revision', () async {
    for (final body in [
      {'invoice': invoiceJson(status: 'PREVIEW')},
      {'invoice': invoiceJson(revision: false)},
      <String, dynamic>{},
    ]) {
      final client = VisitFieldClient(
        get: (path, {queryParameters}) async => body,
        post: (path, {required data}) async => throw StateError('Unexpected POST'),
      );
      expect(await ReadCommittedVisitInvoice.fromClient(client).execute(11),
        isA<CommittedInvoiceInvalidResponse>());
    }
  });

  test('both invoice use-cases preserve exact ApiFailure evidence without retry', () async {
    final original = ApiFailure.fromDioException(responseError(
      code: 'COMMERCIAL_CONTEXT_LOCKED', context: {'required_action': 'BACKOFFICE_REVIEW'},
    ));
    var previewCalls = 0;
    var readCalls = 0;
    final preview = PreviewVisitInvoice(preview: (id, request) async {
      previewCalls++;
      throw ApiFailureException(original);
    });
    final read = ReadCommittedVisitInvoice(read: (id) async {
      readCalls++;
      throw ApiFailureException(original);
    });
    final previewOutcome = await preview.execute(11, soldItems()) as InvoicePreviewFailed;
    final readOutcome = await read.execute(11) as CommittedInvoiceFailed;
    expect(previewCalls, 1);
    expect(readCalls, 1);
    for (final failure in [previewOutcome.failure, readOutcome.failure]) {
      expect(failure, same(original));
      expect(failure.context, same(original.context));
      expect(failure.status, 409);
      expect(failure.code, 'COMMERCIAL_CONTEXT_LOCKED');
      expect(failure.requestId, 'canonical-id');
    }
  });
}
