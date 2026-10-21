import '../network/api_failure.dart';
import 'src/field_json.dart';

enum ReturnEvidenceField {
  lotNumber('lot_number'),
  productionDate('production_date'),
  expiryDate('expiry_date'),
  deliveryDate('delivery_date');

  const ReturnEvidenceField(this.code);
  final String code;

  static ReturnEvidenceField fromCode(Object? value) => FieldJson.code(
    value, values, (field) => field.code, 'required_evidence',
  );
}

/// Human business facts only. No raw response or database Batch locator.
class ReturnEvidence {
  const ReturnEvidence({
    this.lotNumber,
    this.productionDate,
    this.expiryDate,
    this.deliveryDate,
  });

  final String? lotNumber;
  final String? productionDate;
  final String? expiryDate;
  final String? deliveryDate;

  factory ReturnEvidence.fromJson(Object? value) {
    final json = FieldJson.object(value, 'return.evidence');
    return ReturnEvidence(
      lotNumber: FieldJson.optionalText(json['lot_number'], 'lot_number'),
      productionDate: FieldJson.date(json['production_date'], 'production_date'),
      expiryDate: FieldJson.date(json['expiry_date'], 'expiry_date'),
      deliveryDate: FieldJson.date(json['delivery_date'], 'delivery_date'),
    );
  }

  Map<String, dynamic> toJson() => {
    if (lotNumber != null) 'lot_number': lotNumber,
    if (productionDate != null) 'production_date': productionDate,
    if (expiryDate != null) 'expiry_date': expiryDate,
    if (deliveryDate != null) 'delivery_date': deliveryDate,
  };
}

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
      final required = FieldJson.list(
        failure.context['required_evidence'], 'required_evidence',
      ).map(ReturnEvidenceField.fromCode).toList();
      if (required.isEmpty || required.toSet().length != required.length) {
        return null;
      }
      final choices = failure.context['choices'] == null
          ? <ReturnEvidence>[]
          : FieldJson.list(failure.context['choices'], 'choices')
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
