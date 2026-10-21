import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/auth/application/stored_auth_identity.dart';

void main() {
  group('StoredAuthIdentity.tryParse', () {
    test('restores a complete valid stored identity safely', () {
      final identity = StoredAuthIdentity.tryParse(
        token: '  access-token  ',
        refreshToken: '  refresh-token  ',
        driverId: ' 42 ',
        companyCode: ' WNS-01 ',
      );

      expect(identity, isNotNull);
      expect(identity!.token, 'access-token');
      expect(identity.refreshToken, 'refresh-token');
      expect(identity.driverId, 42);
      expect(identity.companyCode, 'WNS-01');
    });

    test('rejects incomplete or malformed identity without repair guesses', () {
      final cases = <Map<String, String?>>[
        {
          'token': null,
          'refreshToken': 'refresh',
          'driverId': '42',
          'companyCode': 'WNS-01',
        },
        {
          'token': ' ',
          'refreshToken': 'refresh',
          'driverId': '42',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'null',
          'refreshToken': 'refresh',
          'driverId': '42',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': null,
          'driverId': '42',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': ' ',
          'driverId': '42',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': 'null',
          'driverId': '42',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': 'refresh',
          'driverId': null,
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': 'refresh',
          'driverId': 'not-an-id',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': 'refresh',
          'driverId': '0',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': 'refresh',
          'driverId': '-9',
          'companyCode': 'WNS-01',
        },
        {
          'token': 'token',
          'refreshToken': 'refresh',
          'driverId': '42',
          'companyCode': null,
        },
        {
          'token': 'token',
          'refreshToken': 'refresh',
          'driverId': '42',
          'companyCode': ' ',
        },
        {
          'token': 'token',
          'refreshToken': 'refresh',
          'driverId': '42',
          'companyCode': 'null',
        },
      ];

      for (final stored in cases) {
        expect(
          StoredAuthIdentity.tryParse(
            token: stored['token'],
            refreshToken: stored['refreshToken'],
            driverId: stored['driverId'],
            companyCode: stored['companyCode'],
          ),
          isNull,
          reason: stored.toString(),
        );
      }
    });
  });
}
