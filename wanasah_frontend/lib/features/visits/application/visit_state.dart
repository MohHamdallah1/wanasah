import 'package:equatable/equatable.dart';

import '../../../models/cart_item_model.dart';
import '../../../models/product_model.dart';

abstract class VisitState extends Equatable {
  const VisitState();

  @override
  List<Object?> get props => [];
}

class VisitLoading extends VisitState {}

class VisitError extends VisitState {
  final String message;

  const VisitError(this.message);

  @override
  List<Object?> get props => [message];
}

class VisitSubmissionSuccess extends VisitState {}

class VisitReady extends VisitState {
  final List<ProductModel> catalog;
  final List<CartItemModel> cart;
  final double shopBalance;
  final double cashCollected;
  final double debtPaid;
  final String? notes;

  const VisitReady({
    required this.catalog,
    this.cart = const [],
    required this.shopBalance,
    this.cashCollected = 0.0,
    this.debtPaid = 0.0,
    this.notes,
  });

  double get totalSales =>
      cart.fold(0.0, (sum, item) => sum + item.totalSalePrice);

  double get totalReturns =>
      cart.fold(0.0, (sum, item) => sum + item.totalReturnPrice);

  double get netInvoice => totalSales;

  double get expectedNewBalance =>
      (shopBalance + netInvoice) - cashCollected - debtPaid;

  VisitReady copyWith({
    List<ProductModel>? catalog,
    List<CartItemModel>? cart,
    double? shopBalance,
    double? cashCollected,
    double? debtPaid,
    String? notes,
  }) {
    return VisitReady(
      catalog: catalog ?? this.catalog,
      cart: cart ?? this.cart,
      shopBalance: shopBalance ?? this.shopBalance,
      cashCollected: cashCollected ?? this.cashCollected,
      debtPaid: debtPaid ?? this.debtPaid,
      notes: notes ?? this.notes,
    );
  }

  @override
  List<Object?> get props =>
      [catalog, cart, shopBalance, cashCollected, debtPaid, notes];
}
