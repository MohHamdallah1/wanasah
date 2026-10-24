// File: lib/blocs/dashboard/dashboard_event.dart

import 'package:equatable/equatable.dart';
import '../../features/custody/domain/transfer_decision.dart';

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

// ─── جلب البيانات الشاملة للداشبورد (API + Local) ────────────────────────
/// يُرسَل من الشاشة لجلب الماليات من السيرفر والمزامنة مع القاعدة المحلية.
class FetchDashboardData extends DashboardEvent {
  final int driverId;
  const FetchDashboardData({required this.driverId});

  @override
  List<Object?> get props => [driverId];
}

// ─── أوامر المصافحة للحوالات المعلقة ──────────────────────────────────────
/// يُرسَل للتحقق من وجود بضاعة مرسلة/مسحوبة من الإدارة
class CheckPendingTransfers extends DashboardEvent {
  const CheckPendingTransfers();
}

/// يُرسَل للرد على الحوالة (موافقة أو رفض)
class RespondToTransfer extends DashboardEvent {
  final int transferId;
  final String responseStatus;
  final String? reason;

  const RespondToTransfer({
    required this.transferId,
    required this.responseStatus,
    this.reason,
  });

  @override
  List<Object?> get props => [transferId, responseStatus, reason];
}

class RespondToBatchTransfer extends DashboardEvent {
  final List<TransferDecision> decisions;

  const RespondToBatchTransfer({
    this.decisions = const <TransferDecision>[],
  });

  @override
  List<Object?> get props => [decisions];
}

// ─── أوامر إدارة جلسة العمل (Session Management) ──────────────────────────
/// يُرسَل لبدء جلسة عمل جديدة مع موقع الـ GPS
class StartSessionEvent extends DashboardEvent {
  final int driverId;
  const StartSessionEvent({required this.driverId});
  
  @override
  List<Object?> get props => [driverId];
}

/// يُرسَل لإنهاء جلسة العمل الحالية
class EndSessionEvent extends DashboardEvent {
  final int driverId;
  const EndSessionEvent({required this.driverId});
  
  @override
  List<Object?> get props => [driverId];
}

/// يُرسَل لتسجيل بدء أو إنهاء استراحة (مع دعم الأوفلاين)
class ToggleBreakEvent extends DashboardEvent {
  final int driverId;
  final String action; // 'start' or 'end'
  
  const ToggleBreakEvent({required this.driverId, required this.action});
  
  @override
  List<Object?> get props => [driverId, action];
}

// +++ حدث جديد لتنظيف رسالة النجاح من الـ State بعد عرضها +++
class ClearActionMessageEvent extends DashboardEvent {
  const ClearActionMessageEvent();
}

class ClearWorkSessionIssueEvent extends DashboardEvent {
  const ClearWorkSessionIssueEvent();
}
