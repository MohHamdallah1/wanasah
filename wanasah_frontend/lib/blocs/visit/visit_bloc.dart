// File: lib/blocs/visit/visit_bloc.dart

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';
import 'dart:developer' as developer;
import 'package:dio/dio.dart';
import '../../core/db/local_database.dart';
import '../../models/product_model.dart';
import '../../models/cart_item_model.dart';
import '../../repositories/sync_repository.dart'; // +++ للتعامل مع الخزنة وحفظ الفاتورة +++

// ============================================================================
// 1. الأوامر (Events)
// ============================================================================
abstract class VisitEvent extends Equatable {
  const VisitEvent();
  @override
  List<Object?> get props => [];
}

class LoadVisitCatalog extends VisitEvent {
  final double shopBalance;
  const LoadVisitCatalog(this.shopBalance);
  @override
  List<Object?> get props => [shopBalance];
}

class AddOrUpdateCartItem extends VisitEvent {
  final CartItemModel item;
  const AddOrUpdateCartItem(this.item);
  @override
  List<Object?> get props => [item];
}

class RemoveCartItem extends VisitEvent {
  final int productVariantId;
  const RemoveCartItem(this.productVariantId);
  @override
  List<Object?> get props => [productVariantId];
}

class UpdateCashCollected extends VisitEvent {
  final double amount;
  const UpdateCashCollected(this.amount);
  @override
  List<Object?> get props => [amount];
}

// +++ سد ثغرة التضارب المالي: حدث لتحديث الدين اللحظي +++
class UpdateDebtPaid extends VisitEvent {
  final double amount;
  const UpdateDebtPaid(this.amount);
  @override
  List<Object?> get props => [amount];
}

// +++ إضافة الحدث المفقود الذي سيوجه الضربة النهائية +++
class SubmitVisit extends VisitEvent {
  final int visitId;
  final String outcome;
  final String? notes;
  final double debtPaid; // +++ إضافة حقل سداد الدين +++
  const SubmitVisit({
    required this.visitId,
    required this.outcome,
    required this.debtPaid,
    this.notes,
  });
  @override
  List<Object?> get props => [visitId, outcome, debtPaid, notes];
}

// ============================================================================
// 2. الحالات (States)
// ============================================================================
abstract class VisitState extends Equatable {
  const VisitState();
  @override
  List<Object?> get props => [];
}

class VisitLoading extends VisitState {}

// +++ حالة لعرض رسائل SnackBar عند الأخطاء اللحظية أو الجسيمة +++
class VisitError extends VisitState {
  final String message;
  const VisitError(this.message);
  @override
  List<Object?> get props => [message];
}

// +++ حالة النجاح لإغلاق الشاشة +++
class VisitSubmissionSuccess extends VisitState {}

class VisitReady extends VisitState {
  final List<ProductModel> catalog; // قائمة المنتجات للبحث السريع
  final List<CartItemModel> cart; // السلة الذكية المدمجة
  final double shopBalance;
  final double cashCollected;
  final double debtPaid; // +++ المتغير المحاسبي المفقود +++

  const VisitReady({
    required this.catalog,
    this.cart = const [],
    required this.shopBalance,
    this.cashCollected = 0.0,
    this.debtPaid = 0.0, // +++
  });

  // --- حسابات الـ BLoC اللحظية (مدرسة الاستبدال العيني) ---
  double get totalSales =>
      cart.fold(0.0, (sum, item) => sum + item.totalSalePrice);
  double get totalReturns =>
      cart.fold(0.0, (sum, item) => sum + item.totalReturnPrice);

  // +++ الكيّ الجراحي: المرتجعات قيمتها المالية صفر لأنها تُستبدل عيناً +++
  double get netInvoice => totalSales;

  // الذمة تتأثر بالمبيعات فقط ولا تتأثر بالتبديل
  double get expectedNewBalance =>
      (shopBalance + netInvoice) - cashCollected - debtPaid;

  VisitReady copyWith({
    List<ProductModel>? catalog,
    List<CartItemModel>? cart,
    double? shopBalance,
    double? cashCollected,
    double? debtPaid,
  }) {
    return VisitReady(
      catalog: catalog ?? this.catalog,
      cart: cart ?? this.cart,
      shopBalance: shopBalance ?? this.shopBalance,
      cashCollected: cashCollected ?? this.cashCollected,
      debtPaid: debtPaid ?? this.debtPaid,
    );
  }

  @override
  List<Object?> get props => [
    catalog,
    cart,
    shopBalance,
    cashCollected,
    debtPaid,
  ];
}

// ============================================================================
// 3. العقل المدبر (Bloc)
// ============================================================================
class VisitBloc extends Bloc<VisitEvent, VisitState> {
  final LocalDatabase _db;
  final SyncRepository _syncRepo;

  VisitBloc({LocalDatabase? db, SyncRepository? syncRepo})
    : _db = db ?? LocalDatabase.instance,
      _syncRepo = syncRepo ?? SyncRepository(),
      super(VisitLoading()) {
    on<LoadVisitCatalog>(_onLoadCatalog);
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

  void _onAddOrUpdateCartItem(
    AddOrUpdateCartItem event,
    Emitter<VisitState> emit,
  ) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    // +++ حل مشكلة التعليق الصامت: إرسال رسالة خطأ للواجهة ثم العودة للسلة فوراً +++
    if (!event.item.hasEnoughInventory) {
      developer.log(
        '[VisitBloc] Inventory Blocked: Not enough stock for ${event.item.name}',
      );
      emit(
        VisitError(
          'عفواً، كمية ${event.item.name} المطلوبة غير متوفرة في سيارتك.',
        ),
      );
      emit(
        currentState,
      ); // إجبار الواجهة على إبقاء السلة مفتوحة بعد إظهار الخطأ
      return;
    }

    final updatedCart = List<CartItemModel>.from(currentState.cart);
    final index = updatedCart.indexWhere(
      (i) => i.productVariantId == event.item.productVariantId,
    );

    if (index >= 0) {
      updatedCart[index] = event.item; // تحديث
    } else {
      updatedCart.add(event.item); // إضافة جديدة
    }

    emit(currentState.copyWith(cart: updatedCart));
  }

  void _onRemoveCartItem(RemoveCartItem event, Emitter<VisitState> emit) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    final updatedCart =
        currentState.cart
            .where((i) => i.productVariantId != event.productVariantId)
            .toList();
    emit(currentState.copyWith(cart: updatedCart));
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

  // +++ الحدث المعماري الأضخم: تجهيز الفاتورة وإرسالها للخزنة السرية +++
  Future<void> _onSubmitVisit(
    SubmitVisit event,
    Emitter<VisitState> emit,
  ) async {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    emit(VisitLoading()); // إظهار مؤشر التحميل أثناء التشفير والحفظ

    try {
      // 1. تجميع المبيعات والعينات (الصنف الذي فيه مبيع أو عينة يذهب لـ cart_items ليفهمه السيرفر)
      final List<Map<String, dynamic>> cartItems =
          currentState.cart
              .where(
                (i) =>
                    i.cartons > 0 ||
                    i.packs > 0 ||
                    i.sampleCartons > 0 ||
                    i.samplePacks > 0,
              )
              .map(
                (i) => {
                  'product_variant_id': i.productVariantId,
                  'quantity': i.cartons,
                  'packs': i.packs,
                  'sample_cartons': i.sampleCartons,
                  'sample_packs': i.samplePacks,
                  'sample_reason':
                      i.sampleReason, // +++ إرسال سبب العينة الجديد للسيرفر +++
                },
              )
              .toList();

      // 2. تجميع المرتجعات والتوالف
      final List<Map<String, dynamic>> returns =
          currentState.cart
              .where((i) => i.returnCartons > 0 || i.returnPacks > 0)
              .map(
                (i) => {
                  'product_variant_id': i.productVariantId,
                  'cartons': i.returnCartons,
                  'packs': i.returnPacks,
                  'return_type': i.returnType,
                  // تم حذف 'reason': i.returnReason بالكامل لسد الخطأ
                },
              )
              .toList();

      // 3. بناء الـ Payload المطابق 100% للسيرفر بعد التحديث
      final payload = {
        'outcome': event.outcome,
        'notes': event.notes ?? '',
        'cash_collected': currentState.cashCollected,
        'debt_paid': event.debtPaid,
      };

      // +++ السماح بإرسال محتويات السلة (العينات والمرتجعات) حتى في حالة NoSale +++
      if (event.outcome == 'Sale' || event.outcome == 'NoSale') {
        if (cartItems.isNotEmpty) payload['cart_items'] = cartItems;
        if (returns.isNotEmpty) payload['returns'] = returns;

        if (event.outcome == 'NoSale') {
          payload['no_sale_reason'] = event.notes ?? '';
        }
      }

      // 5. الضرب المباشر على الخزنة السرية (SyncRepository)
      await _syncRepo.saveInvoice(visitId: event.visitId, payload: payload);

      // إعلان نجاح العملية لتغلق الشاشة
      emit(VisitSubmissionSuccess());
    } catch (e) {
      developer.log('[VisitBloc] Error submitting visit: $e');
      String errorMsg = 'حدث خطأ أثناء حفظ الفاتورة في الخزنة المحلية.';

      // +++ الكيّ الجراحي: التقاط رسالة الرفض الصريحة من السيرفر وعرضها للمندوب +++
      if (e is DioException &&
          e.response?.data != null &&
          e.response!.data is Map) {
        errorMsg =
            e.response!.data['message'] ??
            'رفض السيرفر العملية (${e.response!.statusCode})';
      }

      emit(VisitError(errorMsg));
      emit(currentState); // حماية البيانات: العودة للسلة فوراً في حال فشل الحفظ
    }
  }
}
