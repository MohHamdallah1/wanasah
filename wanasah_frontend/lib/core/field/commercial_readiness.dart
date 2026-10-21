import 'src/field_json.dart';

enum CommercialReadinessStatus { ready, actionRequired }

/// Tax setup readiness only, not stock/credit or final sale authorization.
class CommercialReadiness {
  const CommercialReadiness._(this.status, this.code, this.requiredAction);

  final CommercialReadinessStatus status;
  final String? code;
  final String? requiredAction;

  bool get saleReady => status == CommercialReadinessStatus.ready;

  /// Accepts the readiness object shared by GET and POST /shops responses.
  factory CommercialReadiness.fromJson(Object? value) {
    final json = FieldJson.object(value, 'commercial_readiness');
    final saleReady = FieldJson.boolean(json['sale_ready'], 'sale_ready');
    switch (json['status']) {
      case 'READY':
        if (!saleReady || json['code'] != null || json['required_action'] != null) {
          FieldJson.invalid('commercial_readiness.READY');
        }
        return const CommercialReadiness._(
          CommercialReadinessStatus.ready, null, null,
        );
      case 'ACTION_REQUIRED':
        if (saleReady) FieldJson.invalid('commercial_readiness.ACTION_REQUIRED');
        return CommercialReadiness._(
          CommercialReadinessStatus.actionRequired,
          FieldJson.text(json['code'], 'commercial_readiness.code'),
          FieldJson.text(json['required_action'], 'required_action'),
        );
      default:
        FieldJson.invalid('commercial_readiness.status');
    }
  }

  factory CommercialReadiness.fromResponse(Object? value) =>
      CommercialReadiness.fromJson(
        FieldJson.object(value, 'commercial_state')['commercial_readiness'],
      );
}
