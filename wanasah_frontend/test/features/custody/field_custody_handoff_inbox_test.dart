import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/recovery/field_custody_handoff_client.dart';
import 'package:wanasah_frontend/features/custody/recovery/field_custody_handoff_inbox.dart';

const handoff = '11111111-1111-4111-8111-111111111111';
const snapshot =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

class _ServerFixture extends FieldCustodyHandoffClient {
  _ServerFixture() : super(dio: Dio());
  String state = 'PENDING';
  int inboxReads = 0, details = 0, decisions = 0;
  String? actualDecision, actualReason;
  bool? counted;
  FieldCustodyRequest record({bool detail = false}) => FieldCustodyRequest(
    handoffId: handoff,
    vehicleId: 13,
    vehiclePlate: '12-25132',
    state: state,
    expiresAt: '2026-11-14T13:00:00Z',
    stockSnapshot: detail ? snapshot : null,
    stockLines:
        detail
            ? [
              {
                'product_name': 'Rice',
                'sku': 'R',
                'batch_number': '',
                'expiry_date': null,
                'base_uom': 'EACH',
                'base_uom_name': 'حبة',
                'on_hand_base': '5',
                'reserved_base': '0',
                'stock_status': 'AVAILABLE',
              },
              {
                'product_name': 'Rice',
                'sku': 'R',
                'batch_number': '',
                'expiry_date': null,
                'base_uom': 'EACH',
                'base_uom_name': 'حبة',
                'on_hand_base': '20',
                'reserved_base': '0',
                'stock_status': 'AVAILABLE',
              },
            ]
            : const [],
  );
  @override
  Future<List<FieldCustodyRequest>> pending() async {
    inboxReads++;
    return [record()];
  }

  @override
  Future<FieldCustodyRequest> detail(String id) async {
    details++;
    expect(id, handoff);
    return record(detail: true);
  }

  @override
  String newRequestId() => '22222222-2222-4222-8222-222222222222';
  @override
  Future<FieldCustodyRequest> decide({
    required FieldCustodyRequest request,
    required String requestId,
    required String decision,
    bool physicalCountConfirmed = false,
    String? reasonCode,
    String? reasonText,
  }) async {
    decisions++;
    actualDecision = decision;
    actualReason = reasonCode;
    counted = physicalCountConfirmed;
    state = decision == 'CONFIRM' ? 'CONFIRMED' : 'DECLINED';
    return record(detail: true);
  }
}

void main() {
  testWidgets(
    'FIELD own-principal inbox physically confirms one request without clipboard',
    (tester) async {
      final server = _ServerFixture();
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: FieldCustodyHandoffInbox(client: server),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Pending vehicle custody receipts'), findsOneWidget);
      expect(find.text('12-25132'), findsOneWidget);
      await tester.tap(
        find.byKey(const ValueKey('field-custody-inbox-$handoff')),
      );
      await tester.pumpAndSettle();
      expect(find.textContaining('25 حبة'), findsOneWidget);
      final confirm = find.byKey(const ValueKey('field-handoff-confirm'));
      expect(tester.widget<FilledButton>(confirm).onPressed, isNull);
      await tester.ensureVisible(
        find.byKey(const ValueKey('field-handoff-count-checkbox')),
      );
      await tester.tap(
        find.byKey(const ValueKey('field-handoff-count-checkbox')),
      );
      await tester.pumpAndSettle();
      expect(tester.widget<FilledButton>(confirm).onPressed, isNotNull);
      await tester.ensureVisible(confirm);
      await tester.tap(confirm);
      await tester.pumpAndSettle();
      expect(server.decisions, 1);
      expect(server.actualDecision, 'CONFIRM');
      expect(server.counted, isTrue);
      expect(
        find.textContaining('Waiting for manager approval.'),
        findsOneWidget,
      );
      expect(find.textContaining('Copy signed receipt'), findsNothing);
    },
  );

  testWidgets('FIELD refuses with mandatory reason; no physical-count flag', (
    tester,
  ) async {
    final server = _ServerFixture();
    await tester.pumpWidget(
      MaterialApp(
        home: FieldCustodyHandoffRequestScreen(
          handoffId: handoff,
          client: server,
        ),
      ),
    );
    await tester.pumpAndSettle();
    final decline = find.byKey(const ValueKey('field-handoff-decline'));
    await tester.scrollUntilVisible(
      decline,
      200,
      scrollable: find.byType(Scrollable).first,
    );
    expect(tester.widget<OutlinedButton>(decline).onPressed, isNull);
    await tester.ensureVisible(
      find.byKey(const ValueKey('field-handoff-reason')),
    );
    await tester.tap(find.byKey(const ValueKey('field-handoff-reason')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Stock quantity differs').last);
    await tester.pumpAndSettle();
    expect(tester.widget<OutlinedButton>(decline).onPressed, isNotNull);
    await tester.ensureVisible(decline);
    await tester.tap(decline);
    await tester.pumpAndSettle();
    expect(server.decisions, 1);
    expect(server.actualDecision, 'DECLINE');
    expect(server.actualReason, 'DISCREPANCY');
    expect(server.counted, isFalse);
  });
}
