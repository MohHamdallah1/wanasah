// File: lib/blocs/dashboard/dashboard_bloc.dart
//
// الوسيط بين SyncRepository (الشبكة/SQLite) وشاشة لوحة التحكم.
// لا يحتوي على أي منطق UI.

import 'package:flutter_bloc/flutter_bloc.dart';
import 'dart:developer' as developer;

import '../../core/db/local_database.dart';
import '../../models/product_model.dart';
import '../../models/visit_model.dart';
import '../../repositories/sync_repository.dart';
import 'dashboard_event.dart';
import 'dashboard_state.dart';
import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../../core/network/api_client.dart';

class DashboardBloc extends Bloc<DashboardEvent, DashboardState> {
  final SyncRepository _syncRepository;
  final LocalDatabase _db;

  DashboardBloc({SyncRepository? syncRepository, LocalDatabase? db})
    : _syncRepository = syncRepository ?? SyncRepository(),
      _db = db ?? LocalDatabase.instance,
      super(const DashboardInitial()) {
    on<LoadDashboardData>(_onLoadDashboardData);
    on<ForceSyncData>(_onForceSyncData);
    on<FetchDashboardData>(_onFetchDashboardData);
    on<CheckPendingTransfers>(_onCheckPendingTransfers);
    on<RespondToTransfer>(_onRespondToTransfer);
  }

  // ─── LoadDashboardData ────────────────────────────────────────────────────
  /// يقرأ من SQLite مباشرة — لا شبكة، لا انتظار.
  Future<void> _onLoadDashboardData(
    LoadDashboardData event,
    Emitter<DashboardState> emit,
  ) async {
    emit(const DashboardLoading());

    try {
      final loaded = await _loadFromLocal();
      emit(loaded);
    } catch (e) {
      developer.log('[DashboardBloc] LoadDashboardData error: $e');
      emit(DashboardError(message: 'فشل تحميل البيانات المحلية: $e'));
    }
  }

  // ─── ForceSyncData ────────────────────────────────────────────────────────
  /// يستدعي syncDown() لجلب أحدث بيانات من السيرفر، ثم يُعيد تحميل SQLite.
  Future<void> _onForceSyncData(
    ForceSyncData event,
    Emitter<DashboardState> emit,
  ) async {
    emit(const DashboardLoading());

    try {
      // 1. مزامنة من السيرفر (تشمل syncUp داخلياً كضمان)
      await _syncRepository.syncDown();
      developer.log('[DashboardBloc] syncDown() completed.');

      // 2. قراءة البيانات المحدَّثة من SQLite
      final loaded = await _loadFromLocal();
      emit(loaded);
    } catch (e) {
      developer.log('[DashboardBloc] ForceSyncData error: $e');
      // عند فشل الشبكة: نُحاول قراءة البيانات المحلية القديمة بدلاً من إظهار خطأ
      try {
        // +++ تفعيل الإشارة التحذيرية للواجهة +++
        final cached = await _loadFromLocal(isOffline: true);
        // نُصدر البيانات القديمة كـ Loaded لضمان استمرارية العمل Offline
        emit(cached);
        developer.log(
          '[DashboardBloc] Emitting cached data after sync failure.',
        );
      } catch (localError) {
        emit(
          DashboardError(
            message: 'لا يوجد اتصال ولا بيانات محلية: $localError',
          ),
        );
      }
    }
  }

  // ─── Helper: قراءة وتحويل البيانات من SQLite (نسخة الذاكرة الفولاذية) ─────────────────────────────
  Future<DashboardLoaded> _loadFromLocal({bool isOffline = false}) async {
    final rawVisits = await _db.getVisits();
    final rawProducts = await _db.getProducts();

    final visits = rawVisits.map((row) => VisitModel.fromJson(row)).toList();
    final products =
        rawProducts.map((row) => ProductModel.fromJson(row)).toList();

    // +++ الكيّ الجراحي: القضاء على الـ I/O Waterfall البطيء (قراءة كل المفاتيح بدفعة واحدة) +++
    final storage = const FlutterSecureStorage();
    final allData = await storage.readAll();

    final int total =
        visits.isNotEmpty
            ? visits.length
            : (int.tryParse(allData['cached_total_visits'] ?? '0') ?? 0);
    final int completed =
        visits.isNotEmpty
            ? visits.where((v) => v.status == 'Completed').length
            : (int.tryParse(allData['cached_completed_visits'] ?? '0') ?? 0);
    final int pending =
        visits.isNotEmpty
            ? visits.where((v) => v.status == 'Pending').length
            : (int.tryParse(allData['cached_pending_visits'] ?? '0') ?? 0);

    // +++ حل لغم المصادر المفقودة (salesInCompleted Offline) +++
    final int salesInCompleted =
        visits
            .where((v) => v.status == 'Completed' && v.outcome == 'Sale')
            .length;

    final pendingSyncs = await _db.getPendingSyncs();
    final int offlineCount = pendingSyncs.length;

    // +++ حل فخ "فقدان الذاكرة المالية وهوية المندوب" +++
    final driverName = allData['cached_driver_name'] ?? 'مندوب (أوفلاين)';
    final assignedRegion = allData['cached_assigned_region'] ?? '...';
    final totalSalesCash =
        double.tryParse(allData['cached_total_sales_cash'] ?? '0.0') ?? 0.0;
    final totalDebtPaid =
        double.tryParse(allData['cached_total_debt_paid'] ?? '0.0') ?? 0.0;
    final debtPaymentsCount =
        int.tryParse(allData['cached_debt_payments_count'] ?? '0') ?? 0;
    final totalCashOverall =
        double.tryParse(allData['cached_total_cash_overall'] ?? '0.0') ?? 0.0;

    // +++ الكيّ الجراحي: قراءة حالة الجلسة والاستراحة أوفلاين لتحديث الأزرار بشكل حي +++
    final bool isActiveSession =
        (allData['cached_is_active_session'] == 'true');
    final String? activeSessionStartTime = allData['cached_session_start_time'];
    final bool isOnBreak = (allData['is_on_break'] == 'true');

    developer.log(
      '[DashboardBloc] Local Stats: Total($total), Done($completed), Sales($salesInCompleted), Offline($offlineCount)',
    );

    return DashboardLoaded(
      visits: visits,
      products: products,
      totalVisits: total,
      completedVisits: completed,
      pendingVisits: pending,
      offlineVisits: offlineCount,
      salesInCompleted: salesInCompleted,
      driverName: driverName,
      assignedRegion: assignedRegion,
      totalSalesCash: totalSalesCash,
      totalDebtPaid: totalDebtPaid,
      debtPaymentsCount: debtPaymentsCount,
      totalCashOverall: totalCashOverall,
      isOffline: isOffline,
      isActiveSession: isActiveSession, // +++ إرجاع حالة الجلسة +++
      activeSessionStartTime:
          activeSessionStartTime != '' ? activeSessionStartTime : null,
      isOnBreak:
          isOnBreak, // +++ إرجاع حالة الاستراحة ليقلب الزر لـ "إنهاء الاستراحة" +++
    );
  }

  // ─── FetchDashboardData (المحرك المالي الشامل المحصن) ─────────────────────────────
  Future<void> _onFetchDashboardData(
    FetchDashboardData event,
    Emitter<DashboardState> emit,
  ) async {
    emit(const DashboardLoading());

    try {
      final response = await ApiClient.instance.get(
        '/driver/${event.driverId}/dashboard',
      );
      final Map<String, dynamic> data = response.data;

      final sessionData = data['active_session'] as Map<String, dynamic>?;
      final bool sessionIsActive =
          (sessionData != null && sessionData['session_id'] != null);

      bool isAuthorized = false;
      bool isOnBreak = false;
      String? startTimeStr;
      List<ProductModel> apiProducts = [];

      if (sessionData != null) {
        isAuthorized = sessionData['is_authorized_to_sell'] == true;
        isOnBreak =
            sessionData['break_start_time'] != null &&
            sessionData['break_end_time'] == null;
        startTimeStr = sessionData['start_time'] as String?;
        final inventoryList = sessionData['inventory'] as List<dynamic>? ?? [];
        apiProducts =
            inventoryList.map((p) => ProductModel.fromJson(p)).toList();
      }

      final financials = data['financials'] as Map<String, dynamic>?;
      final countsData = data['counts'] as Map<String, dynamic>?;

      // +++ حفظ الذاكرة المالية وهوية المندوب أوفلاين (دفعة واحدة لمنع شلل الواجهة) +++
      final storage = const FlutterSecureStorage();
      await Future.wait([
        storage.write(key: 'is_authorized', value: isAuthorized.toString()),
        storage.write(
          key: 'cached_driver_name',
          value: data['driver_name']?.toString() ?? '',
        ),
        storage.write(
          key: 'cached_assigned_region',
          value: data['assigned_region']?.toString() ?? '',
        ),
        storage.write(
          key: 'cached_total_sales_cash',
          value: (financials?['total_sales_cash']?.toString() ?? '0.0'),
        ),
        storage.write(
          key: 'cached_total_debt_paid',
          value: (financials?['total_debt_paid']?.toString() ?? '0.0'),
        ),
        storage.write(
          key: 'cached_debt_payments_count',
          value: (financials?['debt_payments_count']?.toString() ?? '0'),
        ),
        storage.write(
          key: 'cached_total_cash_overall',
          value: (financials?['total_cash_overall']?.toString() ?? '0.0'),
        ),
        storage.write(
          key: 'cached_total_visits',
          value:
              ((countsData?['total_pending'] ?? 0) +
                      (countsData?['total_completed'] ?? 0))
                  .toString(),
        ),
        storage.write(
          key: 'cached_completed_visits',
          value: (countsData?['total_completed']?.toString() ?? '0'),
        ),
        storage.write(
          key: 'cached_pending_visits',
          value: (countsData?['total_pending']?.toString() ?? '0'),
        ),
        storage.write(
          key: 'cached_is_active_session',
          value: sessionIsActive.toString(),
        ),
        storage.write(
          key: 'cached_session_start_time',
          value: startTimeStr ?? '',
        ),
      ]);

      try {
        await _syncRepository.syncDown();
      } catch (syncError) {
        developer.log(
          '[DashboardBloc] SyncDown failed during fetch: $syncError',
        );
      }

      final localData = await _loadFromLocal(isOffline: false);

      emit(
        DashboardLoaded(
          visits: localData.visits,
          products: apiProducts.isNotEmpty ? apiProducts : localData.products,
          totalVisits:
              (countsData?['total_pending'] ?? 0) +
              (countsData?['total_completed'] ?? 0),
          completedVisits:
              countsData?['total_completed'] ?? localData.completedVisits,
          pendingVisits:
              countsData?['total_pending'] ?? localData.pendingVisits,
          offlineVisits: localData.offlineVisits,
          salesInCompleted:
              countsData?['sales_in_completed'] ?? localData.salesInCompleted,
          driverName: data['driver_name'] ?? localData.driverName,
          assignedRegion: data['assigned_region'] ?? localData.assignedRegion,
          totalSalesCash:
              (financials?['total_sales_cash'] as num?)?.toDouble() ?? 0.0,
          totalDebtPaid:
              (financials?['total_debt_paid'] as num?)?.toDouble() ?? 0.0,
          debtPaymentsCount: financials?['debt_payments_count'] as int? ?? 0,
          totalCashOverall:
              (financials?['total_cash_overall'] as num?)?.toDouble() ?? 0.0,
          isActiveSession: sessionIsActive,
          activeSessionStartTime: startTimeStr,
          isOnBreak: isOnBreak,
        ),
      );

      // +++ التحقق التلقائي من الحوالات المعلقة إذا كانت الجلسة نشطة +++
      if (sessionIsActive) {
        add(CheckPendingTransfers());
      }
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) return;

      developer.log('[DashboardBloc] Dio Error: ${e.type} - ${e.message}');

      // +++ التفريق الهندسي: هل النت مقطوع فعلاً؟ أم أن السيرفر فيه خلل (404/500)؟ +++
      final bool isOfflineError =
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.sendTimeout ||
          e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.unknown;

      if (isOfflineError) {
        try {
          // النت مقطوع -> نعرض بيانات الخزنة
          final localData = await _loadFromLocal(isOffline: true);
          emit(localData);
        } catch (localErr) {
          emit(
            const DashboardError(
              message: 'انقطع الإنترنت ولا توجد بيانات محلية.',
            ),
          );
        }
      } else {
        // النت شغال ممتاز، لكن المسار في السيرفر غير موجود (404) أو معطل (500)
        emit(
          DashboardError(
            message:
                'أنت متصل بالإنترنت، لكن هناك خطأ في السيرفر: ${e.response?.statusCode}',
          ),
        );
      }
    } catch (e) {
      developer.log('[DashboardBloc] Parsing Error: $e');
      emit(DashboardError(message: 'حدث خطأ في معالجة بيانات لوحة التحكم: $e'));
    }
  }

  // ─── دوال المصافحة (Transfers Handshake) ──────────────────────────────────
  Future<void> _onCheckPendingTransfers(
    CheckPendingTransfers event,
    Emitter<DashboardState> emit,
  ) async {
    if (state is! DashboardLoaded) return;
    final currentState = state as DashboardLoaded;

    try {
      final response = await ApiClient.instance.get(
        '/driver/transfers/pending',
      );
      final List<dynamic> transfers = response.data ?? [];

      if (transfers.isNotEmpty) {
        // +++ تحديث آمن بسطر واحد باستخدام copyWith +++
        emit(currentState.copyWith(pendingTransfer: transfers.first));
      }
    } catch (e) {
      developer.log('[DashboardBloc] Error checking transfers: $e');
    }
  }

  Future<void> _onRespondToTransfer(
    RespondToTransfer event,
    Emitter<DashboardState> emit,
  ) async {
    if (state is! DashboardLoaded) return;

    // +++ إخفاء الحوالة فوراً من الـ State لكي يختفي الـ Dialog من الشاشة ولا يتكرر +++
    emit((state as DashboardLoaded).copyWith(clearPendingTransfer: true));

    try {
      await ApiClient.instance.put(
        '/driver/transfers/${event.transferId}/respond',
        data: {'response': event.responseStatus},
      );

      final String? driverIdStr = await const FlutterSecureStorage().read(
        key: 'driver_id',
      );
      if (driverIdStr != null) {
        // تحديث البيانات بعد الرد لضمان دخول البضاعة للمخزون
        add(FetchDashboardData(driverId: int.parse(driverIdStr)));
      }
    } catch (e) {
      developer.log('[DashboardBloc] Error responding to transfer: $e');
      emit(DashboardError(message: 'فشل إرسال الرد للإدارة: $e'));
    }
  }
}
