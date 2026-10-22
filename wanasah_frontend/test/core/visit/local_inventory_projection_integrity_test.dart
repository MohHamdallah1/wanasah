import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/visit/local_inventory_projection.dart';

void main() {
  group('local AVAILABLE inventory projection integrity', () {
    test('normal initial projection applies exact outgoing quantity', () {
      final outgoing = visitInventoryProjection(
        cartItems: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 7,
            'quantity': 1,
            'packs_quantity': 4,
          },
        ],
        returns: const <dynamic>[],
      );

      final delta = inventoryCorrectionDeltaBasePacks(
        oldProjection: const VisitInventoryQuantity(),
        newProjection: outgoing[7]!,
        packsPerCarton: 10,
        variantId: 7,
      );
      final next = applyLocalAvailableInventoryDelta(
        variantId: 7,
        currentCartons: 5,
        currentPacks: 2,
        packsPerCarton: 10,
        deltaBasePacks: delta,
      );

      expect(delta, -14);
      expect(next.cartons, 3);
      expect(next.packs, 8);
    });

    test('carton and pack quantities normalize using exact packs-per-carton',
        () {
      final outgoing = const VisitInventoryQuantity(
        cartons: 0,
        packs: 15,
      );
      final delta = inventoryCorrectionDeltaBasePacks(
        oldProjection: const VisitInventoryQuantity(),
        newProjection: outgoing,
        packsPerCarton: 10,
        variantId: 8,
      );
      final next = applyLocalAvailableInventoryDelta(
        variantId: 8,
        currentCartons: 2,
        currentPacks: 9,
        packsPerCarton: 10,
        deltaBasePacks: delta,
      );

      expect(delta, -15);
      expect(next.cartons, 1);
      expect(next.packs, 4);
    });

    test('invalid packs-per-carton fails closed instead of defaulting to one',
        () {
      expect(
        () => const VisitInventoryQuantity(cartons: 1).toBasePacks(
          0,
          variantId: 9,
        ),
        throwsA(
          isA<LocalInventoryProjectionException>().having(
            (error) => error.code,
            'code',
            LocalInventoryProjectionCode.invalidPacksPerCarton,
          ),
        ),
      );
    });

    test('internally inconsistent current projection fails closed', () {
      expect(
        () => applyLocalAvailableInventoryDelta(
          variantId: 10,
          currentCartons: 2,
          currentPacks: 10,
          packsPerCarton: 10,
          deltaBasePacks: 0,
        ),
        throwsA(
          isA<LocalInventoryProjectionException>().having(
            (error) => error.code,
            'code',
            LocalInventoryProjectionCode.invalidCurrentState,
          ),
        ),
      );
    });

    test('projection underflow fails closed instead of clamping to zero', () {
      expect(
        () => applyLocalAvailableInventoryDelta(
          variantId: 11,
          currentCartons: 1,
          currentPacks: 0,
          packsPerCarton: 10,
          deltaBasePacks: -11,
        ),
        throwsA(
          isA<LocalInventoryProjectionException>().having(
            (error) => error.code,
            'code',
            LocalInventoryProjectionCode.underflow,
          ),
        ),
      );
    });

    test('negative outgoing projection quantity fails closed', () {
      expect(
        () => visitInventoryProjection(
          cartItems: <dynamic>[
            <String, dynamic>{
              'product_variant_id': 12,
              'quantity': -1,
              'packs_quantity': 0,
            },
          ],
          returns: const <dynamic>[],
        ),
        throwsA(
          isA<LocalInventoryProjectionException>().having(
            (error) => error.code,
            'code',
            LocalInventoryProjectionCode.invalidQuantity,
          ),
        ),
      );
    });
  });

  group('correction delta and exactly-once semantics', () {
    test('same projection replay has zero second inventory effect', () {
      const projection = VisitInventoryQuantity(
        cartons: 2,
        packs: 3,
      );

      expect(
        inventoryCorrectionDeltaBasePacks(
          oldProjection: projection,
          newProjection: projection,
          packsPerCarton: 12,
          variantId: 20,
        ),
        0,
      );
    });

    test('completed Visit correction old to new applies only the delta', () {
      const oldProjection = VisitInventoryQuantity(cartons: 2);
      const newProjection = VisitInventoryQuantity(
        cartons: 2,
        packs: 5,
      );

      final delta = inventoryCorrectionDeltaBasePacks(
        oldProjection: oldProjection,
        newProjection: newProjection,
        packsPerCarton: 10,
        variantId: 21,
      );
      final next = applyLocalAvailableInventoryDelta(
        variantId: 21,
        currentCartons: 8,
        currentPacks: 0,
        packsPerCarton: 10,
        deltaBasePacks: delta,
      );

      expect(delta, -5);
      expect(next.cartons, 7);
      expect(next.packs, 5);
    });

    test('correction increasing outgoing quantity decreases AVAILABLE only once',
        () {
      const oldProjection = VisitInventoryQuantity(cartons: 1);
      const newProjection = VisitInventoryQuantity(cartons: 3);

      final delta = inventoryCorrectionDeltaBasePacks(
        oldProjection: oldProjection,
        newProjection: newProjection,
        packsPerCarton: 10,
        variantId: 22,
      );

      expect(delta, -20);
      final next = applyLocalAvailableInventoryDelta(
        variantId: 22,
        currentCartons: 6,
        currentPacks: 0,
        packsPerCarton: 10,
        deltaBasePacks: delta,
      );
      expect(next.cartons, 4);
      expect(next.packs, 0);
    });

    test('correction decreasing outgoing quantity restores AVAILABLE delta',
        () {
      const oldProjection = VisitInventoryQuantity(cartons: 3);
      const newProjection = VisitInventoryQuantity(cartons: 1);

      final delta = inventoryCorrectionDeltaBasePacks(
        oldProjection: oldProjection,
        newProjection: newProjection,
        packsPerCarton: 10,
        variantId: 23,
      );

      expect(delta, 20);
      final next = applyLocalAvailableInventoryDelta(
        variantId: 23,
        currentCartons: 4,
        currentPacks: 0,
        packsPerCarton: 10,
        deltaBasePacks: delta,
      );
      expect(next.cartons, 6);
      expect(next.packs, 0);
    });

    test('replacement return remains outgoing AVAILABLE projection only', () {
      final projected = visitInventoryProjection(
        cartItems: const <dynamic>[],
        returns: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 24,
            'quantity': 1,
            'packs_quantity': 2,
            'return_type': 'Damaged',
          },
        ],
      );

      expect(projected[24]!.cartons, 1);
      expect(projected[24]!.packs, 2);
    });
  });

  group('durable command transaction invariants', () {
    test('split persistence has no silent clamp and uses one projection engine',
        () async {
      final databaseSource =
          await File('lib/core/db/local_database.dart').readAsString();
      final projectionPersistence = await File(
        'lib/core/db/visit/visit_inventory_projection_persistence.dart',
      ).readAsString();

      expect(databaseSource, isNot(contains('MAX(0,')));
      expect(databaseSource, isNot(contains('applyLocalAvailableInventoryDelta(')));
      expect(projectionPersistence, isNot(contains('MAX(0,')));
      expect(projectionPersistence, contains('Future<void> applyDelta('));
      expect(
        projectionPersistence,
        contains('applyLocalAvailableInventoryDelta('),
      );
      expect(
        projectionPersistence,
        contains('inventoryCorrectionDeltaBasePacks('),
      );
    });

    test('already-applied durable command exits before projection replay',
        () async {
      final source = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();
      final methodStart =
          source.indexOf('Future<void> finalizeVisitCommandLocalState({');
      final alreadyApplied = source.indexOf(
        'if (alreadyApplied) return;',
        methodStart,
      );
      final projectionApply = source.indexOf(
        'await _inventoryProjection.applyCorrection(',
        methodStart,
      );

      expect(methodStart, greaterThanOrEqualTo(0));
      expect(alreadyApplied, greaterThan(methodStart));
      expect(projectionApply, greaterThan(alreadyApplied));
    });

    test('local effect marker is written only after projection and visit update',
        () async {
      final source = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();
      final methodStart =
          source.indexOf('Future<void> finalizeVisitCommandLocalState({');
      final projectionApply = source.indexOf(
        'await _inventoryProjection.applyCorrection(',
        methodStart,
      );
      final visitUpdate = source.indexOf(
        'await updateVisitStatus(',
        projectionApply,
      );
      final effectMarker = source.indexOf(
        "'local_effect_applied': 1",
        visitUpdate,
      );

      expect(projectionApply, greaterThan(methodStart));
      expect(visitUpdate, greaterThan(projectionApply));
      expect(effectMarker, greaterThan(visitUpdate));
    });

    test('failed projection transaction preserves typed unresolved evidence',
        () async {
      final dbSource = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();
      final syncSource =
          await File('lib/repositories/sync_repository.dart').readAsString();

      expect(
        dbSource,
        contains('on LocalInventoryProjectionException catch (error)'),
      );
      expect(
        dbSource,
        contains('errorCode: error.code'),
      );
      expect(
        syncSource,
        contains('on LocalInventoryProjectionException catch (error)'),
      );
      expect(
        syncSource,
        contains('errorCode: error.code'),
      );

      final finalizeStart =
          dbSource.indexOf('Future<void> finalizeVisitCommandLocalState({');
      final finalizeEnd = dbSource.indexOf(
        'Future<void> updateShopBalanceLocally(',
        finalizeStart,
      );
      final finalizeBody = dbSource.substring(finalizeStart, finalizeEnd);
      expect(finalizeBody, isNot(contains('deletePendingSync')));
    });

    test('repository deletes durable command only after local finalize succeeds',
        () async {
      final source =
          await File('lib/repositories/sync_repository.dart').readAsString();
      final replayDispatch = source.indexOf(
        'await _dispatchPendingRecord(type: type, payload: payload);',
      );
      final replayFinalize = source.indexOf(
        '_finalizeVisitCommandLocalState(',
        replayDispatch,
      );
      final replayDelete = source.indexOf(
        'await _db.deletePendingSync(recordId);',
        replayFinalize,
      );

      expect(replayDispatch, greaterThanOrEqualTo(0));
      expect(replayFinalize, greaterThan(replayDispatch));
      expect(replayDelete, greaterThan(replayFinalize));
    });

    test('projection classification uses stable codes, not localized text',
        () async {
      final projectionSource = await File(
        'lib/core/visit/local_inventory_projection.dart',
      ).readAsString();
      final syncSource =
          await File('lib/repositories/sync_repository.dart').readAsString();

      expect(projectionSource, contains('LOCAL_PROJECTION_UNDERFLOW'));
      expect(
        projectionSource,
        contains('LOCAL_PROJECTION_CURRENT_STATE_INVALID'),
      );
      expect(projectionSource, isNot(contains('message.contains')));
      expect(
        syncSource,
        contains('errorCode: error.code'),
      );
    });
  });
}
