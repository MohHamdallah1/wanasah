import 'package:wanasah_frontend/core/serialization/json_contract.dart';

enum NonSellableCustodyStatus {
  quarantined('QUARANTINED'),
  blocked('BLOCKED'),
  recalled('RECALLED'),
  damaged('DAMAGED'),
  disposalPending('DISPOSAL_PENDING');

  const NonSellableCustodyStatus(this.code);
  final String code;
}

class NonSellableCustodyItem {
  const NonSellableCustodyItem._({
    required this.productVariantId,
    required this.productName,
    required this.status,
    required this.uomCode,
    required this.quantity,
  });

  final int productVariantId;
  final String productName;
  final NonSellableCustodyStatus status;
  final String uomCode;
  final String quantity;

  factory NonSellableCustodyItem.fromJson(Object? value) {
    final json = JsonContract.object(value, 'custody.item');
    return NonSellableCustodyItem._(
      productVariantId: JsonContract.integer(
        json['product_variant_id'], 'product_variant_id', minimum: 1),
      productName: JsonContract.text(json['product_name'], 'product_name'),
      status: JsonContract.code(json['stock_status'], NonSellableCustodyStatus.values,
        (status) => status.code, 'stock_status'),
      uomCode: JsonContract.text(json['uom_code'], 'uom_code'),
      quantity: JsonContract.decimal(json['quantity'], 'quantity'),
    );
  }
}

class NonSellableCustodyPage {
  NonSellableCustodyPage._(this.sessionId, List<NonSellableCustodyItem> items, this.nextCursor)
    : items = List.unmodifiable(items);

  final int sessionId;
  final List<NonSellableCustodyItem> items;
  /// Opaque owner/session-bound transport, never interpreted or logged.
  final String? nextCursor;

  factory NonSellableCustodyPage.fromJson(Object? value) {
    final json = JsonContract.object(value, 'custody');
    final rows = JsonContract.list(json['items'], 'custody.items');
    if (rows.length > 200) JsonContract.invalid('custody.items');
    return NonSellableCustodyPage._(
      JsonContract.integer(json['session_id'], 'session_id', minimum: 1),
      rows.map(NonSellableCustodyItem.fromJson).toList(),
      JsonContract.optionalText(json['next_cursor'], 'next_cursor'),
    );
  }
}

class CustodyQuery {
  CustodyQuery({this.limit = 100, this.cursor}) {
    if (limit < 1 || limit > 200) JsonContract.invalid('custody.limit');
    if (cursor != null) {
      JsonContract.text(cursor, 'custody.cursor');
      if (cursor!.length > 8192) JsonContract.invalid('custody.cursor');
    }
  }

  final int limit;
  final String? cursor;

  Map<String, dynamic> toQueryParameters() => {
    'limit': limit,
    if (cursor != null) 'cursor': cursor,
  };
}
