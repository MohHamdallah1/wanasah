import 'package:dio/dio.dart';

import '../../../core/network/api_client.dart';
import '../../../core/network/api_failure.dart';
import '../domain/shop_creation.dart';

class ShopCreationClient implements ShopCreationGateway {
  ShopCreationClient({ApiClient? apiClient})
      : _api = apiClient ?? ApiClient.instance;

  final ApiClient _api;

  @override
  Future<ShopCreateResult> create(ShopCreateCommand command) async {
    try {
      final response = await _api.post('/shops', data: command.toJson());
      final data = Map<String, dynamic>.from(response.data as Map);
      final shop = Map<String, dynamic>.from(data['shop'] as Map);
      final readiness = Map<String, dynamic>.from(
        data['commercial_readiness'] as Map,
      );
      return ShopCreateResult(
        shopId: (shop['id'] as num).toInt(),
        shopName: shop['name']?.toString() ?? command.name,
        commercialReadiness: ShopCommercialReadiness.fromJson(readiness),
      );
    } on DioException catch (error) {
      final failure = error.apiFailure;
      final ambiguous = failure.kind == ApiFailureKind.connection ||
          failure.kind == ApiFailureKind.timeout ||
          (failure.status != null && failure.status! >= 500);
      final kind = _shopFailureKind(failure);
      throw ShopCreateFailure(
        kind: kind,
        ambiguous: ambiguous,
        status: failure.status,
        code: failure.code,
        context: failure.context,
        requestId: failure.requestId,
        displayFallback: failure.displayFallback,
      );
    }
  }
}


ShopCreateFailureKind _shopFailureKind(ApiFailure failure) {
  final status = failure.status;

  if (failure.kind == ApiFailureKind.connection) {
    return ShopCreateFailureKind.connectivity;
  }
  if (failure.kind == ApiFailureKind.timeout) {
    return ShopCreateFailureKind.timeout;
  }
  if (failure.kind == ApiFailureKind.cancelled) {
    return ShopCreateFailureKind.cancelled;
  }
  if (failure.kind != ApiFailureKind.serverResponse || status == null) {
    return ShopCreateFailureKind.unexpected;
  }
  if (status == 401 || status == 403) {
    return ShopCreateFailureKind.authorization;
  }
  if (status == 429) {
    return ShopCreateFailureKind.rateLimited;
  }
  if (status >= 500) {
    return ShopCreateFailureKind.server;
  }
  if (status >= 400) {
    return ShopCreateFailureKind.businessRejected;
  }
  return ShopCreateFailureKind.unexpected;
}
