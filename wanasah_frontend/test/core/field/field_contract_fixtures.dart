import 'package:dio/dio.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';

Map<String, dynamic> invoiceJson({String status = 'COMMITTED', bool revision = true}) => {
  'status': status,
  'currency_code': 'JOD',
  'calculated_at': '2026-10-22T10:15:30.123456+03:00',
  'rounding': {'precision': 3, 'mode': 'HALF_UP'},
  'totals': {
    'gross_amount': '9007199254740993.123456',
    'discount_amount': '1.000000',
    'post_offer_amount': '9007199254740992.123456',
    'taxable_amount': '9007199254740992.123456',
    'tax_amount': '0.000000',
    'line_total_amount': '9007199254740992.123456',
    'rounding_adjustment': '-0.000456',
    'final_amount': '9007199254740992.123000',
  },
  'lines': [{
    'product_variant_id': 44,
    'gross_amount': '9007199254740993.123456',
    'discount_amount': '1.000000',
    'tax_amount': '0.000000',
    'final_amount': '9007199254740992.123456',
  }],
  'rewards': [{'product_variant_id': 45, 'base_quantity': '0.500000'}],
  if (revision) 'revision_number': 2,
};

Map<String, dynamic> resolvedJson() => {
  'status': 'RESOLVED',
  'resolution_token': 'opaque.header.signature-DO_NOT_DECODE',
  'evidence': {
    'lot_number': 'LOT / A  ',
    'production_date': '2026-01-03',
    'expiry_date': '2027-01-03',
  },
};

Map<String, dynamic> custodyItemJson({String status = 'DAMAGED'}) => {
  'product_variant_id': 44,
  'product_name': 'عصير',
  'stock_status': status,
  'uom_code': 'EACH',
  'quantity': '9007199254740993.125000',
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
