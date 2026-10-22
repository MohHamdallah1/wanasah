import 'package:sqflite/sqflite.dart';

import 'durable_command.dart';
import 'durable_command_owner.dart';

typedef OfflineDatabaseProvider = Future<Database> Function();
typedef OfflineTenantProvider = String Function();

class PendingCommandStore {
  PendingCommandStore({
    required OfflineDatabaseProvider databaseProvider,
    required OfflineTenantProvider tenantProvider,
  })  : _databaseProvider = databaseProvider,
        _tenantProvider = tenantProvider;

  final OfflineDatabaseProvider _databaseProvider;
  final OfflineTenantProvider _tenantProvider;

  Future<DatabaseExecutor> _executor(Transaction? txn) async =>
      txn ?? await _databaseProvider();

  Future<int> add({
    required String type,
    required String payload,
    String? commandId,
    DurableCommandState state = DurableCommandState.pending,
    int? ownerDriverId,
    String? lastErrorCode,
    String? lastErrorMessage,
    String? lastRequestId,
    Transaction? txn,
  }) async {
    final tenant = _tenantProvider();
    if (DurableCommandType.isReplayable(type) &&
        (ownerDriverId == null || ownerDriverId <= 0)) {
      throw const DurableCommandOwnerException('DURABLE_OWNER_REQUIRED');
    }
    if (tenant.trim().isEmpty || tenant == 'null') {
      throw const DurableCommandOwnerException('DURABLE_OWNER_COMPANY_REQUIRED');
    }
    final db = await _executor(txn);
    if (_tenantProvider() != tenant) {
      throw const DurableCommandOwnerException('DURABLE_OWNER_COMPANY_MISMATCH');
    }
    final now = DateTime.now().toIso8601String();
    return db.insert('pending_sync', {
      'type': type,
      'payload': payload,
      'created_at': now,
      'command_id': commandId,
      'state': state.storageValue,
      'owner_company_code': tenant,
      'owner_driver_id': ownerDriverId,
      'attempt_count': 0,
      'last_error_code': lastErrorCode,
      'last_error_message': lastErrorMessage,
      'last_request_id': lastRequestId,
      'updated_at': now,
    });
  }

  Future<List<Map<String, dynamic>>> all({int? limit}) async {
    final db = await _databaseProvider();
    return db.query(
      'pending_sync',
      orderBy: 'created_at ASC, id ASC',
      limit: limit,
    );
  }

  Future<void> deleteAfterConfirmedSuccess(int id) async {
    final db = await _databaseProvider();
    await db.delete('pending_sync', where: 'id = ?', whereArgs: [id]);
  }

  Future<void> markInFlight(int id) async {
    final db = await _databaseProvider();
    final updated = await db.rawUpdate(
      'UPDATE pending_sync '
      'SET state = ?, attempt_count = attempt_count + 1, updated_at = ? '
      'WHERE id = ?',
      [
        DurableCommandState.inFlight.storageValue,
        DateTime.now().toIso8601String(),
        id,
      ],
    );
    _requireSingleRow(updated, id);
  }

  Future<void> markPending(
    int id, {
    String? lastErrorCode,
    String? lastErrorMessage,
    String? lastRequestId,
  }) async {
    final db = await _databaseProvider();
    final updated = await db.update(
      'pending_sync',
      {
        'state': DurableCommandState.pending.storageValue,
        'last_error_code': lastErrorCode,
        'last_error_message': lastErrorMessage,
        'last_request_id': lastRequestId,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    _requireSingleRow(updated, id);
  }

  Future<void> markBlocked(
    int id, {
    required String errorCode,
    String? errorMessage,
    String? requestId,
  }) async {
    final db = await _databaseProvider();
    final updated = await db.update(
      'pending_sync',
      {
        'state': DurableCommandState.blocked.storageValue,
        'last_error_code': errorCode,
        'last_error_message': errorMessage,
        'last_request_id': requestId,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    _requireSingleRow(updated, id);
  }

  Future<void> updatePayload(int id, String payload) async {
    final db = await _databaseProvider();
    final updated = await db.update(
      'pending_sync',
      {
        'payload': payload,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    _requireSingleRow(updated, id);
  }

  Future<void> updateCommandId(int id, String commandId) async {
    final db = await _databaseProvider();
    final updated = await db.update(
      'pending_sync',
      {
        'command_id': commandId,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    _requireSingleRow(updated, id);
  }

  Future<List<Map<String, dynamic>>> blocked() async {
    final db = await _databaseProvider();
    return db.query(
      'pending_sync',
      where: "state = ? OR type LIKE 'quarantined_%'",
      whereArgs: [DurableCommandState.blocked.storageValue],
      orderBy: 'created_at DESC, id DESC',
    );
  }

  Future<void> retryBlocked(int id) async {
    final db = await _databaseProvider();
    final record = await db.query(
      'pending_sync',
      where: 'id = ?',
      whereArgs: [id],
      limit: 1,
    );
    if (record.isEmpty) {
      throw StateError('Blocked command #$id was not found.');
    }

    final rawType = record.first['type']?.toString() ?? '';
    final normalizedType = DurableCommandType.normalizeLegacyType(rawType);
    if (!DurableCommandType.isReplayable(normalizedType)) {
      throw StateError(
        'Blocked command type "$normalizedType" requires recovery, not generic retry.',
      );
    }

    final updated = await db.update(
      'pending_sync',
      {
        'type': normalizedType,
        'state': DurableCommandState.pending.storageValue,
        'last_error_code': null,
        'last_error_message': null,
        'last_request_id': null,
        'updated_at': DateTime.now().toIso8601String(),
      },
      where: 'id = ?',
      whereArgs: [id],
    );
    _requireSingleRow(updated, id);
  }

  void _requireSingleRow(int updated, int id) {
    if (updated != 1) {
      throw StateError('Offline command #$id was not found.');
    }
  }
}
