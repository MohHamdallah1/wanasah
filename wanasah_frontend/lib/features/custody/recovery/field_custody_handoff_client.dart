import 'package:dio/dio.dart';
import 'package:uuid/uuid.dart';
import '../../../core/network/auth_token_store.dart';
import '../../../services/api_constants.dart';

const custodyHandoffStates = {
  'PENDING',
  'CONFIRMED',
  'DECLINED',
  'CANCELLED',
  'EXPIRED',
  'COMMITTED',
};
final _fingerprint = RegExp(r'^[a-f0-9]{64}$');
final _id = RegExp(r'^[0-9a-fA-F-]{36}$');

/// Only a genuine authenticated FIELD principal can enumerate and decide
/// its OWN vehicle handoffs. No log interceptor, credentials in body, durable
/// offline queue or token/receipt clipboard. The backend is the sole authority.
class FieldCustodyHandoffClient {
  FieldCustodyHandoffClient({Dio? dio, AuthTokenStore? tokens})
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

  Future<Options> _auth() async {
    final token = await _tokens.readAccessToken();
    if (token == null || token.isEmpty) {
      throw StateError('CUSTODY_FIELD_NOT_AUTHENTICATED');
    }
    return Options(
      headers: {'Authorization': 'Bearer $token'},
      extra: const {'sensitive_custody_evidence': true},
      responseType: ResponseType.json,
    );
  }

  Future<dynamic> _get(String path) async =>
      (await _dio.get<dynamic>(path, options: await _auth())).data;

  Future<dynamic> _post(String path, Map<String, dynamic> body) async =>
      (await _dio.post<dynamic>(path, data: body, options: await _auth())).data;

  Future<List<FieldCustodyRequest>> pending() async {
    final raw = await _get('/driver/custody/handoffs/pending');
    final list =
        raw is List
            ? raw
            : raw is Map
            ? raw['items']
            : null;
    if (list is! List || list.length > 100) {
      throw const FormatException('CUSTODY_BAD_INBOX');
    }
    return list
        .map((item) => FieldCustodyRequest.fromMap(item))
        .toList(growable: false);
  }

  Future<FieldCustodyRequest> detail(String handoffId) async {
    if (!_id.hasMatch(handoffId)) throw const FormatException('CUSTODY_BAD_ID');
    final raw = await _get('/driver/custody/handoffs/$handoffId');
    final request = FieldCustodyRequest.fromMap(raw, requireStock: true);
    if (request.handoffId != handoffId) {
      throw const FormatException('CUSTODY_WRONG_HANDOFF');
    }
    return request;
  }

  Future<FieldCustodyRequest> decide({
    required FieldCustodyRequest request,
    required String requestId,
    required String decision,
    bool physicalCountConfirmed = false,
    String? reasonCode,
    String? reasonText,
  }) async {
    if (request.state != 'PENDING' || !_id.hasMatch(requestId)) {
      throw const FormatException('CUSTODY_INVALID_DECISION');
    }
    if (decision == 'CONFIRM') {
      if (!physicalCountConfirmed || request.stockSnapshot == null) {
        throw const FormatException('CUSTODY_COUNT_REQUIRED');
      }
    } else if (decision == 'DECLINE') {
      if (!{
        'DISCREPANCY',
        'NOT_MY_GOODS',
        'VEHICLE_UNAVAILABLE',
        'OTHER',
      }.contains(reasonCode)) {
        throw const FormatException('CUSTODY_REASON_REQUIRED');
      }
      if ((reasonText ?? '').length > 240) {
        throw const FormatException('CUSTODY_REASON_TOO_LONG');
      }
    } else {
      throw const FormatException('CUSTODY_INVALID_DECISION');
    }
    final body = <String, dynamic>{
      'request_id': requestId,
      'decision': decision,
    };
    if (decision == 'CONFIRM') {
      body['confirmed_stock_snapshot'] = request.stockSnapshot;
      body['receiver_confirms_physical_count'] = true;
    } else {
      body['reason_code'] = reasonCode;
      if ((reasonText ?? '').trim().isNotEmpty) {
        body['reason_text'] = reasonText!.trim();
      }
    }
    final raw = await _post(
      '/driver/custody/handoffs/${request.handoffId}/decision',
      body,
    );
    if (raw is! Map ||
        raw['handoff_id'] != request.handoffId ||
        raw['vehicle_id'] != request.vehicleId ||
        raw['state'] != (decision == 'CONFIRM' ? 'CONFIRMED' : 'DECLINED')) {
      throw const FormatException('CUSTODY_UNVERIFIED_DECISION');
    }
    // Re-read the own-principal server truth, not local optimistic state.
    final updated = await detail(request.handoffId);
    if (updated.state != raw['state']) {
      throw const FormatException('CUSTODY_DECISION_CHANGED');
    }
    return updated;
  }

  String newRequestId() => const Uuid().v4();
}

class FieldCustodyRequest {
  const FieldCustodyRequest({
    required this.handoffId,
    required this.vehicleId,
    required this.vehiclePlate,
    required this.state,
    required this.expiresAt,
    this.stockSnapshot,
    this.stockLines = const [],
    this.reasonText,
  });
  final String handoffId;
  final int vehicleId;
  final String vehiclePlate;
  final String state;
  final String expiresAt;
  final String? stockSnapshot;
  final List<Map<String, dynamic>> stockLines;
  final String? reasonText;

  factory FieldCustodyRequest.fromMap(
    dynamic value, {
    bool requireStock = false,
  }) {
    if (value is! Map) throw const FormatException('CUSTODY_INVALID_RECORD');
    final id = value['handoff_id'], vehicle = value['vehicle_id'];
    final status = value['state'], plate = value['vehicle_plate'];
    final expiry = value['expires_at'];
    if (id is! String ||
        !_id.hasMatch(id) ||
        vehicle is! int ||
        vehicle <= 0 ||
        status is! String ||
        !custodyHandoffStates.contains(status) ||
        plate is! String ||
        plate.isEmpty ||
        expiry is! String ||
        expiry.isEmpty) {
      throw const FormatException('CUSTODY_INVALID_RECORD');
    }
    final snapshot = value['stock_snapshot'], raw = value['stock_lines'];
    if (requireStock &&
        (snapshot is! String ||
            !_fingerprint.hasMatch(snapshot) ||
            raw is! List ||
            raw.length > 1000)) {
      throw const FormatException('CUSTODY_INVALID_STOCK_SNAPSHOT');
    }
    final lines =
        raw is List
            ? raw
                .map((entry) {
                  if (entry is! Map) {
                    throw const FormatException('CUSTODY_INVALID_STOCK_LINE');
                  }
                  return Map<String, dynamic>.from(entry);
                })
                .toList(growable: false)
            : <Map<String, dynamic>>[];
    return FieldCustodyRequest(
      handoffId: id,
      vehicleId: vehicle,
      vehiclePlate: plate,
      state: status,
      expiresAt: expiry,
      stockSnapshot:
          snapshot is String && _fingerprint.hasMatch(snapshot)
              ? snapshot
              : null,
      stockLines: lines,
      reasonText:
          value['reason_text'] is String
              ? value['reason_text'] as String
              : null,
    );
  }
}
