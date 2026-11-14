/// Visual grouping only: combines physically indistinguishable unlabelled lots.
/// Signed stock snapshots and authoritative balance/cost rows stay unchanged.
List<Map<String, dynamic>> visibleCustodyHandoffLines(
  List<Map<String, dynamic>> source,
) {
  final result = <Map<String, dynamic>>[], seen = <String, int>{};
  BigInt? fixed(String raw) {
    final match = RegExp(r'^(\d+)(?:\.(\d{1,6}))?$').firstMatch(raw);
    if (match == null) return null;
    return BigInt.parse(match.group(1)!) * BigInt.from(1000000) +
        BigInt.parse(
          (match.group(2) ?? '').padRight(6, '0').isEmpty
              ? '0'
              : (match.group(2) ?? '').padRight(6, '0'),
        );
  }

  String decimal(BigInt n) {
    final base = BigInt.from(1000000);
    final whole = n ~/ base,
        frac = (n % base)
            .toString()
            .padLeft(6, '0')
            .replaceFirst(RegExp(r'0+$'), '');
    return frac.isEmpty ? '$whole' : '$whole.$frac';
  }

  for (final line in source) {
    final lot = (line['batch_number'] ?? '').toString();
    final noLot = lot.isEmpty || lot.contains('__WANASAH_NOLOT__');
    final amount = fixed((line['on_hand_base'] ?? '').toString());
    final reserved = fixed((line['reserved_base'] ?? '0').toString());
    if (!noLot || amount == null || reserved == null) {
      result.add(Map.of(line));
      continue;
    }
    final fields = [
      'sku',
      'product_name',
      'expiry_date',
      'base_uom',
      'base_uom_name',
      'display_uom_name',
      'display_factor_to_base',
      'stock_status',
    ];
    final key = fields.map((f) => '${line[f] ?? "<null>"}').join('\u0001');
    final i = seen[key];
    if (i == null) {
      seen[key] = result.length;
      result.add({...line, 'batch_number': ''});
      continue;
    }
    final previous = result[i];
    final before = fixed((previous['on_hand_base'] ?? '').toString());
    final beforeReserved = fixed((previous['reserved_base'] ?? '0').toString());
    if (before == null || beforeReserved == null) {
      result.add(Map.of(line));
      continue;
    }
    previous['on_hand_base'] = decimal(before + amount);
    previous['reserved_base'] = decimal(beforeReserved + reserved);
  }
  return result;
}
