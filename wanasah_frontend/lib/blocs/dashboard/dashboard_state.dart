// File: lib/blocs/dashboard/dashboard_state.dart

import 'package:equatable/equatable.dart';

import '../../models/product_model.dart';
import '../../models/visit_model.dart';

abstract class DashboardState extends Equatable {
  const DashboardState();

  @override
  List<Object?> get props => [];
}

class DashboardInitial extends DashboardState {
  const DashboardInitial();
}

class DashboardLoading extends DashboardState {
  const DashboardLoading();
}

class DashboardLoaded extends DashboardState {
  final List<VisitModel> visits;
  final List<ProductModel> products; // هذه تغنيك عن _inventoryList البدائية

  // ── إحصائيات الزيارات ──
  final int totalVisits;
  final int completedVisits;
  final int pendingVisits;
  final int offlineVisits;
  final int salesInCompleted;

  // ── المتغيرات المالية والجلسة (تم نقلها من الشاشة لحمايتها) ──
  final String driverName;
  final String assignedRegion;
  final double totalSalesCash;
  final double totalDebtPaid;
  final int debtPaymentsCount;
  final double totalCashOverall;
  final bool isActiveSession;
  final String? activeSessionStartTime;
  final bool isOnBreak;

  final bool isOffline;
  // +++ جديد: للتعامل مع المصافحة المعلقة (Transfers Handshake) +++
  final Map<String, dynamic>? pendingTransfer;
  // +++ الكي الجراحي لـ Bug 1: دمج رسالة النجاح كمتغير لحظي لمنع انهيار الشاشة +++
  final String? actionSuccessMessage;

  const DashboardLoaded({
    required this.visits,
    required this.products,
    required this.totalVisits,
    required this.completedVisits,
    required this.pendingVisits,
    required this.offlineVisits,
    this.salesInCompleted = 0,
    this.driverName = '...',
    this.assignedRegion = '...',
    this.totalSalesCash = 0.0,
    this.totalDebtPaid = 0.0,
    this.debtPaymentsCount = 0,
    this.totalCashOverall = 0.0,
    this.isActiveSession = false,
    this.activeSessionStartTime,
    this.isOnBreak = false,
    this.isOffline = false,
    this.pendingTransfer,
    this.actionSuccessMessage,
  });

  @override
  List<Object?> get props => [
    visits,
    products,
    totalVisits,
    completedVisits,
    pendingVisits,
    offlineVisits,
    salesInCompleted,
    driverName,
    assignedRegion,
    totalSalesCash,
    totalDebtPaid,
    debtPaymentsCount,
    totalCashOverall,
    isActiveSession,
    activeSessionStartTime,
    isOnBreak,
    isOffline,
    pendingTransfer,
    actionSuccessMessage,
  ];

  // +++ النصيحة الذهبية: دالة copyWith لتحديث حقل واحد دون فقدان باقي البيانات +++
  DashboardLoaded copyWith({
    List<VisitModel>? visits,
    List<ProductModel>? products,
    int? totalVisits,
    int? completedVisits,
    int? pendingVisits,
    int? offlineVisits,
    int? salesInCompleted,
    String? driverName,
    String? assignedRegion,
    double? totalSalesCash,
    double? totalDebtPaid,
    int? debtPaymentsCount,
    double? totalCashOverall,
    bool? isActiveSession,
    String? activeSessionStartTime,
    bool? isOnBreak,
    bool? isOffline,
    Map<String, dynamic>? pendingTransfer,
    String? actionSuccessMessage,
    bool clearActionMessage = false, // لتفريغ الرسالة بعد عرضها
    bool clearPendingTransfer =
        false, // خدعة ذكية لتفريغ الحوالة بعد الرد عليها
  }) {
    return DashboardLoaded(
      visits: visits ?? this.visits,
      products: products ?? this.products,
      totalVisits: totalVisits ?? this.totalVisits,
      completedVisits: completedVisits ?? this.completedVisits,
      pendingVisits: pendingVisits ?? this.pendingVisits,
      offlineVisits: offlineVisits ?? this.offlineVisits,
      salesInCompleted: salesInCompleted ?? this.salesInCompleted,
      driverName: driverName ?? this.driverName,
      assignedRegion: assignedRegion ?? this.assignedRegion,
      totalSalesCash: totalSalesCash ?? this.totalSalesCash,
      totalDebtPaid: totalDebtPaid ?? this.totalDebtPaid,
      debtPaymentsCount: debtPaymentsCount ?? this.debtPaymentsCount,
      totalCashOverall: totalCashOverall ?? this.totalCashOverall,
      isActiveSession: isActiveSession ?? this.isActiveSession,
      activeSessionStartTime:
          activeSessionStartTime ?? this.activeSessionStartTime,
      isOnBreak: isOnBreak ?? this.isOnBreak,
      isOffline: isOffline ?? this.isOffline,
      // إذا طلبنا تفريغها نضع null، وإلا نأخذ الجديدة أو نحتفظ بالقديمة
      pendingTransfer:
          clearPendingTransfer
              ? null
              : (pendingTransfer ?? this.pendingTransfer),
      actionSuccessMessage: 
          clearActionMessage
              ? null 
              : (actionSuccessMessage ?? this.actionSuccessMessage),
    );
  }
}

class DashboardError extends DashboardState {
  final String message;

  const DashboardError({required this.message});

  @override
  List<Object?> get props => [message];
}

