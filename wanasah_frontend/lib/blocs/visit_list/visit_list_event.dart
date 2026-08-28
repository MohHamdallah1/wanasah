import 'package:equatable/equatable.dart';

abstract class VisitListEvent extends Equatable {
  const VisitListEvent();

  @override
  List<Object?> get props => [];
}

class LoadVisitsEvent extends VisitListEvent {
  const LoadVisitsEvent();
}

class FilterVisitsEvent extends VisitListEvent {
  final String status; // 'All', 'Completed', 'Pending'
  const FilterVisitsEvent(this.status);

  @override
  List<Object?> get props => [status];
}

// +++ حدث جديد لتحديث الزيارات من السيرفر +++
class RefreshVisitsEvent extends VisitListEvent {
  const RefreshVisitsEvent();
}