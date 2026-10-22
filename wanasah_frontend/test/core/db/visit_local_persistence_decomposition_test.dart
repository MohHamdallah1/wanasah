import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/visit/local_inventory_projection.dart';

void main() {
  group('Visit persistence decomposition architecture', () {
    test('LocalDatabase is a thin Visit facade with no projection orchestration',
        () async {
      final local =
          await File('lib/core/db/local_database.dart').readAsString();

      expect(local.split('\n').length, lessThan(850));
      expect(local, contains('VisitLocalPersistence _visitPersistence'));
      expect(local, contains('_visitPersistence.updateVisitStatus('));
      expect(local, contains('_visitPersistence.deductInventoryLocal('));
      expect(local, contains('_visitPersistence.stageVisitCommandAtomic('));
      expect(
        local,
        contains('_visitPersistence.finalizeVisitCommandLocalState('),
      );
      expect(local, contains('_visitPersistence.updateShopBalanceLocally('));
      expect(local, contains('_visitPersistence.saveOnlineInvoiceAtomic('));
      expect(local, contains('_visitPersistence.saveOfflineInvoiceAtomic('));

      expect(local, isNot(contains('_decodeStoredVisitList')));
      expect(local, isNot(contains('_applyVisitInventoryCorrection')));
      expect(local, isNot(contains('_applyVisitProjectionDelta')));
      expect(local, isNot(contains('applyLocalAvailableInventoryDelta(')));
      expect(local, isNot(contains('inventoryCorrectionDeltaBasePacks(')));
    });

    test('dependency direction never imports feature modules into core', () async {
      final paths = <String>[
        'lib/core/db/local_database.dart',
        'lib/core/db/visit/visit_local_persistence.dart',
        'lib/core/db/visit/visit_inventory_projection_persistence.dart',
      ];

      for (final path in paths) {
        final source = await File(path).readAsString();
        expect(source, isNot(contains("features/")), reason: path);
        expect(source, isNot(contains("../features/")), reason: path);
        expect(source, isNot(contains("../../features/")), reason: path);
      }
    });

    test('compatibility Visit persistence APIs remain as thin delegates',
        () async {
      final local =
          await File('lib/core/db/local_database.dart').readAsString();

      expect(local, contains('Future<void> saveOnlineInvoiceAtomic({'));
      expect(local, contains('Future<void> saveOfflineInvoiceAtomic({'));
      expect(local, contains('Future<void> revertOfflineVisit('));
      expect(
        local,
        contains(
          "'Use SyncRepository.saveInvoice; durable identity must be staged before first send.'",
        ),
      );
      expect(
        local,
        contains(
          "'Unresolved visit commands are immutable until reconciliation; use stageVisitCommandAtomic.'",
        ),
      );
    });
  });

  group('exact Visit finalize transaction contract', () {
    test('single transaction preserves required operation ordering', () async {
      final source = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();

      final start = source.indexOf(
        'Future<void> finalizeVisitCommandLocalState({',
      );
      final end = source.indexOf(
        'Future<void> updateShopBalanceLocally(',
        start,
      );
      final body = source.substring(start, end);

      final transaction = body.indexOf('await db.transaction((txn) async {');
      final commandRead = body.indexOf(
        "final commandRows = await txn.query(\n          'pending_sync'",
      );
      final appliedGuard = body.indexOf('if (alreadyApplied) return;');
      final visitRead = body.indexOf(
        "final previousVisitRows = await txn.query(\n          'visits'",
      );
      final correction = body.indexOf(
        'await _inventoryProjection.applyCorrection(',
      );
      final visitUpdate = body.indexOf('await updateVisitStatus(');
      final markerUpdate = body.indexOf(
        "final updated = await txn.update(\n          'pending_sync'",
      );

      expect(transaction, greaterThanOrEqualTo(0));
      expect(commandRead, greaterThan(transaction));
      expect(appliedGuard, greaterThan(commandRead));
      expect(visitRead, greaterThan(appliedGuard));
      expect(correction, greaterThan(visitRead));
      expect(visitUpdate, greaterThan(correction));
      expect(markerUpdate, greaterThan(visitUpdate));
      expect(body, contains("'local_effect_applied': 1"));
      expect(body, contains('if (updated != 1)'));
    });

    test('same command replay exits before any second projection effect',
        () async {
      final source = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();
      final start = source.indexOf(
        'Future<void> finalizeVisitCommandLocalState({',
      );
      final guard = source.indexOf('if (alreadyApplied) return;', start);
      final correction = source.indexOf(
        'await _inventoryProjection.applyCorrection(',
        start,
      );

      expect(guard, greaterThan(start));
      expect(correction, greaterThan(guard));
    });

    test('projection exception escapes transaction unchanged then blocks evidence',
        () async {
      final source = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();
      final start = source.indexOf(
        'Future<void> finalizeVisitCommandLocalState({',
      );
      final catchIndex = source.indexOf(
        'on LocalInventoryProjectionException catch (error)',
        start,
      );
      final transactionEnd = source.lastIndexOf('});', catchIndex);

      expect(catchIndex, greaterThan(start));
      expect(transactionEnd, lessThan(catchIndex));
      expect(
        source.indexOf('errorCode: error.code', catchIndex),
        greaterThan(catchIndex),
      );
      expect(
        source.substring(start, catchIndex),
        isNot(contains('catch (')),
      );
    });

    test('Visit update failure and marker failure remain inside transaction',
        () async {
      final source = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();
      final start = source.indexOf(
        'Future<void> finalizeVisitCommandLocalState({',
      );
      final end = source.indexOf(
        'on LocalInventoryProjectionException catch (error)',
        start,
      );
      final body = source.substring(start, end);

      final correction = body.indexOf(
        'await _inventoryProjection.applyCorrection(',
      );
      final visitUpdate = body.indexOf('await updateVisitStatus(');
      final marker = body.indexOf(
        "final updated = await txn.update(\n          'pending_sync'",
      );
      final markerGuard = body.indexOf('if (updated != 1)');

      expect(correction, greaterThanOrEqualTo(0));
      expect(visitUpdate, greaterThan(correction));
      expect(marker, greaterThan(visitUpdate));
      expect(markerGuard, greaterThan(marker));
      final transactionStart = body.indexOf('await db.transaction((txn) async {');
      expect(transactionStart, greaterThanOrEqualTo(0));
      expect(
        body.substring(transactionStart),
        isNot(contains('try {')),
      );
    });
  });

  group('projection behavior remains unchanged after persistence split', () {
    test('initial Visit projection keeps exact carton and pack normalization',
        () {
      final projection = visitInventoryProjection(
        cartItems: <dynamic>[
          <String, dynamic>{
            'product_variant_id': 11,
            'quantity': 1,
            'packs_quantity': 4,
          },
        ],
        returns: const <dynamic>[],
      );

      expect(
        inventoryCorrectionDeltaBasePacks(
          oldProjection: const VisitInventoryQuantity(),
          newProjection: projection[11]!,
          packsPerCarton: 10,
          variantId: 11,
        ),
        -14,
      );
    });

    test('completed correction increasing deduction remains OLD to NEW only',
        () {
      expect(
        inventoryCorrectionDeltaBasePacks(
          oldProjection: const VisitInventoryQuantity(cartons: 1),
          newProjection: const VisitInventoryQuantity(cartons: 3),
          packsPerCarton: 10,
          variantId: 12,
        ),
        -20,
      );
    });

    test('completed correction decreasing deduction restores exact delta', () {
      expect(
        inventoryCorrectionDeltaBasePacks(
          oldProjection: const VisitInventoryQuantity(cartons: 3),
          newProjection: const VisitInventoryQuantity(cartons: 1),
          packsPerCarton: 10,
          variantId: 13,
        ),
        20,
      );
    });

    test('underflow code remains exact and fail-closed', () {
      expect(
        () => applyLocalAvailableInventoryDelta(
          variantId: 14,
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

    test('invalid packs-per-carton code remains exact', () {
      expect(
        () => applyLocalAvailableInventoryDelta(
          variantId: 15,
          currentCartons: 1,
          currentPacks: 0,
          packsPerCarton: 0,
          deltaBasePacks: 0,
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

    test('missing product and update failure codes remain in persistence seam',
        () async {
      final source = await File(
        'lib/core/db/visit/visit_inventory_projection_persistence.dart',
      ).readAsString();

      expect(
        source,
        contains('LocalInventoryProjectionCode.productMissing'),
      );
      expect(
        source,
        contains('LocalInventoryProjectionCode.updateFailed'),
      );
      expect(
        source,
        contains('LocalInventoryProjectionCode.invalidCurrentState'),
      );
    });
  });

  group('durable command immutability', () {
    test('same Visit unresolved evidence blocks replacement inside transaction',
        () async {
      final source = await File(
        'lib/core/db/visit/visit_local_persistence.dart',
      ).readAsString();

      final start = source.indexOf('Future<int> stageVisitCommandAtomic({');
      final end = source.indexOf(
        'Future<void> finalizeVisitCommandLocalState({',
        start,
      );
      final body = source.substring(start, end);

      expect(body, contains("txn.query(\n        'pending_sync'"));
      expect(
        body,
        contains(
          "'Visit #\$visitId already has an unresolved command. Resolve it before creating a correction or replacement command.'",
        ),
      );
      expect(body, contains('_pendingCommands.add('));
      expect(body, contains('txn: txn'));
    });
  });

  test('returned DAMAGED custody stays outside AVAILABLE persistence ownership',
      () async {
    final visitPersistence = await File(
      'lib/core/db/visit/visit_local_persistence.dart',
    ).readAsString();
    final projectionPersistence = await File(
      'lib/core/db/visit/visit_inventory_projection_persistence.dart',
    ).readAsString();

    expect(visitPersistence, isNot(contains('PendingReturnCustody')));
    expect(projectionPersistence, isNot(contains('PendingReturnCustody')));
    expect(projectionPersistence, isNot(contains('nonSellableCustody')));
  });
}
