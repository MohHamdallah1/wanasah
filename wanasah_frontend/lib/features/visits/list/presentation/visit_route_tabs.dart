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
  Size get preferredSize => const Size.fromHeight(48);

  @override
  Widget build(BuildContext context) {
    final locale = Localizations.localeOf(context).toLanguageTag();
    return TabBar(
      controller: controller,
      labelColor: const Color.fromARGB(255, 17, 5, 5),
      unselectedLabelColor: const Color.fromARGB(179, 14, 7, 7),
      indicatorColor: const Color.fromARGB(255, 73, 16, 16),
      indicatorWeight: 4,
      labelStyle: const TextStyle(
        fontWeight: FontWeight.bold,
        fontSize: 15,
      ),
      tabs: [
        Tab(
          text: visitListString(
            VisitListStringKey.normalRouteTab,
            localeCode: locale,
          ),
        ),
        Tab(
          text: visitListString(
            VisitListStringKey.emergencyRouteTab,
            localeCode: locale,
            values: <String, Object>{'count': emergencyCount},
          ),
        ),
      ],
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

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        VisitListSummary(
          counts: model.countsFor(activeRoute),
          filter: model.filter,
          onFilterChanged: onFilterChanged,
        ),
        const Divider(height: 1, thickness: 1),
        Expanded(
          child: TabBarView(
            controller: controller,
            children: [
              _VisitRouteList(
                rows: model.rowsFor(VisitRouteKind.normal),
                routeKind: VisitRouteKind.normal,
                filter: model.filter,
                onRefresh: onRefresh,
                onOpenVisit: onOpenVisit,
                onOpenMap: onOpenMap,
              ),
              _VisitRouteList(
                rows: model.rowsFor(VisitRouteKind.emergency),
                routeKind: VisitRouteKind.emergency,
                filter: model.filter,
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
    required this.onRefresh,
    required this.onOpenVisit,
    required this.onOpenMap,
  });

  final List<VisitListRow> rows;
  final VisitRouteKind routeKind;
  final VisitListFilter filter;
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
        padding: const EdgeInsets.only(
          top: 12,
          left: 12,
          right: 12,
          bottom: 80,
        ),
        itemCount: rows.length,
        itemBuilder: (context, index) {
          final row = rows[index];
          return VisitCard(
            row: row,
            onOpen: () => onOpenVisit(row),
            onMap: () => onOpenMap(row),
          );
        },
      ),
    );
  }
}
