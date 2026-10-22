import 'dart:convert';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/auth/application/stored_auth_identity.dart';
import '../fixtures/field_login_fixture.dart';

void main() {
  test('canonical login keeps credential, representative and legacy Driver identities independent', () {
    final identity = StoredAuthIdentity.fromLogin(fieldLogin())!;
    expect(identity.principalId, 101);
    expect(identity.representativeId, 202);
    expect(identity.legacyDriverId, 303);
    expect(identity.driverId, 303);
    expect(identity.companyId, 7);
    expect(identity.companyCode, 'WNS-01');
    expect(identity.token, 'access-token');
    expect(identity.refreshToken, 'refresh-token');
  });

  test('restores canonical snapshot and current token pair without inferring identity from aliases', () {
    final field = StoredAuthIdentity.fromLogin(fieldLogin())!.field;
    final identity = StoredAuthIdentity.tryParse(token: ' rotated-access ',
      refreshToken: ' rotated-refresh ', identityJson: jsonEncode(field.toJson()))!;
    expect(identity.principalId, 101);
    expect(identity.representativeId, 202);
    expect(identity.companyId, 7);
    expect(identity.legacyDriverId, 303);
    expect(identity.token, 'rotated-access');
    expect(identity.refreshToken, 'rotated-refresh');
  });

  test('no legacy-only session, input-company fallback or token decoding guesses', () {
    expect(StoredAuthIdentity.fromLogin({
      'token': 'token', 'refresh_token': 'refresh',
      'driver_id': 303, 'company_code': 'WNS-01',
    }), isNull);
    expect(StoredAuthIdentity.tryParse(token: 'token', refreshToken: 'refresh',
      identityJson: null), isNull);
    expect(StoredAuthIdentity.tryParse(token: 'token', refreshToken: 'refresh',
      identityJson: '{'), isNull);
    for (final key in ['principal_id', 'representative_id', 'company_id',
      'company_code', 'legacy_driver_id', 'driver_id', 'channel', 'principal_type']) {
      final data = fieldLogin()..remove(key);
      expect(StoredAuthIdentity.fromLogin(data), isNull, reason: key);
    }
  });

  test('strict positive IDs reject booleans, fractional values and string coercion', () {
    for (final key in ['principal_id', 'representative_id', 'company_id', 'legacy_driver_id', 'driver_id']) {
      for (final value in [null, 0, -1, true, false, 1.5, '303']) {
        expect(StoredAuthIdentity.fromLogin(fieldLogin(changes: {key: value})),
          isNull, reason: '$key=$value');
      }
    }
    expect(StoredAuthIdentity.fromLogin(fieldLogin(changes: {'driver_id': 202})), isNull);
    // Coincidental numeric equality is allowed; meanings are still separate.
    expect(StoredAuthIdentity.fromLogin(fieldLogin(changes: {
      'principal_id': 303, 'representative_id': 303,
    })), isNotNull);
  });

  test('role/admin/permission/display text never repairs the FIELD contract', () {
    for (final pair in [('DASHBOARD', 'BACKOFFICE'), ('FIELD', 'BACKOFFICE'),
      ('DASHBOARD', 'FIELD_REPRESENTATIVE'), ('field', 'FIELD_REPRESENTATIVE')]) {
      expect(StoredAuthIdentity.fromLogin(fieldLogin(changes: {
        'channel': pair.$1, 'principal_type': pair.$2,
        'is_admin': false, 'role': 'driver', 'is_authorized': true,
        'message': 'Login Successful!',
      })), isNull);
    }
    final identity = StoredAuthIdentity.fromLogin(fieldLogin(changes: {
      'is_admin': true, 'role': 'owner', 'is_authorized': false, 'message': 'رفض',
    }));
    expect(identity!.representativeId, 202);
  });

  test('missing/blank/null token or company values fail closed on login and recovery', () {
    for (final key in ['token', 'refresh_token', 'company_code']) {
      for (final value in [null, '', ' ', 'null', 123]) {
        expect(StoredAuthIdentity.fromLogin(fieldLogin(changes: {key: value})), isNull);
      }
    }
    final snapshot = jsonEncode(StoredAuthIdentity.fromLogin(fieldLogin())!.field.toJson());
    for (final value in <String?>[null, '', ' ', 'null']) {
      expect(StoredAuthIdentity.tryParse(token: value, refreshToken: 'refresh',
        identityJson: snapshot), isNull);
      expect(StoredAuthIdentity.tryParse(token: 'token', refreshToken: value,
        identityJson: snapshot), isNull);
    }
  });
}
