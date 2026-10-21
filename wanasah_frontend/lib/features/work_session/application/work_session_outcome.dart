import '../data/work_session_snapshot.dart';
import 'work_session_failure.dart';

enum WorkSessionOperation {
  start,
  end,
  startBreak,
  endBreak,
}

enum WorkSessionDisposition {
  success,
  reconciledSuccess,
  rejected,
  unresolved,
}

class WorkSessionOperationResult {
  const WorkSessionOperationResult({
    required this.operation,
    required this.disposition,
    this.failure,
    this.reconciledSession,
    this.reconciliationFailure,
  });

  final WorkSessionOperation operation;
  final WorkSessionDisposition disposition;
  final WorkSessionFailure? failure;
  final WorkSessionSnapshot? reconciledSession;
  final WorkSessionFailure? reconciliationFailure;

  bool get isSuccess =>
      disposition == WorkSessionDisposition.success ||
      disposition == WorkSessionDisposition.reconciledSuccess;
}

class WorkSessionRecoveryResult {
  const WorkSessionRecoveryResult.success(this.session) : failure = null;

  const WorkSessionRecoveryResult.failure(this.failure) : session = null;

  final WorkSessionSnapshot? session;
  final WorkSessionFailure? failure;

  bool get succeeded => failure == null && session != null;
}
