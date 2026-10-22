import 'dart:convert';

import 'package:uuid/uuid.dart';
import 'package:wanasah_frontend/core/db/local_database.dart';
import 'package:wanasah_frontend/core/sync/durable_command.dart';
import 'package:wanasah_frontend/features/auth/data/secure_auth_identity_store.dart';

import '../domain/transfer_decision.dart';
import '../domain/transfer_decision_command.dart';

class StoredTransferDecision {
  const StoredTransferDecision({
    required this.recordId,
    required this.commandId,
    required this.decision,
    required this.wasExisting,
  });

  final int recordId;
  final String commandId;
  final TransferDecision decision;
  final bool wasExisting;
}

class TransferDecisionEvidenceException implements Exception {
  const TransferDecisionEvidenceException(this.code);

  final String code;

  @override
  String toString() => 'TransferDecisionEvidenceException($code)';
}

abstract interface class TransferDecisionStore {
  Future<StoredTransferDecision> stageOrReuse(TransferDecision decision);

  Future<void> markInFlight(StoredTransferDecision command);

  Future<void> markPending(
    StoredTransferDecision command, {
    required String code,
    String? displayFallback,
    String? requestId,
  });

  Future<void> markBlocked(
    StoredTransferDecision command, {
    required String code,
    String? displayFallback,
    String? requestId,
  });

  Future<void> finalizeConfirmedSuccess(StoredTransferDecision command);
}

class LocalTransferDecisionStore implements TransferDecisionStore {
  LocalTransferDecisionStore({
    LocalDatabase? database,
    Uuid? uuid,
    SecureAuthIdentityStore? identities,
  }) : _database = database ?? LocalDatabase.instance,
       _uuid = uuid ?? const Uuid(),
       _identities = identities ?? SecureAuthIdentityStore();

  final LocalDatabase _database;
  final Uuid _uuid;
  final SecureAuthIdentityStore _identities;

  @override
  Future<StoredTransferDecision> stageOrReuse(
    TransferDecision decision,
  ) async {
    final owner = await _identities.requireCommandOwner(_database.currentTenant);
    final unresolved = await _database.getPendingSyncs();
    owner.requireRows(unresolved);
    owner.requireTenant(_database.currentTenant);

    for (final row in unresolved) {
      final rawType = row['type']?.toString() ?? '';
      if (DurableCommandType.normalizeLegacyType(rawType) !=
          DurableCommandType.transferResponse) {
        continue;
      }

      final payload = _decodePayload(row['payload']);
      final transferId =
          int.tryParse(payload['transferId']?.toString() ?? '') ?? 0;
      if (transferId != decision.transferId) continue;

      final state = DurableCommandState.fromStorage(row['state']);
      if (state == DurableCommandState.blocked ||
          DurableCommandType.isLegacyQuarantined(rawType)) {
        throw const TransferDecisionEvidenceException(
          'TRANSFER_DECISION_BLOCKED_EVIDENCE',
        );
      }

      final existing = _decisionFromStoredPayload(payload);
      if (!TransferDecisionCommand.sameDecision(existing, decision)) {
        throw const TransferDecisionEvidenceException(
          'TRANSFER_DECISION_CONFLICT',
        );
      }

      var commandId = row['command_id']?.toString().trim() ?? '';
      final recordId = int.tryParse(row['id']?.toString() ?? '') ?? 0;
      if (recordId <= 0) {
        throw const TransferDecisionEvidenceException(
          'TRANSFER_DECISION_RECORD_INVALID',
        );
      }

      if (commandId.isEmpty) {
        commandId = _uuid.v4();
        await _database.updatePendingSyncCommandId(recordId, commandId);
      }

      return StoredTransferDecision(
        recordId: recordId,
        commandId: commandId,
        decision: existing,
        wasExisting: true,
      );
    }

    final incoming = await _database.getIncomingTransfers();
    Map<String, dynamic>? context;
    for (final row in incoming) {
      final id =
          int.tryParse(
            (row['transfer_id'] ?? row['id'])?.toString() ?? '',
          ) ??
          0;
      if (id == decision.transferId) {
        context = row;
        break;
      }
    }

    final commandId = _uuid.v4();
    final payload = TransferDecisionCommand.toPayload(
      decision,
      productName: context?['product_name']?.toString(),
      deltaCartons: context?['delta_cartons'],
      deltaPacks: context?['delta_packs'],
    );
    owner.requireSame(await _identities.requireCommandOwner(_database.currentTenant));
    final recordId = await _database.addPendingSync(
      type: DurableCommandType.transferResponse,
      payload: jsonEncode(payload),
      commandId: commandId,
      ownerDriverId: owner.driverId,
    );

    return StoredTransferDecision(
      recordId: recordId,
      commandId: commandId,
      decision: decision,
      wasExisting: false,
    );
  }

  @override
  Future<void> markInFlight(StoredTransferDecision command) {
    return _database.markPendingSyncInFlight(command.recordId);
  }

  @override
  Future<void> markPending(
    StoredTransferDecision command, {
    required String code,
    String? displayFallback,
    String? requestId,
  }) {
    return _database.markPendingSyncPending(
      command.recordId,
      lastErrorCode: code,
      lastErrorMessage: displayFallback,
      lastRequestId: requestId,
    );
  }

  @override
  Future<void> markBlocked(
    StoredTransferDecision command, {
    required String code,
    String? displayFallback,
    String? requestId,
  }) {
    return _database.markPendingSyncBlocked(
      command.recordId,
      errorCode: code,
      errorMessage: displayFallback,
      requestId: requestId,
    );
  }

  @override
  Future<void> finalizeConfirmedSuccess(
    StoredTransferDecision command,
  ) async {
    await _database.removeIncomingTransfer(command.decision.transferId);
    await _database.deletePendingSync(command.recordId);
  }

  Map<String, dynamic> _decodePayload(Object? raw) {
    try {
      final decoded = jsonDecode(raw?.toString() ?? '');
      if (decoded is Map) {
        return <String, dynamic>{
          for (final entry in decoded.entries)
            if (entry.key is String) entry.key as String: entry.value,
        };
      }
    } catch (_) {
      // Stable fail-closed error below.
    }

    throw const TransferDecisionEvidenceException(
      'TRANSFER_DECISION_PAYLOAD_CORRUPT',
    );
  }

  TransferDecision _decisionFromStoredPayload(
    Map<String, dynamic> payload,
  ) {
    try {
      return TransferDecisionCommand.fromPayload(payload);
    } catch (_) {
      throw const TransferDecisionEvidenceException(
        'TRANSFER_DECISION_PAYLOAD_CORRUPT',
      );
    }
  }
}
