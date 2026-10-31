// File: lib/blocs/dashboard/dashboard_state.dart

import 'package:equatable/equatable.dart';

import '../../models/product_model.dart';
import '../../models/visit_model.dart';
import '../../features/custody/domain/pending_transfer.dart';
import '../../features/custody/domain/non_sellable_custody.dart';
import '../../features/custody/domain/stock_disclosure.dart';
import '../../features/custody/domain/pending_return_custody.dart';
import '../../features/work_session/application/work_session_action_issue.dart';

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

enum DashboardRefreshIssueKind { connectivity, service }

class DashboardRefreshIssue extends Equatable {
  final DashboardRefreshIssueKind kind;
  final int? statusCode;
  final String? requestId;

  const DashboardRefreshIssue({
    required this.kind,
    this.statusCode,
    this.requestId,
  });

  @override
  List<Object?> get props => [kind, statusCode, requestId];
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
  final int quarantinedVisits; // +++   عداد الفواتير المرفوضة نهائياً +++

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
  final DashboardRefreshIssue? refreshIssue;
  // +++ جديد: للتعامل مع المصافحة المعلقة (Transfers Handshake) +++
  final PendingTransferBatch? pendingTransfer;
  final List<NonSellableCustodyItem> nonSellableCustody;
  final StockDisclosure sellableStockDisclosure;
  final StockDisclosure nonSellableStockDisclosure;
  final List<PendingReturnCustodyItem> pendingReturnCustody;
  // +++  لـ Bug 1: دمج رسالة النجاح كمتغير لحظي لمنع انهيار الشاشة +++
  final String? actionSuccessMessage;
  final WorkSessionActionIssue? workSessionIssue;

  const DashboardLoaded({
    required this.visits,
    required this.products,
    required this.totalVisits,
    required this.completedVisits,
    required this.pendingVisits,
    required this.offlineVisits,
    this.quarantinedVisits = 0, // +++ تهيئة العداد +++
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
    this.refreshIssue,
    this.pendingTransfer,
    this.nonSellableCustody = const <NonSellableCustodyItem>[],
    this.sellableStockDisclosure = StockDisclosure.unavailable,
    this.nonSellableStockDisclosure = StockDisclosure.unavailable,
    this.pendingReturnCustody = const <PendingReturnCustodyItem>[],
    this.actionSuccessMessage,
    this.workSessionIssue,
  });

  @override
  List<Object?> get props => [
    visits,
    products,
    totalVisits,
    completedVisits,
    pendingVisits,
    offlineVisits,
    quarantinedVisits, // +++ تسجيله للمقارنة +++
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
    refreshIssue,
    pendingTransfer,
    nonSellableCustody,
    sellableStockDisclosure,
    nonSellableStockDisclosure,
    pendingReturnCustody,
    actionSuccessMessage,
    workSessionIssue,
  ];

  // +++ النصيحة الذهبية: دالة copyWith لتحديث حقل واحد دون فقدان باقي البيانات +++
  DashboardLoaded copyWith({
    List<VisitModel>? visits,
    List<ProductModel>? products,
    int? totalVisits,
    int? completedVisits,
    int? pendingVisits,
    int? offlineVisits,
    int? quarantinedVisits, // +++ التمرير في النسخ +++
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
    DashboardRefreshIssue? refreshIssue,
    PendingTransferBatch? pendingTransfer,
    List<NonSellableCustodyItem>? nonSellableCustody,
    StockDisclosure? sellableStockDisclosure,
    StockDisclosure? nonSellableStockDisclosure,
    List<PendingReturnCustodyItem>? pendingReturnCustody,
    String? actionSuccessMessage,
    WorkSessionActionIssue? workSessionIssue,
    bool clearActionMessage = false, // لتفريغ الرسالة بعد عرضها
    bool clearWorkSessionIssue = false,
    bool clearRefreshIssue = false,
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
      quarantinedVisits: quarantinedVisits ?? this.quarantinedVisits, // +++ التعيين +++
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
      refreshIssue:
          clearRefreshIssue ? null : (refreshIssue ?? this.refreshIssue),
      // إذا طلبنا تفريغها نضع null، وإلا نأخذ الجديدة أو نحتفظ بالقديمة
      pendingTransfer:
          clearPendingTransfer
              ? null
              : (pendingTransfer ?? this.pendingTransfer),
      nonSellableCustody:
          nonSellableCustody ?? this.nonSellableCustody,
      sellableStockDisclosure:
          sellableStockDisclosure ?? this.sellableStockDisclosure,
      nonSellableStockDisclosure:
          nonSellableStockDisclosure ?? this.nonSellableStockDisclosure,
      pendingReturnCustody:
          pendingReturnCustody ?? this.pendingReturnCustody,
      actionSuccessMessage:
          clearActionMessage
              ? null
              : (actionSuccessMessage ?? this.actionSuccessMessage),
      workSessionIssue:
          clearWorkSessionIssue
              ? null
              : (workSessionIssue ?? this.workSessionIssue),
    );
  }
}

class DashboardError extends DashboardState {
  final String message;
  final DateTime timestamp; // ختم زمني لإجبار الواجهة على الاستجابة

  // +++ شلنا كلمة const من هنا عشان الكومبايلر ما يزعل +++
  DashboardError({required this.message}) : timestamp = DateTime.now();

  @override
  List<Object?> get props => [message, timestamp];
}
