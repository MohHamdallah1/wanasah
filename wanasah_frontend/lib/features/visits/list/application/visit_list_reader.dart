import '../../../../models/visit_model.dart';
import '../data/visit_list_data_source.dart';
import 'visit_list_filter.dart';
import 'visit_list_read_model.dart';

class VisitListReader {
  VisitListReader({
    required VisitListDataSource dataSource,
  }) : _dataSource = dataSource;

  final VisitListDataSource _dataSource;

  Future<VisitListReadModel> read({
    VisitListFilter filter = VisitListFilter.all,
  }) async {
    final visits = await _dataSource.readVisits();
    visits.sort((left, right) {
      final sequence = left.sequence.compareTo(right.sequence);
      if (sequence != 0) return sequence;
      return left.id.compareTo(right.id);
    });

    return VisitListReadModel(
      orderedRows: List<VisitListRow>.unmodifiable(
        visits.map(_toRow),
      ),
      filter: filter,
    );
  }

  VisitListRow _toRow(VisitModel visit) {
    final normalizedStatus = visit.status.trim().toLowerCase();
    final normalizedOutcome = visit.outcome.trim().toLowerCase();

    final presentation = switch (normalizedStatus) {
      'completed' => VisitExecutionPresentation.completed,
      'pending' when normalizedOutcome == 'postponed' =>
        VisitExecutionPresentation.postponed,
      'pending' when normalizedOutcome.isNotEmpty =>
        VisitExecutionPresentation.attempted,
      'pending' => VisitExecutionPresentation.pending,
      _ => VisitExecutionPresentation.other,
    };

    return VisitListRow(
      visit: visit,
      routeKind:
          visit.isEmergency
              ? VisitRouteKind.emergency
              : VisitRouteKind.normal,
      presentation: presentation,
    );
  }
}
