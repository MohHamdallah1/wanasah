import '../application/work_session_action_issue.dart';
import 'work_session_strings.dart';

String workSessionIssueMessage(
  WorkSessionActionIssue issue, {
  String localeCode = 'ar',
}) {
  String text(WorkSessionStringKey key) =>
      workSessionString(key, localeCode: localeCode);

  if (issue.isBusinessRefusal &&
      issue.displayFallback != null &&
      issue.displayFallback!.trim().isNotEmpty) {
    return issue.displayFallback!.trim();
  }

  final key = switch (issue.kind) {
    WorkSessionActionIssueKind.authenticationRequired =>
      WorkSessionStringKey.issueAuthentication,
    WorkSessionActionIssueKind.invalidStartEvidence =>
      WorkSessionStringKey.issueInvalidStartEvidence,
    WorkSessionActionIssueKind.vehicleCustodyPrerequisite =>
      WorkSessionStringKey.issueVehicleCustody,
    WorkSessionActionIssueKind.startPrerequisite =>
      WorkSessionStringKey.issueStartPrerequisite,
    WorkSessionActionIssueKind.endPrerequisite =>
      WorkSessionStringKey.issueEndPrerequisite,
    WorkSessionActionIssueKind.breakStateConflict =>
      WorkSessionStringKey.issueBreakState,
    WorkSessionActionIssueKind.rateLimited =>
      WorkSessionStringKey.issueRateLimited,
    WorkSessionActionIssueKind.connectivity =>
      WorkSessionStringKey.issueConnectivity,
    WorkSessionActionIssueKind.timeout =>
      WorkSessionStringKey.issueTimeout,
    WorkSessionActionIssueKind.unresolved =>
      WorkSessionStringKey.issueUnresolved,
  };

  return text(key);
}

/// Support/observability detail. Never render this string directly to operators.
String workSessionIssueDiagnosticMessage(
  WorkSessionActionIssue issue, {
  String localeCode = 'ar',
}) {
  final visible = workSessionIssueMessage(issue, localeCode: localeCode);
  final parts = <String>[visible];

  if (issue.code != null && issue.code!.trim().isNotEmpty) {
    parts.add('code=${issue.code!.trim()}');
  }
  if (issue.requestId != null && issue.requestId!.trim().isNotEmpty) {
    parts.add('request_id=${issue.requestId!.trim()}');
  }

  return parts.join(' | ');
}
