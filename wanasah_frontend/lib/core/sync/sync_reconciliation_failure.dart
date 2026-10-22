import 'package:sqflite/sqflite.dart';

enum SyncLocalFailureDisposition {
  pending,
  blocked,
}

class SyncLocalFailure {
  const SyncLocalFailure({
    required this.disposition,
    required this.code,
    required this.displayFallback,
  });

  final SyncLocalFailureDisposition disposition;
  final String code;

  /// Diagnostic/display evidence only. Never use this text for classification.
  final String? displayFallback;

  factory SyncLocalFailure.from(Object error) {
    if (error is DatabaseException) {
      return SyncLocalFailure(
        disposition: SyncLocalFailureDisposition.pending,
        code: 'LOCAL_DATABASE_TRANSIENT',
        displayFallback: error.toString(),
      );
    }

    return SyncLocalFailure(
      disposition: SyncLocalFailureDisposition.blocked,
      code: 'LOCAL_COMMAND_ERROR',
      displayFallback: error.toString(),
    );
  }
}

abstract final class SyncReconciliationCode {
  static const blockedEvidence = 'SYNC_BLOCKED_EVIDENCE';
  static const pendingSensitiveEvidence = 'SYNC_PENDING_SENSITIVE_EVIDENCE';
  static const pendingVisitEvidence = 'SYNC_PENDING_VISIT_EVIDENCE';
  static const invalidAuthoritativeProjection =
      'SYNC_AUTHORITATIVE_RESPONSE_INVALID';
  static const commandAppearedDuringRefresh =
      'SYNC_COMMAND_APPEARED_DURING_REFRESH';
}

class SyncReconciliationException implements Exception {
  const SyncReconciliationException(this.code);

  final String code;

  @override
  String toString() => 'SyncReconciliationException($code)';
}
