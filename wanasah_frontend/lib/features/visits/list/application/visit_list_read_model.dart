import '../../../../models/visit_model.dart';
import 'visit_list_filter.dart';

enum VisitRouteKind {
  normal,
  emergency,
}

enum VisitExecutionPresentation {
  completed,
  pending,
  attempted,
  postponed,
  other,
}

class VisitListRow {
  const VisitListRow({
    required this.visit,
    required this.routeKind,
    required this.presentation,
  });

  final VisitModel visit;
  final VisitRouteKind routeKind;
  final VisitExecutionPresentation presentation;

  int get id => visit.id;
  int get sequence => visit.sequence;
  String get shopName => visit.shopName;
  double get shopBalance => visit.shopBalance;
  String get backendStatus => visit.status;
  String get backendOutcome => visit.outcome;
  bool get isEmergency => routeKind == VisitRouteKind.emergency;
  bool get isCompleted =>
      presentation == VisitExecutionPresentation.completed;
  bool get isAttempted =>
      presentation == VisitExecutionPresentation.attempted ||
      presentation == VisitExecutionPresentation.postponed;
}

class VisitRouteCounts {
  const VisitRouteCounts({
    required this.total,
    required this.completed,
    required this.pending,
  });

  final int total;
  final int completed;
  final int pending;
}

class VisitListReadModel {
  const VisitListReadModel({
    required this.orderedRows,
    required this.filter,
  });

  final List<VisitListRow> orderedRows;
  final VisitListFilter filter;

  List<VisitListRow> rowsFor(VisitRouteKind route) {
    return List<VisitListRow>.unmodifiable(
      orderedRows.where(
        (row) =>
            row.routeKind == route &&
            _matchesFilter(row, filter),
      ),
    );
  }

  VisitRouteCounts countsFor(VisitRouteKind route) {
    final routeRows = orderedRows.where((row) => row.routeKind == route);
    return VisitRouteCounts(
      total: routeRows.length,
      completed:
          routeRows
              .where(
                (row) =>
                    row.backendStatus.toLowerCase() == 'completed',
              )
              .length,
      pending:
          routeRows
              .where(
                (row) => row.backendStatus.toLowerCase() == 'pending',
              )
              .length,
    );
  }

  int get emergencyCount =>
      orderedRows
          .where((row) => row.routeKind == VisitRouteKind.emergency)
          .length;

  VisitListReadModel withFilter(VisitListFilter nextFilter) {
    return VisitListReadModel(
      orderedRows: orderedRows,
      filter: nextFilter,
    );
  }

  static bool _matchesFilter(
    VisitListRow row,
    VisitListFilter filter,
  ) {
    switch (filter) {
      case VisitListFilter.all:
        return true;
      case VisitListFilter.completed:
        return row.backendStatus.toLowerCase() == 'completed';
      case VisitListFilter.pending:
        return row.backendStatus.toLowerCase() == 'pending';
    }
  }
}
