import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/recovery/custody_handoff_client.dart';
import 'package:wanasah_frontend/features/custody/recovery/custody_handoff_screen.dart';

class _SignedFixtureClient extends CustodyHandoffClient {
  _SignedFixtureClient() : super(dio: Dio());
  int previews = 0;
  int confirms = 0;

  @override
  Future<CustodyHandoffPreview> review(String offer) async {
    previews++;
    if (offer != 'signed-by-manager') throw const FormatException('Invalid');
    return CustodyHandoffPreview(
      vehicleId: 99, vehiclePlate: 'TEST-PLATE',
      stockSnapshot: 'a' * 64,
      rows: [
        {
          'product_name': 'Lolo chips',
          'batch_number': 'B-2026',
          'expiry_date': null,
          'base_uom': 'EACH',
          'on_hand_base': '12',
          'reserved_base': '0',
          'stock_status': 'AVAILABLE',
        },
      ],
    );
  }

  @override
  Future<String> confirm(String offer, CustodyHandoffPreview review) async {
    confirms++;
    expect(offer, 'signed-by-manager');
    expect(review.stockSnapshot, 'a' * 64);
    return 'signed-field-receipt-' + ('x' * 55);
  }
}

void main() {
  testWidgets('C03 FIELD cannot sign before viewing exact stock and checking count',
      (tester) async {
    final client = _SignedFixtureClient();
    await tester.pumpWidget(MaterialApp(
      home: CustodyHandoffScreen(client: client),
    ));
    expect(find.text('Receive vehicle custody'), findsOneWidget);
    final inspect = find.byKey(const ValueKey('c03-inspect-stock'));
    expect(tester.widget<FilledButton>(inspect).onPressed, isNull);

    await tester.enterText(find.byType(TextField), 'signed-by-manager');
    await tester.pump();
    expect(tester.widget<FilledButton>(inspect).onPressed, isNotNull);
    await tester.tap(inspect);
    await tester.pumpAndSettle();
    expect(client.previews, 1);
    expect(find.textContaining('Lolo chips'), findsOneWidget);
    expect(find.textContaining('B-2026'), findsOneWidget);
    expect(find.textContaining('TEST-PLATE'), findsOneWidget);
    final submit = find.byKey(const ValueKey('c03-field-sign'));
    expect(tester.widget<FilledButton>(submit).onPressed, isNull);

    await tester.ensureVisible(find.byType(CheckboxListTile));
    await tester.tap(find.byType(CheckboxListTile));
    await tester.pumpAndSettle();
    expect(tester.widget<FilledButton>(submit).onPressed, isNotNull);
    await tester.ensureVisible(submit);
    await tester.tap(submit);
    await tester.pumpAndSettle();
    expect(client.confirms, 1);
    expect(find.textContaining('Receipt signed.'), findsOneWidget);
    expect(find.text('Copy signed receipt for the manager'), findsOneWidget);
  });

  testWidgets('invalid offer stays unconfirmed and never signs',
      (tester) async {
    final client = _SignedFixtureClient();
    await tester.pumpWidget(MaterialApp(home: CustodyHandoffScreen(client: client)));
    await tester.enterText(find.byType(TextField), 'tampered-offer');
    await tester.pump();
    await tester.tap(find.byKey(const ValueKey('c03-inspect-stock')));
    await tester.pumpAndSettle();
    expect(find.textContaining('Could not verify your handoff'), findsOneWidget);
    expect(client.confirms, 0);
    expect(find.text('Sign my receipt'), findsNothing);
  });
}
