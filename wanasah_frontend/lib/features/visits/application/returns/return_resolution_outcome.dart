import 'package:wanasah_frontend/core/network/api_failure.dart';

import '../../domain/returns/return_ambiguity.dart';
import '../../domain/returns/return_resolution.dart';

sealed class ReturnResolutionOutcome {
  const ReturnResolutionOutcome();
}

final class ReturnResolved extends ReturnResolutionOutcome {
  const ReturnResolved(this.resolution);

  /// Backend-owned opaque evidence, retained without decoding or reconstruction.
  final FieldReturnResolution resolution;
}

final class ReturnEvidenceRequired extends ReturnResolutionOutcome {
  const ReturnEvidenceRequired({
    required this.visitId,
    required this.request,
    required this.ambiguity,
    required this.failure,
  });

  final int visitId;
  final ReturnResolutionRequest request;
  final ReturnAmbiguity ambiguity;
  /// Original structured refusal; human prompts come only from [ambiguity].
  final ApiFailure failure;
}

final class ReturnResolutionFailed extends ReturnResolutionOutcome {
  const ReturnResolutionFailed(this.failure);
  final ApiFailure failure;
}

/// No server failure code, context or request ID is fabricated for a bad payload.
final class ReturnResolutionInvalidResponse extends ReturnResolutionOutcome {
  const ReturnResolutionInvalidResponse();
}

enum ReturnEvidenceIssue { missingRequired, unrequested, malformed }

/// Local shape rejection, kept distinct from authoritative Backend refusals.
final class ReturnEvidenceNotAccepted extends ReturnResolutionOutcome {
  const ReturnEvidenceNotAccepted(this.issue);
  final ReturnEvidenceIssue issue;
}
