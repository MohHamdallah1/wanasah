import '../../../core/visit/visit_command_serializer.dart';
import '../../../repositories/sync_repository.dart';
import '../data/visit_submission_mapper.dart';
import 'visit_state.dart';

class VisitSubmissionService {
  VisitSubmissionService(this._syncRepository);

  final SyncRepository _syncRepository;

  Future<void> submit({
    required int visitId,
    required String outcome,
    String? notes,
    required double debtPaid,
    required VisitReady state,
  }) async {
    final lines = mapVisitSubmissionLines(state.cart);
    final payload = buildCanonicalVisitPayload(
      outcome: outcome,
      notes: notes,
      cashCollected: state.cashCollected.toStringAsFixed(3),
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
