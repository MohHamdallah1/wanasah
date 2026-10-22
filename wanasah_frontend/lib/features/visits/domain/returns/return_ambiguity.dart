import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/core/serialization/json_contract.dart';

import 'return_evidence.dart';

/// A server request for the smallest distinguishing human evidence.
/// Unsupported/malformed evidence is not converted into an input prompt.
class ReturnAmbiguity {
  ReturnAmbiguity._(List<ReturnEvidenceField> required, List<ReturnEvidence> choices)
    : requiredEvidence = List.unmodifiable(required),
      choices = List.unmodifiable(choices);

  final List<ReturnEvidenceField> requiredEvidence;
  final List<ReturnEvidence> choices;

  static ReturnAmbiguity? fromFailure(ApiFailure failure) {
    if (failure.kind != ApiFailureKind.serverResponse ||
        failure.status != 409 ||
        failure.code != 'FIELD_RETURN_EVIDENCE_REQUIRED') {
      return null;
    }
    try {
      final required = JsonContract.list(
        failure.context['required_evidence'], 'required_evidence',
      ).map(ReturnEvidenceField.fromCode).toList();
      if (required.isEmpty || required.toSet().length != required.length) {
        return null;
      }
      final choices = failure.context['choices'] == null
          ? <ReturnEvidence>[]
          : JsonContract.list(failure.context['choices'], 'choices')
              .map(ReturnEvidence.fromJson).toList();
      if (choices.any((choice) => required.any(
        (field) => !choice.toJson().containsKey(field.code),
      ))) {
        return null;
      }
      return ReturnAmbiguity._(required, choices);
    } on FormatException {
      return null; // Original ApiFailure remains intact for recovery.
    }
  }
}

/// Return-specific interpretation stays with Visits, never shared transport.
extension VisitReturnFailureDetails on ApiFailureException {
  ReturnAmbiguity? get returnAmbiguity => ReturnAmbiguity.fromFailure(apiFailure);
}
