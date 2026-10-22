import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/features/visits/application/commercial/commercial_readiness_outcome.dart';
import 'package:wanasah_frontend/features/visits/application/commercial/read_commercial_readiness.dart';
import 'package:wanasah_frontend/features/visits/data/visit_field_client.dart';
import 'package:wanasah_frontend/features/visits/domain/commercial/commercial_readiness.dart';

import '../../domain/returns/return_fixtures.dart';

void main() {
  test('ready state comes only from canonical commercial readiness', () async {
    var calls = 0;
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async {
        calls++;
        expect(path, '/visits/11/commercial-state');
        expect(queryParameters, isNull);
        return {'commercial_readiness': {
          'status': 'READY', 'sale_ready': true, 'code': null, 'required_action': null,
        }};
      },
      post: (path, {required data}) async => throw StateError('Unexpected POST'),
    );
    final outcome = await ReadCommercialReadiness.fromClient(client).execute(11) as CommercialReady;
    expect(calls, 1);
    expect(outcome.taxSetupReady, isTrue);
    expect(outcome.readiness.saleReady, isTrue);
    expect(outcome.readiness.status, CommercialReadinessStatus.ready);
    expect(outcome.readiness.code, isNull);
    expect(outcome.readiness.requiredAction, isNull);
  });

  for (final code in [
    'SHOP_TAX_JURISDICTION_REQUIRED', 'SHOP_TAX_JURISDICTION_REVIEW_REQUIRED',
  ]) {
    test('Backoffice completion remains actionable for $code without tax inference', () async {
      var calls = 0;
      final client = VisitFieldClient(
        get: (path, {queryParameters}) async {
          calls++;
          expect(path, '/visits/11/commercial-state');
          return {
            'latitude': '31.9', 'longitude': '35.9', 'zone_id': 42,
            'tax_jurisdiction_id': 99,
            'commercial_readiness': {
              'status': 'ACTION_REQUIRED', 'sale_ready': false, 'code': code,
              'required_action': 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
            },
          };
        },
        post: (path, {required data}) async => throw StateError('Unexpected POST'),
      );
      final outcome = await ReadCommercialReadiness.fromClient(client).execute(11)
        as CommercialActionRequired;
      expect(calls, 1);
      expect(outcome.taxSetupReady, isFalse);
      expect(outcome.readiness.saleReady, isFalse);
      expect(outcome.code, code);
      expect(outcome.requiredAction, 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION');
    });
  }

  test('typed readiness is preserved without rebuilding or inferring fields', () async {
    final expected = CommercialReadiness.fromJson({
      'status': 'ACTION_REQUIRED', 'sale_ready': false,
      'code': 'SHOP_TAX_JURISDICTION_REQUIRED',
      'required_action': 'BACKOFFICE_SET_SHOP_TAX_JURISDICTION',
    });
    final useCase = ReadCommercialReadiness(read: (id) async => expected);
    final outcome = await useCase.execute(11) as CommercialActionRequired;
    expect(outcome.readiness, same(expected));
  });

  test('malformed readiness fails closed and never permits the tax prerequisite', () async {
    for (final body in [
      <String, dynamic>{},
      {'commercial_readiness': {'status': 'READY', 'sale_ready': false}},
      {'commercial_readiness': {'status': 'UNKNOWN', 'sale_ready': true}},
      {'commercial_readiness': {
        'status': 'ACTION_REQUIRED', 'sale_ready': false,
        'code': 'SHOP_TAX_JURISDICTION_REQUIRED',
      }},
    ]) {
      final client = VisitFieldClient(
        get: (path, {queryParameters}) async => body,
        post: (path, {required data}) async => throw StateError('Unexpected POST'),
      );
      final outcome = await ReadCommercialReadiness.fromClient(client).execute(11);
      expect(outcome, isA<CommercialReadinessInvalidResponse>());
      expect(outcome.taxSetupReady, isFalse);
      expect(() => (outcome as dynamic).failure, throwsA(isA<NoSuchMethodError>()));
    }
  });

  test('failure retains original structured evidence and stays non-ready without retry', () async {
    final original = ApiFailure.fromDioException(responseError(
      status: 403, code: 'FIELD_VISIT_OUTSIDE_ASSIGNMENT',
      context: {'safe_reason': 'ASSIGNMENT', 'evidence': {'retained': true}},
    ));
    var calls = 0;
    final useCase = ReadCommercialReadiness(read: (id) async {
      calls++;
      throw ApiFailureException(original);
    });
    final outcome = await useCase.execute(11) as CommercialReadinessFailed;
    expect(calls, 1);
    expect(outcome.taxSetupReady, isFalse);
    expect(outcome.failure, same(original));
    expect(outcome.failure.context, same(original.context));
    expect(outcome.failure.status, 403);
    expect(outcome.failure.code, 'FIELD_VISIT_OUTSIDE_ASSIGNMENT');
    expect(outcome.failure.requestId, 'canonical-id');
  });
}
