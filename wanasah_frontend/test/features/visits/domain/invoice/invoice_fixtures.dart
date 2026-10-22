Map<String, dynamic> invoiceJson({String status = 'COMMITTED', bool revision = true}) => {
  'status': status,
  'currency_code': 'JOD',
  'calculated_at': '2026-10-22T10:15:30.123456+03:00',
  'rounding': {'precision': 3, 'mode': 'HALF_UP'},
  'totals': <String, dynamic>{
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

