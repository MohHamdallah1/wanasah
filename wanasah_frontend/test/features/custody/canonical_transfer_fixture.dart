Map<String, dynamic> canonicalTransfer({String quantity = '8', int id = 17}) =>
    {
      'real_transfer_id': id,
      'transfer_id': id,
      'product_name': 'منتج',
      'delta_cartons': 0,
      'delta_packs': int.parse(quantity),
      'quantity_contract': 'CANONICAL_BASE_V1',
      'signed_base_quantity': quantity,
      'base_uom_id': 1,
      'base_uom_code': 'EACH',
      'base_uom_name': 'حبة',
      'quantity_scale': 0,
      'quantity_step': '1',
      'display_uom_name': 'باكيت',
      'display_factor_to_base': '8',
      'packs_per_carton': 32,
    };
