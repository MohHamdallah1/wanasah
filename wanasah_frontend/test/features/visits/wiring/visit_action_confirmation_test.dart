import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/visits/application/commercial/read_commercial_readiness.dart';
import 'package:wanasah_frontend/features/visits/application/invoice/preview_visit_invoice.dart';
import 'package:wanasah_frontend/features/visits/application/returns/return_resolution_coordinator.dart';
import 'package:wanasah_frontend/features/visits/presentation/confirm_visit_field_submission.dart';
import 'package:wanasah_frontend/models/cart_item_model.dart';
import 'visit_submission_wiring_test.dart' show draft;

Future<void> start(WidgetTester tester, {
  required List<CartItemModel> cart,
  String cash = '0', String debt = '0', String notes = '',
  required void Function(VisitFieldConfirmation?) receive,
}) async {
  await tester.pumpWidget(MaterialApp(home: Scaffold(body: Builder(
    builder: (context) => TextButton(onPressed: () async {
      receive(await confirmVisitFieldSubmission(context, visitId: 11,
        cart: cart, notes: notes, cashText: cash, debtText: debt,
        readiness: ReadCommercialReadiness(read: (_) => throw StateError('NoSale / Postponed must not read readiness')),
        returns: ReturnResolutionCoordinator(resolve: (_, __) => throw StateError('Invalid action must not resolve')),
        preview: PreviewVisitInvoice(preview: (_, __) => throw StateError('NoSale / Postponed must not preview')),
      ));
    }, child: const Text('start')),
  ))));
  await tester.tap(find.text('start'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('NoSale requires actual operator notes instead of inventing a reason', (tester) async {
    VisitFieldConfirmation? result;
    await start(tester, cart: [], debt: '3', receive: (value) => result = value);
    await tester.tap(find.text('No sale'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Enter the reason for no sale'), findsOneWidget);
    expect(find.text('No goods required'), findsNothing);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(result, isNull);
  });

  testWidgets('collection-only NoSale preserves exact amount and human notes', (tester) async {
    VisitFieldConfirmation? result;
    await start(tester, cart: [], debt: '12.340', notes: 'Customer paid old debt',
      receive: (value) => result = value);
    await tester.tap(find.text('No sale'));
    await tester.pumpAndSettle();
    expect(result!.outcome, 'NoSale');
    expect(result!.notes, 'Customer paid old debt');
    expect(result!.debt, '12.340');
    expect(result!.cash, '0');
    expect(result!.sale, isNull);
  });

  testWidgets('Postponed with collection input is blocked rather than silently discarding it', (tester) async {
    VisitFieldConfirmation? result;
    await start(tester, cart: [], debt: '12.340', notes: 'Later',
      receive: (value) => result = value);
    await tester.tap(find.text('Postponed'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Postponed cannot include'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(result, isNull);
  });

  testWidgets('Postponed does not require or invent a reason', (tester) async {
    VisitFieldConfirmation? result;
    await start(tester, cart: [], receive: (value) => result = value);
    await tester.tap(find.text('Postponed'));
    await tester.pumpAndSettle();
    expect(result!.outcome, 'Postponed');
    expect(result!.notes, '');
    expect(result!.returns.resolutions, isEmpty);
    expect(result!.sale, isNull);
  });

  testWidgets('positive NoSale cash is blocked before return resolution', (tester) async {
    VisitFieldConfirmation? result;
    await start(tester, cart: [draft()], cash: '0.001',
      receive: (value) => result = value);
    expect(find.textContaining('No sale cannot include sale cash'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(result, isNull);
  });

  testWidgets('sample without reason is blocked before any Backend seam', (tester) async {
    VisitFieldConfirmation? result;
    await start(tester, cart: [draft(damaged: 0).copyWith(samplePacks: 2)],
      receive: (value) => result = value);
    expect(find.textContaining('Enter a sample reason'), findsOneWidget);
    await tester.tap(find.text('Close'));
    await tester.pumpAndSettle();
    expect(result, isNull);
  });
}
