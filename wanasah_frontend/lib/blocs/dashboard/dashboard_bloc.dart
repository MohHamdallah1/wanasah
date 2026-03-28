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

class DashboardBloc extends Bloc<DashboardEvent, DashboardState> {
  final SyncRepository _syncRepository;
  final LocalDatabase _db;

  DashboardBloc({SyncRepository? syncRepository, LocalDatabase? db})
    : _syncRepository = syncRepository ?? SyncRepository(),
      _db = db ?? LocalDatabase.instance,
      super(const DashboardInitial()) {
    on<LoadDashboardData>(_onLoadDashboardData);
    on<ForceSyncData>(_onForceSyncData);
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

  // ─── Helper: قراءة وتحويل البيانات من SQLite ─────────────────────────────
  Future<DashboardLoaded> _loadFromLocal({bool isOffline = false}) async {
    // جلب الصفوف الخام من SQLite
    final rawVisits = await _db.getVisits();
    final rawProducts = await _db.getProducts();

    // تحويل الصفوف إلى نماذج Dart
    final visits = rawVisits.map((row) => VisitModel.fromJson(row)).toList();

    final products =
        rawProducts.map((row) => ProductModel.fromJson(row)).toList();

    // ── احتساب الإحصائيات ───────────────────────────────────────────────
    final total = visits.length;
    final completed = visits.where((v) => v.status == 'Completed').length;
    final offline =
        visits.where((v) => v.status == 'Completed (Offline)').length;
    final pending = visits.where((v) => v.status == 'Pending').length;

    developer.log(
      '[DashboardBloc] Loaded: $total visits '
      '($completed done, $offline offline, $pending pending), '
      '${products.length} products.',
    );

    return DashboardLoaded(
      visits: visits,
      products: products,
      totalVisits: total,
      completedVisits: completed + offline, // المكتمل الفعلي + الأوفلاين
      pendingVisits: pending,
      offlineVisits: offline,
      isOffline: isOffline, // +++ إرسال الإشارة للواجهة +++
    );
  }
}
