import '../../../core/visit/visit_command_serializer.dart';
import '../../../repositories/sync_repository.dart';
import '../data/visit_submission_mapper.dart';
import '../../../models/cart_item_model.dart';

class VisitSubmissionService {
  VisitSubmissionService(this._syncRepository);

  final SyncRepository _syncRepository;

  Future<void> submit({
    required int visitId,
    required String outcome,
    String? notes,
    required double debtPaid,
    required double cashCollected,
    required List<CartItemModel> cart,
  }) async {
    final lines = mapVisitSubmissionLines(cart);
    final payload = buildCanonicalVisitPayload(
      outcome: outcome,
      notes: notes,
      cashCollected: cashCollected.toStringAsFixed(3),
      debtPaid: debtPaid.toStringAsFixed(3),
      cartItems: lines.cartItems,
      returns: lines.returns,
    );

    await _syncRepository.saveInvoice(
      visitId: visitId,
      payload: payload,
    );
  }
}
