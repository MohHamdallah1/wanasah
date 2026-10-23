import 'work_session_failure.dart';
import 'work_session_outcome.dart';

enum WorkSessionActionIssueKind {
  authenticationRequired,
  invalidStartEvidence,
  vehicleCustodyPrerequisite,
  startPrerequisite,
  endPrerequisite,
  breakStateConflict,
  rateLimited,
  connectivity,
  timeout,
  unresolved,
}

class WorkSessionActionIssue {
  WorkSessionActionIssue({
    required this.operation,
    required this.kind,
    required this.status,
    required this.code,
    required Map<String, dynamic> context,
    required this.requestId,
    required this.displayFallback,
  }) : context = Map<String, dynamic>.unmodifiable(context);

  final WorkSessionOperation operation;
  final WorkSessionActionIssueKind kind;
  final int? status;
  final String? code;
  final Map<String, dynamic> context;
  final String? requestId;

  /// Display-only evidence. Never used for classification.
  final String? displayFallback;

  bool get isBusinessRefusal =>
      kind == WorkSessionActionIssueKind.invalidStartEvidence ||
      kind == WorkSessionActionIssueKind.vehicleCustodyPrerequisite ||
      kind == WorkSessionActionIssueKind.startPrerequisite ||
      kind == WorkSessionActionIssueKind.endPrerequisite ||
      kind == WorkSessionActionIssueKind.breakStateConflict;

  factory WorkSessionActionIssue.fromResult(
    WorkSessionOperationResult result,
  ) {
    if (result.isSuccess) {
      throw ArgumentError(
        'Successful Work Session results do not have an action issue.',
      );
    }

    final failure = result.failure ?? const WorkSessionFailure.unknown();

    return WorkSessionActionIssue(
      operation: result.operation,
      kind: _kindFor(result.operation, failure),
      status: failure.status,
      code: failure.code,
      context: failure.context,
      requestId: failure.requestId,
      displayFallback:
          failure.kind == WorkSessionFailureKind.businessRejected
              ? failure.displayFallback
              : null,
    );
  }

  static WorkSessionActionIssueKind _kindFor(
    WorkSessionOperation operation,
    WorkSessionFailure failure,
  ) {
    switch (failure.kind) {
      case WorkSessionFailureKind.authRejected:
        return WorkSessionActionIssueKind.authenticationRequired;
      case WorkSessionFailureKind.rateLimited:
        return WorkSessionActionIssueKind.rateLimited;
      case WorkSessionFailureKind.businessRejected:
        return _businessKindFor(operation, failure);
      case WorkSessionFailureKind.connectivity:
        return WorkSessionActionIssueKind.connectivity;
      case WorkSessionFailureKind.timeout:
        return WorkSessionActionIssueKind.timeout;
      case WorkSessionFailureKind.network:
      case WorkSessionFailureKind.server:
      case WorkSessionFailureKind.unknown:
        return WorkSessionActionIssueKind.unresolved;
    }
  }

  static WorkSessionActionIssueKind _businessKindFor(
    WorkSessionOperation operation,
    WorkSessionFailure failure,
  ) {
    switch (operation) {
      case WorkSessionOperation.start:
        if (failure.status == 422 || failure.code == 'VALIDATION_ERROR') {
          return WorkSessionActionIssueKind.invalidStartEvidence;
        }

        final code = failure.code ?? '';
        if (code.startsWith('VEHICLE_CUSTODY_')) {
          return WorkSessionActionIssueKind.vehicleCustodyPrerequisite;
        }

        return WorkSessionActionIssueKind.startPrerequisite;
      case WorkSessionOperation.end:
        return WorkSessionActionIssueKind.endPrerequisite;
      case WorkSessionOperation.startBreak:
      case WorkSessionOperation.endBreak:
        return WorkSessionActionIssueKind.breakStateConflict;
    }
  }
}
