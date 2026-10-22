import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/features/visits/application/returns/return_resolution_coordinator.dart';
import 'package:wanasah_frontend/features/visits/application/returns/return_resolution_outcome.dart';
import 'package:wanasah_frontend/features/visits/data/visit_field_client.dart';
import 'package:wanasah_frontend/features/visits/domain/returns/return_evidence.dart';
import 'package:wanasah_frontend/features/visits/domain/returns/return_resolution.dart';

import '../../domain/returns/return_fixtures.dart';

VisitFieldClient returnClient(
  Future<Object?> Function(String, {required Map<String, dynamic> data}) post,
) => VisitFieldClient(
  get: (path, {queryParameters}) async => throw StateError('Unexpected GET'),
  post: post,
);

ReturnResolutionRequest businessRequest() => ReturnResolutionRequest(
  productVariantId: 44, quantity: 1, packsQuantity: 2,
  returnType: FieldReturnType.factoryDefect,
  evidence: const ReturnEvidence(productionDate: '2026-01-03'),
);

void main() {
  test('deterministic business request delegates once and preserves opaque token', () async {
    final request = businessRequest();
    var calls = 0;
    const token = '  opaque+/=signed.header.signature  ';
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async {
        calls++;
        expect(path, '/visits/11/return-resolution');
        expect(data, request.toJson());
        return resolvedJson()..['resolution_token'] = token;
      },
    ));
    final outcome = await coordinator.resolve(11, request) as ReturnResolved;
    expect(calls, 1);
    expect(outcome.resolution.request, same(request));
    expect(outcome.resolution.resolutionToken, token);
    expect(outcome.resolution.evidence.lotNumber, 'LOT / A  ');
    expect(outcome.resolution.evidence.productionDate, '2026-01-03');
    expect(outcome.resolution.toVisitReturnJson()['resolution_token'], token);
    expect(() => (outcome as dynamic).batchId, throwsA(isA<NoSuchMethodError>()));
    expect(() => (outcome.resolution as dynamic).batchId,
      throwsA(isA<NoSuchMethodError>()));
  });

  test('typed success object is passed through without reconstruction', () async {
    final request = businessRequest();
    final resolution = FieldReturnResolution.fromJson(resolvedJson(), request: request);
    final coordinator = ReturnResolutionCoordinator(resolve: (visitId, input) async => resolution);
    final outcome = await coordinator.resolve(11, request) as ReturnResolved;
    expect(outcome.resolution, same(resolution));
  });

  test('ambiguity preserves only human choices and does not select or retry', () async {
    var calls = 0;
    final request = businessRequest();
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async {
        calls++;
        throw responseError(context: {
          'required_evidence': ['lot_number'],
          'choices': [
            {'lot_number': 'Printed A  ', 'batch_id': 91},
            {'lot_number': 'Printed B', 'batch_id': 92},
          ],
        });
      },
    ));
    final outcome = await coordinator.resolve(11, request) as ReturnEvidenceRequired;
    expect(calls, 1);
    expect(outcome.visitId, 11);
    expect(outcome.request, same(request));
    expect(outcome.ambiguity.requiredEvidence, [ReturnEvidenceField.lotNumber]);
    expect(outcome.ambiguity.choices.map((value) => value.toJson()), [
      {'lot_number': 'Printed A  '}, {'lot_number': 'Printed B'},
    ]);
    expect(outcome.failure.status, 409);
    expect(outcome.failure.code, 'FIELD_RETURN_EVIDENCE_REQUIRED');
    expect(outcome.failure.requestId, 'canonical-id');
    expect(() => (outcome as dynamic).batchId, throwsA(isA<NoSuchMethodError>()));
    expect(() => (outcome.ambiguity.choices.first as dynamic).batchId,
      throwsA(isA<NoSuchMethodError>()));
  });

  test('human follow-up re-resolves selected evidence and retains original quantities', () async {
    final bodies = <Map<String, dynamic>>[];
    final request = businessRequest();
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async {
        expect(path, '/visits/11/return-resolution');
        bodies.add(data);
        if (bodies.length == 1) throw responseError();
        return resolvedJson()..['resolution_token'] = 'new-canonical-opaque+/=';
      },
    ));
    final pending = await coordinator.resolve(11, request) as ReturnEvidenceRequired;
    expect(bodies.length, 1);
    final outcome = await coordinator.submitEvidence(
      pending, const ReturnEvidence(lotNumber: 'LOT-B'),
    ) as ReturnResolved;
    expect(bodies.length, 2);
    expect(bodies.last, {...request.toJson(), 'lot_number': 'LOT-B'});
    expect(request.evidence.lotNumber, isNull);
    expect(outcome.resolution.request.quantity, 1);
    expect(outcome.resolution.request.packsQuantity, 2);
    expect(outcome.resolution.request.returnType, FieldReturnType.factoryDefect);
    expect(outcome.resolution.resolutionToken, 'new-canonical-opaque+/=');
  });

  test('missing, extra or malformed discriminator fails locally without another read', () async {
    var calls = 0;
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async { calls++; throw responseError(); },
    ));
    final pending = await coordinator.resolve(11, businessRequest()) as ReturnEvidenceRequired;
    final missing = await coordinator.submitEvidence(pending, const ReturnEvidence())
      as ReturnEvidenceNotAccepted;
    expect(missing.issue, ReturnEvidenceIssue.missingRequired);
    final extra = await coordinator.submitEvidence(pending,
      const ReturnEvidence(lotNumber: 'LOT-A', expiryDate: '2027-01-03'))
      as ReturnEvidenceNotAccepted;
    expect(extra.issue, ReturnEvidenceIssue.unrequested);
    final malformed = await coordinator.submitEvidence(pending,
      const ReturnEvidence(lotNumber: '  ')) as ReturnEvidenceNotAccepted;
    expect(malformed.issue, ReturnEvidenceIssue.malformed);
    expect(calls, 1);
  });

  test('a delivery-date discriminator is forwarded as business evidence only', () async {
    var calls = 0;
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async {
        calls++;
        if (calls == 1) {
          throw responseError(context: {'required_evidence': ['delivery_date']});
        }
        expect(data['delivery_date'], '2026-10-21');
        return resolvedJson();
      },
    ));
    final pending = await coordinator.resolve(11, businessRequest()) as ReturnEvidenceRequired;
    final bad = await coordinator.submitEvidence(pending,
      const ReturnEvidence(deliveryDate: '2026-02-31'));
    expect(bad, isA<ReturnEvidenceNotAccepted>());
    expect(calls, 1);
    expect(await coordinator.submitEvidence(pending,
      const ReturnEvidence(deliveryDate: '2026-10-21')), isA<ReturnResolved>());
    expect(calls, 2);
  });

  test('a further ambiguity remains explicit and preserves previously supplied facts', () async {
    var calls = 0;
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async {
        calls++;
        if (calls == 1) throw responseError();
        if (calls == 2) {
          expect(data['lot_number'], 'LOT-B');
          throw responseError(context: {'required_evidence': ['expiry_date']});
        }
        expect(data['lot_number'], 'LOT-B');
        expect(data['production_date'], '2026-01-03');
        expect(data['expiry_date'], '2027-01-03');
        return resolvedJson();
      },
    ));
    final first = await coordinator.resolve(11, businessRequest()) as ReturnEvidenceRequired;
    final second = await coordinator.submitEvidence(first,
      const ReturnEvidence(lotNumber: 'LOT-B')) as ReturnEvidenceRequired;
    expect(calls, 2);
    expect(second.request.evidence.lotNumber, 'LOT-B');
    expect(await coordinator.submitEvidence(second,
      const ReturnEvidence(expiryDate: '2027-01-03')), isA<ReturnResolved>());
    expect(calls, 3);
  });

  test('failure retains the original ApiFailure object and never classifies message text', () async {
    final original = ApiFailure.fromDioException(responseError(
      code: 'FIELD_RETURN_PROVENANCE_REVIEW_REQUIRED',
      message: 'FIELD_RETURN_EVIDENCE_REQUIRED أكد التشغيلة',
      context: {'required_action': 'BACKOFFICE_REVIEW_RETURN_PROVENANCE',
        'structured': {'preserved': [1, true, null]}},
    ));
    var calls = 0;
    final coordinator = ReturnResolutionCoordinator(resolve: (id, input) async {
      calls++;
      throw ApiFailureException(original);
    });
    final outcome = await coordinator.resolve(11, businessRequest()) as ReturnResolutionFailed;
    expect(calls, 1);
    expect(outcome.failure, same(original));
    expect(outcome.failure.context, same(original.context));
    expect(outcome.failure.status, 409);
    expect(outcome.failure.code, 'FIELD_RETURN_PROVENANCE_REVIEW_REQUIRED');
    expect(outcome.failure.requestId, 'canonical-id');
  });

  test('malformed ambiguity metadata remains a structured refusal without a prompt', () async {
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async => throw responseError(
        context: {'required_evidence': ['batch_id']}),
    ));
    final outcome = await coordinator.resolve(11, businessRequest()) as ReturnResolutionFailed;
    expect(outcome.failure.code, 'FIELD_RETURN_EVIDENCE_REQUIRED');
    expect(outcome.failure.requestId, 'canonical-id');
  });

  test('malformed success fails closed without fabricated ApiFailure evidence', () async {
    for (final body in [
      <String, dynamic>{},
      {...resolvedJson(), 'resolution_token': ''},
      {...resolvedJson(), 'status': 'UNKNOWN'},
    ]) {
      final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
        (path, {required data}) async => body,
      ));
      final outcome = await coordinator.resolve(11, businessRequest());
      expect(outcome, isA<ReturnResolutionInvalidResponse>());
      expect(() => (outcome as dynamic).failure, throwsA(isA<NoSuchMethodError>()));
    }
  });

  test('timeout is surfaced as original structured transport evidence without retry', () async {
    var calls = 0;
    final coordinator = ReturnResolutionCoordinator.fromClient(returnClient(
      (path, {required data}) async {
        calls++;
        throw DioException(requestOptions: RequestOptions(path: path),
          type: DioExceptionType.receiveTimeout);
      },
    ));
    final outcome = await coordinator.resolve(11, businessRequest()) as ReturnResolutionFailed;
    expect(calls, 1);
    expect(outcome.failure.kind, ApiFailureKind.timeout);
    expect(outcome.failure.code, isNull);
    expect(outcome.failure.requestId, isNull);
  });
}
