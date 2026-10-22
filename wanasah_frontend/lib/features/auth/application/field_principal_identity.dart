import 'dart:convert';

/// The mounted Backend FIELD login contract. These IDs are independent.
class FieldPrincipalIdentity {
  const FieldPrincipalIdentity._({
    required this.principalId, required this.representativeId,
    required this.companyId, required this.companyCode,
    required this.legacyDriverId,
  });

  final int principalId;
  final int representativeId;
  final int companyId;
  final String companyCode;
  /// Explicit Backend bridge for existing workflow/offline rows, not authority.
  final int legacyDriverId;

  static FieldPrincipalIdentity? tryParse(Object? value) {
    if (value is! Map || value['channel'] != 'FIELD' ||
        value['principal_type'] != 'FIELD_REPRESENTATIVE') { return null; }
    int? id(Object? raw) => raw is int && raw > 0 ? raw : null;
    final principal = id(value['principal_id']);
    final representative = id(value['representative_id']);
    final company = id(value['company_id']);
    final legacy = id(value['legacy_driver_id']);
    final alias = id(value['driver_id']);
    final code = value['company_code'];
    if (principal == null || representative == null || company == null ||
        legacy == null || alias != legacy || code is! String ||
        code.trim().length < 2 || code.trim().length > 50 || code.trim() == 'null') {
      return null;
    }
    return FieldPrincipalIdentity._(principalId: principal,
      representativeId: representative, companyId: company,
      companyCode: code.trim(), legacyDriverId: legacy);
  }

  static FieldPrincipalIdentity? fromStorage(String? value) {
    try { return tryParse(jsonDecode(value ?? '')); }
    on FormatException { return null; }
  }

  Map<String, dynamic> toJson() => {
    'principal_id': principalId, 'representative_id': representativeId,
    'company_id': companyId, 'company_code': companyCode,
    'legacy_driver_id': legacyDriverId, 'driver_id': legacyDriverId,
    'channel': 'FIELD', 'principal_type': 'FIELD_REPRESENTATIVE',
  };
}
