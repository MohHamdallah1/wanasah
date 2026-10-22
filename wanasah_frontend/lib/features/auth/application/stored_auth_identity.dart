import 'field_principal_identity.dart';

class StoredAuthIdentity {
  const StoredAuthIdentity({
    required this.token, required this.refreshToken, required this.field,
  });
  final String token;
  final String refreshToken;
  final FieldPrincipalIdentity field;

  int get principalId => field.principalId;
  int get representativeId => field.representativeId;
  int get companyId => field.companyId;
  String get companyCode => field.companyCode;
  int get legacyDriverId => field.legacyDriverId;

  /// Compatibility for existing operational consumers; never a principal alias.
  int get driverId => legacyDriverId;

  static String? _token(Object? value) {
    if (value is! String || value.trim().isEmpty || value.trim() == 'null') return null;
    return value.trim();
  }

  static StoredAuthIdentity? fromLogin(Object? value) {
    if (value is! Map) return null;
    final field = FieldPrincipalIdentity.tryParse(value);
    final token = _token(value['token']);
    final refresh = _token(value['refresh_token']);
    if (field == null || token == null || refresh == null) return null;
    return StoredAuthIdentity(token: token, refreshToken: refresh, field: field);
  }

  static StoredAuthIdentity? tryParse({
    required String? token, required String? refreshToken,
    required String? identityJson,
  }) {
    final field = FieldPrincipalIdentity.fromStorage(identityJson);
    final access = _token(token);
    final refresh = _token(refreshToken);
    if (field == null || access == null || refresh == null) return null;
    return StoredAuthIdentity(token: access, refreshToken: refresh, field: field);
  }
}
