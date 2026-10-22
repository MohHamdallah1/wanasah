import 'dart:developer' as developer;

import 'package:flutter_bloc/flutter_bloc.dart';

import '../../features/visits/list/application/visit_list_filter.dart';
import '../../features/visits/list/application/visit_list_reader.dart';
import '../../features/visits/list/application/visit_list_refresh.dart';
import '../../features/visits/list/data/visit_list_data_source.dart';
import '../../features/visits/list/data/visit_list_refresh_source.dart';
import 'visit_list_event.dart';
import 'visit_list_state.dart';

class VisitListBloc extends Bloc<VisitListEvent, VisitListState> {
  VisitListBloc({
    VisitListReader? reader,
    VisitListRefreshCoordinator? refreshCoordinator,
  }) : _reader =
           reader ??
           VisitListReader(
             dataSource: LocalVisitListDataSource(),
           ),
       _refreshCoordinator =
           refreshCoordinator ??
           VisitListRefreshCoordinator(
             source: CompatibilityVisitListRefreshSource(),
           ),
       super(const VisitListLoading()) {
    on<LoadVisitsEvent>(_onLoadVisits, transformer: _sequential());
    on<FilterVisitsEvent>(_onFilterVisits, transformer: _sequential());
    on<RefreshVisitsEvent>(_onRefreshVisits, transformer: _sequential());
  }

  final VisitListReader _reader;
  final VisitListRefreshCoordinator _refreshCoordinator;

  EventTransformer<T> _sequential<T>() {
    return (events, mapper) => events.asyncExpand(mapper);
  }

  VisitListFilter get _currentFilter {
    final current = state;
    return current is VisitListLoaded
        ? current.model.filter
        : VisitListFilter.all;
  }

  Future<void> _onLoadVisits(
    LoadVisitsEvent event,
    Emitter<VisitListState> emit,
  ) async {
    if (state is! VisitListLoaded) {
      emit(const VisitListLoading());
    }
    await _loadVisitsInternal(
      emit,
      filter: _currentFilter,
    );
  }

  Future<void> _onRefreshVisits(
    RefreshVisitsEvent event,
    Emitter<VisitListState> emit,
  ) async {
    final filter = _currentFilter;
    try {
      final result = await _refreshCoordinator.refresh();
      final model = await _reader.read(filter: filter);
      emit(
        VisitListLoaded(
          model: model,
          refreshResult: result,
        ),
      );
    } catch (error) {
      developer.log('[VisitListBloc] Refresh reload failed: $error');
      emit(VisitListError(VisitListLoadFailure.localRead));
    } finally {
      final completion = event.completion;
      if (completion != null && !completion.isCompleted) {
        completion.complete();
      }
    }
  }

  Future<void> _loadVisitsInternal(
    Emitter<VisitListState> emit, {
    required VisitListFilter filter,
  }) async {
    try {
      emit(
        VisitListLoaded(
          model: await _reader.read(filter: filter),
        ),
      );
    } catch (error) {
      developer.log('[VisitListBloc] Local visit read failed: $error');
      emit(VisitListError(VisitListLoadFailure.localRead));
    }
  }

  void _onFilterVisits(
    FilterVisitsEvent event,
    Emitter<VisitListState> emit,
  ) {
    final current = state;
    if (current is! VisitListLoaded) return;

    emit(
      VisitListLoaded(
        model: current.model.withFilter(event.filter),
      ),
    );
  }
}
