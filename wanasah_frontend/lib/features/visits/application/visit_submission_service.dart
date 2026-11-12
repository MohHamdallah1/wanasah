import '../../../core/visit/visit_command_serializer.dart';
import '../../work_session/data/execution_context.dart';
import '../../../repositories/sync_repository.dart';
import '../data/visit_submission_mapper.dart';
import '../../../models/cart_item_model.dart';
import 'visit_command_evidence.dart';
import 'visit_return_submission.dart';
import 'visit_sale_confirmation.dart';
import 'visit_money_input.dart';
import 'visit_action_policy.dart';

typedef SaveVisitCommand = Future<void> Function({
  required int visitId, required Map<String, dynamic> payload,
});
typedef ReadVisitCommandEvidence = Future<List<Map<String, dynamic>>> Function();
typedef ReadSignedExecution = Future<ExecutionContextProof?> Function();

class VisitSubmissionService {
  VisitSubmissionService(SyncRepository repository,
    {required ReadVisitCommandEvidence readPending,
     ReadSignedExecution? readExecution, bool requireExecutionProof = false})
    : this.withPorts(save: repository.saveInvoice, readPending: readPending,
        readExecution: readExecution, requireExecutionProof: requireExecutionProof);

  VisitSubmissionService.withPorts({
    required SaveVisitCommand save, required ReadVisitCommandEvidence readPending,
    ReadSignedExecution? readExecution, bool requireExecutionProof = false,
  }) : _save = save, _readPending = readPending,
       _readExecution = readExecution, _requireExecutionProof = requireExecutionProof;

  final SaveVisitCommand _save;
  final ReadVisitCommandEvidence _readPending;
  final ReadSignedExecution? _readExecution;
  final bool _requireExecutionProof;

  Future<bool> hasUnresolvedVisit(int visitId) async =>
      visitHasUnresolvedCommand(visitId, await _readPending());

  Future<VisitSubmissionDisposition> submit({
    required int visitId,
    required String outcome,
    String? notes,
    required double debtPaid,
    required double cashCollected,
    required List<CartItemModel> cart,
    String? exactCashCollected,
    String? exactDebtPaid,
    ResolvedVisitReturns? resolvedReturns,
    VisitSaleConfirmation? saleConfirmation,
  }) async {
    if (visitHasUnresolvedCommand(visitId, await _readPending())) {
      throw const VisitPriorCommandUnresolved();
    }
    final cash = canonicalVisitMoney(
      exactCashCollected ?? cashCollected.toStringAsFixed(3));
    final debt = canonicalVisitMoney(exactDebtPaid ?? debtPaid.toStringAsFixed(3));
    validateVisitActions(outcome: outcome, cart: cart, cash: cash, debt: debt,
      notes: notes);
    if (outcome == 'Sale') {
      if (saleConfirmation == null) {
        throw const FormatException('Sale requires readiness and preview');
      }
      saleConfirmation.validate(visitId, cart);
    }
    final lines = mapVisitSubmissionLines(cart);
    final returns = outcome == 'Postponed' ? <Map<String, dynamic>>[] :
      (resolvedReturns ?? ResolvedVisitReturns(visitId: visitId, resolutions: []))
        .forSubmission(visitId, cart);
    final payload = buildCanonicalVisitPayload(
      outcome: outcome,
      notes: notes,
      cashCollected: cash,
      debtPaid: debt,
      cartItems: lines.cartItems,
      returns: returns,
    );

    // Capture the exact signed source-period BEFORE staging the offline
    // command. Never rebind a pending A request to B (or new A after ABA).
    if (_requireExecutionProof && _readExecution == null) {
      throw StateError('M05_SIGNED_EXECUTION_PROVIDER_REQUIRED');
    }
    final execution = await _readExecution?.call();
    if (_requireExecutionProof && execution == null) {
      throw StateError('M05_NO_ACTIVE_EXECUTION_PERIOD');
    }
    if (execution != null) payload['execution_context'] = execution.toJson();

    // UUID, staging, immutable replay and local projection belong to this port.
    await _save(visitId: visitId, payload: payload);
    return visitHasUnresolvedCommand(visitId, await _readPending())
      ? VisitSubmissionDisposition.unresolved
      : VisitSubmissionDisposition.confirmed;
  }
}
