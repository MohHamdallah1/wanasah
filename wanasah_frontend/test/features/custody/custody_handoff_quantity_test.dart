import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/recovery/custody_handoff_quantity.dart';

void main() {
  test(
    'custody review uses the signed largest exact UOM, not floating quantities',
    () {
      const item = <String, dynamic>{
        'on_hand_base': '10.000000',
        'base_uom': 'EACH',
        'base_uom_name': 'حبة',
        'display_uom_name': 'باكيت',
        'display_factor_to_base': '8',
      };
      expect(
        formatCustodyHandoffQuantity(item, locale: 'en'),
        '1 باكيت + 2 حبة',
      );
      expect(
        formatCustodyHandoffQuantity({
          ...item,
          'on_hand_base': '15.000000',
        }, locale: 'en'),
        '1 باكيت + 7 حبة',
      );
      expect(
        formatCustodyHandoffQuantity({
          ...item,
          'on_hand_base': '16.000000',
        }, locale: 'en'),
        '2 باكيت',
      );
    },
  );

  test(
    'missing conversion leaves real base UOM and eliminates raw decimals',
    () {
      const item = <String, dynamic>{
        'on_hand_base': '20.000000',
        'base_uom': 'EACH',
        'base_uom_name': 'حبة',
        'display_uom_name': null,
        'display_factor_to_base': null,
      };
      expect(formatCustodyHandoffQuantity(item, locale: 'en'), '20 حبة');
    },
  );
}
