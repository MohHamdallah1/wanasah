import 'package:dio/dio.dart';

import '../network/api_client.dart';
import 'commercial_readiness.dart';
import 'field_invoice.dart';
import 'field_seam_failure.dart';
import 'invoice_preview_request.dart';
import 'non_sellable_custody.dart';
import 'return_resolution.dart';
import 'src/field_json.dart';

typedef FieldGet = Future<Object?> Function(
  String path, {Map<String, dynamic>? queryParameters}
);
typedef FieldPost = Future<Object?> Function(
  String path, {required Map<String, dynamic> data}
);

/// Typed seam adapter, with no retries, queue, auth policy or local projection.
/// Supply the existing authenticated ApiClient; callbacks support focused tests.
class FieldSeamsClient {
  const FieldSeamsClient({required FieldGet get, required FieldPost post})
    : _get = get, _post = post;

  factory FieldSeamsClient.withApiClient(ApiClient client) => FieldSeamsClient(
    get: (path, {queryParameters}) async =>
        (await client.get<Object?>(path, queryParameters: queryParameters)).data,
    post: (path, {required data}) async =>
        (await client.post<Object?>(path, data: data)).data,
  );

  final FieldGet _get;
  final FieldPost _post;

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

  Future<NonSellableCustodyPage> custody({CustodyQuery? query}) => _read(
    () => _get('/driver/custody',
      queryParameters: (query ?? CustodyQuery()).toQueryParameters()),
    NonSellableCustodyPage.fromJson,
  );

  static String _visit(int id) {
    FieldJson.integer(id, 'visit_id', minimum: 1);
    return '/visits/$id';
  }

  static Future<T> _read<T>(
    Future<Object?> Function() send, T Function(Object?) parse,
  ) async {
    try {
      return parse(await send());
    } on DioException catch (error) {
      throw FieldSeamFailure.fromDioException(error);
    }
  }
}
