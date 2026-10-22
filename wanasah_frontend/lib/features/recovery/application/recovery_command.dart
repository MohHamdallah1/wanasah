import 'dart:convert';

import '../../../core/sync/durable_command.dart';

class RecoveryCommand {
  const RecoveryCommand({
    required this.recordId,
    required this.commandId,
    required this.normalizedType,
    required this.state,
    required this.legacyQuarantined,
    required this.createdAt,
    required this.attemptCount,
    required this.lastErrorCode,
    required this.lastRequestId,
    required this.displayFallback,
    required this.visitId,
    required this.transferId,
    required this.referenceLabel,
  });

  final int recordId;
  final String? commandId;
  final String normalizedType;
  final DurableCommandState state;
  final bool legacyQuarantined;
  final DateTime? createdAt;
  final int attemptCount;
  final String? lastErrorCode;
  final String? lastRequestId;

  /// Display-only evidence. Never use this value for retry/business decisions.
  final String? displayFallback;

  final int? visitId;
  final int? transferId;
  final String? referenceLabel;

  bool get isBlocked =>
      state == DurableCommandState.blocked || legacyQuarantined;

  bool get isReplayable =>
      DurableCommandType.isReplayable(normalizedType);

  bool get canGenericRetry => isBlocked && isReplayable;

  factory RecoveryCommand.fromRow(Map<String, dynamic> row) {
    final rawType = row['type']?.toString().trim() ?? '';
    final legacyQuarantined =
        DurableCommandType.isLegacyQuarantined(rawType);
    final normalizedType = rawType.isEmpty
        ? DurableCommandType.corrupt
        : DurableCommandType.normalizeLegacyType(rawType);

    final persistedState = DurableCommandState.fromStorage(row['state']);
    final state =
        legacyQuarantined ? DurableCommandState.blocked : persistedState;

    Map<String, dynamic>? payload;
    try {
      final decoded = jsonDecode(row['payload']?.toString() ?? '');
      if (decoded is Map) {
        payload = <String, dynamic>{
          for (final entry in decoded.entries)
            if (entry.key is String) entry.key as String: entry.value,
        };
      }
    } catch (_) {
      payload = null;
    }

    final lastErrorMessage = _nonEmptyString(row['last_error_message']);
    final legacyFallback = _nonEmptyString(payload?['quarantine_reason']);

    return RecoveryCommand(
      recordId: _intValue(row['id']) ?? 0,
      commandId: _nonEmptyString(row['command_id']),
      normalizedType: normalizedType,
      state: state,
      legacyQuarantined: legacyQuarantined,
      createdAt: _dateTimeValue(row['created_at']),
      attemptCount: _intValue(row['attempt_count']) ?? 0,
      lastErrorCode: _nonEmptyString(row['last_error_code']),
      lastRequestId: _nonEmptyString(row['last_request_id']),
      displayFallback: lastErrorMessage ?? legacyFallback,
      visitId:
          _intValue(payload?['visitId']) ??
          _intValue(payload?['visit_id']),
      transferId:
          _intValue(payload?['transferId']) ??
          _intValue(payload?['transfer_id']),
      referenceLabel:
          _nonEmptyString(payload?['context_product_name']) ??
          _nonEmptyString(payload?['reference']),
    );
  }

  static int? _intValue(Object? value) {
    if (value is int) return value;
    if (value is num) return value.toInt();
    return int.tryParse(value?.toString() ?? '');
  }

  static DateTime? _dateTimeValue(Object? value) {
    final raw = value?.toString().trim() ?? '';
    if (raw.isEmpty) return null;
    return DateTime.tryParse(raw);
  }

  static String? _nonEmptyString(Object? value) {
    final raw = value?.toString().trim() ?? '';
    return raw.isEmpty ? null : raw;
  }
}
