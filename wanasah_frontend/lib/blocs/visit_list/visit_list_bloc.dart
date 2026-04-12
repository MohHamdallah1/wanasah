import 'package:flutter_bloc/flutter_bloc.dart';
import 'dart:developer' as developer;

import '../../core/db/local_database.dart';
import '../../models/visit_model.dart';
import 'visit_list_event.dart';
import 'visit_list_state.dart';

class VisitListBloc extends Bloc<VisitListEvent, VisitListState> {
  final LocalDatabase _db;

  VisitListBloc({LocalDatabase? db})
    : _db = db ?? LocalDatabase.instance,
      super(VisitListLoading()) {
    on<LoadVisitsEvent>(_onLoadVisits);
    on<FilterVisitsEvent>(_onFilterVisits);
  }

  Future<void> _onLoadVisits(
    LoadVisitsEvent event,
    Emitter<VisitListState> emit,
  ) async {
    emit(VisitListLoading());
    try {
      // +++ الكيّ الجراحي: تحويل البيانات الخام (Maps) إلى كائنات محمية (VisitModel) +++
      final List<Map<String, dynamic>> rawVisits = await _db.getVisits();
      final List<VisitModel> visits =
          rawVisits.map((v) => VisitModel.fromJson(v)).toList();

      // الترتيب الافتراضي حسب الـ sequence الذي أضفناه سابقاً
      visits.sort((a, b) => a.sequence.compareTo(b.sequence));

      emit(
        VisitListLoaded(
          allVisits: visits,
          filteredVisits: visits,
          currentFilter: 'All',
        ),
      );
    } catch (e) {
      developer.log('[VisitListBloc] Error loading visits: $e');
      emit(const VisitListError('حدث خطأ أثناء تحميل خط السير.'));
    }
  }

  void _onFilterVisits(FilterVisitsEvent event, Emitter<VisitListState> emit) {
    if (state is! VisitListLoaded) return;

    final currentState = state as VisitListLoaded;
    List<VisitModel> filtered;

    if (event.status == 'All') {
      filtered = currentState.allVisits;
    } else {
      filtered =
          currentState.allVisits
              .where((v) => v.status == event.status)
              .toList();
    }

    emit(
      VisitListLoaded(
        allVisits: currentState.allVisits,
        filteredVisits: filtered,
        currentFilter: event.status,
      ),
    );
  }
}
