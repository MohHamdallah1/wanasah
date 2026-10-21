import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/features/visits/visit_field_contracts.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';

import '../domain/invoice/invoice_fixtures.dart';
import '../domain/returns/return_fixtures.dart';

void main() {
  test('all four Visit reads use exact routes, verbs and quantity-only bodies', () async {
    final calls = <Map<String, dynamic>>[];
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async {
        calls.add({'method': 'GET', 'path': path, 'query': queryParameters});
        switch (path) {
          case '/visits/11/commercial-state':
            return {'commercial_readiness': {
              'status': 'READY', 'sale_ready': true, 'code': null, 'required_action': null,
            }};
          case '/visits/11/invoice':
            return {'invoice': invoiceJson()};
          default:
            throw StateError('Unexpected GET');
        }
      },
      post: (path, {required data}) async {
        calls.add({'method': 'POST', 'path': path, 'data': data});
        if (path == '/visits/11/return-resolution') return resolvedJson();
        if (path == '/visits/11/invoice-preview') {
          return {'invoice': invoiceJson(status: 'PREVIEW', revision: false), 'commit_required': true};
        }
        throw StateError('Unexpected POST');
      },
    );

    final request = ReturnResolutionRequest(productVariantId: 44, packsQuantity: 2);
    final resolved = await client.resolveReturn(11, request);
    expect(resolved.request, same(request));
    expect((await client.commercialState(11)).saleReady, isTrue);
    final previewRequest = InvoicePreviewRequest([InvoicePreviewLine(
      productVariantId: 44, quantity: 1, packsQuantity: 3)]);
    expect((await client.previewInvoice(11, previewRequest)).commitRequired, isTrue);
    expect((await client.readInvoice(11)).invoice!.revisionNumber, 2);

    expect(calls, [
      {'method': 'POST', 'path': '/visits/11/return-resolution', 'data': request.toJson()},
      {'method': 'GET', 'path': '/visits/11/commercial-state', 'query': null},
      {'method': 'POST', 'path': '/visits/11/invoice-preview', 'data': previewRequest.toJson()},
      {'method': 'GET', 'path': '/visits/11/invoice', 'query': null},
    ]);
  });

  test('structured failure preserves Network metadata and typed ambiguity', () async {
    final error = responseError();
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async => throw error,
      post: (path, {required data}) async => throw error,
    );
    try {
      await client.resolveReturn(11, ReturnResolutionRequest(productVariantId: 44, packsQuantity: 1));
      fail('Expected ApiFailureException');
    } on ApiFailureException catch (failure) {
      expect(failure.apiFailure.kind, ApiFailureKind.serverResponse);
      expect(failure.apiFailure.status, 409);
      expect(failure.code, 'FIELD_RETURN_EVIDENCE_REQUIRED');
      expect(failure.requestId, 'canonical-id');
      expect(failure.context, error.apiFailure.context);
      expect(failure.returnAmbiguity!.requiredEvidence, [ReturnEvidenceField.lotNumber]);
      expect(failure.toString(), isNot(contains('Human display text')));
      expect(() => failure.context['changed'] = true, throwsUnsupportedError);
    }
  });

  test('existing ApiFailure can be carried without reparsing or losing context', () {
    final original = ambiguityFailure(context: {
      'required_evidence': ['delivery_date'],
      'structured_extra': {'nested': [1, true, null]},
    });
    final failure = ApiFailureException(original);
    expect(failure.apiFailure, same(original));
    expect(failure.context, same(original.context));
    expect(failure.requestId, original.requestId);
  });

  test('timeout on read-only POST is surfaced once without a client retry policy', () async {
    var sends = 0;
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async => throw StateError('No GET'),
      post: (path, {required data}) async {
        sends++;
        throw DioException(
          requestOptions: RequestOptions(path: path, method: 'POST'),
          type: DioExceptionType.receiveTimeout,
        );
      },
    );
    await expectLater(
      client.resolveReturn(11, ReturnResolutionRequest(productVariantId: 44, packsQuantity: 1)),
      throwsA(isA<ApiFailureException>().having(
        (failure) => failure.apiFailure.kind, 'kind', ApiFailureKind.timeout)),
    );
    expect(sends, 1);
  });

  test('malformed success stays a contract failure without invented server metadata', () async {
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async => {},
      post: (path, {required data}) async => {},
    );
    await expectLater(client.commercialState(11), throwsFormatException);
    await expectLater(client.readInvoice(11), throwsFormatException);
  });

  test('invalid visit locator fails before transport', () async {
    var sends = 0;
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async { sends++; return {}; },
      post: (path, {required data}) async { sends++; return {}; },
    );
    await expectLater(client.readInvoice(0), throwsFormatException);
    expect(sends, 0);
  });

  test('all Visit endpoint failures reuse ApiFailure correlation header fallback', () async {
    final request = RequestOptions(path: '/visits/11/invoice');
    final error = DioException(
      requestOptions: request, type: DioExceptionType.badResponse,
      response: Response(requestOptions: request, statusCode: 503,
        headers: Headers.fromMap({'x-request-id': ['only-header-id']}),
        data: {'error': {'code': 'TEMPORARY', 'context': {'retry': true}}}),
    );
    final client = VisitFieldClient(
      get: (path, {queryParameters}) async => throw error,
      post: (path, {required data}) async => throw error,
    );
    for (final send in <Future<Object?> Function()>[
      () => client.commercialState(11),
      () => client.readInvoice(11),
      () => client.resolveReturn(11, ReturnResolutionRequest(productVariantId: 44, packsQuantity: 1)),
      () => client.previewInvoice(11, InvoicePreviewRequest([
        InvoicePreviewLine(productVariantId: 44, packsQuantity: 1)])),
    ]) {
      await expectLater(send(), throwsA(isA<ApiFailureException>()
        .having((failure) => failure.requestId, 'requestId', 'only-header-id')
        .having((failure) => failure.code, 'code', 'TEMPORARY')
        .having((failure) => failure.context, 'context', {'retry': true})));
    }
  });
}
