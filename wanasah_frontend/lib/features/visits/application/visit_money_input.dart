/// Parse operator cash/debt syntax without floating point or client rounding.
/// Authoritative invoice money never enters this input path.
String canonicalVisitMoney(String text) {
  var value = text.trim();
  const arabic = '٠١٢٣٤٥٦٧٨٩';
  const persian = '۰۱۲۳۴۵۶۷۸۹';
  for (var digit = 0; digit < 10; digit++) {
    value = value.replaceAll(arabic[digit], digit.toString())
      .replaceAll(persian[digit], digit.toString());
  }
  value = value.replaceAll('٫', '.').replaceAll('،', '.').replaceAll(',', '.');
  if (value.isEmpty) return '0.000';
  if (!RegExp(r'^[0-9]+(?:\.[0-9]+)?$').hasMatch(value)) {
    throw const FormatException('Invalid nonnegative money input');
  }
  return value;
}
