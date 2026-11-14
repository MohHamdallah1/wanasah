import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/recovery/field_custody_handoff_client.dart';
import 'package:wanasah_frontend/features/custody/recovery/field_custody_handoff_inbox.dart';

const handoff = 37;
const snapshot =
    'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa';

class _ServerFixture extends FieldCustodyHandoffClient {
  _ServerFixture() : super(dio: Dio());
  String state = 'PENDING';
  bool hasRequest = true;
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
    return hasRequest && (state == 'PENDING' || state == 'CONFIRMED')
        ? [record()]
        : [];
  }

  @override
  Future<FieldCustodyRequest> detail(
    int id, {
    String? previouslyVerifiedPlate,
  }) async {
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
  test(
    'actual Backend #1015 pending/detail: numeric handoff, verified vehicle plate, UUID separate',
    () {
      final pending = <String, dynamic>{
        'handoff_id': 37,
        'vehicle_id': 13,
        'vehicle_plate': '12-25132',
        'state': 'PENDING',
        'expires_at': '2026-11-14T13:00:00Z',
        'target_driver_id': 7,
        'recipient_label': 'Khaled (khaled)',
        'context_revision': 1,
        'stock_snapshot': snapshot,
      };
      final decoded = FieldCustodyRequest.fromMap(pending);
      expect(decoded.handoffId, 37);
      expect(decoded.vehiclePlate, '12-25132');
      expect(
        () => FieldCustodyRequest.fromMap({...pending, 'handoff_id': 0}),
        throwsFormatException,
      );
      expect(
        () => FieldCustodyRequest.fromMap({
          ...pending,
          'handoff_id': '11111111-1111-4111-8111-111111111111',
        }),
        throwsFormatException,
      );
      expect(
        () => FieldCustodyRequest.fromMap({...pending, 'vehicle_plate': null}),
        throwsFormatException,
      );
      // The terminal detail endpoint currently returns null plate; only
      // reuse the plate already received from the authenticated FIELD inbox.
      final terminal = FieldCustodyRequest.fromMap(
        {
          ...pending,
          'vehicle_plate': null,
          'state': 'DECLINED',
          'stock_lines': <Map<String, dynamic>>[],
        },
        requireStock: true,
        previouslyVerifiedPlate: decoded.vehiclePlate,
      );
      expect(terminal.state, 'DECLINED');
      expect(terminal.vehiclePlate, '12-25132');
      expect(
        RegExp(r'^[0-9a-f-]{36}$').hasMatch(_ServerFixture().newRequestId()),
        isTrue,
      );
    },
  );

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

  testWidgets(
    'no permanent inbox; new signed request appears and committed request disappears',
    (tester) async {
      final server = _ServerFixture()..hasRequest = false;
      Widget app(int nonce) => MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: FieldCustodyHandoffInbox(
              key: const ValueKey('stable-inbox'),
              client: server,
              refreshNonce: nonce,
            ),
          ),
        ),
      );
      await tester.pumpWidget(app(0));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('field-custody-inbox')), findsNothing);
      server.hasRequest = true;
      await tester.pumpWidget(app(1));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('field-custody-inbox')), findsOneWidget);
      expect(find.text('12-25132'), findsOneWidget);
      server.state = 'COMMITTED';
      await tester.pumpWidget(app(2));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('field-custody-inbox')), findsNothing);
      expect(server.inboxReads, 3);
      expect(tester.takeException(), isNull);
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
    expect(server.actualReason, 'DIFFERENCE');
    expect(server.counted, isFalse);
  });
}
