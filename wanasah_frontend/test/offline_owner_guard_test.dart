import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/blocs/auth/offline_owner_guard.dart';

Map<String, dynamic> pendingRow(String type) => <String, dynamic>{'type': type};

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

  group('evaluateOfflineOwnerLoginSafety', () {
    test(
      'same owner is allowed and preserved pending work can resume',
      () async {
        final pendingRows = <Map<String, dynamic>>[
          pendingRow('sale_create'),
          pendingRow('payment_collect'),
        ];
        var revokeAttempts = 0;

        final result = await evaluateOfflineOwnerLoginSafety(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '10',
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 10,
          returnedRefreshToken: 'fresh-refresh',
          readPendingSyncs: (_) async => List.of(pendingRows),
          revokeRejectedRefresh: (_) async {
            revokeAttempts++;
          },
        );

        expect(result.outcome, OfflineOwnerLoginOutcome.allowSameOwner);
        expect(result.allowsLogin, isTrue);
        expect(result.shouldClearMarkerAfterAcceptedSession, isTrue);
        expect(revokeAttempts, 0);
        expect(pendingRows.map((row) => row['type']).toList(), <String>[
          'sale_create',
          'payment_collect',
        ]);
      },
    );

    test(
      'different driver in same company with active pending is blocked without mutation',
      () async {
        final pendingRows = <Map<String, dynamic>>[
          pendingRow('sale_create'),
          pendingRow('return_create'),
        ];
        final before = List<Map<String, dynamic>>.from(pendingRows);
        final revokedTokens = <String>[];

        final result = await evaluateOfflineOwnerLoginSafety(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '10',
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 20,
          returnedRefreshToken: 'new-refresh-20',
          readPendingSyncs: (_) async => List.of(pendingRows),
          revokeRejectedRefresh: (token) async {
            revokedTokens.add(token);
          },
        );

        expect(
          result.outcome,
          OfflineOwnerLoginOutcome.blockDifferentDriverSameCompany,
        );
        expect(result.allowsLogin, isFalse);
        expect(pendingRows, orderedEquals(before));
        expect(revokedTokens, <String>['new-refresh-20']);
      },
    );

    test(
      'different company with active pending is blocked and preserved',
      () async {
        final pendingRows = <Map<String, dynamic>>[pendingRow('sale_create')];
        var revokeAttempts = 0;

        final result = await evaluateOfflineOwnerLoginSafety(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '10',
          returnedCompanyCode: 'WNS-02',
          returnedDriverId: 20,
          returnedRefreshToken: 'new-refresh-company-b',
          readPendingSyncs: (companyCode) async {
            if (companyCode == 'WNS-01') {
              return List.of(pendingRows);
            }
            return <Map<String, dynamic>>[];
          },
          revokeRejectedRefresh: (_) async {
            revokeAttempts++;
          },
        );

        expect(result.outcome, OfflineOwnerLoginOutcome.blockDifferentCompany);
        expect(result.allowsLogin, isFalse);
        expect(pendingRows.single['type'], 'sale_create');
        expect(revokeAttempts, 1);
      },
    );

    test('quarantine-only evidence still blocks a different driver', () async {
      final pendingRows = <Map<String, dynamic>>[
        <String, dynamic>{
          'type': 'quarantined_submit_sale',
          'state': 'blocked',
        },
      ];
      var revokeAttempts = 0;

      final result = await evaluateOfflineOwnerLoginSafety(
        ownerCompanyCode: 'WNS-01',
        ownerDriverId: '10',
        returnedCompanyCode: 'WNS-01',
        returnedDriverId: 20,
        returnedRefreshToken: 'fresh-refresh',
        readPendingSyncs: (_) async => List.of(pendingRows),
        revokeRejectedRefresh: (_) async {
          revokeAttempts++;
        },
      );

      expect(
        result.outcome,
        OfflineOwnerLoginOutcome.blockDifferentDriverSameCompany,
      );
      expect(result.allowsLogin, isFalse);
      expect(result.shouldClearStaleMarker, isFalse);
      expect(revokeAttempts, 1);
      expect(pendingRows.single['type'], 'quarantined_submit_sale');
    });

    test('stale marker is clearable only when no unresolved rows exist', () async {
      var revokeAttempts = 0;

      final result = await evaluateOfflineOwnerLoginSafety(
        ownerCompanyCode: 'WNS-01',
        ownerDriverId: '10',
        returnedCompanyCode: 'WNS-01',
        returnedDriverId: 20,
        returnedRefreshToken: 'fresh-refresh',
        readPendingSyncs: (_) async => <Map<String, dynamic>>[],
        revokeRejectedRefresh: (_) async {
          revokeAttempts++;
        },
      );

      expect(result.outcome, OfflineOwnerLoginOutcome.allowStaleOwner);
      expect(result.allowsLogin, isTrue);
      expect(result.shouldClearStaleMarker, isTrue);
      expect(revokeAttempts, 0);
    });

    test(
      'blocked different driver cannot consume work and owner can resume later',
      () async {
        final pendingRows = <Map<String, dynamic>>[pendingRow('sale_create')];
        var revokeAttempts = 0;

        final blocked = await evaluateOfflineOwnerLoginSafety(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '10',
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 20,
          returnedRefreshToken: 'refresh-20',
          readPendingSyncs: (_) async => List.of(pendingRows),
          revokeRejectedRefresh: (_) async {
            revokeAttempts++;
          },
        );
        final resumed = await evaluateOfflineOwnerLoginSafety(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '10',
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 10,
          returnedRefreshToken: 'refresh-10',
          readPendingSyncs: (_) async => List.of(pendingRows),
          revokeRejectedRefresh: (_) async {
            revokeAttempts++;
          },
        );

        expect(blocked.allowsLogin, isFalse);
        expect(resumed.outcome, OfflineOwnerLoginOutcome.allowSameOwner);
        expect(resumed.allowsLogin, isTrue);
        expect(pendingRows.single['type'], 'sale_create');
        expect(revokeAttempts, 1);
      },
    );

    test(
      'active pending with unknown owner fails closed against cross-driver replay',
      () async {
        final pendingRows = <Map<String, dynamic>>[
          pendingRow('payment_collect'),
        ];
        var revokeAttempts = 0;

        final result = await evaluateOfflineOwnerLoginSafety(
          ownerCompanyCode: null,
          ownerDriverId: null,
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 20,
          returnedRefreshToken: 'unattributed-refresh',
          readPendingSyncs: (_) async => List.of(pendingRows),
          revokeRejectedRefresh: (_) async {
            revokeAttempts++;
          },
        );

        expect(
          result.outcome,
          OfflineOwnerLoginOutcome.blockUnattributedPending,
        );
        expect(result.allowsLogin, isFalse);
        expect(pendingRows.single['type'], 'payment_collect');
        expect(revokeAttempts, 1);
      },
    );

    test(
      'refresh cleanup failure never turns a blocked login into allow',
      () async {
        final pendingRows = <Map<String, dynamic>>[pendingRow('sale_create')];
        var revokeAttempts = 0;

        final result = await evaluateOfflineOwnerLoginSafety(
          ownerCompanyCode: 'WNS-01',
          ownerDriverId: '10',
          returnedCompanyCode: 'WNS-01',
          returnedDriverId: 20,
          returnedRefreshToken: 'refresh-that-cannot-be-revoked',
          readPendingSyncs: (_) async => List.of(pendingRows),
          revokeRejectedRefresh: (_) async {
            revokeAttempts++;
            throw StateError('network unavailable');
          },
        );

        expect(
          result.outcome,
          OfflineOwnerLoginOutcome.blockDifferentDriverSameCompany,
        );
        expect(result.allowsLogin, isFalse);
        expect(revokeAttempts, 1);
        expect(pendingRows.single['type'], 'sale_create');
      },
    );
  });

  group('AuthBloc financial safety source invariants', () {
    test(
      'auth transitions never request automatic pending_sync deletion',
      () async {
        final source =
            await File('lib/blocs/auth/auth_bloc.dart').readAsString();

        expect(source, isNot(contains('clearPendingSyncs: true')));
        expect(source, contains('clearSessionData(clearPendingSyncs: false)'));
        expect(source, isNot(contains('quarantined_')));
      },
    );

    test('offline guard blocks before returned session is persisted', () async {
      final source = await File('lib/blocs/auth/auth_bloc.dart').readAsString();
      final guardIndex = source.indexOf('if (!offlineGuard.allowsLogin)');
      final tokenWriteIndex = source.indexOf(
        "await _storage.write(key: 'auth_token', value: token);",
      );

      expect(guardIndex, greaterThanOrEqualTo(0));
      expect(tokenWriteIndex, greaterThan(guardIndex));
      expect(
        source,
        contains('revokeRejectedRefresh: _revokeRejectedLoginSession'),
      );
    });
  });
}
