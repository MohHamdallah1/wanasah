import 'package:flutter_bloc/flutter_bloc.dart';
import 'dart:developer' as developer;

import '../../core/db/local_database.dart';
import '../../models/visit_model.dart';
import 'visit_list_event.dart';
import 'visit_list_state.dart';

// +++ استيراد الـ Sync Repository +++
import '../../repositories/sync_repository.dart';

class VisitListBloc extends Bloc<VisitListEvent, VisitListState> {
  final LocalDatabase _db;
  final SyncRepository _syncRepository; // +++ الكي الجراحي لـ Bug 3 +++

  VisitListBloc({LocalDatabase? db, SyncRepository? syncRepo})
    : _db = db ?? LocalDatabase.instance,
      _syncRepository = syncRepo ?? SyncRepository(),
      super(VisitListLoading()) {
    on<LoadVisitsEvent>(_onLoadVisits);
    on<FilterVisitsEvent>(_onFilterVisits);
    on<RefreshVisitsEvent>(_onRefreshVisits); // +++ إضافة الـ Event الجديد +++
  }

  // +++ الكي الجراحي الشامل: دالة مركزية لجلب البيانات من SQLite دون المرور بـ Event Bus +++
  Future<void> _loadVisitsInternal(Emitter<VisitListState> emit) async {
    try {
      final List<Map<String, dynamic>> rawVisits = await _db.getVisits();
      final List<VisitModel> visits = rawVisits.map((v) => VisitModel.fromJson(v)).toList();

      // +++ العودة للهندسة النظيفة: الاعتماد على الـ Type System الصارم لـ Dart (لا تستمع لوسوسة البوت هنا) +++
      visits.sort((a, b) => a.sequence.compareTo(b.sequence));

      // +++ الحفاظ على الفلتر الحالي إذا كانت الشاشة محملة مسبقاً لمنع إعادة تعيين القائمة +++
      String currentFilter = 'All';
      if (state is VisitListLoaded) {
        currentFilter = (state as VisitListLoaded).currentFilter;
      }

      List<VisitModel> filtered = visits;
      if (currentFilter != 'All') {
        filtered = visits.where((v) => v.status == currentFilter).toList();
      }

      emit(VisitListLoaded(
        allVisits: visits,
        filteredVisits: filtered,
        currentFilter: currentFilter,
      ));
    } catch (e) {
      developer.log('[VisitListBloc] Error loading visits: $e');
      emit(VisitListError('حدث خطأ أثناء تحميل خط السير.'));
    }
  }

  Future<void> _onLoadVisits(
    LoadVisitsEvent event,
    Emitter<VisitListState> emit,
  ) async {
    emit(VisitListLoading());
    await _loadVisitsInternal(emit); // تحميل مباشر
  }

  Future<void> _onRefreshVisits(
    RefreshVisitsEvent event,
    Emitter<VisitListState> emit,
  ) async {
    // +++ الكي الجراحي لـ Bug 2: منع الشاشة من الانهيار للوضع الأبيض إذا كانت الداتا موجودة أصلاً +++
    if (state is! VisitListLoaded) {
      emit(VisitListLoading());
    }
    
    try {
      await _syncRepository.syncDown();
      // +++ الكي الجراحي لـ Bug 3: تحميل داخلي مباشر لمنع دورة الـ Event البطيئة +++
      await _loadVisitsInternal(emit); 
    } catch (e) {
      developer.log('[VisitListBloc] Error syncing visits: $e');
      // +++ الكي الجراحي لـ Bug 1: نعرض الخطأ، ثم نعرض البيانات المحلية فوراً دون أن يطمسها الحدث +++
      emit(VisitListError('انقطع الاتصال. جاري عرض الزيارات المحلية.'));
      await _loadVisitsInternal(emit);
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
              .where((v) => v.status.toLowerCase() == event.status.toLowerCase())
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
