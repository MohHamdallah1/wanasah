import 'package:dio/dio.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';

Map<String, dynamic> resolvedJson() => {
  'status': 'RESOLVED',
  'resolution_token': 'opaque.header.signature-DO_NOT_DECODE',
  'evidence': <String, dynamic>{
    'lot_number': 'LOT / A  ',
    'production_date': '2026-01-03',
    'expiry_date': '2027-01-03',
  },
};

DioException responseError({
  String? code = 'FIELD_RETURN_EVIDENCE_REQUIRED',
  String message = 'Human display text',
  Map<String, dynamic> context = const {
    'required_evidence': ['lot_number'],
    'choices': [{'lot_number': 'LOT-A'}, {'lot_number': 'LOT-B'}],
  },
  int status = 409,
}) {
  final request = RequestOptions(path: '/visits/11/return-resolution', method: 'POST');
  return DioException(
    requestOptions: request,
    type: DioExceptionType.badResponse,
    response: Response(
      requestOptions: request,
      statusCode: status,
      headers: Headers.fromMap({'x-request-id': ['header-id']}),
      data: {
        'request_id': 'root-id',
        'error': {
          'code': code,
          'message': message,
          'context': context,
          'request_id': 'canonical-id',
        },
      },
    ),
  );
}

ApiFailure ambiguityFailure({Map<String, dynamic>? context, String? code}) =>
    responseError(
      code: code ?? 'FIELD_RETURN_EVIDENCE_REQUIRED',
      context: context ?? const {
        'required_evidence': ['lot_number'],
        'choices': [{'lot_number': 'LOT-A'}, {'lot_number': 'LOT-B'}],
      },
    ).apiFailure;
