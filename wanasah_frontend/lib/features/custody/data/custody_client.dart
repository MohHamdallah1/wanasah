import 'package:dio/dio.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/core/network/api_client.dart';

import '../domain/non_sellable_custody.dart';

typedef CustodyGet = Future<Object?> Function(
  String path, {Map<String, dynamic>? queryParameters}
);

/// Non-sellable custody read only; no Visits, retries or local projection.
class CustodyClient {
  const CustodyClient({required CustodyGet get}) : _get = get;

  factory CustodyClient.withApiClient(ApiClient client) => CustodyClient(
    get: (path, {queryParameters}) async =>
        (await client.get<Object?>(path, queryParameters: queryParameters)).data,
  );

  final CustodyGet _get;

  Future<NonSellableCustodyPage> custody({CustodyQuery? query}) async {
    try {
      return NonSellableCustodyPage.fromJson(await _get(
        '/driver/custody',
        queryParameters: (query ?? CustodyQuery()).toQueryParameters(),
      ));
    } on DioException catch (error) {
      throw ApiFailureException.fromDioException(error);
    }
  }
}
