import 'package:intl/intl.dart';

/// Reads trusted display-UOM metadata only. Never modifies canonical base stock.
String formatCustodyHandoffQuantity(
  Map<String, dynamic> line, {
  String locale = 'ar',
}) {
  final raw = (line['on_hand_base'] ?? '').toString();
  final match = RegExp(r'^(\d+)(?:\.(\d{1,6}))?$').firstMatch(raw);
  final base = (line['base_uom_name'] ?? line['base_uom'] ?? '').toString();
  if (match == null || base.isEmpty) return raw;
  final scale = BigInt.from(1000000);
  final fractional = (match.group(2) ?? '').padRight(6, '0');
  final amount =
      BigInt.parse(match.group(1)!) * scale +
      BigInt.parse(fractional.isEmpty ? '0' : fractional);
  final numbers = NumberFormat.decimalPattern(locale);
  String pretty(BigInt scaled) {
    final units = scaled ~/ scale;
    final rest = (scaled % scale)
        .toString()
        .padLeft(6, '0')
        .replaceFirst(RegExp(r'0+$'), '');
    final whole = numbers.format(units.toInt());
    return rest.isEmpty ? whole : '$whole.$rest';
  }

  final display = (line['display_uom_name'] ?? '').toString();
  final factorText = (line['display_factor_to_base'] ?? '').toString();
  final factor =
      RegExp(r'^[1-9]\d*$').hasMatch(factorText)
          ? BigInt.tryParse(factorText)
          : null;
  if (display.isNotEmpty && factor != null && factor > BigInt.one) {
    final outer = factor * scale;
    if (amount >= outer) {
      final whole = amount ~/ outer;
      final remainder = amount % outer;
      final first = '${numbers.format(whole.toInt())} $display';
      return remainder == BigInt.zero
          ? first
          : '$first + ${pretty(remainder)} $base';
    }
  }
  return '${pretty(amount)} $base';
}
