import 'package:flutter/widgets.dart';

import '../../../../l10n/generated/app_localizations.dart';

enum VisitListStringKey {
  title,
  refreshTooltip,
  normalRouteTab,
  emergencyRouteTab,
  filterAll,
  filterCompleted,
  filterPending,
  statusCompleted,
  statusPending,
  statusAttempted,
  statusPostponed,
  statusNoSale,
  statusUnknown,
  balanceLabel,
  mapTooltip,
  emptyNormalAll,
  emptyEmergencyAll,
  emptyNormalPending,
  emptyEmergencyPending,
  emptyNormalCompleted,
  emptyEmergencyCompleted,
  addShopTooltip,
  gateOnBreak,
  gateUnauthorizedAdd,
  gateUnauthorizedOpen,
  gateUnavailable,
  refreshSuccess,
  refreshAlreadySyncing,
  refreshTransportAmbiguous,
  refreshBlocked,
  refreshDeterministicFailure,
  loadFailure,
  retry,
  mapNoLocation,
  mapNoApplication,
  mapInvalidLink,
  mapOpenFailed,
  requestIdLabel,
  routeOverview,
  nextLabel,
  urgentLabel,
  openVisitHint,
}

String visitListString(
  VisitListStringKey key, {
  String localeCode = 'ar',
  Map<String, Object> values = const <String, Object>{},
}) {
  final languageCode = localeCode.split(RegExp('[-_]')).first.toLowerCase();
  final l10n = lookupAppLocalizations(Locale(languageCode));
  String value(String name) => values[name]?.toString() ?? '';

  return switch (key) {
    VisitListStringKey.title => l10n.visitListTitle,
    VisitListStringKey.refreshTooltip => l10n.visitRefreshTooltip,
    VisitListStringKey.normalRouteTab => l10n.visitNormalRouteTab,
    VisitListStringKey.emergencyRouteTab => l10n.visitEmergencyRouteTab,
    VisitListStringKey.filterAll => l10n.visitFilterAll(value('count')),
    VisitListStringKey.filterCompleted => l10n.visitFilterCompleted(
      value('count'),
    ),
    VisitListStringKey.filterPending => l10n.visitFilterPending(value('count')),
    VisitListStringKey.statusCompleted => l10n.visitStatusCompleted,
    VisitListStringKey.statusPending => l10n.visitStatusPending,
    VisitListStringKey.statusAttempted => l10n.visitStatusAttempted,
    VisitListStringKey.statusPostponed => l10n.visitStatusPostponed,
    VisitListStringKey.statusNoSale => l10n.visitStatusNoSale,
    VisitListStringKey.statusUnknown => l10n.visitStatusUnknown(
      value('status'),
    ),
    VisitListStringKey.balanceLabel => l10n.visitBalanceLabel(value('amount')),
    VisitListStringKey.mapTooltip => l10n.visitMapTooltip,
    VisitListStringKey.emptyNormalAll => l10n.visitEmptyNormalAll,
    VisitListStringKey.emptyEmergencyAll => l10n.visitEmptyEmergencyAll,
    VisitListStringKey.emptyNormalPending => l10n.visitEmptyNormalPending,
    VisitListStringKey.emptyEmergencyPending => l10n.visitEmptyEmergencyPending,
    VisitListStringKey.emptyNormalCompleted => l10n.visitEmptyNormalCompleted,
    VisitListStringKey.emptyEmergencyCompleted =>
      l10n.visitEmptyEmergencyCompleted,
    VisitListStringKey.addShopTooltip => l10n.visitAddShopAction,
    VisitListStringKey.gateOnBreak => l10n.visitGateOnBreak,
    VisitListStringKey.gateUnauthorizedAdd => l10n.visitGateUnauthorizedAdd,
    VisitListStringKey.gateUnauthorizedOpen => l10n.visitGateUnauthorizedOpen,
    VisitListStringKey.gateUnavailable => l10n.visitGateUnavailable,
    VisitListStringKey.refreshSuccess => l10n.visitRefreshSuccess,
    VisitListStringKey.refreshAlreadySyncing => l10n.visitRefreshAlreadySyncing,
    VisitListStringKey.refreshTransportAmbiguous =>
      l10n.visitRefreshTransportAmbiguous,
    VisitListStringKey.refreshBlocked => l10n.visitRefreshBlocked,
    VisitListStringKey.refreshDeterministicFailure =>
      l10n.visitRefreshDeterministicFailure,
    VisitListStringKey.loadFailure => l10n.visitLoadFailure,
    VisitListStringKey.retry => l10n.retry,
    VisitListStringKey.mapNoLocation => l10n.visitMapNoLocation,
    VisitListStringKey.mapNoApplication => l10n.visitMapNoApplication,
    VisitListStringKey.mapInvalidLink => l10n.visitMapInvalidLink,
    VisitListStringKey.mapOpenFailed => l10n.visitMapOpenFailed,
    VisitListStringKey.requestIdLabel => l10n.visitRequestIdLabel,
    VisitListStringKey.routeOverview => l10n.visitRouteOverview(
      value('total'),
      value('completed'),
      value('pending'),
    ),
    VisitListStringKey.nextLabel => l10n.visitNextLabel,
    VisitListStringKey.urgentLabel => l10n.visitUrgentLabel,
    VisitListStringKey.openVisitHint => l10n.visitOpenVisitHint,
  };
}
