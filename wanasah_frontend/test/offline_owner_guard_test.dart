import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/blocs/auth/offline_owner_guard.dart';

void main() {
  group('classifyOfflineOwnerLogin', () {
    test('allows the same mapped legacy driver to resume its queue', () {
      expect(
        classifyOfflineOwnerLogin(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '303',
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 303,
        ),
        OfflineOwnerLoginDecision.sameOwner,
      );
    });

    test('detects a different driver in the same company', () {
      expect(
        classifyOfflineOwnerLogin(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '303',
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 404,
        ),
        OfflineOwnerLoginDecision.differentDriverSameCompany,
      );
    });

    test('blocks cross-company ownership reuse', () {
      expect(
        classifyOfflineOwnerLogin(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '303',
          returnedCompanyCode: 'WNS-02',
          returnedDriverId: 303,
        ),
        OfflineOwnerLoginDecision.differentCompany,
      );
    });

    test('treats incomplete or invalid markers as absent', () {
      for (final owner in <(String?, String?)>{
        (null, null),
        ('', '303'),
        ('WNS-01', ''),
        ('WNS-01', '0'),
        ('WNS-01', 'not-an-id'),
      }) {
        expect(
          classifyOfflineOwnerLogin(
            ownerCompanyCode: owner.$1,
            ownerDriverId: owner.$2,
            returnedCompanyCode: 'WNS-01',
            returnedDriverId: 303,
          ),
          OfflineOwnerLoginDecision.noOwner,
        );
      }
    });
  });
}
