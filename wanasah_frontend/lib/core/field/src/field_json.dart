/// Shape validation only. Business acceptance remains Backend-owned.
abstract final class FieldJson {
  static Never invalid(String field) =>
      throw FormatException('Invalid FIELD contract: $field');

  static Map<String, dynamic> object(Object? value, String field) {
    if (value is! Map) invalid(field);
    final result = <String, dynamic>{};
    for (final entry in value.entries) {
      if (entry.key is! String) invalid(field);
      result[entry.key as String] = entry.value;
    }
    return result;
  }

  static List<dynamic> list(Object? value, String field) {
    if (value is! List) invalid(field);
    return value;
  }

  static String text(Object? value, String field) {
    if (value is! String || value.trim().isEmpty) invalid(field);
    return value;
  }

  static String? optionalText(Object? value, String field) =>
      value == null ? null : text(value, field);

  static int integer(Object? value, String field, {int minimum = 0}) {
    if (value is! int || value < minimum) invalid(field);
    return value;
  }

  static bool boolean(Object? value, String field) {
    if (value is! bool) invalid(field);
    return value;
  }

  static String decimal(Object? value, String field) {
    final encoded = text(value, field);
    if (!RegExp(r'^-?[0-9]+(?:\.[0-9]+)?$').hasMatch(encoded)) {
      invalid(field);
    }
    // Keep the original bytes/scale. Never pass money through num or double.
    return encoded;
  }

  static String? date(Object? value, String field) {
    if (value == null) return null;
    final encoded = text(value, field);
    if (!RegExp(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}$').hasMatch(encoded)) {
      invalid(field);
    }
    final parsed = DateTime.tryParse(encoded);
    if (parsed == null ||
        parsed.toIso8601String().substring(0, 10) != encoded) {
      invalid(field);
    }
    return encoded;
  }

  static T code<T>(
    Object? value,
    List<T> values,
    String Function(T) wireCode,
    String field,
  ) {
    for (final item in values) {
      if (wireCode(item) == value) return item;
    }
    invalid(field);
  }
}
