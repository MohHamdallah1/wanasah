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
  final String responseStatus; // 'accepted' or 'rejected'

  const RespondToTransfer({
    required this.transferId,
    required this.responseStatus,
  });

  @override
  List<Object?> get props => [transferId, responseStatus];
}

// +++ الصاروخ الباليستي: حدث الرد الجماعي على الحوالات +++
class RespondToBatchTransfer extends DashboardEvent {
  final List<int> transferIds;
  final String responseStatus;
  // +++ إضافة المصفوفة التفصيلية للحوالات الفردية +++
  final List<Map<String, dynamic>> detailedTransfers;

  const RespondToBatchTransfer({
    required this.transferIds,
    required this.responseStatus,
    this.detailedTransfers = const [],
  });

  // +++ درع Equatable: مقارنة الـ Maps كنصوص لمنع تجاوز الأحداث المتشابهة +++
  @override
  List<Object> get props => [transferIds, responseStatus, detailedTransfers.toString()];
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

// +++ حدث مسح فواتير الحجر الصحي بعد تسويتها مع المسؤول +++
class ClearQuarantineEvent extends DashboardEvent {
  const ClearQuarantineEvent();
  @override
  List<Object?> get props => [];
}