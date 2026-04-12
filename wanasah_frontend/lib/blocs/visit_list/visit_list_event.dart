import 'package:equatable/equatable.dart';

abstract class VisitListEvent extends Equatable {
  const VisitListEvent();

  @override
  List<Object?> get props => [];
}

class LoadVisitsEvent extends VisitListEvent {}

class FilterVisitsEvent extends VisitListEvent {
  final String status; // 'All', 'Completed', 'Pending'
  const FilterVisitsEvent(this.status);

  @override
  List<Object?> get props => [status];
}
