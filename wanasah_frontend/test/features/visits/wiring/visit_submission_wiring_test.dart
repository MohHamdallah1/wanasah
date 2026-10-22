import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/visits/application/visit_command_evidence.dart';
import 'package:wanasah_frontend/features/visits/application/visit_money_input.dart';
import 'package:wanasah_frontend/features/visits/application/visit_return_submission.dart';
import 'package:wanasah_frontend/features/visits/application/visit_sale_confirmation.dart';
import 'package:wanasah_frontend/features/visits/application/visit_submission_service.dart';
import 'package:wanasah_frontend/features/visits/application/completed_visit_restorer.dart';
import 'package:wanasah_frontend/features/visits/application/visit_cart_policy.dart';
import 'package:wanasah_frontend/features/visits/application/commercial/commercial_readiness_outcome.dart';
import 'package:wanasah_frontend/features/visits/domain/commercial/commercial_readiness.dart';
import 'package:wanasah_frontend/features/visits/domain/invoice/field_invoice.dart';
import 'package:wanasah_frontend/features/visits/domain/returns/return_resolution.dart';
import 'package:wanasah_frontend/models/cart_item_model.dart';
import 'package:wanasah_frontend/models/product_model.dart';
import '../domain/invoice/invoice_fixtures.dart';
import '../domain/returns/return_fixtures.dart';

CartItemModel draft({int damaged = 1, int sale = 0}) => CartItemModel(
  productVariantId: 44, name: 'Product', pricePerCarton: 999999,
  pricePerPack: 999, packsPerCarton: 10,
  availableCartons: 20, availablePacks: 0, cartons: sale,
  returnDamagedCartons: damaged, returnDamagedPacks: damaged == 0 ? 0 : 2,
);

ResolvedVisitReturns resolved(List<CartItemModel> cart) => ResolvedVisitReturns(
  visitId: 11, resolutions: [
    for (final request in visitReturnRequests(cart))
      FieldReturnResolution.fromJson({
        ...resolvedJson(), 'resolution_token': '  opaque.signed/+= token  ',
      }, request: request),
  ],
);

VisitSaleConfirmation saleEvidence(List<CartItemModel> cart) => VisitSaleConfirmation(
  visitId: 11,
  readiness: CommercialReady(CommercialReadiness.fromJson({
    'status': 'READY', 'sale_ready': true, 'code': null, 'required_action': null,
  })),
  preview: InvoicePreview.fromJson({
    'commit_required': true, 'invoice': invoiceJson(status: 'PREVIEW', revision: false),
  }),
  request: visitInvoiceRequest(cart),
);

void main() {
  test('all canonical return reasons preserve carton/base-pack quantities', () {
    final cart = [draft().copyWith(returnFactoryCartons: 3, returnFactoryPacks: 4,
      returnExpiredCartons: 5, returnExpiredPacks: 6)];
    final requests = visitReturnRequests(cart);
    expect(requests.map((r) => r.returnType.code), ['Factory_Defect', 'Expired', 'Damaged']);
    expect(requests.map((r) => [r.quantity, r.packsQuantity]), [[3,4], [5,6], [1,2]]);
    final body = resolved(cart).forSubmission(11, cart);
    expect(body.every((line) => line['resolution_token'] == '  opaque.signed/+= token  '), isTrue);
    expect(body.every((line) => !line.containsKey('batch_id')), isTrue);
    expect(body.last, {
      'product_variant_id': 44, 'quantity': 1, 'packs_quantity': 2,
      'return_type': 'Damaged', 'resolution_token': '  opaque.signed/+= token  ',
    });
  });

  test('missing/stale/duplicate/wrong-visit return evidence fails closed', () {
    final cart = [draft()];
    expect(() => ResolvedVisitReturns(visitId: 11, resolutions: []).forSubmission(11, cart),
      throwsFormatException);
    expect(() => resolved(cart).forSubmission(12, cart), throwsFormatException);
    expect(() => resolved(cart).forSubmission(11, [draft(damaged: 2)]), throwsFormatException);
    expect(() => ResolvedVisitReturns(visitId: 11, resolutions: [
      ...resolved(cart).resolutions, ...resolved(cart).resolutions,
    ]).forSubmission(11, cart), throwsFormatException);
  });

  test('Damaged restoration and cached replacement-out guard include both UOMs', () {
    final cart = restoreCompletedVisitCart(catalog: [
      const ProductModel(id: 44, name: 'Product', pricePerCarton: 1, pricePerPack: 1,
        packsPerCarton: 10, currentCartons: 2, currentPacks: 0),
    ], returnsJson: jsonEncode([
      {'product_variant_id': 44, 'return_type': 'Damaged', 'quantity': 1, 'packs_quantity': 2},
    ]));
    expect(cart.single.returnDamagedCartons, 1);
    expect(cart.single.returnDamagedPacks, 2);
    expect(cart.single.availableCartons, 3);
    expect(cart.single.availablePacks, 2);
    expect(cart.single.totalDeductedPacks, 12);
    expect(applyVisitCartItem(currentCart: [], item: cart.single).cart, hasLength(1));
    expect(applyVisitCartItem(currentCart: [], item: cart.single.copyWith(
      availableCartons: 0, availablePacks: 0)).isAccepted, isFalse);
  });

  test('operator money syntax remains exact, including above binary precision', () {
    expect(canonicalVisitMoney('9007199254740993.123000'), '9007199254740993.123000');
    expect(canonicalVisitMoney('١٢٫٣٤٠'), '12.340');
    expect(canonicalVisitMoney(''), '0.000');
    for (final invalid in ['NaN', 'Infinity', '-1', '1.2.3', '1e4']) {
      expect(() => canonicalVisitMoney(invalid), throwsFormatException);
    }
  });

  test('canonical submission sends opaque evidence and exact cash with no new UUID/body fields', () async {
    Map<String, dynamic>? body;
    final cart = [draft(sale: 2)];
    final service = VisitSubmissionService.withPorts(
      readPending: () async => [],
      save: ({required visitId, required payload}) async {
        expect(visitId, 11);
        body = payload;
      },
    );
    expect(await service.submit(visitId: 11, outcome: 'Sale',
      debtPaid: 0, cashCollected: 0, cart: cart,
      exactCashCollected: '9007199254740993.123000', exactDebtPaid: '0.000001',
      resolvedReturns: resolved(cart), saleConfirmation: saleEvidence(cart)),
      VisitSubmissionDisposition.confirmed);
    expect(body!.keys.toSet(), {'outcome', 'notes', 'cash_collected', 'debt_paid', 'cart_items', 'returns'});
    expect(body!['cash_collected'], '9007199254740993.123000');
    expect(body!['debt_paid'], '0.000001');
    expect((body!['returns'] as List).single['resolution_token'], '  opaque.signed/+= token  ');
    expect((body!['cart_items'] as List).single.keys,
      isNot(contains('price')));
  });

  test('queued command remains unresolved and blocks replacement/correction without calling save again', () async {
    var rows = <Map<String, dynamic>>[];
    var sends = 0;
    final service = VisitSubmissionService.withPorts(
      readPending: () async => rows,
      save: ({required visitId, required payload}) async {
        sends++;
        rows = [{'type': 'submit_sale', 'state': 'in_flight',
          'payload': jsonEncode({...payload, 'visitId': visitId, 'request_id': 'original-uuid'})}];
      },
    );
    final cart = [draft()];
    expect(await service.submit(visitId: 11, outcome: 'NoSale',
      debtPaid: 0, cashCollected: 0, cart: cart, resolvedReturns: resolved(cart)),
      VisitSubmissionDisposition.unresolved);
    final original = rows.single['payload'];
    await expectLater(service.submit(visitId: 11, outcome: 'NoSale',
      debtPaid: 0, cashCollected: 0, cart: cart, resolvedReturns: resolved(cart)),
      throwsA(isA<VisitPriorCommandUnresolved>()));
    expect(sends, 1);
    expect(rows.single['payload'], original);
    // After canonical recovery removes the row, a deliberate new correction is permitted.
    rows = [];
    await service.submit(visitId: 11, outcome: 'NoSale',
      debtPaid: 0, cashCollected: 0, cart: cart, resolvedReturns: resolved(cart));
    expect(sends, 2);
  });

  test('Sale requires readiness/preview bound to the exact sold draft', () async {
    var saves = 0;
    final cart = [draft(damaged: 0, sale: 1)];
    final service = VisitSubmissionService.withPorts(readPending: () async => [],
      save: ({required visitId, required payload}) async { saves++; });
    await expectLater(service.submit(visitId: 11, outcome: 'Sale',
      debtPaid: 0, cashCollected: 0, cart: cart), throwsFormatException);
    await expectLater(service.submit(visitId: 11, outcome: 'Sale',
      debtPaid: 0, cashCollected: 0, cart: [draft(damaged: 0, sale: 2)],
      saleConfirmation: saleEvidence(cart)), throwsFormatException);
    expect(saves, 0);
  });

  test('NoSale and Postponed do not require commercial readiness or invoice preview', () async {
    final bodies = <Map<String, dynamic>>[];
    final service = VisitSubmissionService.withPorts(readPending: () async => [],
      save: ({required visitId, required payload}) async { bodies.add(payload); });
    await service.submit(visitId: 11, outcome: 'NoSale', notes: 'Collection',
      debtPaid: 1, cashCollected: 9, cart: []);
    await service.submit(visitId: 11, outcome: 'Postponed', notes: 'Closed',
      debtPaid: 1, cashCollected: 9, cart: []);
    expect(bodies.first['cash_collected'], '0.000');
    expect(bodies.last, {'outcome': 'Postponed', 'notes': 'Closed'});
  });

  test('unknown/corrupt and legacy quarantined command evidence fails closed', () {
    expect(visitHasUnresolvedCommand(11, [{'type': 'quarantined_submit_sale',
      'payload': '{"visitId":11}', 'state': 'blocked'}]), isTrue);
    expect(visitHasUnresolvedCommand(11, [{'type': 'submit_sale', 'payload': '{'}]), isTrue);
    expect(visitHasUnresolvedCommand(11, [{'type': 'corrupt', 'payload': 'bad'}]), isTrue);
    expect(visitHasUnresolvedCommand(11, [{'type': 'submit_sale', 'payload': '{"visitId":12}'}]), isFalse);
  });
}
