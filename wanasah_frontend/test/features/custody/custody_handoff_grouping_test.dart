import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/recovery/custody_handoff_grouping.dart';
import 'package:wanasah_frontend/features/custody/recovery/custody_handoff_quantity.dart';

void main() {
  test(
    'group only identical real physical no-lot stock; preserve signed originals',
    () {
      final original = [
        {
          'sku': 'R',
          'product_name': 'Rice',
          'batch_number': '',
          'expiry_date': null,
          'base_uom': 'EACH',
          'base_uom_name': 'حبة',
          'display_uom_name': null,
          'display_factor_to_base': null,
          'stock_status': 'AVAILABLE',
          'on_hand_base': '5',
          'reserved_base': '0',
        },
        {
          'sku': 'R',
          'product_name': 'Rice',
          'batch_number': '',
          'expiry_date': null,
          'base_uom': 'EACH',
          'base_uom_name': 'حبة',
          'display_uom_name': null,
          'display_factor_to_base': null,
          'stock_status': 'AVAILABLE',
          'on_hand_base': '20',
          'reserved_base': '0',
        },
        {
          'sku': 'V',
          'product_name': 'Vermicelli',
          'batch_number': 'LOT11',
          'expiry_date': null,
          'base_uom': 'EACH',
          'base_uom_name': 'حبة',
          'display_uom_name': 'باكيت',
          'display_factor_to_base': '8',
          'stock_status': 'AVAILABLE',
          'on_hand_base': '10',
          'reserved_base': '0',
        },
        {
          'sku': 'V',
          'product_name': 'Vermicelli',
          'batch_number': 'LOT12',
          'expiry_date': null,
          'base_uom': 'EACH',
          'base_uom_name': 'حبة',
          'display_uom_name': 'باكيت',
          'display_factor_to_base': '8',
          'stock_status': 'AVAILABLE',
          'on_hand_base': '15',
          'reserved_base': '0',
        },
      ];
      final visible = visibleCustodyHandoffLines(original);
      expect(visible.length, 3);
      expect(visible[0]['on_hand_base'], '25');
      expect(
        formatCustodyHandoffQuantity(visible[0], locale: 'ar'),
        contains('25'),
      );
      expect(visible[1]['batch_number'], 'LOT11');
      expect(visible[2]['batch_number'], 'LOT12');
      expect(original[0]['on_hand_base'], '5');
      expect(original[1]['on_hand_base'], '20');
    },
  );
}
