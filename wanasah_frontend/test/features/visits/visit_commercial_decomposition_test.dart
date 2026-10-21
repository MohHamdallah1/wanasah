import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/visits/application/completed_visit_restorer.dart';
import 'package:wanasah_frontend/features/visits/application/visit_cart_policy.dart';
import 'package:wanasah_frontend/features/visits/data/visit_submission_mapper.dart';
import 'package:wanasah_frontend/models/cart_item_model.dart';
import 'package:wanasah_frontend/models/product_model.dart';

void main() {
  group('completed visit restoration', () {
    const product = ProductModel(
      id: 7,
      name: 'منتج',
      pricePerCarton: 10,
      pricePerPack: 1,
      packsPerCarton: 10,
      currentCartons: 5,
      currentPacks: 0,
    );

    test('restores sale/sample/return quantities with prior availability', () {
      final restored = restoreCompletedVisitCart(
        catalog: const <ProductModel>[product],
        cartItemsJson:
            '[{"product_variant_id":7,"quantity":2,"packs_quantity":1,'
            '"sample_quantity":1,"sample_packs_quantity":2,'
            '"sample_reason":"sample"}]',
        returnsJson:
            '[{"product_variant_id":7,"quantity":1,"packs_quantity":0,'
            '"return_type":"Factory_Defect"},'
            '{"product_variant_id":7,"quantity":0,"packs_quantity":2,'
            '"return_type":"Expired"}]',
      );

      expect(restored, hasLength(1));
      final item = restored.single;
      expect(item.cartons, 2);
      expect(item.packs, 1);
      expect(item.sampleCartons, 1);
      expect(item.samplePacks, 2);
      expect(item.sampleReason, 'sample');
      expect(item.returnFactoryCartons, 1);
      expect(item.returnFactoryPacks, 0);
      expect(item.returnExpiredCartons, 0);
      expect(item.returnExpiredPacks, 2);
      expect(item.availableCartons, 9);
      expect(item.availablePacks, 5);
    });
  });

  group('visit cart policy', () {
    CartItemModel item({
      int cartons = 0,
      int packs = 0,
      int sampleCartons = 0,
      int samplePacks = 0,
      int returnFactoryCartons = 0,
      int returnFactoryPacks = 0,
      int returnExpiredCartons = 0,
      int returnExpiredPacks = 0,
      int availableCartons = 3,
      int availablePacks = 0,
    }) {
      return CartItemModel(
        productVariantId: 7,
        name: 'منتج',
        pricePerCarton: 10,
        pricePerPack: 1,
        packsPerCarton: 10,
        availableCartons: availableCartons,
        availablePacks: availablePacks,
        cartons: cartons,
        packs: packs,
        sampleCartons: sampleCartons,
        samplePacks: samplePacks,
        returnFactoryCartons: returnFactoryCartons,
        returnFactoryPacks: returnFactoryPacks,
        returnExpiredCartons: returnExpiredCartons,
        returnExpiredPacks: returnExpiredPacks,
      );
    }

    test('blocks aggregate sale/sample/replacement quantity over vehicle stock', () {
      final result = applyVisitCartItem(
        currentCart: const <CartItemModel>[],
        item: item(
          cartons: 1,
          sampleCartons: 1,
          returnExpiredCartons: 2,
        ),
      );

      expect(result.isAccepted, isFalse);
      expect(result.errorMessage, contains('لا تكفي'));
      expect(result.cart, isEmpty);
    });

    test('zero quantity removes existing item', () {
      final existing = item(cartons: 1);
      final result = applyVisitCartItem(
        currentCart: <CartItemModel>[existing],
        item: item(),
      );

      expect(result.isAccepted, isTrue);
      expect(result.cart, isEmpty);
    });
  });

  group('visit submission mapping', () {
    test('separates sale/sample transport lines from replacement returns', () {
      final item = CartItemModel(
        productVariantId: 7,
        name: 'منتج',
        pricePerCarton: 10,
        pricePerPack: 1,
        packsPerCarton: 10,
        availableCartons: 10,
        availablePacks: 0,
        cartons: 1,
        packs: 2,
        sampleCartons: 0,
        samplePacks: 3,
        sampleReason: 'تجربة',
        returnFactoryCartons: 1,
        returnFactoryPacks: 4,
        returnExpiredCartons: 0,
        returnExpiredPacks: 2,
      );

      final lines = mapVisitSubmissionLines(<CartItemModel>[item]);

      expect(lines.cartItems, <Map<String, dynamic>>[
        <String, dynamic>{
          'product_variant_id': 7,
          'quantity': 1,
          'packs_quantity': 2,
          'sample_quantity': 0,
          'sample_packs_quantity': 3,
          'sample_reason': 'تجربة',
        },
      ]);
      expect(lines.returns, <Map<String, dynamic>>[
        <String, dynamic>{
          'product_variant_id': 7,
          'quantity': 1,
          'packs_quantity': 4,
          'return_type': 'Factory_Defect',
        },
        <String, dynamic>{
          'product_variant_id': 7,
          'quantity': 0,
          'packs_quantity': 2,
          'return_type': 'Expired',
        },
      ]);
    });
  });

  test('VisitBloc keeps orchestration and delegates commercial details', () async {
    final source = await File('lib/blocs/visit/visit_bloc.dart').readAsString();

    expect(source, contains('restoreCompletedVisitCart('));
    expect(source, contains('applyVisitCartItem('));
    expect(source, contains('VisitSubmissionService'));
    expect(source, isNot(contains('jsonDecode(')));
    expect(source, isNot(contains("ret['cartons']")));
    expect(source, isNot(contains("'sample_quantity':")));
  });
}
