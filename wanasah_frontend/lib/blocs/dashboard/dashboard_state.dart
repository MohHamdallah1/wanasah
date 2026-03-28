// File: lib/blocs/dashboard/dashboard_state.dart

import 'package:equatable/equatable.dart';

import '../../models/product_model.dart';
import '../../models/visit_model.dart';

abstract class DashboardState extends Equatable {
  const DashboardState();

  @override
  List<Object?> get props => [];
}

// ─── الحالة الابتدائية ────────────────────────────────────────────────────────
class DashboardInitial extends DashboardState {
  const DashboardInitial();
}

// ─── جاري التحميل (محلي أو شبكة) ────────────────────────────────────────────
class DashboardLoading extends DashboardState {
  const DashboardLoading();
}

// ─── البيانات محمَّلة بنجاح ──────────────────────────────────────────────────
class DashboardLoaded extends DashboardState {
  final List<VisitModel> visits;
  final List<ProductModel> products;

  // ── إحصائيات محسوبة جاهزة للعرض المباشر ─────────────────────────────────
  /// إجمالي عدد الزيارات
  final int totalVisits;

  /// عدد الزيارات المكتملة (Completed أو Completed (Offline))
  final int completedVisits;

  /// عدد الزيارات المتبقية (Pending)
  final int pendingVisits;

  /// عدد الزيارات المحفوظة Offline وبانتظار المزامنة
  final int offlineVisits;

  // +++ الدرع المعماري: مؤشر لمعرفة ما إذا كانت البيانات معروضة بسبب انقطاع الإنترنت +++
  final bool isOffline;

  const DashboardLoaded({
    required this.visits,
    required this.products,
    required this.totalVisits,
    required this.completedVisits,
    required this.pendingVisits,
    required this.offlineVisits,
    this.isOffline = false, // القيمة الافتراضية
  });

  @override
  List<Object?> get props => [
    visits,
    products,
    totalVisits,
    completedVisits,
    pendingVisits,
    offlineVisits,
    isOffline,
  ];
}

// ─── خطأ ─────────────────────────────────────────────────────────────────────
class DashboardError extends DashboardState {
  final String message;

  const DashboardError({required this.message});

  @override
  List<Object?> get props => [message];
}
