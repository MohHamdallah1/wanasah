import 'return_evidence.dart';
import 'src/field_json.dart';

enum FieldReturnType {
  damaged('Damaged'),
  expired('Expired'),
  factoryDefect('Factory_Defect');

  const FieldReturnType(this.code);
  final String code;
}

/// Read-only resolver input, reused unchanged when sending the resolved line.
class ReturnResolutionRequest {
  ReturnResolutionRequest({
    required this.productVariantId,
    this.quantity = 0,
    this.packsQuantity = 0,
    this.returnType = FieldReturnType.damaged,
    this.evidence = const ReturnEvidence(),
  }) {
    FieldJson.integer(productVariantId, 'product_variant_id', minimum: 1);
    FieldJson.integer(quantity, 'quantity');
    FieldJson.integer(packsQuantity, 'packs_quantity');
    if (quantity == 0 && packsQuantity == 0) {
      FieldJson.invalid('return.quantity');
    }
  }

  final int productVariantId;
  final int quantity;
  final int packsQuantity;
  final FieldReturnType returnType;
  final ReturnEvidence evidence;

  Map<String, dynamic> toJson() => {
    'product_variant_id': productVariantId,
    'quantity': quantity,
    'packs_quantity': packsQuantity,
    'return_type': returnType.code,
    ...evidence.toJson(),
  };
}

/// Signed resolution is opaque: never decode, trim, log or regenerate its token.
/// Persist the resulting visit line with the existing durable visit UUID/body.
/// Backend revalidates provenance and remains the acceptance authority.
class FieldReturnResolution {
  const FieldReturnResolution._({
    required this.request,
    required this.resolutionToken,
    required this.evidence,
  });

  final ReturnResolutionRequest request;
  final String resolutionToken;
  final ReturnEvidence evidence;

  factory FieldReturnResolution.fromJson(
    Object? value, {
    required ReturnResolutionRequest request,
  }) {
    final json = FieldJson.object(value, 'return.resolution');
    if (json['status'] != 'RESOLVED') FieldJson.invalid('return.status');
    final token = FieldJson.text(json['resolution_token'], 'resolution_token');
    if (token.length > 8192) FieldJson.invalid('resolution_token');
    return FieldReturnResolution._(
      request: request,
      resolutionToken: token,
      evidence: ReturnEvidence.fromJson(json['evidence']),
    );
  }

  /// This is one line for the existing PUT body, not a new mutation workflow.
  Map<String, dynamic> toVisitReturnJson({String? reason}) => {
    'product_variant_id': request.productVariantId,
    'quantity': request.quantity,
    'packs_quantity': request.packsQuantity,
    'return_type': request.returnType.code,
    'resolution_token': resolutionToken,
    if (reason != null) 'reason': reason,
  };
}
