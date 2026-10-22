import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';

import '../../data/visit_field_client.dart';
import '../../domain/returns/return_ambiguity.dart';
import '../../domain/returns/return_evidence.dart';
import '../../domain/returns/return_resolution.dart';
import 'return_resolution_outcome.dart';

typedef ReturnResolutionRead = Future<FieldReturnResolution> Function(
  int visitId, ReturnResolutionRequest request,
);

/// Stateless read orchestration. No allocation, mutation, persistence or retry.
class ReturnResolutionCoordinator {
  const ReturnResolutionCoordinator({required ReturnResolutionRead resolve})
    : _resolve = resolve;

  factory ReturnResolutionCoordinator.fromClient(VisitFieldClient client) =>
      ReturnResolutionCoordinator(resolve: client.resolveReturn);

  final ReturnResolutionRead _resolve;

  Future<ReturnResolutionOutcome> resolve(
    int visitId, ReturnResolutionRequest request,
  ) async {
    try {
      return ReturnResolved(await _resolve(visitId, request));
    } on ApiFailureException catch (error) {
      final ambiguity = ReturnAmbiguity.fromFailure(error.apiFailure);
      if (ambiguity != null) {
        return ReturnEvidenceRequired(
          visitId: visitId, request: request, ambiguity: ambiguity,
          failure: error.apiFailure,
        );
      }
      return ReturnResolutionFailed(error.apiFailure);
    } on FormatException {
      return const ReturnResolutionInvalidResponse();
    }
  }

  /// Accept only the requested human facts. Values are re-resolved by Backend;
  /// prior candidates are never selected or converted into identity locally.
  Future<ReturnResolutionOutcome> submitEvidence(
    ReturnEvidenceRequired pending, ReturnEvidence discriminator,
  ) async {
    final supplied = discriminator.toJson();
    final required = pending.ambiguity.requiredEvidence
        .map((field) => field.code).toSet();
    if (supplied.keys.any((key) => !required.contains(key))) {
      return const ReturnEvidenceNotAccepted(ReturnEvidenceIssue.unrequested);
    }
    if (required.any((key) => !supplied.containsKey(key))) {
      return const ReturnEvidenceNotAccepted(ReturnEvidenceIssue.missingRequired);
    }
    final ReturnEvidence evidence;
    try {
      evidence = ReturnEvidence.fromJson({
        ...pending.request.evidence.toJson(),
        ...supplied,
      });
    } on FormatException {
      return const ReturnEvidenceNotAccepted(ReturnEvidenceIssue.malformed);
    }
    final request = ReturnResolutionRequest(
      productVariantId: pending.request.productVariantId,
      quantity: pending.request.quantity,
      packsQuantity: pending.request.packsQuantity,
      returnType: pending.request.returnType,
      evidence: evidence,
    );
    return resolve(pending.visitId, request);
  }
}
