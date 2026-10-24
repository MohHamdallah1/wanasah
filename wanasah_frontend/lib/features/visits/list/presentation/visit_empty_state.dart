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
    final colors = Theme.of(context).colorScheme;
    final emergency = routeKind == VisitRouteKind.emergency;

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsetsDirectional.fromSTEB(24, 72, 24, 120),
        children: [
          Center(
            child: Column(
              children: [
                Container(
                  width: 54,
                  height: 54,
                  decoration: BoxDecoration(
                    color:
                        emergency
                            ? colors.errorContainer.withValues(alpha: 0.72)
                            : colors.surfaceContainerHigh,
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: Icon(
                    emergency
                        ? Icons.priority_high_rounded
                        : Icons.route_outlined,
                    color:
                        emergency
                            ? colors.onErrorContainer
                            : colors.onSurfaceVariant,
                  ),
                ),
                const SizedBox(height: 14),
                Text(
                  visitListString(_messageKey(), localeCode: locale),
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(
                    color: colors.onSurfaceVariant,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
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
