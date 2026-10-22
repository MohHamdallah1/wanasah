import 'package:dio/dio.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_client.dart';
import 'package:wanasah_frontend/core/serialization/json_contract.dart';

import '../domain/commercial/commercial_readiness.dart';
import '../domain/invoice/field_invoice.dart';
import '../domain/invoice/invoice_preview_request.dart';
import '../domain/returns/return_resolution.dart';

typedef VisitGet = Future<Object?> Function(
  String path, {Map<String, dynamic>? queryParameters}
);
typedef VisitPost = Future<Object?> Function(
  String path, {required Map<String, dynamic> data}
);

/// Visits-only FIELD reads, with no retries, queue or local projection.
/// Supply the existing authenticated ApiClient; callbacks support focused tests.
class VisitFieldClient {
  const VisitFieldClient({required VisitGet get, required VisitPost post})
    : _get = get, _post = post;

  factory VisitFieldClient.withApiClient(ApiClient client) => VisitFieldClient(
    get: (path, {queryParameters}) async =>
        (await client.get<Object?>(path, queryParameters: queryParameters)).data,
    post: (path, {required data}) async =>
        (await client.post<Object?>(path, data: data)).data,
  );

  final VisitGet _get;
  final VisitPost _post;

  Future<FieldReturnResolution> resolveReturn(
    int visitId, ReturnResolutionRequest request,
  ) => _read(
    () => _post('${_visit(visitId)}/return-resolution', data: request.toJson()),
    (body) => FieldReturnResolution.fromJson(body, request: request),
  );

  Future<CommercialReadiness> commercialState(int visitId) => _read(
    () => _get('${_visit(visitId)}/commercial-state'),
    CommercialReadiness.fromResponse,
  );

  Future<InvoicePreview> previewInvoice(
    int visitId, InvoicePreviewRequest request,
  ) => _read(
    () => _post('${_visit(visitId)}/invoice-preview', data: request.toJson()),
    InvoicePreview.fromJson,
  );

  Future<CommittedInvoiceResult> readInvoice(int visitId) => _read(
    () => _get('${_visit(visitId)}/invoice'),
    CommittedInvoiceResult.fromReadResponse,
  );

  static String _visit(int id) {
    JsonContract.integer(id, 'visit_id', minimum: 1);
    return '/visits/$id';
  }

  static Future<T> _read<T>(
    Future<Object?> Function() send, T Function(Object?) parse,
  ) async {
    try {
      return parse(await send());
    } on DioException catch (error) {
      throw ApiFailureException.fromDioException(error);
    }
  }
}
