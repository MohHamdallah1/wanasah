import 'package:wanasah_frontend/core/serialization/json_contract.dart';

enum ReturnEvidenceField {
  lotNumber('lot_number'),
  productionDate('production_date'),
  expiryDate('expiry_date'),
  deliveryDate('delivery_date');

  const ReturnEvidenceField(this.code);
  final String code;

  static ReturnEvidenceField fromCode(Object? value) => JsonContract.code(
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
    final json = JsonContract.object(value, 'return.evidence');
    return ReturnEvidence(
      lotNumber: JsonContract.optionalText(json['lot_number'], 'lot_number'),
      productionDate: JsonContract.date(json['production_date'], 'production_date'),
      expiryDate: JsonContract.date(json['expiry_date'], 'expiry_date'),
      deliveryDate: JsonContract.date(json['delivery_date'], 'delivery_date'),
    );
  }

  Map<String, dynamic> toJson() => {
    if (lotNumber != null) 'lot_number': lotNumber,
    if (productionDate != null) 'production_date': productionDate,
    if (expiryDate != null) 'expiry_date': expiryDate,
    if (deliveryDate != null) 'delivery_date': deliveryDate,
  };
}

