import 'package:flutter/material.dart';

import '../application/visit_list_filter.dart';
import '../application/visit_list_read_model.dart';
import 'visit_list_strings.dart';

class VisitEmptyState extends StatelessWidget {
  const VisitEmptyState({
    required this.routeKind,
    required this.filter,
    required this.onRefresh,
    super.key,
  });

  final VisitRouteKind routeKind;
  final VisitListFilter filter;
  final Future<void> Function() onRefresh;

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 50),
            child: Center(
              child: Text(
                visitListString(
                  _messageKey(),
                  localeCode: locale,
                ),
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 16,
                  color: Colors.grey,
                  fontWeight: FontWeight.bold,
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  VisitListStringKey _messageKey() {
    final emergency = routeKind == VisitRouteKind.emergency;
    switch (filter) {
      case VisitListFilter.all:
        return emergency
            ? VisitListStringKey.emptyEmergencyAll
            : VisitListStringKey.emptyNormalAll;
      case VisitListFilter.completed:
        return emergency
            ? VisitListStringKey.emptyEmergencyCompleted
            : VisitListStringKey.emptyNormalCompleted;
      case VisitListFilter.pending:
        return emergency
            ? VisitListStringKey.emptyEmergencyPending
            : VisitListStringKey.emptyNormalPending;
    }
  }
}
