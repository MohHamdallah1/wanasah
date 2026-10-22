import 'package:flutter/material.dart';
import '../../../../models/cart_item_model.dart';
import '../../application/visit_return_submission.dart';
import '../../application/returns/return_resolution_coordinator.dart';
import '../../application/returns/return_resolution_outcome.dart';
import '../../domain/returns/return_evidence.dart';
import '../../domain/returns/return_resolution.dart';
import '../visit_field_failure.dart';
import 'return_ambiguity_chooser.dart';

Future<ResolvedVisitReturns?> resolveVisitReturns(BuildContext context, {
  required int visitId, required List<CartItemModel> cart,
  required ReturnResolutionCoordinator coordinator,
}) async {
  final resolved = <FieldReturnResolution>[];
  for (final request in visitReturnRequests(cart)) {
    var outcome = await coordinator.resolve(visitId, request);
    while (true) {
      if (!context.mounted) return null;
      switch (outcome) {
        case ReturnResolved():
          resolved.add(outcome.resolution);
          break;
        case ReturnEvidenceRequired():
          final pending = outcome;
          final evidence = await showDialog<ReturnEvidence>(
            context: context, barrierDismissible: false,
            builder: (_) => ReturnAmbiguityChooser(pending: pending,
              productName: cart.firstWhere((item) => item.productVariantId == request.productVariantId).name),
          );
          if (!context.mounted) return null;
          if (evidence == null) return null;
          outcome = await coordinator.submitEvidence(pending, evidence);
          continue; // Another prompt requires another explicit operator action.
        case ReturnResolutionFailed():
          await showVisitFieldFailure(context, failure: outcome.failure);
          return null;
        case ReturnResolutionInvalidResponse():
        case ReturnEvidenceNotAccepted():
          await showVisitFieldFailure(context);
          return null;
      }
      break;
    }
    if (!context.mounted) return null;
  }
  return ResolvedVisitReturns(visitId: visitId, resolutions: resolved);
}
