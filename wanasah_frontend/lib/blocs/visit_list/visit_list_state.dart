import 'package:equatable/equatable.dart';
import '../../models/visit_model.dart';

abstract class VisitListState extends Equatable {
  const VisitListState();

  @override
  List<Object?> get props => [];
}

class VisitListLoading extends VisitListState {}

class VisitListLoaded extends VisitListState {
  final List<VisitModel> allVisits;
  final List<VisitModel> filteredVisits;
  final String currentFilter; // 'All', 'Completed', 'Pending'

  const VisitListLoaded({
    required this.allVisits,
    required this.filteredVisits,
    required this.currentFilter,
  });

  @override
  List<Object?> get props => [allVisits, filteredVisits, currentFilter];
}

class VisitListError extends VisitListState {
  final String message;
  const VisitListError(this.message);

  @override
  List<Object?> get props => [message];
}
