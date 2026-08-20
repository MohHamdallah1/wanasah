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
import '../../services/location_service.dart';
import '../../repositories/dashboard_repository.dart';

class DashboardBloc extends Bloc<DashboardEvent, DashboardState> {
  final SyncRepository _syncRepository;
  final LocalDatabase _db;
  final DashboardRepository _dashboardRepo;
  final LocationService _locationService;

  DashboardBloc({
    SyncRepository? syncRepository, 
    LocalDatabase? db,
    DashboardRepository? dashboardRepo,
    LocationService? locationService,
  })
    : _syncRepository = syncRepository ?? SyncRepository(),
      _db = db ?? LocalDatabase.instance,
      _dashboardRepo = dashboardRepo ?? DashboardRepository(),
      _locationService = locationService ?? LocationService.instance,
      super(const DashboardInitial()) {
    on<LoadDashboardData>(_onLoadDashboardData);
    on<ForceSyncData>(_onForceSyncData);
    on<FetchDashboardData>(_onFetchDashboardData);
    on<CheckPendingTransfers>(_onCheckPendingTransfers);
    on<RespondToTransfer>(_onRespondToTransfer);
    on<RespondToBatchTransfer>(_onRespondToBatchTransfer);
    // +++ الكي الجراحي: تسجيل أحداث إدارة الجلسة +++
    on<StartSessionEvent>(_onStartSession);
    on<EndSessionEvent>(_onEndSession);
    on<ToggleBreakEvent>(_onToggleBreak);
    // +++ الكي الجراحي لـ Bug 3: الاستماع لحدث التنظيف في المكان الصحيح +++
    on<ClearActionMessageEvent>((event, emit) {
      if (state is DashboardLoaded) {
        emit((state as DashboardLoaded).copyWith(clearActionMessage: true));
      }
    });
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

    // +++ الكيّ الجراحي لـ Bug 2: القراءة من المستودع بدلاً من الخزنة مباشرة +++
    final allData = await _dashboardRepo.getAllCachedData();

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
    // +++ الكي الجراحي لـ Bug 3: منع الشاشة البيضاء (Jank) وتفريغ الواجهة إذا كانت محملة مسبقاً +++
    if (state is! DashboardLoaded) emit(const DashboardLoading());

    try {
      // +++ الكي الجراحي لـ Bug 2: الاعتماد على المستودع لجلب البيانات +++
      final response = await _dashboardRepo.fetchDashboardRaw();

      // +++ الدرع النوعي النخبوي (Elite Cast): منع كراش الـ TypeError بدون طرد المندوب ظلماً بسبب تعقيدات Dart +++
      if (response.data is! Map) {
        emit(const DashboardError(message: 'استجابة غير صالحة من الخادم.'));
        return;
      }
      final Map<String, dynamic> data = Map<String, dynamic>.from(response.data as Map);

      final sessionData = data['active_session'] is Map 
          ? Map<String, dynamic>.from(data['active_session'] as Map) 
          : null;
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
        startTimeStr = sessionData['start_time']?.toString();
        
        // +++ درع القوائم: حماية الـ List من الانهيار إذا أرسل السيرفر null أو Map بالخطأ +++
        final dynamic rawInv = sessionData['inventory'];
        final List<dynamic> inventoryList = rawInv is List ? rawInv : [];
        apiProducts = inventoryList.map((p) => ProductModel.fromJson(p is Map ? Map<String, dynamic>.from(p) : {})).toList();
      }

      final financials = data['financials'] is Map ? Map<String, dynamic>.from(data['financials'] as Map) : null;
      final countsData = data['counts'] is Map ? Map<String, dynamic>.from(data['counts'] as Map) : null;

      // +++ الكي الجراحي لـ Bug 2: تخزين الذاكرة عبر المستودع +++
      await _dashboardRepo.cacheDashboardData({
        'is_authorized': isAuthorized.toString(),
        'cached_driver_name': data['driver_name']?.toString() ?? '',
        'cached_assigned_region': data['assigned_region']?.toString() ?? '',
        'cached_total_sales_cash': (financials?['total_sales_cash']?.toString() ?? '0.0'),
        'cached_total_debt_paid': (financials?['total_debt_paid']?.toString() ?? '0.0'),
        'cached_debt_payments_count': (financials?['debt_payments_count']?.toString() ?? '0'),
        'cached_total_cash_overall': (financials?['total_cash_overall']?.toString() ?? '0.0'),
        'cached_total_visits': ((countsData?['total_pending'] ?? 0) + (countsData?['total_completed'] ?? 0)).toString(),
        'cached_completed_visits': (countsData?['total_completed']?.toString() ?? '0'),
        'cached_pending_visits': (countsData?['total_pending']?.toString() ?? '0'),
        'cached_is_active_session': sessionIsActive.toString(),
        'cached_session_start_time': startTimeStr ?? '',
      });

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
          // +++ الكي الجراحي لـ Bug 5: الاعتماد على الإجمالي المحلي إذا كان السيرفر معطلاً أو البيانات ناقصة +++
          totalVisits: countsData != null 
              ? (int.tryParse(countsData['total_pending']?.toString() ?? '0') ?? 0) + (int.tryParse(countsData['total_completed']?.toString() ?? '0') ?? 0)
              : localData.totalVisits,
          completedVisits:
              countsData?['total_completed'] != null 
                  ? (int.tryParse(countsData!['total_completed'].toString()) ?? 0)
                  : localData.completedVisits,
          pendingVisits:
              countsData?['total_pending'] != null 
                  ? (int.tryParse(countsData!['total_pending'].toString()) ?? 0)
                  : localData.pendingVisits,
          offlineVisits: localData.offlineVisits,
          salesInCompleted:
              countsData?['sales_in_completed'] != null 
                  ? (int.tryParse(countsData!['sales_in_completed'].toString()) ?? 0)
                  : localData.salesInCompleted,
          driverName: data['driver_name'] ?? localData.driverName,
          assignedRegion: data['assigned_region'] ?? localData.assignedRegion,
          // +++ النسف المعماري (Float Precision Loss): قراءة المبالغ كنصوص وتحويلها بأمان لمنع الـ Crash +++
          totalSalesCash:
              double.tryParse(
                financials?['total_sales_cash']?.toString() ?? '0',
              ) ??
              0.0,
          totalDebtPaid:
              double.tryParse(
                financials?['total_debt_paid']?.toString() ?? '0',
              ) ??
              0.0,
          debtPaymentsCount:
              int.tryParse(
                financials?['debt_payments_count']?.toString() ?? '0',
              ) ??
              0,
          totalCashOverall:
              double.tryParse(
                financials?['total_cash_overall']?.toString() ?? '0',
              ) ??
              0.0,
          isActiveSession: sessionIsActive,
          activeSessionStartTime: startTimeStr,
          isOnBreak: isOnBreak,
          // +++ الكي الجراحي لـ Bug 5: حفظ رسالة النجاح من الطمس أثناء تحديث البيانات +++
          actionSuccessMessage: (state is DashboardLoaded) ? (state as DashboardLoaded).actionSuccessMessage : null,
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

    try {
      final response = await _dashboardRepo.checkPendingTransfersRaw();
      final dynamic rawTransfers = response.data;
      final List<dynamic> transfers = rawTransfers is List ? rawTransfers : [];

      if (transfers.isNotEmpty) {
        // +++ الكي الجراحي لـ Bug 1: فحص State الحية قبل الـ Emit لمنع طمس البيانات +++
        if (state is DashboardLoaded) {
          emit((state as DashboardLoaded).copyWith(pendingTransfer: transfers.first));
        }
      }
    } catch (e) {
      developer.log('[DashboardBloc] Error checking transfers (Offline?): $e');
      // +++ الدرع الأوفلاين: إذا فشل الاتصال بالسيرفر، نقرأ الحوالات من الخزنة المحلية +++
      try {
        final localTransfers = await _db.getIncomingTransfers();
        if (localTransfers.isNotEmpty) {
          if (state is DashboardLoaded) {
            emit((state as DashboardLoaded).copyWith(pendingTransfer: localTransfers.first));
          }
          developer.log('[DashboardBloc] Loaded pending transfer from local DB.');
        }
      } catch (localErr) {
        developer.log('[DashboardBloc] Error reading local transfers: $localErr');
      }
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
      await _dashboardRepo.respondToTransfer(event.transferId, event.responseStatus);

      // +++ الكي الجراحي لـ Bug 3: إعدام الحوالة من الداتابيز المحلية لكي لا تظهر كشبح لاحقاً +++
      await _dashboardRepo.removeLocalTransfer(event.transferId);

      final int? driverId = await _dashboardRepo.getDriverId();
      if (driverId != null) {
        add(FetchDashboardData(driverId: driverId));
      } else {
        // +++ الكي الجراحي لـ Bug 4: الاستعانة بالمزامنة القسرية إذا فُقد المعرف بدلاً من الموت بصمت +++
        add(const ForceSyncData()); 
      }
    } catch (e) {
      developer.log('[DashboardBloc] Error responding to transfer: $e');
      emit(DashboardError(message: 'فشل إرسال الرد للإدارة: $e'));
    }
  }

  // ─── المحرك الصاروخي (Batch Handshake) ──────────────────────────────────
  Future<void> _onRespondToBatchTransfer(
    RespondToBatchTransfer event,
    Emitter<DashboardState> emit,
  ) async {
    if (state is! DashboardLoaded) return;

    // +++ إخفاء الحوالة فوراً من الـ State لكي يختفي الـ Dialog من الشاشة +++
    emit((state as DashboardLoaded).copyWith(clearPendingTransfer: true));

    try {
      await _dashboardRepo.respondToBatchTransfer(event.detailedTransfers);

      // +++ الكي الجراحي لـ Bug 3: إعدام كافة الحوالات المستجابة محلياً +++
      for (final t in event.detailedTransfers) {
        final tid = (t['transfer_id'] as num?)?.toInt();
        if (tid != null) {
          await _dashboardRepo.removeLocalTransfer(tid);
        }
      }

      final int? driverId = await _dashboardRepo.getDriverId();
      if (driverId != null) {
        add(FetchDashboardData(driverId: driverId));
      } else {
        add(const ForceSyncData());
      }
    } catch (e) {
      developer.log('[DashboardBloc] Error responding to batch transfer: $e');
      emit(DashboardError(message: 'فشل إرسال الرد الجماعي للإدارة: $e'));
    }
  }


  // ─── دوال إدارة جلسة العمل (Clean Architecture: Delegation to Repository) ───

  Future<void> _onStartSession(StartSessionEvent event, Emitter<DashboardState> emit) async {
    try {
      final position = await _locationService.getCurrentLocation();
      await _dashboardRepo.startSession(position?.latitude, position?.longitude);

      if (state is DashboardLoaded) emit((state as DashboardLoaded).copyWith(actionSuccessMessage: 'تم بدء جلسة العمل!'));
      add(FetchDashboardData(driverId: event.driverId)); 
      
    } on DioException catch (e) {
      if (e.response?.statusCode == 409) {
        if (state is DashboardLoaded) emit((state as DashboardLoaded).copyWith(actionSuccessMessage: 'يوجد جلسة عمل نشطة بالفعل.'));
        add(FetchDashboardData(driverId: event.driverId));
      } else if (e.response?.statusCode != 401) {
        emit(DashboardError(message: 'خطأ: ${e.response?.data?['message'] ?? 'فشل الاتصال'}'));
      }
    } catch (e) {
      // +++ الكي الجراحي: اصطياد كافة مشاكل الـ GPS ومنع الجلسة من البدء بدون إحداثيات +++
      if (e.toString().contains('GPS_DISABLED')) {
        emit(const DashboardError(message: 'الرجاء تفعيل خدمة الموقع (GPS) لبدء العمل.'));
      } else if (e.toString().contains('GPS_DENIED')) {
        emit(const DashboardError(message: 'صلاحية الموقع مطلوبة لبدء العمل.'));
      } else if (e.toString().contains('GPS_TIMEOUT')) {
        emit(const DashboardError(message: 'فشل تحديد الموقع. الرجاء التأكد من قوة إشارة الـ GPS والمحاولة في مكان مفتوح.'));
      } else {
        emit(DashboardError(message: 'حدث خطأ غير متوقع: $e'));
      }
    }
  }

  Future<void> _onEndSession(EndSessionEvent event, Emitter<DashboardState> emit) async {
    try {
      await _dashboardRepo.endSession();
      if (state is DashboardLoaded) emit((state as DashboardLoaded).copyWith(actionSuccessMessage: 'تم إنهاء العمل.'));
      add(FetchDashboardData(driverId: event.driverId));
      
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) return;

      if (e.response?.statusCode == 404) {
        await _dashboardRepo.clearSessionLocally();
        if (state is DashboardLoaded) emit((state as DashboardLoaded).copyWith(actionSuccessMessage: 'تم اكتشاف تصفير للسيرفر. تم تنظيف الجلسة الوهمية محلياً 🧹'));
        add(FetchDashboardData(driverId: event.driverId));
        return;
      }

      // +++ الكي الجراحي: إضافة كافة حالات الـ Offline لمنع الخطأ الوهمي +++
      final isOffline = e.response == null || 
                        e.type == DioExceptionType.connectionTimeout || 
                        e.type == DioExceptionType.receiveTimeout || 
                        e.type == DioExceptionType.sendTimeout || 
                        e.type == DioExceptionType.connectionError || 
                        e.type == DioExceptionType.unknown ||
                        e.error.toString().contains('SocketException');

      emit(DashboardError(message: isOffline 
          ? 'لا يمكن إنهاء العمل وأنت أوفلاين. يجب الاتصال بالإنترنت لمطابقة العهدة وتسليمها.' 
          : 'خطأ: ${e.response?.data?['message'] ?? 'فشل الإنهاء'}'));
    } catch (e) {
      emit(DashboardError(message: 'حدث خطأ أثناء إنهاء الجلسة.'));
    }
  }

  Future<void> _onToggleBreak(ToggleBreakEvent event, Emitter<DashboardState> emit) async {
    try {
      await _dashboardRepo.toggleBreak(event.driverId, event.action);
      
      if (state is DashboardLoaded) emit((state as DashboardLoaded).copyWith(actionSuccessMessage: event.action == 'start' ? 'تم بدء الاستراحة (مسجلة).' : 'تم إنهاء الاستراحة (مسجلة).'));
      add(FetchDashboardData(driverId: event.driverId));
      
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) return; // +++ الكي الجراحي لـ Bug 6: منع الشبح والـ SnackBar الأحمر عند انتهاء الجلسة +++
      if (e.response?.statusCode == 404) {
        await _dashboardRepo.clearSessionLocally();
        if (state is DashboardLoaded) emit((state as DashboardLoaded).copyWith(actionSuccessMessage: 'الجلسة غير موجودة على السيرفر! تم إعادة الضبط 🧹'));
        add(FetchDashboardData(driverId: event.driverId));
        return;
      }
      emit(DashboardError(message: 'خطأ: ${e.response?.data?['message'] ?? 'فشل الاتصال'}'));
    } catch (e) {
      emit(DashboardError(message: 'فشل في عملية الاستراحة.'));
    }
  }
} // +++ الكي الجراحي: هذا القوس اللي طار وكسرلك الملف كله! +++