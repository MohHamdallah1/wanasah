import 'dart:convert';

import 'package:dio/dio.dart';

import '../../../core/network/auth_token_store.dart';
import '../../../services/api_constants.dart';

/// Independent no-log transport: the generic debug ApiClient LogInterceptor
/// prints request/response bodies, which MUST NEVER include signed custody
/// offers or receiver proofs. No durable queue, analytics or offline retry.
class CustodyHandoffClient {
  CustodyHandoffClient({Dio? dio, AuthTokenStore? tokens})
    : _dio =
          dio ??
          Dio(
            BaseOptions(
              baseUrl: ApiConstants.baseUrl,
              connectTimeout: const Duration(seconds: 25),
              receiveTimeout: const Duration(seconds: 35),
              headers: {'Content-Type': 'application/json'},
            ),
          ),
      _tokens = tokens ?? SecureAuthTokenStore();

  final Dio _dio;
  final AuthTokenStore _tokens;

  /// Decode ONLY for the routing path. Untrusted token data has no authority;
  /// the real scoped FIELD POST preview verifies HMAC, TTL, tenant and actor.
  static int offerVehicleRouteId(String token) {
    if (token.length < 50 || token.length > 2048) {
      throw const FormatException('CUSTODY_PROOF_INVALID');
    }
    try {
      final parts = token.split('.');
      if (parts.length != 2) {
        throw const FormatException('CUSTODY_PROOF_INVALID');
      }
      final decoded = jsonDecode(
        utf8.decode(base64Url.decode(base64Url.normalize(parts[0]))),
      );
      if (decoded is! Map || decoded['purpose'] != 'CUSTODY_OFFER') {
        throw const FormatException('CUSTODY_PROOF_INVALID');
      }
      final id = decoded['vehicle'];
      if (id is! int || id <= 0) {
        throw const FormatException('CUSTODY_PROOF_INVALID');
      }
      return id;
    } catch (_) {
      throw const FormatException('CUSTODY_PROOF_INVALID');
    }
  }

  Future<Map<String, dynamic>> _post(
    int id,
    String action,
    Map<String, dynamic> data,
  ) async {
    final token = await _tokens.readAccessToken();
    if (token == null || token.isEmpty) {
      throw StateError('CUSTODY_FIELD_NOT_AUTHENTICATED');
    }
    final response = await _dio.post<Map<String, dynamic>>(
      '/driver/vehicles/$id/custody/$action',
      data: data,
      options: Options(
        headers: {'Authorization': 'Bearer $token'},
        extra: const {'sensitive_custody_evidence': true},
      ),
    );
    final body = response.data;
    if (body == null) {
      throw const FormatException('CUSTODY_UNVERIFIED_RESPONSE');
    }
    return body;
  }

  Future<CustodyHandoffPreview> review(String signedOffer) async {
    final vehicleId = offerVehicleRouteId(signedOffer);
    final response = await _post(vehicleId, 'offer-preview', {
      'offer_token': signedOffer,
    });
    if (response['vehicle_id'] != vehicleId ||
        response['stock_snapshot'] is! String ||
        !RegExp(r'^[a-f0-9]{64}$').hasMatch(response['stock_snapshot']) ||
        response['stock_lines'] is! List ||
        response['vehicle_plate'] is! String ||
        (response['vehicle_plate'] as String).isEmpty) {
      throw const FormatException('CUSTODY_UNVERIFIED_RESPONSE');
    }
    return CustodyHandoffPreview(
      vehicleId: vehicleId,
      vehiclePlate: response['vehicle_plate'] as String,
      stockSnapshot: response['stock_snapshot'] as String,
      rows: (response['stock_lines'] as List)
          .map((e) => Map<String, dynamic>.from(e as Map))
          .toList(growable: false),
    );
  }

  Future<String> confirm(String offer, CustodyHandoffPreview review) async {
    if (review.vehicleId != offerVehicleRouteId(offer)) {
      throw const FormatException('CUSTODY_OFFER_CHANGED');
    }
    final response = await _post(review.vehicleId, 'confirm', {
      'offer_token': offer,
      'confirmed_stock_snapshot': review.stockSnapshot,
      'receiver_confirms_physical_count': true,
    });
    if (response['confirmed'] != true ||
        response['stock_snapshot'] != review.stockSnapshot ||
        response['receiver_proof'] is! String) {
      throw const FormatException('CUSTODY_RECEIPT_UNVERIFIED');
    }
    return response['receiver_proof'] as String;
  }
}

class CustodyHandoffPreview {
  const CustodyHandoffPreview({
    required this.vehicleId,
    required this.vehiclePlate,
    required this.stockSnapshot,
    required this.rows,
  });
  final int vehicleId;
  final String vehiclePlate;
  final String stockSnapshot;
  final List<Map<String, dynamic>> rows;
}
