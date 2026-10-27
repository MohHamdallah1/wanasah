import 'package:wanasah_frontend/core/serialization/json_contract.dart';
import 'pending_transfer_quantity.dart';

class PendingTransferItem {
  const PendingTransferItem({
    required this.transferId,
    required this.productName,
    required this.deltaCartons,
    required this.deltaPacks,
    this.canonicalQuantity,
  });

  final int transferId;
  final String productName;
  final int deltaCartons;
  final int deltaPacks;
  final PendingTransferQuantity? canonicalQuantity;
  bool get isAddition =>
      canonicalQuantity != null
          ? canonicalQuantity!.signedUnits > 0
          : deltaCartons > 0 || (deltaCartons == 0 && deltaPacks > 0);

  factory PendingTransferItem.fromServerJson(Object? value) {
    final json = JsonContract.object(value, 'pending_transfer.item');
    final quantity = PendingTransferQuantity.fromEvidence(json);
    return PendingTransferItem(
      canonicalQuantity: quantity,
      transferId: JsonContract.integer(
        json['real_transfer_id'],
        'real_transfer_id',
        minimum: 1,
      ),
      productName: JsonContract.text(json['product_name'], 'product_name'),
      deltaCartons: JsonContract.integer(
        json['delta_cartons'],
        'delta_cartons',
        minimum: -2147483648,
      ),
      deltaPacks: JsonContract.integer(
        json['delta_packs'],
        'delta_packs',
        minimum: quantity == null ? -2147483648 : -99999999999999,
      ),
    );
  }

  factory PendingTransferItem.fromLocalRow(Map<String, dynamic> row) {
    final id = int.tryParse(
      (row['transfer_id'] ?? row['id'])?.toString() ?? '',
    );
    if (id == null || id <= 0) {
      JsonContract.invalid('local_transfer.transfer_id');
    }
    return PendingTransferItem(
      canonicalQuantity: PendingTransferQuantity.fromEvidence(row),
      transferId: id,
      productName:
          row['product_name']?.toString().trim().isNotEmpty == true
              ? row['product_name'].toString().trim()
              : 'غير معروف',
      deltaCartons: int.tryParse(row['delta_cartons']?.toString() ?? '') ?? 0,
      deltaPacks: int.tryParse(row['delta_packs']?.toString() ?? '') ?? 0,
    );
  }
}

class PendingTransferBatch {
  PendingTransferBatch({
    required this.batchId,
    required List<PendingTransferItem> items,
    this.createdAt,
    this.fromLocalCache = false,
  }) : items = List.unmodifiable(items) {
    if (items.isEmpty) {
      JsonContract.invalid('pending_transfer.items');
    }
    final ids = items.map((item) => item.transferId).toList(growable: false);
    if (ids.toSet().length != ids.length) {
      JsonContract.invalid('pending_transfer.duplicate_transfer_id');
    }
  }

  final String batchId;
  final String? createdAt;
  final List<PendingTransferItem> items;
  final bool fromLocalCache;

  factory PendingTransferBatch.fromServerJson(Object? value) {
    final json = JsonContract.object(value, 'pending_transfer.batch');
    final rawItems = JsonContract.list(json['items'], 'pending_transfer.items');
    return PendingTransferBatch(
      batchId: JsonContract.text(json['transfer_id'], 'transfer_id'),
      createdAt: JsonContract.optionalText(json['created_at'], 'created_at'),
      items: rawItems
          .map(PendingTransferItem.fromServerJson)
          .toList(growable: false),
    );
  }

  factory PendingTransferBatch.fromLocalRows(List<Map<String, dynamic>> rows) {
    return PendingTransferBatch(
      batchId: 'local-pending',
      items: rows.map(PendingTransferItem.fromLocalRow).toList(growable: false),
      fromLocalCache: true,
    );
  }
}
