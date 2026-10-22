import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_dotenv/flutter_dotenv.dart';
import 'package:wanasah_frontend/core/network/api_client.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/features/visits/application/visit_command_evidence.dart';
import 'package:wanasah_frontend/features/visits/application/visit_submission_service.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_route_action_gate.dart';
import 'package:wanasah_frontend/features/visits/presentation/visit_field_failure.dart';
import 'package:wanasah_frontend/screens/add_shop_screen.dart';

DioException rejection(int status, String code, String requestId) {
  final options = RequestOptions(path: '/visits/11', method: 'PUT');
  return DioException(requestOptions: options, type: DioExceptionType.badResponse,
    response: Response(requestOptions: options, statusCode: status, data: {
      'request_id': requestId,
      'error': {'code': code, 'context': {'source': 'Backend'},
        // Deliberately contradictory text must never turn rejection into success.
        'message': 'allowed success retry authorized انتهت الاستراحة',
      },
    }));
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  for (final evidence in [
    ('true', 'true'), ('false', 'false'), ('true', 'false'),
    ('invalid', 'invalid'), (null, null),
  ]) {
    test('stale/unknown flags $evidence do not add a Visit preflight or prevent offline staging', () async {
      FlutterSecureStorage.setMockInitialValues({
        if (evidence.$1 != null) 'is_on_break': evidence.$1!,
        if (evidence.$2 != null) 'is_authorized': evidence.$2!,
      });
      var mutations = 0;
      var rows = <Map<String, dynamic>>[];
      final submission = VisitSubmissionService.withPorts(
        readPending: () async => rows,
        save: ({required visitId, required payload}) async {
          mutations++;
          // Existing durable repository port owns UUID creation/staging and
          // reports a network-ambiguous save by retaining its original row.
          rows = [{'type': 'submit_sale', 'state': 'pending',
            'payload': jsonEncode({...payload, 'visitId': visitId,
              'request_id': '11111111-1111-4111-8111-111111111111'})}];
        },
      );
      expect(await const VisitRouteActionGate().evaluate(VisitRouteAction.openVisit),
        VisitRouteActionDecision.allowed);
      final disposition = await submission.submit(visitId: 11, outcome: 'NoSale',
        notes: 'Customer declined goods', cart: [], debtPaid: 0, cashCollected: 0);
      expect(disposition, VisitSubmissionDisposition.unresolved);
      expect(mutations, 1);
      final original = rows.single['payload'];
      await expectLater(submission.submit(visitId: 11, outcome: 'NoSale',
        notes: 'Correction must not replace unresolved work',
        cart: [], debtPaid: 0, cashCollected: 0),
        throwsA(isA<VisitPriorCommandUnresolved>()));
      expect(mutations, 1);
      expect(rows.single['payload'], original);
    });
  }

  for (final authority in [
    ('current unauthorized', 403, 'HTTP_403'),
    ('current active break', 403, 'HTTP_403'),
    ('pending handshake', 403, 'HTTP_403'),
    ('no current session or route', 403, 'HTTP_403'),
    ('sealed session', 409, 'HTTP_409'),
    ('vehicle custody', 409, 'VEHICLE_CUSTODY_LOCATION_INACTIVE'),
    ('authentication', 401, 'HTTP_401'),
  ]) {
    test('Backend ${authority.$1} remains a structured refusal despite allowed cached flags', () async {
      FlutterSecureStorage.setMockInitialValues({
        'is_authorized': 'true', 'is_on_break': 'false',
      });
      final failure = rejection(authority.$2, authority.$3, 'incident-${authority.$1}');
      var mutations = 0;
      var rows = <Map<String, dynamic>>[];
      final submission = VisitSubmissionService.withPorts(
        readPending: () async => rows,
        save: ({required visitId, required payload}) async {
          mutations++;
          rows = [{'type': 'submit_sale', 'state': authority.$2 == 401 ? 'pending' : 'blocked',
            'payload': jsonEncode({...payload, 'visitId': visitId,
              'request_id': '22222222-2222-4222-8222-222222222222'})}];
          throw failure;
        },
      );
      expect(await const VisitRouteActionGate().evaluate(VisitRouteAction.openVisit),
        VisitRouteActionDecision.allowed);
      await expectLater(submission.submit(visitId: 11, outcome: 'NoSale',
        notes: 'Customer declined goods', cart: [], debtPaid: 0, cashCollected: 0),
        throwsA(same(failure)));
      final parsed = failure.apiFailure;
      expect(parsed.status, authority.$2);
      expect(parsed.code, authority.$3);
      expect(parsed.context, {'source': 'Backend'});
      expect(parsed.requestId, 'incident-${authority.$1}');
      expect(visitFailureCategory(parsed), authority.$2 == 409
        ? VisitFailureCategory.business : VisitFailureCategory.authorization);
      expect(mutations, 1);
      final original = rows.single['payload'];
      await expectLater(submission.submit(visitId: 11, outcome: 'NoSale',
        notes: 'New command forbidden', cart: [], debtPaid: 0, cashCollected: 0),
        throwsA(isA<VisitPriorCommandUnresolved>()));
      expect(rows.single['payload'], original);
      expect(mutations, 1);
    });
  }

  testWidgets('Add Shop form remains editable with stale break and unauthorized cache', (tester) async {
    FlutterSecureStorage.setMockInitialValues({
      'is_on_break': 'true', 'is_authorized': 'false',
    });
    var reads = 0;
    const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
    TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, (_) async { reads++; throw StateError('stale storage'); });
    addTearDown(() => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
      .setMockMethodCallHandler(channel, null));
    dotenv.testLoad(fileInput: 'API_BASE_URL=http://127.0.0.1:8000');
    ApiClient.init(onUnauthorized: () {});
    await tester.pumpWidget(const MaterialApp(home: AddShopScreen()));
    await tester.pumpAndSettle();
    final form = find.byType(TextFormField).first;
    await tester.enterText(form, 'Shop draft');
    expect(find.text('Shop draft'), findsOneWidget);
    expect(reads, 0);
    expect(tester.takeException(), isNull);
  });

  test('Visit navigation and editing contain no cached authorization or live preflight', () {
    final screen = File('lib/screens/visit_screen.dart').readAsStringSync();
    final list = File('lib/screens/visit_list_screen.dart').readAsStringSync();
    final gate = File('lib/features/visits/list/application/visit_route_action_gate.dart').readAsStringSync();
    final shop = File('lib/screens/add_shop_screen.dart').readAsStringSync();
    for (final source in [screen, list, gate, shop]) {
      expect(source, isNot(contains('FlutterSecureStorage')));
      expect(source, isNot(contains('is_authorized')));
      expect(source, isNot(contains('is_on_break')));
    }
    expect(screen, contains('final bool isLocked = _isSubmitting;'));
    expect(screen, contains('if (_isSubmitting) return;'));
    expect(screen, isNot(contains('_shopZone != _allowedZone')));
    expect(screen, contains('hasUnresolvedVisit('));
    expect(screen, contains('confirmVisitFieldSubmission('));
    expect(gate, isNot(contains('import ')));
    expect(gate, isNot(contains('readCompatibilityState(')));
    expect(shop, contains('_shopCreationService.execute(command)'));
  });
}
