import '../application/work_session_failure.dart';
import '../application/work_session_outcome.dart';
import 'work_session_strings.dart';

String workSessionResultMessage(
  WorkSessionOperationResult result, {
  String localeCode = 'ar',
}) {
  String text(WorkSessionStringKey key) =>
      workSessionString(key, localeCode: localeCode);

  if (result.disposition == WorkSessionDisposition.success) {
    switch (result.operation) {
      case WorkSessionOperation.start:
        return text(WorkSessionStringKey.startSuccess);
      case WorkSessionOperation.end:
        return text(WorkSessionStringKey.endSuccess);
      case WorkSessionOperation.startBreak:
        return text(WorkSessionStringKey.breakStartSuccess);
      case WorkSessionOperation.endBreak:
        return text(WorkSessionStringKey.breakEndSuccess);
    }
  }

  if (result.disposition == WorkSessionDisposition.reconciledSuccess) {
    switch (result.operation) {
      case WorkSessionOperation.start:
        return text(WorkSessionStringKey.startReconciled);
      case WorkSessionOperation.end:
        return text(WorkSessionStringKey.endReconciled);
      case WorkSessionOperation.startBreak:
        return text(WorkSessionStringKey.breakStartReconciled);
      case WorkSessionOperation.endBreak:
        return text(WorkSessionStringKey.breakEndReconciled);
    }
  }

  final failure = result.failure;
  if (failure == null) {
    return text(WorkSessionStringKey.unresolved);
  }

  switch (failure.kind) {
    case WorkSessionFailureKind.authRejected:
      return _withRequestId(
        text(WorkSessionStringKey.authRejected),
        failure.requestId,
        localeCode,
      );
    case WorkSessionFailureKind.businessRejected:
      return _withRequestId(
        failure.displayFallback ?? text(WorkSessionStringKey.businessRejected),
        failure.requestId,
        localeCode,
      );
    case WorkSessionFailureKind.rateLimited:
      return _withRequestId(
        text(WorkSessionStringKey.rateLimited),
        failure.requestId,
        localeCode,
      );
    case WorkSessionFailureKind.network:
      return _withRequestId(
        text(WorkSessionStringKey.networkUnresolved),
        failure.requestId,
        localeCode,
      );
    case WorkSessionFailureKind.server:
      return _withRequestId(
        text(WorkSessionStringKey.serverUnresolved),
        failure.requestId,
        localeCode,
      );
    case WorkSessionFailureKind.unknown:
      return _withRequestId(
        text(WorkSessionStringKey.unresolved),
        failure.requestId,
        localeCode,
      );
  }
}

String _withRequestId(
  String message,
  String? requestId,
  String localeCode,
) {
  if (requestId == null || requestId.isEmpty) return message;
  final label = workSessionString(
    WorkSessionStringKey.requestIdLabel,
    localeCode: localeCode,
  );
  return '$message\n$label: $requestId';
}
