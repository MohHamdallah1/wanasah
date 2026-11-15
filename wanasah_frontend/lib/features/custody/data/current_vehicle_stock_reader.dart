import 'package:wanasah_frontend/core/network/api_client.dart';
import 'package:wanasah_frontend/core/serialization/json_contract.dart';
import '../domain/vehicle_route_authority.dart';

class CurrentVehicleStockItem {
  const CurrentVehicleStockItem({
    required this.productVariantId,
    required this.name,
    required this.status,
    required this.baseUomCode,
    required this.quantity,
  });

  final int productVariantId;
  final String name;
  final String status;
  final String baseUomCode;
  final String quantity;

  static const statuses = <String>{
    'AVAILABLE',
    'DAMAGED',
    'QUARANTINED',
    'BLOCKED',
    'RECALLED',
    'DISPOSAL_PENDING',
  };

  factory CurrentVehicleStockItem.parse(
    Object? value, {
    required bool sellable,
  }) {
    final map = JsonContract.object(value, 'vehicle_stock.item');
    final variantId = JsonContract.integer(
      map['product_variant_id'],
      'vehicle_stock.variant_id',
      minimum: 1,
    );
    final name = JsonContract.text(map['product_name'], 'vehicle_stock.name');
    final status = JsonContract.text(
      map['stock_status'],
      'vehicle_stock.status',
    );
    if (!statuses.contains(status) ||
        (sellable ? status != 'AVAILABLE' : status == 'AVAILABLE')) {
      JsonContract.invalid('vehicle_stock.status');
    }
    final base = JsonContract.text(map['uom_code'], 'vehicle_stock.uom');
    final quantity = JsonContract.decimal(
      map['quantity'],
      'vehicle_stock.quantity',
    );
    if (quantity.startsWith('-') || !RegExp(r'[1-9]').hasMatch(quantity)) {
      JsonContract.invalid('vehicle_stock.quantity');
    }
    if (sellable) {
      JsonContract.integer(
        map['packs_per_carton'],
        'vehicle_stock.packs',
        minimum: 1,
      );
    }
    return CurrentVehicleStockItem(
      productVariantId: variantId,
      name: name,
      status: status,
      baseUomCode: base,
      quantity: quantity,
    );
  }
}

class CurrentVehicleStockSnapshot {
  const CurrentVehicleStockSnapshot({
    required this.vehicleId,
    required this.locationId,
    required this.custodyEpochId,
    required this.stockFingerprint,
    required this.sellable,
    required this.nonSellable,
  });

  final int vehicleId;
  final int locationId;
  final int custodyEpochId;
  final String stockFingerprint;
  final List<CurrentVehicleStockItem> sellable;
  final List<CurrentVehicleStockItem> nonSellable;
}

typedef CurrentVehicleStockFetch =
    Future<Object?> Function(int limit, String? cursor);

class CurrentVehicleStockReader {
  CurrentVehicleStockReader({CurrentVehicleStockFetch? fetch})
    : _fetch = fetch ?? _authorizedHttp;

  final CurrentVehicleStockFetch _fetch;

  static Future<Object?> _authorizedHttp(int limit, String? cursor) async {
    final response = await ApiClient.instance.get<Object?>(
      '/driver/vehicle-stock',
      queryParameters: {'limit': limit, if (cursor != null) 'cursor': cursor},
    );
    return response.data;
  }

  static const pageLimit = 100;
  static const maximumPages = 50;
  static const maximumRows = 5000;

  Future<CurrentVehicleStockSnapshot> read(VehicleRouteAuthority route) async {
    if (route.kind != VehicleRouteKind.active ||
        route.vehicleId == null ||
        route.routeId == null) {
      throw StateError(
        'Current signed FIELD route is required before stock read',
      );
    }
    final sellable = <CurrentVehicleStockItem>[];
    final nonSellable = <CurrentVehicleStockItem>[];
    final seenCursors = <String>{};
    final seenItems = <String>{};
    String? nextCursor;
    int? locationId;
    int? epochId;
    int? contextRevision;
    String? stockFingerprint;
    var pages = 0;
    do {
      if (++pages > maximumPages) {
        throw const FormatException('Vehicle stock exceeds read page bound');
      }
      final payload = JsonContract.object(
        await _fetch(pageLimit, nextCursor),
        'vehicle_stock',
      );
      if (payload['status'] != 'VERIFIED' ||
          payload['source'] != 'INVENTORY_BALANCE') {
        JsonContract.invalid('vehicle_stock.authority');
      }
      final vehicle = JsonContract.integer(
        payload['vehicle_id'],
        'vehicle_stock.vehicle_id',
        minimum: 1,
      );
      if (vehicle != route.vehicleId) {
        JsonContract.invalid('vehicle_stock.vehicle_route_mismatch');
      }
      final location = JsonContract.integer(
        payload['vehicle_location_id'],
        'vehicle_stock.location_id',
        minimum: 1,
      );
      final epoch = JsonContract.integer(
        payload['custody_epoch_id'],
        'vehicle_stock.epoch_id',
        minimum: 1,
      );
      final revision = JsonContract.integer(
        payload['context_revision'],
        'vehicle_stock.revision',
      );
      final fingerprint = JsonContract.text(
        payload['stock_snapshot'],
        'vehicle_stock.stock_snapshot',
      );
      if (locationId != null &&
          (locationId != location ||
              epochId != epoch ||
              contextRevision != revision ||
              stockFingerprint != fingerprint)) {
        JsonContract.invalid('vehicle_stock.pagination_snapshot_changed');
      }
      locationId ??= location;
      epochId ??= epoch;
      contextRevision ??= revision;
      stockFingerprint ??= fingerprint;

      final liveRows = JsonContract.list(
        payload['sellable_items'],
        'vehicle_stock.sellable_items',
      );
      final restrictedRows = JsonContract.list(
        payload['non_sellable_items'],
        'vehicle_stock.non_sellable_items',
      );
      if (liveRows.length + restrictedRows.length > pageLimit ||
          sellable.length +
                  nonSellable.length +
                  liveRows.length +
                  restrictedRows.length >
              maximumRows) {
        JsonContract.invalid('vehicle_stock.page_bound');
      }
      for (final row in liveRows) {
        final item = CurrentVehicleStockItem.parse(row, sellable: true);
        if (!seenItems.add('${item.productVariantId}:${item.status}')) {
          JsonContract.invalid('vehicle_stock.duplicate_item');
        }
        sellable.add(item);
      }
      for (final row in restrictedRows) {
        final item = CurrentVehicleStockItem.parse(row, sellable: false);
        if (!seenItems.add('${item.productVariantId}:${item.status}')) {
          JsonContract.invalid('vehicle_stock.duplicate_item');
        }
        nonSellable.add(item);
      }
      final returned = JsonContract.optionalText(
        payload['next_cursor'],
        'vehicle_stock.next_cursor',
      );
      if (returned != null &&
          (returned.length > 8192 ||
              !seenCursors.add(returned) ||
              (liveRows.isEmpty && restrictedRows.isEmpty))) {
        JsonContract.invalid('vehicle_stock.cursor');
      }
      nextCursor = returned;
    } while (nextCursor != null);

    return CurrentVehicleStockSnapshot(
      vehicleId: route.vehicleId!,
      locationId: locationId,
      custodyEpochId: epochId,
      stockFingerprint: stockFingerprint,
      sellable: List.unmodifiable(sellable),
      nonSellable: List.unmodifiable(nonSellable),
    );
  }
}
