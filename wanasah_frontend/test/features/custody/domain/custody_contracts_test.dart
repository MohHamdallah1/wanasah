import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/domain/non_sellable_custody.dart';

import 'custody_fixtures.dart';

void main() {
  for (final status in NonSellableCustodyStatus.values) {
    test('custody parses ${status.code} and preserves exact base quantity', () {
      final page = NonSellableCustodyPage.fromJson({
        'session_id': 33, 'items': [custodyItemJson(status: status.code)],
        'next_cursor': 'opaque+/=owner.session.cursor',
      });
      final item = page.items.single;
      expect(page.sessionId, 33);
      expect(item.status, status);
      expect(item.productVariantId, 44);
      expect(item.productName, 'عصير');
      expect(item.uomCode, 'EACH');
      expect(item.quantity, '9007199254740993.125000');
      expect(page.nextCursor, 'opaque+/=owner.session.cursor');
      expect(() => page.items.clear(), throwsUnsupportedError);
    });
  }

  test('empty terminal page remains empty, without synthesizing stock', () {
    final page = NonSellableCustodyPage.fromJson({
      'session_id': 33, 'items': [], 'next_cursor': null,
    });
    expect(page.items, isEmpty);
    expect(page.nextCursor, isNull);
  });

  test('public custody item has no raw Batch property even if server adds one', () {
    final item = NonSellableCustodyItem.fromJson(custodyItemJson()..['batch_id'] = 987);
    expect(() => (item as dynamic).batchId, throwsA(isA<NoSuchMethodError>()));
    expect(() => (item as dynamic).batch_id, throwsA(isA<NoSuchMethodError>()));
  });

  test('unknown/sellable status and numeric quantities are not coerced', () {
    for (final status in ['AVAILABLE', 'NEW_UNKNOWN_STATUS']) {
      expect(() => NonSellableCustodyItem.fromJson(custodyItemJson(status: status)),
        throwsFormatException);
    }
    expect(() => NonSellableCustodyItem.fromJson(
      custodyItemJson()..['quantity'] = 0.125), throwsFormatException);
  });

  test('bounded query preserves opaque cursor and omits absent cursor', () {
    expect(CustodyQuery().toQueryParameters(), {'limit': 100});
    expect(CustodyQuery(limit: 200, cursor: '  opaque+/=  ').toQueryParameters(),
      {'limit': 200, 'cursor': '  opaque+/=  '});
    for (final limit in [0, 201]) {
      expect(() => CustodyQuery(limit: limit), throwsFormatException);
    }
  });
}
