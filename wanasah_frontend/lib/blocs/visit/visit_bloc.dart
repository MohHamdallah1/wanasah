// File: lib/blocs/visit/visit_bloc.dart

import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:equatable/equatable.dart';
import 'dart:developer' as developer;

import '../../core/db/local_database.dart';
import '../../models/product_model.dart';
import '../../models/cart_item_model.dart';

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

// ============================================================================
// 2. الحالات (States)
// ============================================================================
abstract class VisitState extends Equatable {
  const VisitState();
  @override
  List<Object?> get props => [];
}

class VisitLoading extends VisitState {}

class VisitReady extends VisitState {
  final List<ProductModel> catalog; // قائمة المنتجات للبحث السريع
  final List<CartItemModel> cart; // السلة الذكية المدمجة
  final double shopBalance;
  final double cashCollected;

  const VisitReady({
    required this.catalog,
    this.cart = const [],
    required this.shopBalance,
    this.cashCollected = 0.0,
  });

  // --- حسابات الـ BLoC اللحظية للمالية ---
  double get totalSales =>
      cart.fold(0.0, (sum, item) => sum + item.totalSalePrice);
  double get totalReturns =>
      cart.fold(0.0, (sum, item) => sum + item.totalReturnPrice);
  double get netInvoice => totalSales - totalReturns;

  // الذمة الجديدة = (الذمة القديمة + الفاتورة الصافية) - الكاش المستلم
  double get expectedNewBalance => (shopBalance + netInvoice) - cashCollected;

  VisitReady copyWith({
    List<ProductModel>? catalog,
    List<CartItemModel>? cart,
    double? shopBalance,
    double? cashCollected,
  }) {
    return VisitReady(
      catalog: catalog ?? this.catalog,
      cart: cart ?? this.cart,
      shopBalance: shopBalance ?? this.shopBalance,
      cashCollected: cashCollected ?? this.cashCollected,
    );
  }

  @override
  List<Object?> get props => [catalog, cart, shopBalance, cashCollected];
}

// ============================================================================
// 3. العقل المدبر (Bloc)
// ============================================================================
class VisitBloc extends Bloc<VisitEvent, VisitState> {
  final LocalDatabase _db;

  VisitBloc({LocalDatabase? db})
    : _db = db ?? LocalDatabase.instance,
      super(VisitLoading()) {
    on<LoadVisitCatalog>(_onLoadCatalog);
    on<AddOrUpdateCartItem>(_onAddOrUpdateCartItem);
    on<RemoveCartItem>(_onRemoveCartItem);
    on<UpdateCashCollected>(_onUpdateCashCollected);
  }

  Future<void> _onLoadCatalog(
    LoadVisitCatalog event,
    Emitter<VisitState> emit,
  ) async {
    try {
      // +++ الكيّ الجراحي: تحويل الخرائط الخام إلى موديلات محمية لمنع خطأ الـ Assignable +++
      final List<Map<String, dynamic>> rawProducts = await _db.getProducts();
      final List<ProductModel> products =
          rawProducts.map((p) => ProductModel.fromJson(p)).toList();

      emit(VisitReady(catalog: products, shopBalance: event.shopBalance));
    } catch (e) {
      developer.log('[VisitBloc] Error loading catalog: $e');
    }
  }

  void _onAddOrUpdateCartItem(
    AddOrUpdateCartItem event,
    Emitter<VisitState> emit,
  ) {
    if (state is! VisitReady) return;
    final currentState = state as VisitReady;

    // حماية المخزون: تأكد أن المندوب لا يبيع أكثر مما في السيارة
    if (!event.item.hasEnoughInventory) {
      developer.log(
        '[VisitBloc] Inventory Blocked: Not enough stock for ${event.item.name}',
      );
      // يمكن إرسال حالة خطأ هنا لاحقاً إذا أردنا عرض رسالة من البلوك
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
}
