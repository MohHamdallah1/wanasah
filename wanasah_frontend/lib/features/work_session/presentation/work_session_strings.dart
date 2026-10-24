import 'package:flutter/widgets.dart';

import '../../../l10n/generated/app_localizations.dart';

enum WorkSessionStringKey {
  startSuccess,
  endSuccess,
  breakStartSuccess,
  breakEndSuccess,
  startReconciled,
  endReconciled,
  breakStartReconciled,
  breakEndReconciled,
  unresolved,
  authRejected,
  businessRejected,
  rateLimited,
  networkUnresolved,
  timeoutUnresolved,
  serverUnresolved,
  requestIdLabel,
  statusCodeLabel,
  serverDetailLabel,
  issueAuthentication,
  issueInvalidStartEvidence,
  issueVehicleCustody,
  issueStartPrerequisite,
  issueEndPrerequisite,
  issueBreakState,
  issueRateLimited,
  issueConnectivity,
  issueTimeout,
  issueUnresolved,
}

String workSessionString(
  WorkSessionStringKey key, {
  String localeCode = 'ar',
}) {
  final languageCode = localeCode.split(RegExp('[-_]')).first.toLowerCase();
  final l10n = lookupAppLocalizations(Locale(languageCode));
  return switch (key) {
    WorkSessionStringKey.startSuccess => l10n.workSessionStartSuccess,
    WorkSessionStringKey.endSuccess => l10n.workSessionEndSuccess,
    WorkSessionStringKey.breakStartSuccess => l10n.workSessionBreakStartSuccess,
    WorkSessionStringKey.breakEndSuccess => l10n.workSessionBreakEndSuccess,
    WorkSessionStringKey.startReconciled => l10n.workSessionStartReconciled,
    WorkSessionStringKey.endReconciled => l10n.workSessionEndReconciled,
    WorkSessionStringKey.breakStartReconciled => l10n.workSessionBreakStartReconciled,
    WorkSessionStringKey.breakEndReconciled => l10n.workSessionBreakEndReconciled,
    WorkSessionStringKey.unresolved => l10n.workSessionUnresolved,
    WorkSessionStringKey.authRejected => l10n.workSessionAuthRejected,
    WorkSessionStringKey.businessRejected => l10n.workSessionBusinessRejected,
    WorkSessionStringKey.rateLimited => l10n.workSessionRateLimited,
    WorkSessionStringKey.networkUnresolved => l10n.workSessionNetworkUnresolved,
    WorkSessionStringKey.timeoutUnresolved => l10n.workSessionTimeoutUnresolved,
    WorkSessionStringKey.serverUnresolved => l10n.workSessionServerUnresolved,
    WorkSessionStringKey.requestIdLabel => l10n.workSessionRequestIdLabel,
    WorkSessionStringKey.statusCodeLabel => l10n.workSessionStatusCodeLabel,
    WorkSessionStringKey.serverDetailLabel => l10n.workSessionServerDetailLabel,
    WorkSessionStringKey.issueAuthentication => l10n.workSessionIssueAuthentication,
    WorkSessionStringKey.issueInvalidStartEvidence => l10n.workSessionIssueInvalidStartEvidence,
    WorkSessionStringKey.issueVehicleCustody => l10n.workSessionIssueVehicleCustody,
    WorkSessionStringKey.issueStartPrerequisite => l10n.workSessionIssueStartPrerequisite,
    WorkSessionStringKey.issueEndPrerequisite => l10n.workSessionIssueEndPrerequisite,
    WorkSessionStringKey.issueBreakState => l10n.workSessionIssueBreakState,
    WorkSessionStringKey.issueRateLimited => l10n.workSessionIssueRateLimited,
    WorkSessionStringKey.issueConnectivity => l10n.workSessionIssueConnectivity,
    WorkSessionStringKey.issueTimeout => l10n.workSessionIssueTimeout,
    WorkSessionStringKey.issueUnresolved => l10n.workSessionIssueUnresolved,
  };
}
