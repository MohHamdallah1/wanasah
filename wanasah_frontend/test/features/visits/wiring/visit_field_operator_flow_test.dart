import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/features/visits/application/commercial/read_commercial_readiness.dart';
import 'package:wanasah_frontend/features/visits/application/commercial/commercial_readiness_outcome.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/preview_visit_invoice.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/read_committed_visit_invoice.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/committed_invoice_outcome.dart';
import 'package:wanasah_frontend/features/visits/application/returns/return_resolution_coordinator.dart';
import 'package:wanasah_frontend/features/visits/application/visit_command_evidence.dart';
import 'package:wanasah_frontend/features/visits/domain/commercial/commercial_readiness.dart';
import 'package:wanasah_frontend/features/visits/domain/invoice/field_invoice.dart';
import 'package:wanasah_frontend/features/visits/domain/returns/return_resolution.dart';
import 'package:wanasah_frontend/features/visits/presentation/confirm_visit_field_submission.dart';
import 'package:wanasah_frontend/features/visits/presentation/commercial/visit_commercial_gate.dart';
import 'package:wanasah_frontend/features/visits/presentation/invoice/visit_invoice_panel.dart';
import 'package:wanasah_frontend/features/visits/presentation/invoice/visit_invoice_receipt.dart';
import 'package:wanasah_frontend/features/visits/presentation/returns/return_ambiguity_chooser.dart';
import 'package:wanasah_frontend/features/visits/presentation/visit_field_failure.dart';
import '../domain/invoice/invoice_fixtures.dart';
import '../domain/returns/return_fixtures.dart';
import 'visit_submission_wiring_test.dart' show draft;

CommercialReadiness ready() => CommercialReadiness.fromJson({
  'status': 'READY', 'sale_ready': true, 'code': null, 'required_action': null,
});
InvoicePreview preview() => InvoicePreview.fromJson({
  'commit_required': true, 'invoice': invoiceJson(status: 'PREVIEW', revision: false),
});

Future<void> startFlow(WidgetTester tester, {
  required ReturnResolutionCoordinator returns,
  required void Function(VisitFieldConfirmation?) receive,
  ReadCommercialReadiness? readiness, PreviewVisitInvoice? invoice, bool sale = false,
}) async {
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: Builder(
    builder: (context) => TextButton(onPressed: () async {
      receive(await confirmVisitFieldSubmission(context, visitId: 11,
        cart: [draft(sale: sale ? 1 : 0, damaged: sale ? 0 : 1)],
        notes: '', cashText: '0.000', debtText: '0',
        readiness: readiness ?? ReadCommercialReadiness(read: (_) async => ready()),
        returns: returns,
        preview: invoice ?? PreviewVisitInvoice(preview: (_, __) async => preview()),
      ));
    }, child: const Text('start')),
  ))));
  await tester.tap(find.text('start'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('deterministic return resolves without an operator choice', (tester) async {
    VisitFieldConfirmation? confirmation;
    var calls = 0;
    await startFlow(tester, returns: ReturnResolutionCoordinator(resolve: (id, request) async {
      calls++;
      return FieldReturnResolution.fromJson({
        ...resolvedJson(), 'resolution_token': '  exact.opaque/+=  ',
      }, request: request);
    }), receive: (value) => confirmation = value,
      readiness: ReadCommercialReadiness(read: (_) => throw StateError('NoSale must skip readiness')),
      invoice: PreviewVisitInvoice(preview: (_, __) => throw StateError('NoSale must skip preview')));
    expect(calls, 1);
    expect(find.byType(ReturnAmbiguityChooser), findsNothing);
    expect(confirmation!.outcome, 'NoSale');
    expect(confirmation!.returns.resolutions.single.resolutionToken, '  exact.opaque/+=  ');
    expect(confirmation!.returns.resolutions.single.request.quantity, 1);
    expect(confirmation!.returns.resolutions.single.request.packsQuantity, 2);
  });

  testWidgets('ambiguity never selects first candidate; operator business evidence is re-resolved', (tester) async {
    VisitFieldConfirmation? confirmation;
    final seen = <ReturnResolutionRequest>[];
    await startFlow(tester, returns: ReturnResolutionCoordinator(resolve: (id, request) async {
      seen.add(request);
      if (request.evidence.lotNumber == null) {
        throw ApiFailureException(responseError(
          message: 'Anything: success/retry/تالف',
          context: {'required_evidence': ['lot_number'], 'batch_id': 999,
            'choices': [
              {'lot_number': 'LOT-A', 'batch_id': 1},
              {'lot_number': 'LOT-B', 'batch_id': 2},
            ]},
        ).apiFailure);
      }
      return FieldReturnResolution.fromJson(resolvedJson(), request: request);
    }), receive: (value) => confirmation = value);
    expect(seen, hasLength(1));
    expect(confirmation, isNull);
    final button = tester.widget<FilledButton>(find.widgetWithText(FilledButton, 'Continue'));
    expect(button.onPressed, isNull);
    expect(find.textContaining('batch_id'), findsNothing);
    expect(find.textContaining('999'), findsNothing);
    expect(find.text('canonical-id'), findsNothing); // Combined safe diagnostics only.
    expect(find.textContaining('canonical-id'), findsOneWidget);
    await tester.tap(find.textContaining('LOT-B'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Continue'));
    await tester.pumpAndSettle();
    expect(seen, hasLength(2));
    expect(seen.last.evidence.toJson(), {'lot_number': 'LOT-B'});
    expect(seen.last.quantity, 1);
    expect(seen.last.packsQuantity, 2);
    expect(confirmation, isNotNull);
  });

  testWidgets('commercial action blocks sale before preview and preserves required action/code', (tester) async {
    VisitFieldConfirmation? confirmation;
    var previews = 0;
    final action = CommercialReadiness.fromJson({
      'status': 'ACTION_REQUIRED', 'sale_ready': false,
      'code': 'SHOP_TAX_JURISDICTION_REQUIRED',
      'required_action': 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
    });
    await startFlow(tester, sale: true, receive: (value) => confirmation = value,
      returns: ReturnResolutionCoordinator(resolve: (_, __) => throw StateError('No returns')),
      readiness: ReadCommercialReadiness(read: (_) async => action),
      invoice: PreviewVisitInvoice(preview: (_, __) async { previews++; return preview(); }));
    final blocker = tester.widget<VisitCommercialBlocker>(find.byType(VisitCommercialBlocker));
    expect(identical(blocker.outcome.readiness, action), isTrue);
    expect(blocker.outcome.requiredAction, 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION');
    expect(find.text('SHOP_TAX_JURISDICTION_REQUIRED'), findsOneWidget);
    expect(previews, 0);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(confirmation, isNull);
  });

  testWidgets('ready Sale requires explicit preview confirmation with exact Backend money', (tester) async {
    VisitFieldConfirmation? confirmation;
    final authoritative = preview();
    var reads = 0;
    await startFlow(tester, sale: true, receive: (value) => confirmation = value,
      returns: ReturnResolutionCoordinator(resolve: (_, __) => throw StateError('No returns')),
      readiness: ReadCommercialReadiness(read: (_) async { reads++; return ready(); }),
      invoice: PreviewVisitInvoice(preview: (id, request) async {
        expect(id, 11);
        expect(request.toJson(), {'cart_items': [
          {'product_variant_id': 44, 'quantity': 1, 'packs_quantity': 0},
        ]});
        return authoritative;
      }));
    expect(reads, 1);
    expect(confirmation, isNull);
    expect(find.text('Backend invoice preview — not committed'), findsOneWidget);
    expect(find.text('Committed invoice — frozen evidence'), findsNothing);
    expect(find.text(formatVisitExactMoney('9007199254740992.123000', const Locale('en'))), findsOneWidget);
    expect(find.text('Currency: JOD'), findsOneWidget);
    expect(find.text('Rounding: Half up'), findsOneWidget);
    await tester.tap(find.text('Confirm sale'));
    await tester.pumpAndSettle();
    expect(confirmation!.outcome, 'Sale');
    expect(identical(confirmation!.sale!.preview, authoritative), isTrue);
    expect(confirmation!.sale!.preview.invoice.totals.finalAmount, '9007199254740992.123000');
  });

  testWidgets('malformed readiness fails closed without retry or preview', (tester) async {
    var calls = 0;
    VisitFieldConfirmation? confirmation;
    await startFlow(tester, sale: true, receive: (value) => confirmation = value,
      returns: ReturnResolutionCoordinator(resolve: (_, __) => throw StateError('No returns')),
      readiness: ReadCommercialReadiness(read: (_) async {
        calls++; throw const FormatException('malformed');
      }),
      invoice: PreviewVisitInvoice(preview: (_, __) => throw StateError('Must not preview')));
    expect(calls, 1);
    expect(find.byType(VisitFieldFailurePanel), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(confirmation, isNull);
  });

  testWidgets('structured failure context/request ID survive; free text never drives classification/retry', (tester) async {
    final failure = responseError(code: 'OTHER_BUSINESS_CODE', message: 'FIELD_RETURN_EVIDENCE_REQUIRED retry', status: 409).apiFailure;
    var calls = 0;
    await startFlow(tester, receive: (_) {},
      returns: ReturnResolutionCoordinator(resolve: (_, __) async {
        calls++; throw ApiFailureException(failure);
      }));
    expect(calls, 1);
    expect(find.byType(ReturnAmbiguityChooser), findsNothing);
    final panel = tester.widget<VisitFieldFailurePanel>(find.byType(VisitFieldFailurePanel));
    expect(identical(panel.failure, failure), isTrue);
    expect(panel.failure!.context, failure.context);
    expect(find.textContaining('canonical-id'), findsOneWidget);
    expect(visitFailureCategory(failure), VisitFailureCategory.business);
    expect(visitFailureCategory(responseError(status: 403).apiFailure), VisitFailureCategory.authorization);
    const offline = ApiFailure(kind: ApiFailureKind.timeout, status: null, code: null,
      message: 'ready', context: {}, requestId: 'timeout-id', displayFallback: null);
    expect(visitFailureCategory(offline), VisitFailureCategory.connectivity);
  });

  testWidgets('confirmed frozen invoice is separate from preview; queued result never reads old invoice', (tester) async {
    var reads = 0;
    final frozen = CommittedInvoiceResult.fromReadResponse({'invoice': invoiceJson()});
    final reader = ReadCommittedVisitInvoice(read: (_) async { reads++; return frozen; });
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: VisitInvoiceReceipt(
      visitId: 11, disposition: VisitSubmissionDisposition.confirmed,
      initial: CommittedInvoiceAvailable(frozen), read: reader))));
    expect(find.text('Committed invoice — frozen evidence'), findsOneWidget);
    expect(find.text('Backend invoice preview — not committed'), findsNothing);
    expect(find.text('Revision: 2'), findsOneWidget);
    await tester.pumpWidget(MaterialApp(home: Scaffold(body: VisitInvoiceReceipt(
      key: const ValueKey('pending'), visitId: 11,
      disposition: VisitSubmissionDisposition.unresolved,
      initial: null, read: reader))));
    expect(find.textContaining('Submission is unresolved'), findsOneWidget);
    expect(find.text('Committed invoice — frozen evidence'), findsNothing);
    expect(find.text('Read invoice again'), findsNothing);
    expect(reads, 0);
  });

  test('exact separator localization preserves every decimal digit without conversion', () {
    expect(formatVisitExactMoney('9007199254740993.123000', const Locale('en')),
      '9,007,199,254,740,993.123000');
    expect(formatVisitExactMoney('-0.000456', const Locale('en')), '-0.000456');
  });
}
