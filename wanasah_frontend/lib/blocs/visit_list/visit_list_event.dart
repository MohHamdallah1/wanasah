import 'dart:async';

import 'package:equatable/equatable.dart';

import '../../features/visits/list/application/visit_list_filter.dart';

abstract class VisitListEvent extends Equatable {
  const VisitListEvent();

  @override
  List<Object?> get props => [];
}

class LoadVisitsEvent extends VisitListEvent {
  const LoadVisitsEvent();
}

class FilterVisitsEvent extends VisitListEvent {
  const FilterVisitsEvent(this.filter);

  final VisitListFilter filter;

  @override
  List<Object?> get props => [filter];
}

class RefreshVisitsEvent extends VisitListEvent {
  const RefreshVisitsEvent({this.completion});

  final Completer<void>? completion;
}
