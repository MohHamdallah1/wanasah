import 'package:equatable/equatable.dart';

import '../../features/visits/list/application/visit_list_read_model.dart';
import '../../features/visits/list/application/visit_list_refresh.dart';

abstract class VisitListState extends Equatable {
  const VisitListState();

  @override
  List<Object?> get props => [];
}

class VisitListLoading extends VisitListState {
  const VisitListLoading();
}

class VisitListLoaded extends VisitListState {
  const VisitListLoaded({
    required this.model,
    this.refreshResult,
  });

  final VisitListReadModel model;
  final VisitListRefreshResult? refreshResult;

  @override
  List<Object?> get props => [model, refreshResult];
}

enum VisitListLoadFailure {
  localRead,
}

class VisitListError extends VisitListState {
  VisitListError(this.failure) : timestamp = DateTime.now();

  final VisitListLoadFailure failure;
  final DateTime timestamp;

  @override
  List<Object?> get props => [failure, timestamp];
}
