import 'src/field_json.dart';

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
    final json = FieldJson.object(value, 'custody.item');
    return NonSellableCustodyItem._(
      productVariantId: FieldJson.integer(
        json['product_variant_id'], 'product_variant_id', minimum: 1),
      productName: FieldJson.text(json['product_name'], 'product_name'),
      status: FieldJson.code(json['stock_status'], NonSellableCustodyStatus.values,
        (status) => status.code, 'stock_status'),
      uomCode: FieldJson.text(json['uom_code'], 'uom_code'),
      quantity: FieldJson.decimal(json['quantity'], 'quantity'),
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
    final json = FieldJson.object(value, 'custody');
    final rows = FieldJson.list(json['items'], 'custody.items');
    if (rows.length > 200) FieldJson.invalid('custody.items');
    return NonSellableCustodyPage._(
      FieldJson.integer(json['session_id'], 'session_id', minimum: 1),
      rows.map(NonSellableCustodyItem.fromJson).toList(),
      FieldJson.optionalText(json['next_cursor'], 'next_cursor'),
    );
  }
}

class CustodyQuery {
  CustodyQuery({this.limit = 100, this.cursor}) {
    if (limit < 1 || limit > 200) FieldJson.invalid('custody.limit');
    if (cursor != null) {
      FieldJson.text(cursor, 'custody.cursor');
      if (cursor!.length > 8192) FieldJson.invalid('custody.cursor');
    }
  }

  final int limit;
  final String? cursor;

  Map<String, dynamic> toQueryParameters() => {
    'limit': limit,
    if (cursor != null) 'cursor': cursor,
  };
}
