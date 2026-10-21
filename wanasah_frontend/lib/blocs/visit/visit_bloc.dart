// File: lib/blocs/visit/visit_bloc.dart

import 'package:flutter_bloc/flutter_bloc.dart';
import 'dart:developer' as developer;
import 'package:dio/dio.dart';
import '../../core/db/local_database.dart';
import '../../models/product_model.dart';
import '../../repositories/sync_repository.dart';
import '../../features/visits/application/completed_visit_restorer.dart';
import '../../features/visits/application/visit_cart_policy.dart';
import '../../features/visits/application/visit_submission_service.dart';
import '../../features/visits/application/visit_event.dart';
import '../../features/visits/application/visit_state.dart';

export '../../features/visits/application/visit_event.dart';
export '../../features/visits/application/visit_state.dart';

// ============================================================================
// 3. العقل المدبر (Bloc)
// ============================================================================
class VisitBloc extends Bloc<VisitEvent, VisitState> {
  final LocalDatabase _db;
  final VisitSubmissionService _submissionService;

  VisitBloc({LocalDatabase? db, SyncRepository? syncRepo})
    : _db = db ?? LocalDatabase.instance,
      _submissionService = VisitSubmissionService(syncRepo ?? SyncRepository()),
      super(VisitLoading()) {
    on<LoadVisitCatalog>(_onLoadCatalog);
    on<LoadCompletedVisitData>(
      _onLoadCompletedVisitData,
    ); // +++ تسجيل المستمع +++
    on<AddOrUpdateCartItem>(_onAddOrUpdateCartItem);
    on<RemoveCartItem>(_onRemoveCartItem);
    on<UpdateCashCollected>(_onUpdateCashCollected);
    on<UpdateDebtPaid>(_onUpdateDebtPaid); // +++ تسجيل المستمع الجديد +++
    on<SubmitVisit>(_onSubmitVisit); // +++ تسجيل حدث الإنهاء +++
  }

  Future<void> _onLoadCatalog(
    LoadVisitCatalog event,
    Emitter<VisitState> emit,
  ) async {
    try {
      // +++ حل خطأ التحويل النوعي (Type Casting) +++
      final List<Map<String, dynamic>> rawProducts = await _db.getProducts();
      final List<ProductModel> products =
          rawProducts.map((p) => ProductModel.fromJson(p)).toList();

      emit(VisitReady(catalog: products, shopBalance: event.shopBalance));
    } catch (e) {
      developer.log('[VisitBloc] Error loading catalog: $e');
      // +++ حل مشكلة التحميل اللانهائي بإرسال حالة خطأ +++
      emit(
        const VisitError(
          'حدث خطأ أثناء تحميل المنتجات. الرجاء المحاولة لاحقاً.',
        ),
      );
    }
  }

  Future<void> _onLoadCompletedVisitData(
    LoadCompletedVisitData event,
    Emitter<VisitState> emit,
  ) async {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    try {
      final restoredCart = restoreCompletedVisitCart(
        catalog: currentState.catalog,
        cartItemsJson: event.cartItemsJson,
        returnsJson: event.returnsJson,
      );

      emit(
        currentState.copyWith(
          cart: restoredCart,
          cashCollected: event.cashCollected,
          debtPaid: event.debtPaid,
          notes: event.notes,
        ),
      );
    } catch (e) {
      developer.log('[VisitBloc] Error restoring completed visit: $e');
      emit(const VisitError('فشل استعادة بيانات الفاتورة السابقة.'));
      emit(currentState);
    }
  }

  void _onAddOrUpdateCartItem(
    AddOrUpdateCartItem event,
    Emitter<VisitState> emit,
  ) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    final result = applyVisitCartItem(
      currentCart: currentState.cart,
      item: event.item,
    );

    if (!result.isAccepted) {
      developer.log(
        '[VisitBloc] Inventory Blocked: Not enough stock for ${event.item.name}',
      );
      emit(VisitError(result.errorMessage!));
      emit(currentState);
      return;
    }

    emit(currentState.copyWith(cart: result.cart));
  }

  void _onRemoveCartItem(RemoveCartItem event, Emitter<VisitState> emit) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(
      currentState.copyWith(
        cart: removeVisitCartItem(
          currentCart: currentState.cart,
          productVariantId: event.productVariantId,
        ),
      ),
    );
  }

  void _onUpdateCashCollected(
    UpdateCashCollected event,
    Emitter<VisitState> emit,
  ) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(currentState.copyWith(cashCollected: event.amount));
  }

  void _onUpdateDebtPaid(UpdateDebtPaid event, Emitter<VisitState> emit) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(currentState.copyWith(debtPaid: event.amount));
  }

  Future<void> _onSubmitVisit(
    SubmitVisit event,
    Emitter<VisitState> emit,
  ) async {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(VisitLoading());

    try {
      await _submissionService.submit(
        visitId: event.visitId,
        outcome: event.outcome,
        notes: event.notes,
        debtPaid: event.debtPaid,
        cashCollected: currentState.cashCollected,
        cart: currentState.cart,
      );
      emit(VisitSubmissionSuccess());
    } catch (e) {
      developer.log('[VisitBloc] Error submitting visit: $e');
      String errorMsg = 'حدث خطأ أثناء حفظ الفاتورة في الخزنة المحلية.';

      if (e is DioException &&
          e.response?.data != null &&
          e.response!.data is Map) {
        errorMsg =
            e.response!.data['message'] ??
            e.response!.data['detail'] ??
            'رفض السيرفر العملية (${e.response!.statusCode})';
      }

      emit(VisitError(errorMsg));
      emit(currentState);
    }
  }

  // Step 4.4b: Memory leak shield — reserved for future Stream/Timer disposal
  // ignore: unnecessary_overrides
}
