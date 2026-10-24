import 'package:flutter/material.dart';

import '../application/visit_list_filter.dart';
import '../application/visit_list_read_model.dart';
import 'visit_card.dart';
import 'visit_empty_state.dart';
import 'visit_list_strings.dart';
import 'visit_list_summary.dart';

class VisitRouteTabBar extends StatelessWidget
    implements PreferredSizeWidget {
  const VisitRouteTabBar({
    required this.controller,
    required this.emergencyCount,
    super.key,
  });

  final TabController controller;
  final int emergencyCount;

  @override
  Size get preferredSize => const Size.fromHeight(52);

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    final colors = Theme.of(context).colorScheme;

    return AnimatedBuilder(
      animation: controller,
      builder:
          (context, _) => Container(
            height: 44,
            padding: const EdgeInsets.all(4),
            decoration: BoxDecoration(
              color: colors.surfaceContainerHigh.withValues(alpha: 0.72),
              borderRadius: BorderRadius.circular(18),
              border: Border.all(
                color: colors.outlineVariant.withValues(alpha: 0.72),
              ),
            ),
            child: Row(
              children: [
                Expanded(
                  child: _RouteModeButton(
                    selected: controller.index == 0,
                    icon: Icons.route_rounded,
                    label: visitListString(
                      VisitListStringKey.normalRouteTab,
                      localeCode: locale,
                    ),
                    onTap: () => controller.animateTo(0),
                  ),
                ),
                const SizedBox(width: 4),
                Expanded(
                  child: _RouteModeButton(
                    selected: controller.index == 1,
                    icon: Icons.priority_high_rounded,
                    label: visitListString(
                      VisitListStringKey.emergencyRouteTab,
                      localeCode: locale,
                    ),
                    badgeCount: emergencyCount,
                    urgent: true,
                    onTap: () => controller.animateTo(1),
                  ),
                ),
              ],
            ),
          ),
    );
  }
}

class _RouteModeButton extends StatelessWidget {
  const _RouteModeButton({
    required this.selected,
    required this.icon,
    required this.label,
    required this.onTap,
    this.badgeCount,
    this.urgent = false,
  });

  final bool selected;
  final IconData icon;
  final String label;
  final VoidCallback onTap;
  final int? badgeCount;
  final bool urgent;

  @override
  Widget build(BuildContext context) {
    final colors = Theme.of(context).colorScheme;
    final selectedForeground =
        urgent ? colors.onErrorContainer : colors.onPrimaryContainer;
    final selectedBackground =
        urgent ? colors.errorContainer : colors.primaryContainer;
    final foreground =
        selected ? selectedForeground : colors.onSurfaceVariant;

    return InkWell(
      borderRadius: BorderRadius.circular(14),
      onTap: onTap,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        curve: Curves.easeOutCubic,
        decoration: BoxDecoration(
          color: selected ? selectedBackground : Colors.transparent,
          borderRadius: BorderRadius.circular(14),
        ),
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(icon, size: 18, color: foreground),
            const SizedBox(width: 6),
            Flexible(
              child: Text(
                label,
                maxLines: 1,
                overflow: TextOverflow.ellipsis,
                style: Theme.of(context).textTheme.labelLarge?.copyWith(
                  color: foreground,
                  fontWeight: selected ? FontWeight.w800 : FontWeight.w650,
                ),
              ),
            ),
            if ((badgeCount ?? 0) > 0) ...[
              const SizedBox(width: 6),
              Container(
                constraints: const BoxConstraints(minWidth: 20),
                padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                decoration: BoxDecoration(
                  color:
                      selected
                          ? foreground.withValues(alpha: 0.12)
                          : colors.errorContainer,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  badgeCount.toString(),
                  textAlign: TextAlign.center,
                  style: Theme.of(context).textTheme.labelSmall?.copyWith(
                    color:
                        selected
                            ? foreground
                            : colors.onErrorContainer,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}

class VisitRouteTabs extends StatelessWidget {
  const VisitRouteTabs({
    required this.controller,
    required this.model,
    required this.activeRoute,
    required this.onFilterChanged,
    required this.onRefresh,
    required this.onOpenVisit,
    required this.onOpenMap,
    super.key,
  });

  final TabController controller;
  final VisitListReadModel model;
  final VisitRouteKind activeRoute;
  final ValueChanged<VisitListFilter> onFilterChanged;
  final Future<void> Function() onRefresh;
  final ValueChanged<VisitListRow> onOpenVisit;
  final ValueChanged<VisitListRow> onOpenMap;

  int? _nextPendingVisitId() {
    for (final row in model.orderedRows) {
      if (row.routeKind == VisitRouteKind.normal &&
          row.backendStatus.toLowerCase() == 'pending') {
        return row.id;
      }
    }
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final nextPendingVisitId = _nextPendingVisitId();

    return Column(
      children: [
        VisitListSummary(
          counts: model.countsFor(activeRoute),
          filter: model.filter,
          onFilterChanged: onFilterChanged,
        ),
        Expanded(
          child: TabBarView(
            controller: controller,
            children: [
              _VisitRouteList(
                rows: model.rowsFor(VisitRouteKind.normal),
                routeKind: VisitRouteKind.normal,
                filter: model.filter,
                nextVisitId: nextPendingVisitId,
                onRefresh: onRefresh,
                onOpenVisit: onOpenVisit,
                onOpenMap: onOpenMap,
              ),
              _VisitRouteList(
                rows: model.rowsFor(VisitRouteKind.emergency),
                routeKind: VisitRouteKind.emergency,
                filter: model.filter,
                nextVisitId: null,
                onRefresh: onRefresh,
                onOpenVisit: onOpenVisit,
                onOpenMap: onOpenMap,
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _VisitRouteList extends StatelessWidget {
  const _VisitRouteList({
    required this.rows,
    required this.routeKind,
    required this.filter,
    required this.nextVisitId,
    required this.onRefresh,
    required this.onOpenVisit,
    required this.onOpenMap,
  });

  final List<VisitListRow> rows;
  final VisitRouteKind routeKind;
  final VisitListFilter filter;
  final int? nextVisitId;
  final Future<void> Function() onRefresh;
  final ValueChanged<VisitListRow> onOpenVisit;
  final ValueChanged<VisitListRow> onOpenMap;

  @override
  Widget build(BuildContext context) {
    if (rows.isEmpty) {
      return VisitEmptyState(
        routeKind: routeKind,
        filter: filter,
        onRefresh: onRefresh,
      );
    }

    return RefreshIndicator(
      onRefresh: onRefresh,
      child: ListView.builder(
        key: PageStorageKey<String>(
          routeKind == VisitRouteKind.emergency
              ? 'visitListScroll_emg'
              : 'visitListScroll_norm',
        ),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsetsDirectional.fromSTEB(14, 8, 14, 104),
        itemCount: rows.length,
        itemBuilder: (context, index) {
          final row = rows[index];
          return VisitCard(
            row: row,
            isNext: row.id == nextVisitId,
            onOpen: () => onOpenVisit(row),
            onMap: () => onOpenMap(row),
          );
        },
      ),
    );
  }
}
