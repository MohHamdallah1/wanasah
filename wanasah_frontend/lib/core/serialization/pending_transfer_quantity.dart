import 'package:wanasah_frontend/core/serialization/json_contract.dart';

/// Immutable display evidence. Accepted stock always comes from the server line.
class PendingTransferQuantity {
  const PendingTransferQuantity._({
    required this.signedBaseQuantity,
    required this.baseUomId,
    required this.baseUomCode,
    required this.baseUomName,
    required this.quantityScale,
    required this.quantityStep,
    required this.displayUomName,
    required this.displayFactorToBase,
  });

  static const contract = 'CANONICAL_BASE_V1';
  final String signedBaseQuantity;
  final int baseUomId;
  final String baseUomCode;
  final String baseUomName;
  final int quantityScale;
  final String quantityStep;
  final String? displayUomName;
  final String? displayFactorToBase;

  int get signedUnits => int.parse(signedBaseQuantity.split('.').first);

  static PendingTransferQuantity? fromEvidence(Map<String, dynamic> json) {
    final marker = json['quantity_contract'];
    if (marker == null) return null; // Historical rows keep their old meaning.
    if (marker != contract) JsonContract.invalid('quantity_contract');
    for (final field in const [
      'signed_base_quantity',
      'base_uom_id',
      'base_uom_code',
      'base_uom_name',
      'quantity_scale',
      'quantity_step',
      'display_uom_name',
      'display_factor_to_base',
    ]) {
      if (!json.containsKey(field)) JsonContract.invalid(field);
    }
    final signed = JsonContract.decimal(
      json['signed_base_quantity'],
      'signed_base_quantity',
    );
    if (!RegExp(r'^-?\d+(?:\.0{1,6})?$').hasMatch(signed)) {
      JsonContract.invalid('signed_base_quantity.integral');
    }
    final units = BigInt.parse(signed.split('.').first);
    if (units == BigInt.zero || units.abs() > BigInt.from(99999999999999)) {
      JsonContract.invalid('signed_base_quantity.range');
    }
    final scale = JsonContract.integer(
      json['quantity_scale'],
      'quantity_scale',
    );
    if (scale > 6) JsonContract.invalid('quantity_scale');
    final step = JsonContract.decimal(json['quantity_step'], 'quantity_step');
    if (!RegExp(r'^\d+(?:\.\d{1,6})?$').hasMatch(step)) {
      JsonContract.invalid('quantity_step');
    }
    final parts = step.split('.');
    final fraction = parts.length == 2 ? parts[1] : '';
    if (fraction.length > scale) JsonContract.invalid('quantity_step.scale');
    final scaledStep = BigInt.parse(parts[0] + fraction.padRight(6, '0'));
    if (scaledStep <= BigInt.zero ||
        units.abs() * BigInt.from(1000000) % scaledStep != BigInt.zero) {
      JsonContract.invalid('quantity_step.alignment');
    }
    final name = JsonContract.optionalText(
      json['display_uom_name'],
      'display_uom_name',
    );
    final factor = JsonContract.optionalText(
      json['display_factor_to_base'],
      'display_factor_to_base',
    );
    if ((name == null) != (factor == null) ||
        (factor != null &&
            (!RegExp(r'^\d+$').hasMatch(factor) ||
                BigInt.parse(factor) <= BigInt.one))) {
      JsonContract.invalid('display_uom');
    }
    return PendingTransferQuantity._(
      signedBaseQuantity: signed,
      baseUomId: JsonContract.integer(
        json['base_uom_id'],
        'base_uom_id',
        minimum: 1,
      ),
      baseUomCode: JsonContract.text(json['base_uom_code'], 'base_uom_code'),
      baseUomName: JsonContract.text(json['base_uom_name'], 'base_uom_name'),
      quantityScale: scale,
      quantityStep: step,
      displayUomName: name,
      displayFactorToBase: factor,
    );
  }

  Map<String, dynamic> toEvidence() => {
    'quantity_contract': contract,
    'signed_base_quantity': signedBaseQuantity,
    'base_uom_id': baseUomId,
    'base_uom_code': baseUomCode,
    'base_uom_name': baseUomName,
    'quantity_scale': quantityScale,
    'quantity_step': quantityStep,
    'display_uom_name': displayUomName,
    'display_factor_to_base': displayFactorToBase,
  };
}
