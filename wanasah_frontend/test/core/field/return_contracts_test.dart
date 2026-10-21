import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/field/field_contracts.dart';

import 'field_contract_fixtures.dart';

void main() {
  test('deterministic tracked resolution preserves human evidence and request', () {
    final request = ReturnResolutionRequest(productVariantId: 44, quantity: 1, packsQuantity: 2);
    final resolution = FieldReturnResolution.fromJson(resolvedJson(), request: request);
    expect(resolution.request, same(request));
    expect(resolution.evidence.lotNumber, 'LOT / A  ');
    expect(resolution.evidence.productionDate, '2026-01-03');
    expect(resolution.evidence.expiryDate, '2027-01-03');
  });

  test('deterministic no-lot resolution requires no invented lot', () {
    final json = resolvedJson();
    json['evidence'] = {'lot_number': null, 'production_date': null, 'expiry_date': null};
    final resolution = FieldReturnResolution.fromJson(json,
      request: ReturnResolutionRequest(productVariantId: 44, packsQuantity: 2));
    expect(resolution.evidence.lotNumber, isNull);
    expect(resolution.toVisitReturnJson().containsKey('lot_number'), isFalse);
  });

  for (final type in FieldReturnType.values) {
    test('opaque token and bound quantities survive durable JSON for ${type.code}', () {
      const token = '  opaque+/=signed.token  ';
      final json = resolvedJson()..['resolution_token'] = token;
      final resolution = FieldReturnResolution.fromJson(json,
        request: ReturnResolutionRequest(
          productVariantId: 44, quantity: 2, packsQuantity: 3, returnType: type));
      final body = resolution.toVisitReturnJson(reason: '  packaging  ');
      expect(jsonDecode(jsonEncode(body)), {
        'product_variant_id': 44, 'quantity': 2, 'packs_quantity': 3,
        'return_type': type.code, 'resolution_token': token, 'reason': '  packaging  ',
      });
      expect(resolution.resolutionToken, token);
      body['resolution_token'] = 'mutated copy';
      expect(resolution.resolutionToken, token);
    });
  }

  test('resolver request sends only selected human evidence', () {
    final request = ReturnResolutionRequest(
      productVariantId: 44, packsQuantity: 1, returnType: FieldReturnType.expired,
      evidence: const ReturnEvidence(expiryDate: '2027-01-03', deliveryDate: '2026-10-21'));
    expect(request.toJson(), {
      'product_variant_id': 44, 'quantity': 0, 'packs_quantity': 1,
      'return_type': 'Expired', 'expiry_date': '2027-01-03', 'delivery_date': '2026-10-21',
    });
  });

  test('ambiguity parses minimal lot choices from structured ApiFailure only', () {
    final ambiguity = ReturnAmbiguity.fromFailure(ambiguityFailure())!;
    expect(ambiguity.requiredEvidence, [ReturnEvidenceField.lotNumber]);
    expect(ambiguity.choices.map((value) => value.lotNumber), ['LOT-A', 'LOT-B']);
    expect(() => ambiguity.requiredEvidence.clear(), throwsUnsupportedError);
    expect(() => ambiguity.choices.clear(), throwsUnsupportedError);
  });

  test('anonymous ambiguity preserves delivery-date request with no choices', () {
    final ambiguity = ReturnAmbiguity.fromFailure(ambiguityFailure(context: {
      'required_evidence': ['delivery_date'],
    }))!;
    expect(ambiguity.requiredEvidence, [ReturnEvidenceField.deliveryDate]);
    expect(ambiguity.choices, isEmpty);
  });

  test('combined expiry/production evidence stays typed without choosing a candidate', () {
    final ambiguity = ReturnAmbiguity.fromFailure(ambiguityFailure(context: {
      'required_evidence': ['expiry_date', 'production_date'],
      'choices': [
        {'expiry_date': '2027-01-01', 'production_date': '2026-01-01'},
        {'expiry_date': '2027-02-01', 'production_date': '2026-02-01'},
      ],
    }))!;
    expect(ambiguity.requiredEvidence,
      [ReturnEvidenceField.expiryDate, ReturnEvidenceField.productionDate]);
    expect(ambiguity.choices.length, 2);
  });

  test('unknown or malformed evidence fails closed without technical input prompts', () {
    for (final context in <Map<String, dynamic>>[
      {'required_evidence': ['batch_id']},
      {'required_evidence': []},
      {'required_evidence': ['lot_number', 'lot_number']},
      {'required_evidence': ['expiry_date'], 'choices': [{'expiry_date': '2026-02-31'}]},
      {'required_evidence': 'lot_number'},
      {'required_evidence': ['lot_number'], 'choices': [{'batch_id': 987}]},
    ]) {
      expect(ReturnAmbiguity.fromFailure(ambiguityFailure(context: context)), isNull);
    }
    expect(ReturnAmbiguity.fromFailure(
      ambiguityFailure(code: 'FIELD_RETURN_PROVENANCE_REVIEW_REQUIRED')), isNull);
  });

  test('public resolution and evidence never retain raw Batch fields', () {
    final json = resolvedJson()..['batch_id'] = 987;
    (json['evidence'] as Map<String, dynamic>)['batch_id'] = 987;
    final resolution = FieldReturnResolution.fromJson(json,
      request: ReturnResolutionRequest(productVariantId: 44, packsQuantity: 1));
    expect(jsonEncode(resolution.evidence.toJson()), isNot(contains('batch')));
    expect(jsonEncode(resolution.toVisitReturnJson()), isNot(contains('batch')));
    expect(() => (resolution as dynamic).batchId, throwsA(isA<NoSuchMethodError>()));
    expect(() => (resolution.evidence as dynamic).batchId, throwsA(isA<NoSuchMethodError>()));
    final ambiguity = ReturnAmbiguity.fromFailure(ambiguityFailure(context: {
      'required_evidence': ['lot_number'],
      'choices': [{'lot_number': 'LOT-A', 'batch_id': 987}],
    }))!;
    expect(ambiguity.choices.single.toJson(), {'lot_number': 'LOT-A'});
  });

  test('malformed successful resolution is never accepted as resolved', () {
    final request = ReturnResolutionRequest(productVariantId: 44, packsQuantity: 1);
    for (final json in [
      {...resolvedJson(), 'status': 'AMBIGUOUS'},
      {...resolvedJson(), 'resolution_token': ''},
      {...resolvedJson(), 'evidence': null},
    ]) {
      expect(() => FieldReturnResolution.fromJson(json, request: request), throwsFormatException);
    }
  });
}
