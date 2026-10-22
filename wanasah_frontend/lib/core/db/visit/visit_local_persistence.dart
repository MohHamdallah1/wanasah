import 'dart:convert';

import 'package:sqflite/sqflite.dart';

import '../../sync/durable_command.dart';
import '../../sync/pending_command_store.dart';
import '../../visit/local_inventory_projection.dart';
import 'visit_inventory_projection_persistence.dart';

typedef VisitDatabaseProvider = Future<Database> Function();

class VisitLocalPersistence {
  VisitLocalPersistence({
    required VisitDatabaseProvider databaseProvider,
    required PendingCommandStore pendingCommands,
    VisitInventoryProjectionPersistence? inventoryProjection,
  }) : _databaseProvider = databaseProvider,
       _pendingCommands = pendingCommands,
       _inventoryProjection =
           inventoryProjection ?? const VisitInventoryProjectionPersistence();

  final VisitDatabaseProvider _databaseProvider;
  final PendingCommandStore _pendingCommands;
  final VisitInventoryProjectionPersistence _inventoryProjection;

  Future<void> updateVisitStatus({
    required int visitId,
    required String status,
    required String outcome,
    double cashCollected = 0.0,
    double debtPaid = 0.0,
    double? newShopBalance,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    Transaction? txn,
  }) async {
    final db = txn ?? await _databaseProvider();
    final updateData = <String, Object?>{
      'status': status,
      'outcome': outcome,
      'cash_collected': cashCollected,
      'debt_paid': debtPaid,
      'cart_items': cartItemsJson,
      'returns': returnsJson,
      'notes': notes,
    };

    if (newShopBalance != null) {
      updateData['shop_balance'] = newShopBalance;
    }

    await db.update(
      'visits',
      updateData,
      where: 'visit_id = ?',
      whereArgs: <Object?>[visitId],
    );
  }

  Future<void> deductInventoryLocal(
    List<dynamic> cartItems, {
    List<dynamic>? returnItems,
    Transaction? txn,
  }) async {
    final returns = returnItems ?? const <dynamic>[];

    if (txn != null) {
      await _inventoryProjection.applyInitial(
        txn: txn,
        cartItems: cartItems,
        returnItems: returns,
      );
      return;
    }

    final db = await _databaseProvider();
    await db.transaction((transaction) async {
      await _inventoryProjection.applyInitial(
        txn: transaction,
        cartItems: cartItems,
        returnItems: returns,
      );
    });
  }

  Future<void> revertOfflineVisit(int visitId, {Transaction? txn}) async {
    throw UnsupportedError(
      'Visit #$visitId has durable offline evidence and cannot be auto-reverted.',
    );
  }

  Future<int> stageVisitCommandAtomic({
    required int visitId,
    required String payload,
    required String requestId,
    int? ownerDriverId,
  }) async {
    final db = await _databaseProvider();
    return db.transaction((txn) async {
      final unresolved = await txn.query(
        'pending_sync',
        orderBy: 'created_at ASC, id ASC',
      );

      for (final row in unresolved) {
        final rawType = row['type']?.toString() ?? '';
        final normalizedType =
            DurableCommandType.normalizeLegacyType(rawType);

        if (normalizedType == DurableCommandType.corrupt) {
          throw StateError(
            'Corrupt unresolved offline evidence must be recovered before creating another visit command.',
          );
        }
        if (normalizedType != DurableCommandType.submitSale) {
          continue;
        }

        Map<String, dynamic> existing;
        try {
          existing = Map<String, dynamic>.from(
            jsonDecode(row['payload'] as String) as Map,
          );
        } catch (_) {
          throw StateError(
            'Unreadable unresolved sale evidence must be recovered before creating another visit command.',
          );
        }

        if (existing['visitId'].toString() == visitId.toString()) {
          throw StateError(
            'Visit #$visitId already has an unresolved command. Resolve it before creating a correction or replacement command.',
          );
        }
      }

      return _pendingCommands.add(
        type: DurableCommandType.submitSale,
        payload: payload,
        commandId: requestId,
        ownerDriverId: ownerDriverId,
        txn: txn,
      );
    });
  }

  Future<void> finalizeVisitCommandLocalState({
    required int commandRecordId,
    required int visitId,
    required String status,
    required String outcome,
    required double cashCollected,
    required double debtPaid,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    required List<dynamic> cartItems,
    List<dynamic>? returnItems,
  }) async {
    final db = await _databaseProvider();
    try {
      await db.transaction((txn) async {
        final commandRows = await txn.query(
          'pending_sync',
          columns: const <String>['local_effect_applied'],
          where: 'id = ?',
          whereArgs: <Object?>[commandRecordId],
          limit: 1,
        );
        if (commandRows.isEmpty) {
          throw StateError(
            'Offline command #$commandRecordId is missing before local finalize.',
          );
        }

        final alreadyApplied =
            (commandRows.first['local_effect_applied'] as num?)?.toInt() == 1;
        if (alreadyApplied) return;

        final previousVisitRows = await txn.query(
          'visits',
          columns: const <String>['cart_items', 'returns'],
          where: 'visit_id = ?',
          whereArgs: <Object?>[visitId],
          limit: 1,
        );
        if (previousVisitRows.isEmpty) {
          throw StateError(
            'Visit #$visitId is missing before local command finalization.',
          );
        }

        final oldCartItems = _inventoryProjection.decodeStoredVisitList(
          previousVisitRows.first['cart_items'],
        );
        final oldReturns = _inventoryProjection.decodeStoredVisitList(
          previousVisitRows.first['returns'],
        );
        final newReturns = returnItems ?? const <dynamic>[];

        await _inventoryProjection.applyCorrection(
          txn: txn,
          oldCartItems: oldCartItems,
          oldReturns: oldReturns,
          newCartItems: cartItems,
          newReturns: newReturns,
        );

        await updateVisitStatus(
          visitId: visitId,
          status: status,
          outcome: outcome,
          cashCollected: cashCollected,
          debtPaid: debtPaid,
          cartItemsJson: cartItemsJson,
          returnsJson: returnsJson,
          notes: notes,
          txn: txn,
        );

        final updated = await txn.update(
          'pending_sync',
          <String, Object?>{
            'local_effect_applied': 1,
            'updated_at': DateTime.now().toIso8601String(),
          },
          where: 'id = ?',
          whereArgs: <Object?>[commandRecordId],
        );
        if (updated != 1) {
          throw StateError(
            'Offline command #$commandRecordId disappeared during local finalize.',
          );
        }
      });
    } on LocalInventoryProjectionException catch (error) {
      await _pendingCommands.markBlocked(
        commandRecordId,
        errorCode: error.code,
        errorMessage: error.toString(),
      );
      rethrow;
    }
  }

  Future<void> updateShopBalanceLocally(
    int visitId,
    double newBalance,
  ) async {
    final db = await _databaseProvider();
    await db.rawUpdate(
      'UPDATE visits SET shop_balance = ? WHERE visit_id = ?',
      <Object?>[newBalance, visitId],
    );
  }

  Future<void> saveOnlineInvoiceAtomic({
    required int visitId,
    required String status,
    required String outcome,
    required double cashCollected,
    required double debtPaid,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    required List<dynamic> cartItems,
    List<dynamic>? returnItems,
  }) async {
    final db = await _databaseProvider();
    await db.transaction((txn) async {
      await updateVisitStatus(
        visitId: visitId,
        status: status,
        outcome: outcome,
        cashCollected: cashCollected,
        debtPaid: debtPaid,
        cartItemsJson: cartItemsJson,
        returnsJson: returnsJson,
        notes: notes,
        txn: txn,
      );
      await deductInventoryLocal(
        cartItems,
        returnItems: returnItems,
        txn: txn,
      );
    });
  }

  Future<void> saveOfflineInvoiceAtomic({
    required int visitId,
    required String payload,
    required String status,
    required String outcome,
    required double cashCollected,
    required double debtPaid,
    String? cartItemsJson,
    String? returnsJson,
    String? notes,
    required List<dynamic> cartItems,
    List<dynamic>? returnItems,
    String? commandId,
    int? ownerDriverId,
  }) async {
    final requestId = commandId?.trim() ?? '';
    if (requestId.isEmpty) {
      throw StateError('Offline visit command requires a durable request ID.');
    }

    final commandRecordId = await stageVisitCommandAtomic(
      visitId: visitId,
      payload: payload,
      requestId: requestId,
      ownerDriverId: ownerDriverId,
    );
    await finalizeVisitCommandLocalState(
      commandRecordId: commandRecordId,
      visitId: visitId,
      status: status,
      outcome: outcome,
      cashCollected: cashCollected,
      debtPaid: debtPaid,
      cartItemsJson: cartItemsJson,
      returnsJson: returnsJson,
      notes: notes,
      cartItems: cartItems,
      returnItems: returnItems,
    );
  }
}
