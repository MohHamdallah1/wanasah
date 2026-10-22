import 'package:equatable/equatable.dart';
import 'visit_return_submission.dart';
import 'visit_sale_confirmation.dart';

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
  final String? exactCashCollected;
  final String? exactDebtPaid;
  final ResolvedVisitReturns? resolvedReturns;
  final VisitSaleConfirmation? saleConfirmation;

  const SubmitVisit({
    required this.visitId,
    required this.outcome,
    required this.debtPaid,
    this.notes,
    this.exactCashCollected,
    this.exactDebtPaid,
    this.resolvedReturns,
    this.saleConfirmation,
  });

  @override
  List<Object?> get props => [visitId, outcome, debtPaid, notes,
    exactCashCollected, exactDebtPaid, resolvedReturns, saleConfirmation];
}
