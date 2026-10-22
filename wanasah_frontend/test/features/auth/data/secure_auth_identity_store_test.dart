import 'dart:convert';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/network/auth_token_store.dart';
import 'package:wanasah_frontend/core/sync/durable_command_owner.dart';
import 'package:wanasah_frontend/features/auth/application/stored_auth_identity.dart';
import 'package:wanasah_frontend/features/auth/data/secure_auth_identity_store.dart';
import '../fixtures/field_login_fixture.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  setUp(() => FlutterSecureStorage.setMockInitialValues({}));

  test('canonical login identity and owner survive a new store instance/app restart', () async {
    final first = SecureAuthIdentityStore();
    await first.persistLogin(StoredAuthIdentity.fromLogin(fieldLogin())!);
    final restored = await SecureAuthIdentityStore().read();
    expect(restored!.principalId, 101);
    expect(restored.representativeId, 202);
    expect(restored.legacyDriverId, 303);
    expect(restored.companyId, 7);
    expect(restored.companyCode, 'WNS-01');
    expect(restored.token, 'access-token');
    expect(restored.refreshToken, 'refresh-token');
    final owner = await SecureAuthIdentityStore().requireCommandOwner('WNS-01');
    expect(owner.driverId, 303);
    expect(owner.companyCode, 'WNS-01');
  });

  test('token-only refresh changes credentials without changing canonical IDs/ownership', () async {
    await SecureAuthIdentityStore().persistLogin(StoredAuthIdentity.fromLogin(fieldLogin())!);
    await SecureAuthTokenStore().persistReplacement(
      accessToken: 'new-access', refreshToken: 'new-refresh');
    final identity = await SecureAuthIdentityStore().read();
    expect(identity!.token, 'new-access');
    expect(identity.refreshToken, 'new-refresh');
    expect(identity.principalId, 101);
    expect(identity.representativeId, 202);
    expect((await SecureAuthIdentityStore().requireCommandOwner('WNS-01')).driverId, 303);
  });

  test('active command owner cannot be fabricated from legacy keys or permission flags', () async {
    FlutterSecureStorage.setMockInitialValues({
      'auth_token': 'a', 'refresh_token': 'r', 'driver_id': '303',
      'company_code': 'WNS-01', 'is_admin': 'false', 'is_authorized': 'true',
    });
    expect(await SecureAuthIdentityStore().read(), isNull);
    await expectLater(SecureAuthIdentityStore().requireCommandOwner('WNS-01'),
      throwsA(isA<DurableCommandOwnerException>()));
    expect(await const FlutterSecureStorage().read(key: 'driver_id'), '303');
  });

  test('tenant mismatch and missing access/refresh fail closed before command creation', () async {
    await SecureAuthIdentityStore().persistLogin(StoredAuthIdentity.fromLogin(fieldLogin())!);
    await expectLater(SecureAuthIdentityStore().requireCommandOwner('WNS-02'),
      throwsA(isA<DurableCommandOwnerException>()));
    await const FlutterSecureStorage().delete(key: 'auth_token');
    await expectLater(SecureAuthIdentityStore().requireCommandOwner('WNS-01'),
      throwsA(isA<DurableCommandOwnerException>()));
    expect((await SecureAuthIdentityStore().readLastIdentity())!.legacyDriverId, 303);
  });

  test('rejected token cleanup retains only identity evidence for logout ownership protection', () async {
    final store = SecureAuthIdentityStore();
    await store.persistLogin(StoredAuthIdentity.fromLogin(fieldLogin())!);
    await SecureAuthTokenStore().clear();
    expect(await store.read(), isNull);
    expect((await store.readLastIdentity())!.principalId, 101);
    await expectLater(store.requireCommandOwner('WNS-01'),
      throwsA(isA<DurableCommandOwnerException>()));
    await store.clearIdentity();
    expect(await store.readLastIdentity(), isNull);
  });

  test('partial/corrupt snapshot is not repaired from unrelated keys', () async {
    FlutterSecureStorage.setMockInitialValues({
      'auth_token': 'a', 'refresh_token': 'r',
      SecureAuthIdentityStore.identityKey: jsonEncode({'principal_id': 101}),
      'driver_id': '303', 'company_code': 'WNS-01',
    });
    expect(await SecureAuthIdentityStore().read(), isNull);
    expect(await const FlutterSecureStorage().read(key: 'driver_id'), '303');
  });
}
