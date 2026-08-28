// File: lib/blocs/dashboard/dashboard_bloc.dart
//
// الوسيط بين SyncRepository (الشبكة/SQLite) وشاشة لوحة التحكم.
// لا يحتوي على أي منطق UI.

import 'package:flutter_bloc/flutter_bloc.dart';
import 'dart:developer' as developer;
import 'dart:async';
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

  // +++ EVT-1: محول تسلسلي (Sequential Transformer) لإجبار البلوك على معالجة الأحداث بالدور ومنع السباق +++
  EventTransformer<T> _sequential<T>() {
    return (events, mapper) => events.asyncExpand(mapper);
  }

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
      
    // +++ ربط جميع الأحداث بالمحول التسلسلي لمنع الانهيار المعماري +++
    on<LoadDashboardData>(_onLoadDashboardData, transformer: _sequential());
    on<ForceSyncData>(_onForceSyncData, transformer: _sequential());
    on<FetchDashboardData>(_onFetchDashboardData, transformer: _sequential());
    on<CheckPendingTransfers>(_onCheckPendingTransfers); // هذا يمكن تركه لأنه يُستدعى داخلياً بعد Fetch
    on<RespondToTransfer>(_onRespondToTransfer, transformer: _sequential());
    on<RespondToBatchTransfer>(_onRespondToBatchTransfer, transformer: _sequential());
    on<StartSessionEvent>(_onStartSession, transformer: _sequential());
    on<EndSessionEvent>(_onEndSession, transformer: _sequential());
    on<ToggleBreakEvent>(_onToggleBreak, transformer: _sequential());
    on<ClearActionMessageEvent>((event, emit) {
      if (state is DashboardLoaded) {
        emit((state as DashboardLoaded).copyWith(clearActionMessage: true));
      }
    }, transformer: _sequential());
    // +++ ربط حدث التسوية +++
    on<ClearQuarantineEvent>(_onClearQuarantine, transformer: _sequential());
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
    // +++ DAB-6: منع وميض الشاشة ومسح المحتوى إذا كانت البيانات محملة مسبقاً +++
    if (state is! DashboardLoaded) emit(const DashboardLoading());

    try {
      // 1. مزامنة من السيرفر (تشمل syncUp داخلياً كضمان)
      final bool syncRan = await _syncRepository.syncDown();
      if (!syncRan) {
        // +++ إبلاغ المندوب بأن الطابور مشغول بدلاً من تجاهل سحبه للشاشة +++
        emit(DashboardError(message: 'المزامنة جارية بالفعل في الخلفية. يرجى الانتظار قليلاً ⏳'));
        // نعيد عرض البيانات المحلية فوراً لكي لا تعلق الشاشة في الـ Loading
        final cached = await _loadFromLocal(isOffline: true);
        emit(cached);
        return;
      }
      developer.log('[DashboardBloc] syncDown() completed.');

      // 2. قراءة البيانات المحدَّثة من SQLite
      final loaded = await _loadFromLocal();
      emit(loaded);
    } catch (e) {
      developer.log('[DashboardBloc] ForceSyncData error: $e');
      try {
        // +++ DAB-1b: التمييز الدقيق (خطأ السيرفر الداخلي 500 ليس انقطاعاً في الإنترنت) +++
        final bool isNetworkError = e is DioException && 
            (e.response == null || e.type == DioExceptionType.connectionTimeout || e.type == DioExceptionType.receiveTimeout);
        final String errorMsg = isNetworkError 
            ? 'فشل التحديث من السيرفر. جاري عرض البيانات المحلية.' 
            : e.toString().replaceAll('Exception: ', '');

        emit(DashboardError(message: errorMsg));
        
        // إذا كان الخطأ برمجي/أعمال (ليس نت)، لا نظهر لافتة "أوفلاين" الحمراء
        final cached = await _loadFromLocal(isOffline: isNetworkError);
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

    // +++ DAB-4: درع الابتلاع الآمن لمنع صف تالف واحد من تدمير الداشبورد بالكامل +++
    final List<VisitModel> visits = [];
    for (var row in rawVisits) {
      try { visits.add(VisitModel.fromJson(row)); } 
      catch (e) { developer.log('[DashboardBloc] Skipped corrupt visit row: $e'); }
    }

    final List<ProductModel> products = [];
    for (var row in rawProducts) {
      try { products.add(ProductModel.fromJson(row)); } 
      catch (e) { developer.log('[DashboardBloc] Skipped corrupt product row: $e'); }
    }

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

    // +++ الكي الجراحي: قراءة الكاش إذا كانت قاعدة البيانات فارغة لمنع التصفير الوهمي +++
    final int salesInCompleted = visits.isNotEmpty
        ? visits.where((v) => v.status == 'Completed' && v.outcome == 'Sale').length
        : (int.tryParse(allData['cached_sales_in_completed'] ?? '0') ?? 0);

    final pendingSyncs = await _db.getPendingSyncs();
    // +++ تصفية السجلات السليمة للأوفلاين +++
    final int offlineCount = pendingSyncs.where((p) => !(p['type']?.toString().startsWith('quarantined_') ?? false)).length;
    // +++ الكي الجراحي: حساب الفواتير المرفوضة نهائياً (الجثث) لتنبيه المندوب +++
    final int quarantinedCount = pendingSyncs.where((p) => p['type']?.toString().startsWith('quarantined_') ?? false).length;

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
      quarantinedVisits: quarantinedCount,
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
  

  // +++ مسح الجثث من الخزنة بعد تسويتها +++
  Future<void> _onClearQuarantine(
    ClearQuarantineEvent event,
    Emitter<DashboardState> emit,
  ) async {
    await _db.clearAllQuarantinedSyncs();
    if (state is DashboardLoaded) {
      emit((state as DashboardLoaded).copyWith(
        quarantinedVisits: 0,
        actionSuccessMessage: 'تمت تسوية الفواتير المرفوضة ومسحها 🧹',
      ));
    }
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
        emit(DashboardError(message: 'استجابة غير صالحة من الخادم.'));
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

      // +++:تخزين الذاكرة عبر المستودع +++
      await _dashboardRepo.cacheDashboardData({
        'is_authorized': isAuthorized.toString(),
        'is_on_break': isOnBreak.toString(), // +++ إصلاح ثغرة الاستراحة الشبح (تزامن إجباري مع السيرفر) +++
        'cached_driver_name': data['driver_name']?.toString() ?? '',
        'cached_sales_in_completed': (countsData?['sales_in_completed']?.toString() ?? '0'), // +++ سد فجوة الكاش +++
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
        // +++ الكي الجراحي: احترام قفل المزامنة الموحد (الـ bool) وتوثيق التخطي الصامت +++
        final bool syncRan = await _syncRepository.syncDown();
        if (!syncRan) {
          developer.log('[DashboardBloc] SyncDown skipped during fetch (already running).');
        }
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
             DashboardError(
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
      // +++ الكي الجراحي (البند 1): تغليف بيانات الأوفلاين المسطحة لتطابق شكل الـ API وتفهمها الشاشة +++
      try {
        final localTransfers = await _db.getIncomingTransfers();
        if (localTransfers.isNotEmpty) {
          if (state is DashboardLoaded) {
            final wrappedData = {
              'items': localTransfers.map((t) => {
                'real_transfer_id': t['transfer_id'],
                'product_variant_id': t['product_variant_id'],
                'product_name': t['product_name'],
                'delta_cartons': t['delta_cartons'],
                'delta_packs': t['delta_packs'],
                'status': t['status'],
              }).toList()
            };
            emit((state as DashboardLoaded).copyWith(pendingTransfer: wrappedData));
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
    
    // +++ DAB-2: أخذ لقطة للحالة (Snapshot) قبل مسح الحوالة لاسترجاعها عند الفشل +++
    final snapshot = state as DashboardLoaded;
    emit(snapshot.copyWith(clearPendingTransfer: true));

    try {
      // +++ الإصلاح: توجيه الرد للـ SyncRepository المحصن بدلاً من الـ Repo القديم +++
      final wasSentLive = await _syncRepository.respondToTransfer(
        transferId: event.transferId, 
        responseStr: event.responseStatus,
      );

      if (wasSentLive) {
        final int? driverId = await _dashboardRepo.getDriverId();
        add(FetchDashboardData(driverId: driverId ?? 0));
      } else {
        emit(snapshot.copyWith(
          clearPendingTransfer: true,
          actionSuccessMessage: 'تم حفظ ردك. سيتم إرساله تلقائياً عند عودة الإنترنت 📡',
        ));
      }
    } catch (e) {
      developer.log('[DashboardBloc] Error responding to transfer: $e');
      emit(DashboardError(message: 'فشل إرسال الرد للإدارة: $e'));
      emit(snapshot); // +++ إعادة الحوالة للشاشة لكي يحاول المندوب مرة أخرى +++
    }
  }

  // ─── المحرك الصاروخي (Batch Handshake) ──────────────────────────────────
  Future<void> _onRespondToBatchTransfer(
    RespondToBatchTransfer event,
    Emitter<DashboardState> emit,
  ) async {
    if (state is! DashboardLoaded) return;
    final snapshot = state as DashboardLoaded;
    emit(snapshot.copyWith(clearPendingTransfer: true));

    // +++ البند 9: خدعة لتنظيف الحوالة العالقة إذا كانت الدفعة فارغة +++
    if (event.detailedTransfers.isEmpty) return;

    try {
      bool isAnyQueued = false;
      for (final t in event.detailedTransfers) {
        final tid = int.tryParse(t['transfer_id']?.toString() ?? '');
        if (tid == null) continue;
        
        // استلام النتيجة الحقيقية (أرسلت فوراً أم تخزنت أوفلاين)
        final wasSentLive = await _syncRepository.respondToTransfer(
          transferId: tid, 
          responseStr: t['status'] as String,
        );
        
        if (!wasSentLive) isAnyQueued = true;
      }

      if (!isAnyQueued) {
        final int? driverId = await _dashboardRepo.getDriverId();
        add(FetchDashboardData(driverId: driverId ?? 0));
      } else {
        emit(snapshot.copyWith(
          clearPendingTransfer: true,
          actionSuccessMessage: 'تم حفظ ردك. سيتم إرساله تلقائياً عند عودة الإنترنت 📡',
        ));
      }
    } catch (e) {
      developer.log('[DashboardBloc] Error responding to batch: $e');
      // اصطياد الخطأ الصريح من السيرفر (4xx) الذي قمنا برميه الآن
      emit(DashboardError(message: e.toString().replaceAll('Exception: ', '')));
      emit(snapshot); // نعيد النافذة ليتدارك المندوب الخطأ
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
        // +++ DAB-3: درع استخراج الرسائل الآمن لمنع كراش الـ NoSuchMethodError +++
        final data = e.response?.data;
        // +++ الكي الجراحي (البند 10): التوافق مع بنية أخطاء Pydantic/FastAPI +++
      final msg = (data is Map) ? (data['message'] ?? data['detail']) : 'فشل (استجابة غير متوقعة)';
        emit(DashboardError(message: 'خطأ: $msg'));
      }
    } catch (e) {
      // +++ الكي الجراحي: اصطياد كافة مشاكل الـ GPS ومنع الجلسة من البدء بدون إحداثيات +++
      if (e.toString().contains('GPS_DISABLED')) {
        emit(DashboardError(message: 'الرجاء تفعيل خدمة الموقع (GPS) لبدء العمل.'));
      } else if (e.toString().contains('GPS_DENIED_FOREVER')) {
        // +++ الكي الجراحي: توجيه المندوب للإعدادات بدلاً من تضليله +++
        emit(DashboardError(message: 'صلاحية الموقع مرفوضة نهائياً. افتح إعدادات الجهاز وامنح التطبيق صلاحية الموقع ثم أعد المحاولة.'));
      } else if (e.toString().contains('GPS_DENIED')) {
        emit(DashboardError(message: 'صلاحية الموقع مطلوبة لبدء العمل.'));
      } else if (e.toString().contains('FAKE_GPS_DETECTED')) {
        // +++ الدرع الأمني: فضح التلاعب أمام المندوب فوراً +++
        emit(DashboardError(message: 'تحذير أمني: تم رصد تطبيق تزوير موقع (Fake GPS). أوقفه لمتابعة العمل.'));
      } else if (e.toString().contains('GPS_TIMEOUT')) {
        emit(DashboardError(message: 'فشل تحديد الموقع. الرجاء التأكد من قوة إشارة الـ GPS والمحاولة في مكان مفتوح.'));
      } else {
        emit(DashboardError(message: 'حدث خطأ غير متوقع: ${e.toString().replaceAll('Exception: ', '')}'));
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

      final data = e.response?.data;
      // +++ الكي الجراحي (البند 10): التوافق مع بنية أخطاء Pydantic/FastAPI +++
      final msg = (data is Map) ? (data['message'] ?? data['detail']) : 'فشل (استجابة غير متوقعة)';
      emit(DashboardError(message: isOffline 
          ? 'لا يمكن إنهاء العمل وأنت أوفلاين. يجب الاتصال بالإنترنت لمطابقة العهدة وتسليمها.' 
          : 'خطأ: $msg'));
    } catch (e) {
      emit(DashboardError(message: 'حدث خطأ أثناء إنهاء الجلسة.'));
    }
  }

  Future<void> _onToggleBreak(ToggleBreakEvent event, Emitter<DashboardState> emit) async {
    try {
      // نستقبل النتيجة الحقيقية (أونلاين أم أوفلاين)
      final wasSentLive = await _dashboardRepo.toggleBreak(event.driverId, event.action);
      
      if (state is DashboardLoaded) {
        final actionText = event.action == 'start' ? 'تم بدء الاستراحة' : 'تم إنهاء الاستراحة';
        // +++ رسالة صادقة للمندوب بناءً على حالة الشبكة +++
        final successMsg = wasSentLive ? '$actionText (مسجلة).' : '$actionText (محفوظة أوفلاين 📡).';
        emit((state as DashboardLoaded).copyWith(actionSuccessMessage: successMsg));
      }
      add(FetchDashboardData(driverId: event.driverId));
      
    } on DioException catch (e) {
      if (e.response?.statusCode == 401) return; // +++ الكي الجراحي لـ Bug 6: منع الشبح والـ SnackBar الأحمر عند انتهاء الجلسة +++
      if (e.response?.statusCode == 404) {
        await _dashboardRepo.clearSessionLocally();
        if (state is DashboardLoaded) emit((state as DashboardLoaded).copyWith(actionSuccessMessage: 'الجلسة غير موجودة على السيرفر! تم إعادة الضبط 🧹'));
        add(FetchDashboardData(driverId: event.driverId));
        return;
      }
      final data = e.response?.data;
      // +++ الكي الجراحي (البند 10): التوافق مع بنية أخطاء Pydantic/FastAPI +++
      final msg = (data is Map) ? (data['message'] ?? data['detail']) : 'فشل (استجابة غير متوقعة)';
      emit(DashboardError(message: 'خطأ: $msg'));
    } catch (e) {
      emit(DashboardError(message: 'فشل في عملية الاستراحة.'));
    }
  }
} // +++ الكي الجراحي: هذا القوس اللي طار وكسرلك الملف كله! +++