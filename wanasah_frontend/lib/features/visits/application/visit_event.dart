import 'package:equatable/equatable.dart';

import '../../../models/cart_item_model.dart';

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

class LoadCompletedVisitData extends VisitEvent {
  final String? cartItemsJson;
  final String? returnsJson;
  final double cashCollected;
  final double debtPaid;
  final String? notes;

  const LoadCompletedVisitData({
    this.cartItemsJson,
    this.returnsJson,
    required this.cashCollected,
    required this.debtPaid,
    required this.notes,
  });

  @override
  List<Object?> get props => [
        cartItemsJson,
        returnsJson,
        cashCollected,
        debtPaid,
        notes,
      ];
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

class UpdateDebtPaid extends VisitEvent {
  final double amount;

  const UpdateDebtPaid(this.amount);

  @override
  List<Object?> get props => [amount];
}

class SubmitVisit extends VisitEvent {
  final int visitId;
  final String outcome;
  final String? notes;
  final double debtPaid;

  const SubmitVisit({
    required this.visitId,
    required this.outcome,
    required this.debtPaid,
    this.notes,
  });

  @override
  List<Object?> get props => [visitId, outcome, debtPaid, notes];
}
