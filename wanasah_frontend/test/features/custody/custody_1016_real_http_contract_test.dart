// #1016 opt-in: actual merged PG16 HTTP snapshot, never a handwritten
// fake FIELD response. Set WANASAH_CUSTODY_1016_CAPTURE to the sanitized
// file emitted by test_custody_1016_merged_cross_client_pg16.py.
import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/recovery/field_custody_handoff_client.dart';

void main() {
  final capture = Platform.environment['WANASAH_CUSTODY_1016_CAPTURE'] ??
      '../wa_backend/tests/fixtures/custody_1016_real_pg16_http.json';

  test('merged FIELD parser accepts the real own-inbox and counted stock detail', () {
    final actual = jsonDecode(File(capture).readAsStringSync()) as Map<String, dynamic>;
    final inbox = actual['field_inbox'] as Map<String, dynamic>;
    final entries = inbox['items'] as List<dynamic>;
    expect(entries, hasLength(1));
    final request = FieldCustodyRequest.fromMap(entries.single);
    final stock = actual['manager_stock'] as Map<String, dynamic>;
    final serverDetail = actual['field_detail'] as Map<String, dynamic>;
    final detailed = FieldCustodyRequest.fromMap(
      serverDetail,
      requireStock: true,
      previouslyVerifiedPlate: request.vehiclePlate,
    );
    expect(request.handoffId, isA<int>());
    expect(request.handoffId, greaterThan(0));
    expect(detailed.handoffId, request.handoffId);
    expect(detailed.vehicleId, request.vehicleId);
    expect(request.vehiclePlate, stock['vehicle_plate']);
    expect(detailed.vehiclePlate, request.vehiclePlate);
    expect(detailed.stockSnapshot, stock['stock_snapshot']);
    expect(detailed.stockLines, isNotEmpty);
    expect(detailed.stockLines.first['product_name'], isNotEmpty);
    expect(detailed.stockLines.first, contains('base_uom'));
    expect(detailed.stockLines.first, contains('batch_number'));
    expect(detailed.stockLines.first, contains('stock_status'));
    final confirmation = actual['field_confirmed'] as Map<String, dynamic>;
    expect(confirmation['handoff_id'], request.handoffId);
    expect(confirmation['state'], 'CONFIRMED');
  });

  test('merged FIELD parser accepts real DECLINED terminal without falsely selecting goods', () {
    final actual = jsonDecode(File(capture).readAsStringSync()) as Map<String, dynamic>;
    final inbox = actual['field_inbox'] as Map<String, dynamic>;
    final verifiedPlate = FieldCustodyRequest.fromMap(
      (inbox['items'] as List<dynamic>).single,
    ).vehiclePlate;
    final terminal = actual['field_terminal'] as Map<String, dynamic>;
    final declined = FieldCustodyRequest.fromMap(
      terminal,
      requireStock: true,
      previouslyVerifiedPlate: verifiedPlate,
    );
    expect(declined.state, 'DECLINED');
    expect(declined.stockLines, isEmpty);
    expect(declined.vehiclePlate, verifiedPlate);
    expect(declined.reasonText, 'Physical count differs');
    expect((actual['field_declined'] as Map<String, dynamic>)['reason_code'], 'DIFFERENCE');
    final wrongId = <String,dynamic>{...terminal, 'handoff_id': 'not-a-server-id'};
    expect(() => FieldCustodyRequest.fromMap(
      wrongId, previouslyVerifiedPlate: verifiedPlate,
    ), throwsFormatException);
  });
}
