import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/visit/local_inventory_projection.dart';
import 'package:wanasah_frontend/core/visit/visit_command_serializer.dart';

void main() {
  group('canonical visit serializer', () {
    test('Sale emits only strict VisitUpdateRequest fields', () {
      final payload = buildCanonicalVisitPayload(
        outcome: 'Sale',
        notes: 'sale note',
        cashCollected: '12.340',
        debtPaid: '1.000',
        cartItems: <Map<String, dynamic>>[
          <String, dynamic>{
            'product_variant_id': 11,
            'quantity': 2,
            'packs_quantity': 1,
            'sample_quantity': 0,
            'sample_packs_quantity': 0,
            'sample_reason': '',
          },
        ],
        returns: const <Map<String, dynamic>>[],
      );

      expect(payload['outcome'], 'Sale');
      expect(payload['cash_collected'], '12.340');
      expect(payload['debt_paid'], '1.000');
      expect(payload['cart_items'], isA<List<dynamic>>());
      expect(payload, isNot(contains('visit_id')));
      expect(payload, isNot(contains('visitId')));
      expect(payload, isNot(contains('no_sale_reason')));
    });

    test('NoSale puts reason in notes and never sends cash', () {
      final payload = buildCanonicalVisitPayload(
        outcome: 'NoSale',
        notes: 'المحل مغلق',
        cashCollected: '99.999',
        debtPaid: '5.250',
        cartItems: const <Map<String, dynamic>>[],
        returns: const <Map<String, dynamic>>[],
      );

      expect(payload['notes'], 'المحل مغلق');
      expect(payload['cash_collected'], '0.000');
      expect(payload['debt_paid'], '5.250');
      expect(payload, isNot(contains('no_sale_reason')));
    });

    test('Postponed excludes finance, cart and returns', () {
      final payload = buildCanonicalVisitPayload(
        outcome: 'Postponed',
        notes: 'ارجع غداً',
        cashCollected: '10.000',
        debtPaid: '2.000',
        cartItems: <Map<String, dynamic>>[
          <String, dynamic>{'product_variant_id': 1, 'quantity': 1},
        ],
        returns: <Map<String, dynamic>>[
          <String, dynamic>{'product_variant_id': 1, 'quantity': 1},
        ],
      );

      expect(payload, <String, dynamic>{
        'outcome': 'Postponed',
        'notes': 'ارجع غداً',
      });
    });
  });

  group('visit local inventory correction', () {
    test('first application deducts sale, sample and replacement stock', () {
      final next = visitInventoryProjection(
        cartItems: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 7,
            'quantity': 2,
            'packs_quantity': 3,
            'sample_quantity': 1,
            'sample_packs_quantity': 2,
          },
        ],
        returns: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 7,
            'quantity': 1,
            'packs_quantity': 4,
            'return_type': 'Damaged',
          },
        ],
      );

      final delta = inventoryCorrectionDeltaBasePacks(
        oldProjection: const VisitInventoryQuantity(),
        newProjection: next[7]!,
        packsPerCarton: 10,
      );

      expect(delta, -49);
    });

    test('completed visit correction applies only old-to-new delta', () {
      final oldProjection = visitInventoryProjection(
        cartItems: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 7,
            'quantity': 2,
            'packs_quantity': 0,
          },
        ],
        returns: const <dynamic>[],
      );
      final newProjection = visitInventoryProjection(
        cartItems: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 7,
            'quantity': 1,
            'packs_quantity': 0,
          },
        ],
        returns: const <dynamic>[],
      );

      expect(
        inventoryCorrectionDeltaBasePacks(
          oldProjection: oldProjection[7]!,
          newProjection: newProjection[7]!,
          packsPerCarton: 10,
        ),
        10,
      );
    });

    test('same replay projection produces zero inventory delta', () {
      final projection = visitInventoryProjection(
        cartItems: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 9,
            'quantity': 1,
            'packs_quantity': 3,
            'sample_quantity': 0,
            'sample_packs_quantity': 2,
          },
        ],
        returns: const <dynamic>[],
      );

      expect(
        inventoryCorrectionDeltaBasePacks(
          oldProjection: projection[9]!,
          newProjection: projection[9]!,
          packsPerCarton: 12,
        ),
        0,
      );
    });

    test('cancelled lines are ignored', () {
      final projection = visitInventoryProjection(
        cartItems: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 3,
            'quantity': 99,
            'is_cancelled': true,
          },
        ],
        returns: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 3,
            'quantity': 99,
            'is_cancelled': 1,
          },
        ],
      );

      expect(projection, isEmpty);
    });
  });

  test('Visit submission path keeps compatibility-only body fields out', () async {
    final blocSource =
        await File('lib/blocs/visit/visit_bloc.dart').readAsString();
    final serviceSource = await File(
      'lib/features/visits/application/visit_submission_service.dart',
    ).readAsString();

    expect(blocSource, contains('VisitSubmissionService'));
    expect(blocSource, contains('await _submissionService.submit('));
    expect(serviceSource, contains('buildCanonicalVisitPayload'));

    for (final source in <String>[blocSource, serviceSource]) {
      expect(source, isNot(contains("'visit_id':")));
      expect(source, isNot(contains("'visitId':")));
      expect(source, isNot(contains("'no_sale_reason':")));
    }
  });
}
