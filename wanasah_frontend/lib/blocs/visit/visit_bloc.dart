// File: lib/blocs/visit/visit_bloc.dart

import 'package:flutter_bloc/flutter_bloc.dart';
import 'dart:developer' as developer;
import 'package:dio/dio.dart';
import '../../core/network/api_client.dart';
import '../../core/network/api_failure.dart';
import '../../features/visits/data/visit_field_client.dart';
import '../../features/visits/application/commercial/read_commercial_readiness.dart';
import '../../features/visits/application/returns/return_resolution_coordinator.dart';
import '../../features/visits/application/invoice/preview_visit_invoice.dart';
import '../../features/visits/application/invoice/read_committed_visit_invoice.dart';
import '../../features/visits/application/invoice/committed_invoice_outcome.dart';
import '../../features/visits/application/visit_command_evidence.dart';
import '../../features/visits/application/visit_action_policy.dart';
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

  late final ReadCommercialReadiness commercialReadiness;
  late final ReturnResolutionCoordinator returnResolution;
  late final PreviewVisitInvoice invoicePreview;
  late final ReadCommittedVisitInvoice committedInvoice;

  VisitBloc({LocalDatabase? db, SyncRepository? syncRepo, VisitFieldClient? fieldClient})
    : _db = db ?? LocalDatabase.instance,
      _submissionService = VisitSubmissionService(syncRepo ?? SyncRepository(),
        readPending: () => (db ?? LocalDatabase.instance).getPendingSyncs()),
      super(VisitLoading()) {
    final client = fieldClient ?? VisitFieldClient.withApiClient(ApiClient.instance);
    commercialReadiness = ReadCommercialReadiness.fromClient(client);
    returnResolution = ReturnResolutionCoordinator.fromClient(client);
    invoicePreview = PreviewVisitInvoice.fromClient(client);
    committedInvoice = ReadCommittedVisitInvoice.fromClient(client);
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

  Future<bool> hasUnresolvedVisit(int visitId) =>
      _submissionService.hasUnresolvedVisit(visitId);

  Future<void> _onSubmitVisit(
    SubmitVisit event,
    Emitter<VisitState> emit,
  ) async {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(VisitLoading());

    try {
      final disposition = await _submissionService.submit(
        visitId: event.visitId,
        outcome: event.outcome,
        notes: event.notes,
        debtPaid: event.debtPaid,
        cashCollected: currentState.cashCollected,
        cart: currentState.cart,
        exactCashCollected: event.exactCashCollected,
        exactDebtPaid: event.exactDebtPaid,
        resolvedReturns: event.resolvedReturns,
        saleConfirmation: event.saleConfirmation,
      );
      // A queued/lost-response command is never labeled committed. A failed
      // invoice read cannot turn a successful mutation into another submission.
      CommittedInvoiceOutcome? invoice;
      if (disposition == VisitSubmissionDisposition.confirmed && event.outcome == 'Sale') {
        try { invoice = await committedInvoice.execute(event.visitId); }
        catch (_) { invoice = const CommittedInvoiceInvalidResponse(); }
      }
      emit(VisitSubmissionSuccess(visitId: event.visitId,
        disposition: disposition, invoice: invoice));
    } catch (e) {
      // Keep structured evidence; never classify or log arbitrary server text.
      emit(VisitFieldSubmissionFailure(
        failure: e is DioException ? e.apiFailure : null,
        issue: e is VisitPriorCommandUnresolved ? 'unresolvedCommand' :
          e is VisitActionViolation ? e.issue.name :
          e is FormatException ? 'contract' : 'persistence',
      ));
      emit(currentState);
    }
  }

  // Step 4.4b: Memory leak shield — reserved for future Stream/Timer disposal
  // ignore: unnecessary_overrides
}
