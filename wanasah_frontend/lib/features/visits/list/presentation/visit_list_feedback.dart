import 'package:flutter/material.dart';

import '../application/visit_list_refresh.dart';
import '../application/visit_route_action_gate.dart';
import 'visit_list_strings.dart';
import 'visit_map_launcher.dart';

void showVisitListRefreshFeedback(
  BuildContext context,
  VisitListRefreshResult result,
) {
  final locale = Localizations.localeOf(context).toLanguageTag();
  final (key, color) = switch (result.outcome) {
    VisitListRefreshOutcome.refreshed => (
      VisitListStringKey.refreshSuccess,
      Colors.green,
    ),
    VisitListRefreshOutcome.alreadySyncing => (
      VisitListStringKey.refreshAlreadySyncing,
      Colors.orange,
    ),
    VisitListRefreshOutcome.transportAmbiguous => (
      VisitListStringKey.refreshTransportAmbiguous,
      Colors.orange,
    ),
    VisitListRefreshOutcome.blockedByUnresolvedDurableWork => (
      VisitListStringKey.refreshBlocked,
      Colors.orange,
    ),
    VisitListRefreshOutcome.deterministicFailure => (
      VisitListStringKey.refreshDeterministicFailure,
      Colors.red,
    ),
  };

  var message = result.displayFallback;
  if (result.outcome != VisitListRefreshOutcome.deterministicFailure ||
      message == null ||
      message.trim().isEmpty) {
    message = visitListString(key, localeCode: locale);
  }

  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(message),
      backgroundColor: color,
      duration: const Duration(seconds: 4),
    ),
  );
}

void showVisitRouteGateFeedback(
  BuildContext context, {
  required VisitRouteAction action,
  required VisitRouteActionDecision decision,
}) {
  if (decision == VisitRouteActionDecision.allowed) return;

  final locale = Localizations.localeOf(context).toLanguageTag();
  final key = switch (decision) {
    VisitRouteActionDecision.onBreak =>
      VisitListStringKey.gateOnBreak,
    VisitRouteActionDecision.unauthorized =>
      action == VisitRouteAction.addShop
          ? VisitListStringKey.gateUnauthorizedAdd
          : VisitListStringKey.gateUnauthorizedOpen,
    VisitRouteActionDecision.unavailable =>
      VisitListStringKey.gateUnavailable,
    VisitRouteActionDecision.allowed =>
      VisitListStringKey.gateUnavailable,
  };

  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(visitListString(key, localeCode: locale)),
      backgroundColor: Colors.orange,
    ),
  );
}

void showVisitMapFeedback(
  BuildContext context,
  VisitMapLaunchOutcome outcome,
) {
  if (outcome == VisitMapLaunchOutcome.opened) return;

  final locale = Localizations.localeOf(context).toLanguageTag();
  final key = switch (outcome) {
    VisitMapLaunchOutcome.noLocation =>
      VisitListStringKey.mapNoLocation,
    VisitMapLaunchOutcome.noMapApplication =>
      VisitListStringKey.mapNoApplication,
    VisitMapLaunchOutcome.invalidLink =>
      VisitListStringKey.mapInvalidLink,
    VisitMapLaunchOutcome.failed => VisitListStringKey.mapOpenFailed,
    VisitMapLaunchOutcome.opened => VisitListStringKey.mapOpenFailed,
  };

  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(
      content: Text(visitListString(key, localeCode: locale)),
      backgroundColor: Colors.orange,
    ),
  );
}
