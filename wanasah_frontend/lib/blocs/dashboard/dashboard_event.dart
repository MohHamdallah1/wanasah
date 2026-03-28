// File: lib/blocs/dashboard/dashboard_event.dart

import 'package:equatable/equatable.dart';

abstract class DashboardEvent extends Equatable {
  const DashboardEvent();

  @override
  List<Object?> get props => [];
}

// ─── قراءة البيانات المحلية فوراً من SQLite ─────────────────────────────────
/// يُرسَل عند فتح DashboardScreen — يقرأ من LocalDatabase بدون شبكة.
class LoadDashboardData extends DashboardEvent {
  const LoadDashboardData();
}

// ─── مزامنة قسرية من السيرفر ─────────────────────────────────────────────────
/// يُرسَل عند سحب التحديث (Pull-to-Refresh) أو بدء جلسة عمل جديدة.
/// يستدعي SyncRepository.syncDown() ثم يُعيد تحميل البيانات المحلية.
class ForceSyncData extends DashboardEvent {
  const ForceSyncData();
}
