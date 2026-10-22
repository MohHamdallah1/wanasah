import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../../../core/network/auth_token_store.dart';
import '../../../core/sync/durable_command_owner.dart';
import '../application/field_principal_identity.dart';
import '../application/stored_auth_identity.dart';

/// One canonical identity snapshot, alongside the existing rotating token pair.
/// Legacy driver/company keys remain compatibility projections only.
class SecureAuthIdentityStore {
  SecureAuthIdentityStore({FlutterSecureStorage? storage})
    : _storage = storage ?? const FlutterSecureStorage();
  static const identityKey = 'field_auth_identity';
  final FlutterSecureStorage _storage;

  Future<StoredAuthIdentity?> read() async {
    final snapshot = await _storage.read(key: identityKey);
    final token = await _storage.read(key: 'auth_token');
    final refresh = await _storage.read(key: 'refresh_token');
    if (snapshot != await _storage.read(key: identityKey)) return null;
    return StoredAuthIdentity.tryParse(token: token,
      refreshToken: refresh, identityJson: snapshot);
  }

  /// Last authenticated metadata protects logout evidence even after confirmed
  /// credential rejection. It cannot authorize a new command without tokens.
  Future<FieldPrincipalIdentity?> readLastIdentity() async =>
      FieldPrincipalIdentity.fromStorage(await _storage.read(key: identityKey));

  Future<void> persistLogin(StoredAuthIdentity identity) => withAuthCredentialWrite(() async {
    final tokens = SecureAuthTokenStore(storage: _storage);
    await tokens.clear();
    await _storage.write(key: identityKey, value: jsonEncode(identity.field.toJson()));
    await _storage.write(key: 'company_code', value: identity.companyCode);
    await _storage.write(key: 'driver_id', value: identity.legacyDriverId.toString());
    await tokens.persistReplacement(accessToken: identity.token,
      refreshToken: identity.refreshToken);
  });

  Future<DurableCommandOwner> requireCommandOwner(String tenant) async {
    final identity = await read();
    if (identity == null) {
      throw const DurableCommandOwnerException('AUTHENTICATED_FIELD_OWNER_REQUIRED');
    }
    final owner = DurableCommandOwner(companyCode: identity.companyCode,
      driverId: identity.legacyDriverId);
    owner.requireTenant(tenant);
    return owner;
  }

  Future<void> clearIdentity() async {
    await _storage.delete(key: identityKey);
    await _storage.delete(key: 'driver_id');
    await _storage.delete(key: 'company_code');
  }
}
