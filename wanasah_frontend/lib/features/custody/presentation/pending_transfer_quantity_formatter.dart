import 'package:intl/intl.dart';
import '../domain/pending_transfer.dart';
import 'pending_transfer_strings.dart';

String formatPendingTransferQuantity(
  PendingTransferItem item, {
  String locale = 'ar',
}) {
  final numbers = NumberFormat('0', locale);
  final evidence = item.canonicalQuantity;
  if (evidence == null) {
    return PendingTransferStrings(locale).legacyQuantity(
      numbers.format(item.deltaCartons.abs()),
      numbers.format(item.deltaPacks.abs()),
    );
  }
  final quantity = evidence.signedUnits.abs();
  final factor =
      evidence.displayFactorToBase == null
          ? null
          : BigInt.parse(evidence.displayFactorToBase!);
  if (factor == null || BigInt.from(quantity) < factor) {
    return '${numbers.format(quantity)} ${evidence.baseUomName}';
  }
  // Presentation of the server's unique exact factor; no product conversion table.
  final whole = BigInt.from(quantity) ~/ factor;
  final remainder = BigInt.from(quantity) % factor;
  final commercial =
      '${numbers.format(whole.toInt())} ${evidence.displayUomName}';
  return remainder == BigInt.zero
      ? commercial
      : '$commercial + ${numbers.format(remainder.toInt())} ${evidence.baseUomName}';
}
