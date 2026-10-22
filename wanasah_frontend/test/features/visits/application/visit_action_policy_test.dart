import 'dart:convert';
import 'dart:io';
import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/visits/application/visit_action_policy.dart';
import 'package:wanasah_frontend/features/visits/application/visit_command_evidence.dart';
import 'package:wanasah_frontend/features/visits/application/visit_submission_service.dart';
import 'package:wanasah_frontend/features/visits/data/visit_submission_mapper.dart';
import 'package:wanasah_frontend/models/cart_item_model.dart';
import '../wiring/visit_submission_wiring_test.dart' show draft, resolved, saleEvidence;

Matcher issue(VisitActionIssue value) =>
    isA<VisitActionViolation>().having((error) => error.issue, 'issue', value);

void validate(String outcome, List<CartItemModel> cart, {
  String cash = '0.000', String debt = '0.000', String? notes,
}) => validateVisitActions(outcome: outcome, cart: cart, cash: cash,
    debt: debt, notes: notes);

void main() {
  test('Sale needs sold carton or pack, never samples, returns or cached price', () {
    for (final cart in <List<CartItemModel>>[
      [], [draft(damaged: 0)], [draft()], [draft(damaged: 0).copyWith(
        sampleCartons: 1, sampleReason: 'Promotion')],
    ]) {
      expect(() => validate('Sale', cart), throwsA(issue(VisitActionIssue.saleQuantityRequired)));
    }
    validate('Sale', [draft(damaged: 0, sale: 1)]);
    validate('Sale', [draft(damaged: 0).copyWith(packs: 1)]);
  });

  test('NoSale allows empty explained visit and prior-debt collection', () {
    validate('NoSale', [], notes: 'Customer does not need goods');
    validate('NoSale', [], notes: 'Prior-debt collection', debt: '999999999.999');
    expect(() => validate('NoSale', [], debt: '1'),
      throwsA(issue(VisitActionIssue.noSaleReason)));
  });

  test('NoSale permits samples, each return reason and their combination with prior debt', () {
    final sample = draft(damaged: 0).copyWith(
      sampleCartons: 2, samplePacks: 3, sampleReason: 'Promotion');
    for (final item in [
      sample, draft(),
      draft(damaged: 0).copyWith(returnExpiredPacks: 2),
      draft(damaged: 0).copyWith(returnFactoryCartons: 1),
      sample.copyWith(returnDamagedCartons: 1, returnExpiredPacks: 2,
        returnFactoryCartons: 3),
    ]) {
      validate('NoSale', [item], debt: '12.340');
    }
  });

  test('NoSale rejects real sales and even very small exact sale cash without stripping', () {
    expect(() => validate('NoSale', [draft(sale: 1)]),
      throwsA(issue(VisitActionIssue.noSaleSoldQuantity)));
    for (final cash in ['1', '0.001', '0.000000000000000001']) {
      expect(() => validate('NoSale', [draft()], cash: cash),
        throwsA(issue(VisitActionIssue.noSaleCash)));
    }
    validate('NoSale', [draft()], cash: '000.000000');
  });

  test('Postponed rejects every inventory/financial action and allows no-action notes', () {
    validate('Postponed', []);
    validate('Postponed', [], notes: 'Return tomorrow');
    for (final item in [
      draft(sale: 1, damaged: 0), draft(),
      draft(damaged: 0).copyWith(samplePacks: 1, sampleReason: 'Sample'),
      draft(damaged: 0).copyWith(returnExpiredPacks: 1),
      draft(damaged: 0).copyWith(returnFactoryPacks: 1),
    ]) {
      expect(() => validate('Postponed', [item]),
        throwsA(issue(VisitActionIssue.postponedActions)));
    }
    expect(() => validate('Postponed', [], cash: '0.001'),
      throwsA(issue(VisitActionIssue.postponedActions)));
    expect(() => validate('Postponed', [], debt: '0.001'),
      throwsA(issue(VisitActionIssue.postponedActions)));
  });

  test('sample reason required only for positive samples; canonical carton/pack quantities survive', () {
    final sample = draft(damaged: 0).copyWith(sampleCartons: 2, samplePacks: 3);
    expect(() => validate('NoSale', [sample]),
      throwsA(issue(VisitActionIssue.sampleReason)));
    expect(() => validate('NoSale', [sample.copyWith(sampleReason: '   ')]),
      throwsA(issue(VisitActionIssue.sampleReason)));
    expect(() => validate('NoSale', [sample.copyWith(sampleReason: 'x' * 256)]),
      throwsA(issue(VisitActionIssue.sampleReason)));
    final valid = sample.copyWith(sampleReason: 'Human reason');
    validate('NoSale', [valid]);
    final line = mapVisitSubmissionLines([valid]).cartItems.single;
    expect(line['sample_quantity'], 2);
    expect(line['sample_packs_quantity'], 3);
    expect(line['sample_reason'], 'Human reason');
    validate('Sale', [draft(damaged: 0, sale: 1)]);
  });

  test('malformed quantities, duplicate products, unsupported status and oversized reason fail closed', () {
    for (final cart in [
      [draft().copyWith(packs: -1)],
      [draft().copyWith(samplePacks: -1)],
      [draft().copyWith(returnDamagedPacks: -1)],
      [draft().copyWith(returnFactoryCartons: 2147483648)],
      [draft(), draft()],
    ]) {
      expect(() => validate('NoSale', cart),
        throwsA(issue(VisitActionIssue.invalidQuantity)));
    }
    for (final outcome in ['Completed', 'Pending', 'postponed', 'sale']) {
      expect(() => validate(outcome, []),
        throwsA(issue(VisitActionIssue.invalidOutcome)));
    }
    expect(() => validate('NoSale', [], notes: 'x' * 201),
      throwsA(issue(VisitActionIssue.invalidNotes)));
    validate('NoSale', [], notes: 'x' * 200);
    validate('Sale', [draft(sale: 1)], notes: 'x' * 4000);
  });

  test('invalid actions fail before staging; no implicit outcome or money rewrite', () async {
    var saves = 0;
    final service = VisitSubmissionService.withPorts(readPending: () async => [],
      save: ({required visitId, required payload}) async { saves++; });
    for (final outcome in ['Sale', 'NoSale', 'Postponed']) {
      await expectLater(service.submit(visitId: 11, outcome: outcome,
        cart: [], debtPaid: 1, cashCollected: 1), throwsFormatException);
    }
    await expectLater(service.submit(visitId: 11, outcome: 'NoSale',
      cart: [draft(damaged: 0).copyWith(samplePacks: 1)],
      debtPaid: 0, cashCollected: 0), throwsA(issue(VisitActionIssue.sampleReason)));
    expect(saves, 0);
  });

  test('valid NoSale combination transports exact collection, sample and all return reasons', () async {
    Map<String, dynamic>? body;
    final cart = [draft().copyWith(sampleCartons: 2, samplePacks: 3,
      sampleReason: 'Promotion', returnExpiredPacks: 2, returnFactoryCartons: 1)];
    final service = VisitSubmissionService.withPorts(readPending: () async => [],
      save: ({required visitId, required payload}) async { body = payload; });
    await service.submit(visitId: 11, outcome: 'NoSale', cart: cart,
      debtPaid: 0, cashCollected: 0, exactDebtPaid: '12.340000',
      resolvedReturns: resolved(cart));
    expect(body!['outcome'], 'NoSale');
    expect(body!['debt_paid'], '12.340000');
    expect(body!['cash_collected'], '0.000');
    expect((body!['cart_items'] as List).single['sample_quantity'], 2);
    expect((body!['returns'] as List).map((line) => line['return_type']),
      ['Factory_Defect', 'Expired', 'Damaged']);
    expect(jsonEncode(body), isNot(contains('batch_id')));
    expect(jsonEncode(body), isNot(contains('bonus_quantity')));
  });

  test('cached prices never change staged body or approval, even when zero or nonfinite', () async {
    final bodies = <Map<String, dynamic>>[];
    final service = VisitSubmissionService.withPorts(readPending: () async => [],
      save: ({required visitId, required payload}) async { bodies.add(payload); });
    for (final price in [0.0, 999999.0, double.nan, double.infinity]) {
      final cart = [CartItemModel(productVariantId: 44, name: 'Product',
        pricePerCarton: price, pricePerPack: price, packsPerCarton: 10,
        availableCartons: 20, availablePacks: 0, cartons: 1)];
      final evidence = saleEvidence(cart);
      await service.submit(visitId: 11, outcome: 'Sale', cart: cart,
        debtPaid: 0, cashCollected: 0, exactCashCollected: '0.000',
        saleConfirmation: evidence);
      expect(evidence.preview.commitRequired, isTrue);
      expect(evidence.preview.invoice.totals.finalAmount, '9007199254740992.123000');
    }
    for (final body in bodies) {
      expect(body, bodies.first);
      expect((body['cart_items'] as List).single.keys.toSet(), {
        'product_variant_id', 'quantity', 'packs_quantity', 'sample_quantity',
        'sample_packs_quantity', 'sample_reason',
      });
    }
  });

  test('valid Postponed stages no financial or inventory fields', () async {
    Map<String, dynamic>? body;
    final service = VisitSubmissionService.withPorts(readPending: () async => [],
      save: ({required visitId, required payload}) async { body = payload; });
    await service.submit(visitId: 11, outcome: 'Postponed', cart: [],
      debtPaid: 0, cashCollected: 0, notes: 'Tomorrow');
    expect(body, {'outcome': 'Postponed', 'notes': 'Tomorrow'});
  });

  test('server rejection propagates once and blocked evidence forbids a correction', () async {
    var rows = <Map<String, dynamic>>[];
    var saves = 0;
    final rejected = DioException(requestOptions: RequestOptions(path: '/visits/11'),
      response: Response(requestOptions: RequestOptions(path: '/visits/11'),
        statusCode: 409, data: {'error': {'code': 'CREDIT_LIMIT_EXCEEDED',
          'context': {'limit': '0'}, 'request_id': 'incident-1'}}));
    final service = VisitSubmissionService.withPorts(readPending: () async => rows,
      save: ({required visitId, required payload}) async {
        saves++;
        rows = [{'type': 'submit_sale', 'state': 'blocked',
          'payload': jsonEncode({...payload, 'visitId': visitId,
            'request_id': 'original-command'})}];
        throw rejected;
      });
    final cart = [draft()];
    await expectLater(service.submit(visitId: 11, outcome: 'NoSale', cart: cart,
      debtPaid: 0, cashCollected: 0, resolvedReturns: resolved(cart)),
      throwsA(same(rejected)));
    final original = rows.single['payload'];
    await expectLater(service.submit(visitId: 11, outcome: 'NoSale', cart: cart,
      debtPaid: 0, cashCollected: 0, resolvedReturns: resolved(cart)),
      throwsA(isA<VisitPriorCommandUnresolved>()));
    expect(rows.single['payload'], original);
    expect(saves, 1);
  });

  test('status finalization preserves the Backend mapping without legacy status rewrite', () {
    final source = File('lib/repositories/sync_repository.dart').readAsStringSync();
    expect(source, contains("outcome == 'Postponed' ? 'Pending' : 'Completed'"));
    final bloc = File('lib/blocs/visit/visit_bloc.dart').readAsStringSync();
    expect(bloc, contains('emit(currentState)'));
    expect(bloc, contains('VisitFieldSubmissionFailure('));
    final policy = File('lib/features/visits/application/visit_action_policy.dart').readAsStringSync();
    expect(RegExp(r'import .*flutter|import .*bloc|import .*core/|import .*repositories/').hasMatch(policy),
      isFalse);
    expect(RegExp(r'pricePer|totalSalePrice|expectedNewBalance|batch_id|Uuid|is_admin').hasMatch(policy),
      isFalse);
  });
}
