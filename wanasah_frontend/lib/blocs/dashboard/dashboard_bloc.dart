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
import '../../core/errors/api_failure_exception.dart';
import '../../services/location_service.dart';
import '../../repositories/dashboard_repository.dart';
import '../../features/work_session/application/work_session_coordinator.dart';
import '../../features/work_session/application/work_session_action_issue.dart';
import '../../features/work_session/application/work_session_failure.dart';
import '../../features/work_session/application/work_session_location_source.dart';
import '../../features/work_session/application/work_session_outcome.dart';
import '../../features/work_session/data/work_session_remote_data_source.dart';
import '../../features/work_session/data/work_session_snapshot.dart';
import '../../features/work_session/presentation/work_session_result_message.dart';
import '../../features/recovery/application/recovery_reader.dart';
import '../../features/recovery/application/recovery_sync_coordinator.dart';
import '../../features/recovery/data/recovery_data_source.dart';
import '../../features/recovery/data/recovery_sync_executor.dart';
import '../../features/custody/application/custody_coordinator.dart';
import '../../features/custody/domain/transfer_decision.dart';
import '../../features/custody/domain/non_sellable_custody.dart';
import '../../features/custody/domain/stock_disclosure.dart';
import '../../features/custody/domain/pending_return_custody.dart';

class DashboardBloc extends Bloc<DashboardEvent, DashboardState> {
  final SyncRepository _syncRepository;
  final LocalDatabase _db;
  final DashboardRepository _dashboardRepo;
  final WorkSessionCoordinator _workSessionCoordinator;
  final RecoveryReader _recoveryReader;
  final RecoverySyncCoordinator _recoverySyncCoordinator;
  final CustodyCoordinator _custodyCoordinator;
  bool _workSessionRecoveryCompleted = false;
  // A confirmed denial must not be bypassed by an offline SQLite reload.
  bool _sellableAccessDenied = false;
  // Different event types execute concurrently despite per-type sequential
  // transformers. Authority transitions revoke all earlier custody reads.
  int _custodyAuthorityEpoch = 0;
  int? _custodySessionId;

  // +++ EVT-1: محول تسلسلي (Sequential Transformer) لإجبار البلوك على معالجة الأحداث بالدور ومنع السباق +++
  EventTransformer<T> _sequential<T>() {
    return (events, mapper) => events.asyncExpand(mapper);
  }

  DashboardBloc({
    SyncRepository? syncRepository,
    LocalDatabase? db,
    DashboardRepository? dashboardRepo,
    LocationService? locationService,
    WorkSessionCoordinator? workSessionCoordinator,
    RecoveryReader? recoveryReader,
    RecoverySyncCoordinator? recoverySyncCoordinator,
    CustodyCoordinator? custodyCoordinator,
  }) : _syncRepository = syncRepository ?? SyncRepository(),
       _db = db ?? LocalDatabase.instance,
       _dashboardRepo = dashboardRepo ?? DashboardRepository(),
       _workSessionCoordinator =
           workSessionCoordinator ??
           WorkSessionCoordinator(
             remote: ApiWorkSessionRemoteDataSource(),
             locationSource: DeviceWorkSessionLocationSource(
               locationService ?? LocationService.instance,
             ),
           ),
       _recoveryReader =
           recoveryReader ??
           RecoveryReader(
             dataSource: LocalRecoveryDataSource(
               database: db ?? LocalDatabase.instance,
             ),
           ),
       _custodyCoordinator =
           custodyCoordinator ?? CustodyCoordinator.defaults(),
       _recoverySyncCoordinator =
           recoverySyncCoordinator ??
           RecoverySyncCoordinator(
             reader:
                 recoveryReader ??
                 RecoveryReader(
                   dataSource: LocalRecoveryDataSource(
                     database: db ?? LocalDatabase.instance,
                   ),
                 ),
             executor: ExistingSyncRepositoryExecutor(
               repository: syncRepository ?? SyncRepository(),
             ),
           ),
       super(const DashboardInitial()) {
    // +++ ربط جميع الأحداث بالمحول التسلسلي لمنع الانهيار المعماري +++
    on<LoadDashboardData>(_onLoadDashboardData, transformer: _sequential());
    on<ForceSyncData>(_onForceSyncData, transformer: _sequential());
    on<FetchDashboardData>(_onFetchDashboardData, transformer: _sequential());
    on<CheckPendingTransfers>(
      _onCheckPendingTransfers,
      transformer: _sequential(),
    );
    on<RespondToTransfer>(_onRespondToTransfer, transformer: _sequential());
    on<RespondToBatchTransfer>(
      _onRespondToBatchTransfer,
      transformer: _sequential(),
    );
    on<StartSessionEvent>(_onStartSession, transformer: _sequential());
    on<EndSessionEvent>(_onEndSession, transformer: _sequential());
    on<ToggleBreakEvent>(_onToggleBreak, transformer: _sequential());
    on<ClearActionMessageEvent>((event, emit) {
      if (state is DashboardLoaded) {
        emit((state as DashboardLoaded).copyWith(clearActionMessage: true));
      }
    }, transformer: _sequential());
    on<ClearWorkSessionIssueEvent>((event, emit) {
      if (state is DashboardLoaded) {
        emit((state as DashboardLoaded).copyWith(clearWorkSessionIssue: true));
      }
    }, transformer: _sequential());
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

  // ─── ForceSyncData compatibility wiring ──────────────────────────────────
  /// Recovery owns durable sync classification. Dashboard only reloads its
  /// existing local read model after that feature-owned orchestration.
  Future<void> _onForceSyncData(
    ForceSyncData event,
    Emitter<DashboardState> emit,
  ) async {
    final previous = state is DashboardLoaded ? state as DashboardLoaded : null;
    final result = await _recoverySyncCoordinator.synchronize();

    developer.log(
      '[DashboardBloc] Recovery sync disposition: ${result.disposition.name}',
    );

    try {
      final loaded = await _loadFromLocal(
        isOffline: result.disposition == RecoverySyncDisposition.unresolved,
      );
      emit(loaded);
    } catch (error) {
      developer.log(
        '[DashboardBloc] Local reload after recovery sync failed: $error',
      );
      if (previous != null) {
        emit(previous.copyWith(
          isOffline: true,
          sellableStockDisclosure: stockDisclosureAfterFailure(
            previous.sellableStockDisclosure, denied: false),
          nonSellableStockDisclosure: stockDisclosureAfterFailure(
            previous.nonSellableStockDisclosure, denied: false),
        ));
      } else {
        emit(const DashboardInitial());
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
      try {
        visits.add(VisitModel.fromJson(row));
      } catch (e) {
        developer.log('[DashboardBloc] Skipped corrupt visit row: $e');
      }
    }

    final List<ProductModel> products = [];
    var localStockContractValid = true;
    for (var row in rawProducts) {
      try {
        products.add(ProductModel.fromJson(row));
      } catch (e) {
        localStockContractValid = false;
        developer.log('[DashboardBloc] Invalid local stock row: $e');
      }
    }
    // Do not show a partial SQLite catalog as the entire vehicle custody.
    if (!localStockContractValid) products.clear();

    // +++ القراءة من المستودع بدلاً من الخزنة مباشرة +++
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

    // +++   قراءة الكاش إذا كانت قاعدة البيانات فارغة لمنع التصفير الوهمي +++
    final int salesInCompleted =
        visits.isNotEmpty
            ? visits
                .where((v) => v.status == 'Completed' && v.outcome == 'Sale')
                .length
            : (int.tryParse(allData['cached_sales_in_completed'] ?? '0') ?? 0);

    final recovery = await _recoveryReader.read();
    final int quarantinedCount = recovery.blockedCount;
    final int offlineCount = recovery.pendingCount;

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

    var pendingReturnCustody = const <PendingReturnCustodyItem>[];
    try {
      pendingReturnCustody =
          await _custodyCoordinator.loadPendingReturnCustody();
    } catch (e) {
      developer.log(
        '[DashboardBloc] Local pending return custody read failed: $e',
      );
    }

    return DashboardLoaded(
      visits: visits,
      products: _sellableAccessDenied ? const <ProductModel>[] : products,
      sellableStockDisclosure: _sellableAccessDenied
          ? StockDisclosure.denied
          : (localStockContractValid && rawProducts.isNotEmpty
              ? StockDisclosure.stale
              : StockDisclosure.unavailable),
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
      pendingReturnCustody: pendingReturnCustody,
    );
  }

  // ─── FetchDashboardData (المحرك المالي الشامل المحصن) ─────────────────────────────
  Future<void> _onFetchDashboardData(
    FetchDashboardData event,
    Emitter<DashboardState> emit,
  ) async {
    // +++  لـ Bug 3: منع الشاشة البيضاء (Jank) وتفريغ الواجهة إذا كانت محملة مسبقاً +++
    if (state is! DashboardLoaded) emit(const DashboardLoading());

    WorkSessionRecoveryResult? restartRecovery;
    if (!_workSessionRecoveryCompleted) {
      restartRecovery = await _workSessionCoordinator.recoverActiveSession();
      if (restartRecovery.succeeded) {
        _workSessionRecoveryCompleted = true;
      }
    }

    try {
      // +++  لـ Bug 2: الاعتماد على المستودع لجلب البيانات +++
      final response = await _dashboardRepo.fetchDashboardRaw();

      // +++ الدرع النوعي النخبوي (Elite Cast): منع كراش الـ TypeError بدون طرد المندوب ظلماً بسبب تعقيدات Dart +++
      if (response.data is! Map) {
        emit(DashboardError(message: 'استجابة غير صالحة من الخادم.'));
        return;
      }
      final Map<String, dynamic> data = Map<String, dynamic>.from(
        response.data as Map,
      );

      final sessionData =
          data['active_session'] is Map
              ? Map<String, dynamic>.from(data['active_session'] as Map)
              : null;
      final sessionSnapshot = WorkSessionSnapshot.fromDashboardResponse(data);
      final bool sessionIsActive = sessionSnapshot.isActive;
      // New authoritative dashboard invalidates older custody reads, even
      // when the representative's session has changed between responses.
      _custodyAuthorityEpoch++;
      _custodySessionId = sessionSnapshot.sessionId;

      bool isAuthorized = false;
      final bool isOnBreak = sessionSnapshot.isOnBreak ?? false;
      final String? startTimeStr = sessionSnapshot.startTime;
      List<ProductModel> apiProducts = [];
      var sellableDisclosure = StockDisclosure.unavailable;

      if (sessionData != null) {
        isAuthorized = sessionData['is_authorized_to_sell'] == true;

        // +++ درع القوائم: حماية الـ List من الانهيار إذا أرسل السيرفر null أو Map بالخطأ +++
        final dynamic rawInv = sessionData['inventory'];
        if (rawInv is List) {
          try {
            // Parse the whole page before declaring any physical quantity live.
            // A bad row must not produce a partial or fabricated balance.
            apiProducts = rawInv
                .map((p) => ProductModel.fromJson(
                      Map<String, dynamic>.from(p as Map),
                    ))
                .toList();
            sellableDisclosure = StockDisclosure.verified;
          } on Object catch (error) {
            developer.log(
              '[DashboardBloc] Invalid custody inventory contract: $error',
            );
            apiProducts = <ProductModel>[];
          }
        } else {
          developer.log('[DashboardBloc] Custody inventory not disclosed');
        }
      }

      // Only an actually disclosed, parsed snapshot clears prior revocation.
      if (sellableDisclosure == StockDisclosure.verified) {
        _sellableAccessDenied = false;
      }
      if (_sellableAccessDenied) {
        apiProducts = <ProductModel>[];
        sellableDisclosure = StockDisclosure.denied;
      }

      final financials =
          data['financials'] is Map
              ? Map<String, dynamic>.from(data['financials'] as Map)
              : null;
      final countsData =
          data['counts'] is Map
              ? Map<String, dynamic>.from(data['counts'] as Map)
              : null;

      // +++:تخزين الذاكرة عبر المستودع +++
      await _dashboardRepo.cacheDashboardData({
        'is_authorized': isAuthorized.toString(),
        'is_on_break':
            isOnBreak
                .toString(), // +++ إصلاح ثغرة الاستراحة الشبح (تزامن إجباري مع السيرفر) +++
        'cached_driver_name': data['driver_name']?.toString() ?? '',
        'cached_sales_in_completed':
            (countsData?['sales_in_completed']?.toString() ??
                '0'), // +++ سد فجوة الكاش +++
        'cached_assigned_region': data['assigned_region']?.toString() ?? '',
        'cached_total_sales_cash':
            (financials?['total_sales_cash']?.toString() ?? '0.0'),
        'cached_total_debt_paid':
            (financials?['total_debt_paid']?.toString() ?? '0.0'),
        'cached_debt_payments_count':
            (financials?['debt_payments_count']?.toString() ?? '0'),
        'cached_total_cash_overall':
            (financials?['total_cash_overall']?.toString() ?? '0.0'),
        'cached_total_visits':
            ((countsData?['total_pending'] ?? 0) +
                    (countsData?['total_completed'] ?? 0))
                .toString(),
        'cached_completed_visits':
            (countsData?['total_completed']?.toString() ?? '0'),
        'cached_pending_visits':
            (countsData?['total_pending']?.toString() ?? '0'),
        'cached_is_active_session': sessionIsActive.toString(),
        'cached_session_start_time': startTimeStr ?? '',
      });

      try {
        // +++   احترام قفل المزامنة الموحد (الـ bool) وتوثيق التخطي الصامت +++
        final bool syncRan = await _syncRepository.syncDown();
        if (!syncRan) {
          developer.log(
            '[DashboardBloc] SyncDown skipped during fetch (already running).',
          );
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
          products: apiProducts,
          sellableStockDisclosure: sellableDisclosure,
          // +++  لـ Bug 5: الاعتماد على الإجمالي المحلي إذا كان السيرفر معطلاً أو البيانات ناقصة +++
          totalVisits:
              countsData != null
                  ? (int.tryParse(
                            countsData['total_pending']?.toString() ?? '0',
                          ) ??
                          0) +
                      (int.tryParse(
                            countsData['total_completed']?.toString() ?? '0',
                          ) ??
                          0)
                  : localData.totalVisits,
          completedVisits:
              countsData?['total_completed'] != null
                  ? (int.tryParse(countsData!['total_completed'].toString()) ??
                      0)
                  : localData.completedVisits,
          pendingVisits:
              countsData?['total_pending'] != null
                  ? (int.tryParse(countsData!['total_pending'].toString()) ?? 0)
                  : localData.pendingVisits,
          offlineVisits: localData.offlineVisits,
          salesInCompleted:
              countsData?['sales_in_completed'] != null
                  ? (int.tryParse(
                        countsData!['sales_in_completed'].toString(),
                      ) ??
                      0)
                  : localData.salesInCompleted,
          driverName: data['driver_name'] ?? localData.driverName,
          assignedRegion: data['assigned_region'] ?? localData.assignedRegion,
          // +++  (Float Precision Loss): قراءة المبالغ كنصوص وتحويلها بأمان لمنع الـ Crash +++
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
          // +++  لـ Bug 5: حفظ رسالة النجاح من الطمس أثناء تحديث البيانات +++
          actionSuccessMessage:
              (state is DashboardLoaded)
                  ? (state as DashboardLoaded).actionSuccessMessage
                  : null,
          workSessionIssue:
              (state is DashboardLoaded)
                  ? (state as DashboardLoaded).workSessionIssue
                  : null,
          pendingReturnCustody: localData.pendingReturnCustody,
        ),
      );

      // +++ التحقق التلقائي من الحوالات المعلقة إذا كانت الجلسة نشطة +++
      if (sessionIsActive) {
        add(CheckPendingTransfers());
      }
    } on DioException catch (e) {
      if (e.response?.statusCode == 401 || e.response?.statusCode == 403) {
        _custodyAuthorityEpoch++;
        _custodySessionId = null;
        _sellableAccessDenied = true;
        if (state is DashboardLoaded) {
          emit((state as DashboardLoaded).copyWith(
            products: const <ProductModel>[],
            nonSellableCustody: const <NonSellableCustodyItem>[],
            sellableStockDisclosure: StockDisclosure.denied,
            nonSellableStockDisclosure: StockDisclosure.denied,
            clearPendingTransfer: true,
            clearRefreshIssue: true,
          ));
        } else {
          emit(DashboardError(message: 'dashboard_access_denied'));
        }
        return;
      }

      final status = e.response?.statusCode;
      final isConnectivityFailure =
          e.type == DioExceptionType.connectionTimeout ||
          e.type == DioExceptionType.receiveTimeout ||
          e.type == DioExceptionType.sendTimeout ||
          e.type == DioExceptionType.connectionError ||
          e.type == DioExceptionType.unknown;
      final isServiceFailure = status != null && status >= 500;
      final requestId = _requestIdFromDio(e);

      developer.log(
        '[DashboardBloc] Dashboard refresh failed: '
        'type=${e.type.name}, status=$status, requestId=$requestId',
      );

      if (isConnectivityFailure || isServiceFailure) {
        try {
          var localData = await _loadFromLocal(
            isOffline: isConnectivityFailure,
          );
          if (restartRecovery?.succeeded == true) {
            localData = _applyRecoveredWorkSession(
              localData,
              restartRecovery!.session!,
            );
          }
          emit(
            localData.copyWith(
              refreshIssue: DashboardRefreshIssue(
                kind:
                    isConnectivityFailure
                        ? DashboardRefreshIssueKind.connectivity
                        : DashboardRefreshIssueKind.service,
                statusCode: status,
                requestId: requestId,
              ),
            ),
          );
          return;
        } catch (localErr) {
          developer.log(
            '[DashboardBloc] Cached dashboard fallback failed: $localErr',
          );
        }
      }

      emit(
        DashboardError(
          message:
              isServiceFailure
                  ? 'dashboard_service_unavailable'
                  : 'dashboard_request_failed',
        ),
      );
    } catch (e) {
      developer.log('[DashboardBloc] Parsing Error: $e');
      emit(DashboardError(message: 'dashboard_processing_failure'));
    }
  }

  String? _requestIdFromDio(DioException error) {
    final headers = error.response?.headers;
    final headerRequestId =
        headers?.value('x-request-id') ?? headers?.value('x-correlation-id');
    if (headerRequestId != null && headerRequestId.trim().isNotEmpty) {
      return headerRequestId.trim();
    }

    final body = error.response?.data;
    if (body is Map) {
      final dynamic requestId =
          body['request_id'] ??
          body['requestId'] ??
          body['correlation_id'] ??
          body['correlationId'];
      final normalized = requestId?.toString().trim();
      if (normalized != null && normalized.isNotEmpty) {
        return normalized;
      }
    }
    return null;
  }

  Future<void> _onCheckPendingTransfers(
    CheckPendingTransfers event,
    Emitter<DashboardState> emit,
  ) async {
    if (state is! DashboardLoaded) return;
    final snapshot = state as DashboardLoaded;
    if (_sellableAccessDenied) return;
    final authorityEpoch = _custodyAuthorityEpoch;
    final authoritySessionId = _custodySessionId;

    var pendingTransfer = snapshot.pendingTransfer;
    var nonSellableCustody = snapshot.nonSellableCustody;
    var pendingReturnCustody = snapshot.pendingReturnCustody;
    var pendingReadCompleted = false;
    var nonSellableDisclosure = snapshot.nonSellableStockDisclosure;
    var pendingDenied = false;

    try {
      pendingTransfer = await _custodyCoordinator.loadPendingTransfers();
      pendingReadCompleted = true;
    } catch (e) {
      if (_isCustodyDenied(e)) {
        pendingTransfer = null;
        pendingDenied = true;
      }
      developer.log('[DashboardBloc] Custody pending-transfer read failed: $e');
    }

    try {
      nonSellableCustody = await _custodyCoordinator.loadNonSellableCustody();
      nonSellableDisclosure = StockDisclosure.verified;
    } catch (e) {
      if (_isCustodyDenied(e)) {
        nonSellableCustody = const <NonSellableCustodyItem>[];
        nonSellableDisclosure = StockDisclosure.denied;
      } else {
        nonSellableDisclosure = stockDisclosureAfterFailure(
          snapshot.nonSellableStockDisclosure, denied: false);
      }
      developer.log('[DashboardBloc] Non-sellable custody read failed: $e');
    }

    try {
      pendingReturnCustody =
          await _custodyCoordinator.loadPendingReturnCustody();
    } catch (e) {
      developer.log('[DashboardBloc] Pending return custody read failed: $e');
    }

    if (state is! DashboardLoaded ||
        _sellableAccessDenied ||
        authorityEpoch != _custodyAuthorityEpoch ||
        authoritySessionId != _custodySessionId) {
      // Never allow an old response to resurrect revoked or previous-session
      // custody as verified. No partial or synthetic zero disclosure.
      return;
    }
    emit(
      (state as DashboardLoaded).copyWith(
        pendingTransfer: pendingTransfer,
        clearPendingTransfer: pendingDenied || (pendingReadCompleted && pendingTransfer == null),
        nonSellableCustody: nonSellableCustody,
        nonSellableStockDisclosure: nonSellableDisclosure,
        pendingReturnCustody: pendingReturnCustody,
      ),
    );
  }

  bool _isCustodyDenied(Object error) {
    final status = error is ApiFailureException
        ? error.apiFailure.status
        : error is DioException ? error.response?.statusCode : null;
    return status == 401 || status == 403;
  }

  Future<void> _onRespondToTransfer(
    RespondToTransfer event,
    Emitter<DashboardState> emit,
  ) async {
    if (state is! DashboardLoaded) return;
    final snapshot = state as DashboardLoaded;

    final status = switch (event.responseStatus) {
      'accepted' => TransferDecisionStatus.accepted,
      'rejected' => TransferDecisionStatus.rejected,
      _ => null,
    };
    if (status == null) {
      emit(DashboardError(message: 'رد الحوالة غير صالح.'));
      emit(snapshot);
      return;
    }

    try {
      final outcome = await _custodyCoordinator.respond([
        TransferDecision(
          transferId: event.transferId,
          status: status,
          reason: event.reason,
        ),
      ]);

      if (outcome.anyBlocked) {
        emit(
          DashboardError(
            message:
                'تعذر اعتماد رد العهدة بسبب تعارض مؤكد. بقي القرار محفوظاً للاسترداد.',
          ),
        );
        emit(snapshot);
        add(const CheckPendingTransfers());
      } else if (outcome.anyQueued || outcome.hasUnattempted) {
        emit(
          snapshot.copyWith(
            actionSuccessMessage:
                'تم حفظ رد العهدة بنفس القرار وسيُعاد التحقق منه عند عودة الاتصال.',
          ),
        );
        add(const CheckPendingTransfers());
      } else {
        emit(snapshot.copyWith(clearPendingTransfer: true));
        add(
          FetchDashboardData(driverId: await _dashboardRepo.getDriverId() ?? 0),
        );
      }
    } catch (e) {
      developer.log('[DashboardBloc] Custody transfer response failed: $e');
      emit(DashboardError(message: 'تعذر إكمال رد العهدة. أعد المحاولة.'));
      emit(snapshot);
    }
  }

  Future<void> _onRespondToBatchTransfer(
    RespondToBatchTransfer event,
    Emitter<DashboardState> emit,
  ) async {
    if (state is! DashboardLoaded) return;
    final snapshot = state as DashboardLoaded;

    if (event.decisions.isEmpty) {
      emit(snapshot.copyWith(clearPendingTransfer: true));
      return;
    }

    try {
      final outcome = await _custodyCoordinator.respond(event.decisions);
      if (outcome.anyBlocked) {
        emit(
          DashboardError(
            message:
                'تعذر اعتماد بعض قرارات العهدة بسبب تعارض مؤكد. بقيت الأدلة محفوظة للاسترداد.',
          ),
        );
        emit(snapshot);
        add(const CheckPendingTransfers());
      } else if (outcome.anyQueued || outcome.hasUnattempted) {
        emit(
          snapshot.copyWith(
            actionSuccessMessage:
                'تم حفظ قرارات العهدة غير المحسومة بنفس القيم دون اعتبارها مكتملة.',
          ),
        );
        add(const CheckPendingTransfers());
      } else {
        emit(snapshot.copyWith(clearPendingTransfer: true));
        add(
          FetchDashboardData(driverId: await _dashboardRepo.getDriverId() ?? 0),
        );
      }
    } catch (e) {
      developer.log('[DashboardBloc] Custody batch response failed: $e');
      emit(DashboardError(message: 'تعذر إكمال ردود العهدة. أعد المحاولة.'));
      emit(snapshot);
    }
  }

  Future<void> _onStartSession(
    StartSessionEvent event,
    Emitter<DashboardState> emit,
  ) async {
    final result = await _workSessionCoordinator.startSession();
    _completeWorkSessionAction(result, event.driverId, emit);
  }

  Future<void> _onEndSession(
    EndSessionEvent event,
    Emitter<DashboardState> emit,
  ) async {
    final result = await _workSessionCoordinator.endSession();
    _completeWorkSessionAction(result, event.driverId, emit);
  }

  Future<void> _onToggleBreak(
    ToggleBreakEvent event,
    Emitter<DashboardState> emit,
  ) async {
    final result = await _workSessionCoordinator.toggleBreak(
      start: event.action == 'start',
    );
    _completeWorkSessionAction(result, event.driverId, emit);
  }

  void _completeWorkSessionAction(
    WorkSessionOperationResult result,
    int driverId,
    Emitter<DashboardState> emit,
  ) {
    final message = workSessionResultMessage(result);

    if (result.isSuccess) {
      if (result.operation == WorkSessionOperation.start ||
          result.operation == WorkSessionOperation.end) {
        _custodyAuthorityEpoch++;
        _custodySessionId = null;
      }
      if (state is DashboardLoaded) {
        var next = state as DashboardLoaded;
        if (result.reconciledSession != null) {
          next = _applyRecoveredWorkSession(next, result.reconciledSession!);
        }
        if (result.operation == WorkSessionOperation.start ||
            result.operation == WorkSessionOperation.end) {
          next = next.copyWith(
            products: const <ProductModel>[],
            sellableStockDisclosure: StockDisclosure.unavailable,
            nonSellableCustody: const <NonSellableCustodyItem>[],
            nonSellableStockDisclosure: StockDisclosure.unavailable,
            clearPendingTransfer: true,
          );
        }
        emit(
          next.copyWith(
            actionSuccessMessage: message,
            clearWorkSessionIssue: true,
          ),
        );
      }
      add(FetchDashboardData(driverId: driverId));
      return;
    }

    final issue = WorkSessionActionIssue.fromResult(result);
    if (state is DashboardLoaded) {
      var next = state as DashboardLoaded;
      if (result.reconciledSession != null) {
        next = _applyRecoveredWorkSession(next, result.reconciledSession!);
      }

      emit(next.copyWith(workSessionIssue: issue, clearActionMessage: true));
    } else {
      emit(DashboardError(message: message));
    }

    final failure = result.failure;
    final shouldRefreshAuthoritativeState =
        result.reconciledSession != null ||
        (failure?.kind == WorkSessionFailureKind.businessRejected &&
            (failure?.status == 404 || failure?.status == 409));

    if (shouldRefreshAuthoritativeState) {
      add(FetchDashboardData(driverId: driverId));
    }
  }

  DashboardLoaded _applyRecoveredWorkSession(
    DashboardLoaded current,
    WorkSessionSnapshot session,
  ) {
    return DashboardLoaded(
      visits: current.visits,
      products: current.products,
      sellableStockDisclosure: current.sellableStockDisclosure,
      nonSellableStockDisclosure: current.nonSellableStockDisclosure,
      totalVisits: current.totalVisits,
      completedVisits: current.completedVisits,
      pendingVisits: current.pendingVisits,
      offlineVisits: current.offlineVisits,
      quarantinedVisits: current.quarantinedVisits,
      salesInCompleted: current.salesInCompleted,
      driverName: current.driverName,
      assignedRegion: current.assignedRegion,
      totalSalesCash: current.totalSalesCash,
      totalDebtPaid: current.totalDebtPaid,
      debtPaymentsCount: current.debtPaymentsCount,
      totalCashOverall: current.totalCashOverall,
      isActiveSession: session.isActive,
      activeSessionStartTime: session.startTime,
      isOnBreak:
          session.isActive ? (session.isOnBreak ?? current.isOnBreak) : false,
      isOffline: current.isOffline,
      refreshIssue: current.refreshIssue,
      pendingTransfer: current.pendingTransfer,
      nonSellableCustody: current.nonSellableCustody,
      pendingReturnCustody: current.pendingReturnCustody,
      actionSuccessMessage: current.actionSuccessMessage,
      workSessionIssue: current.workSessionIssue,
    );
  }
}
