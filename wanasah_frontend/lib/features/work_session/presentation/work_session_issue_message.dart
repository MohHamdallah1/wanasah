import '../application/work_session_action_issue.dart';
import 'work_session_strings.dart';

String workSessionIssueMessage(
  WorkSessionActionIssue issue, {
  String localeCode = 'ar',
}) {
  String text(WorkSessionStringKey key) =>
      workSessionString(key, localeCode: localeCode);

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

  final parts = <String>[text(key)];

  if (issue.isBusinessRefusal &&
      issue.displayFallback != null &&
      issue.displayFallback!.trim().isNotEmpty) {
    parts.add(
      '${text(WorkSessionStringKey.serverDetailLabel)}: '
      '${issue.displayFallback!.trim()}',
    );
  }

  if (issue.code != null && issue.code!.trim().isNotEmpty) {
    parts.add(
      '${text(WorkSessionStringKey.statusCodeLabel)}: '
      '${issue.code!.trim()}',
    );
  }

  if (issue.requestId != null && issue.requestId!.trim().isNotEmpty) {
    parts.add(
      '${text(WorkSessionStringKey.requestIdLabel)}: '
      '${issue.requestId!.trim()}',
    );
  }

  return parts.join('\n');
}
