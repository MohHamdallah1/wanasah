import 'dart:convert';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/visits/data/local_visit_replay_adapter.dart';

LocalVisitReplayAdapter adapter({
  required VisitReplaySend send,
  VisitBalanceUpdate? updateBalance,
  VisitCommandFinalize? finalize,
}) {
  return LocalVisitReplayAdapter(
    send: send,
    updateBalance: updateBalance ?? (visitId, newBalance) async {},
    finalize: finalize ??
        ({
          required commandRecordId,
          required visitId,
          required status,
          required outcome,
          required cashCollected,
          required debtPaid,
          cartItemsJson,
          returnsJson,
          notes,
          required cartItems,
          returnItems,
        }) async {},
  );
}

void main() {
  group('Visit replay dispatch', () {
    test('preserves exact PUT payload and durable request identity', () async {
      String? path;
      Map<String, dynamic>? sent;
      int? balanceVisitId;
      double? balance;

      final replay = adapter(
        send: (requestPath, {required data}) async {
          path = requestPath;
          sent = Map<String, dynamic>.from(data);
          return Response<dynamic>(
            requestOptions: RequestOptions(path: requestPath),
            statusCode: 200,
            data: <String, dynamic>{'new_balance': '123.450'},
          );
        },
        updateBalance: (visitId, newBalance) async {
          balanceVisitId = visitId;
          balance = newBalance;
        },
      );

      final payload = <String, dynamic>{
        'visitId': 77,
        'request_id': 'stable-request-77',
        'idempotency_key': 'legacy-only',
        'quarantine_reason': 'legacy-only',
        'outcome': 'Sale',
        'cash_collected': '9007199254740993.123000',
        'debt_paid': '0.000001',
        'notes': 'exact payload',
        'cart_items': <Map<String, dynamic>>[
          <String, dynamic>{
            'product_variant_id': 4,
            'quantity': 1,
            'packs_quantity': 2,
          },
        ],
        'returns': <Map<String, dynamic>>[
          <String, dynamic>{
            'product_variant_id': 4,
            'return_type': 'Damaged',
            'quantity': 1,
          },
        ],
      };
      final before = jsonEncode(payload);

      await replay.dispatch(payload);

      expect(path, '/visits/77');
      expect(sent!['request_id'], 'stable-request-77');
      expect(sent!['cash_collected'], '9007199254740993.123000');
      expect(sent!['debt_paid'], '0.000001');
      expect(sent, isNot(contains('visitId')));
      expect(sent, isNot(contains('idempotency_key')));
      expect(sent, isNot(contains('quarantine_reason')));
      expect(jsonEncode(payload), before);
      expect(balanceVisitId, 77);
      expect(balance, 123.45);
    });

    test('missing durable request_id fails before transport', () async {
      var sends = 0;
      final replay = adapter(
        send: (path, {required data}) async {
          sends++;
          return Response<dynamic>(
            requestOptions: RequestOptions(path: path),
            statusCode: 200,
          );
        },
      );

      await expectLater(
        replay.dispatch(<String, dynamic>{'visitId': 8, 'outcome': 'NoSale'}),
        throwsA(isA<StateError>()),
      );
      expect(sends, 0);
    });

    test('non-2xx response remains a Dio badResponse and never updates balance',
        () async {
      var balanceWrites = 0;
      final replay = adapter(
        send: (path, {required data}) async => Response<dynamic>(
          requestOptions: RequestOptions(path: path),
          statusCode: 409,
          data: <String, dynamic>{'error': <String, dynamic>{'code': 'CONFLICT'}},
        ),
        updateBalance: (visitId, newBalance) async {
          balanceWrites++;
        },
      );

      await expectLater(
        replay.dispatch(<String, dynamic>{
          'visitId': 8,
          'request_id': 'stable-request',
        }),
        throwsA(
          isA<DioException>().having(
            (error) => error.type,
            'type',
            DioExceptionType.badResponse,
          ),
        ),
      );
      expect(balanceWrites, 0);
    });

    test('post-success local balance failure remains best-effort', () async {
      final replay = adapter(
        send: (path, {required data}) async => Response<dynamic>(
          requestOptions: RequestOptions(path: path),
          statusCode: 200,
          data: <String, dynamic>{'new_balance': '55.25'},
        ),
        updateBalance: (visitId, newBalance) async {
          throw StateError('local balance cache unavailable');
        },
      );

      await replay.dispatch(<String, dynamic>{
        'visitId': 8,
        'request_id': 'stable-request',
      });
    });
  });

  group('Visit replay local finalization', () {
    test('maps durable payload to the existing atomic Visit finalizer', () async {
      Map<String, dynamic>? call;
      final replay = adapter(
        send: (path, {required data}) async => Response<dynamic>(
          requestOptions: RequestOptions(path: path),
          statusCode: 200,
        ),
        finalize: ({
          required commandRecordId,
          required visitId,
          required status,
          required outcome,
          required cashCollected,
          required debtPaid,
          cartItemsJson,
          returnsJson,
          notes,
          required cartItems,
          returnItems,
        }) async {
          call = <String, dynamic>{
            'commandRecordId': commandRecordId,
            'visitId': visitId,
            'status': status,
            'outcome': outcome,
            'cashCollected': cashCollected,
            'debtPaid': debtPaid,
            'cartItemsJson': cartItemsJson,
            'returnsJson': returnsJson,
            'notes': notes,
            'cartItems': cartItems,
            'returnItems': returnItems,
          };
        },
      );

      final cart = <Map<String, dynamic>>[
        <String, dynamic>{'product_variant_id': 4, 'quantity': 2},
      ];
      final returns = <Map<String, dynamic>>[
        <String, dynamic>{
          'product_variant_id': 4,
          'return_type': 'Expired',
          'packs_quantity': 3,
        },
      ];

      await replay.finalizeLocalState(
        commandRecordId: 91,
        payload: <String, dynamic>{
          'visitId': '77',
          'outcome': 'Postponed',
          'cash_collected': '12.340',
          'debt_paid': '0.005',
          'notes': 'unchanged',
          'cart_items': cart,
          'returns': returns,
        },
      );

      expect(call!['commandRecordId'], 91);
      expect(call!['visitId'], 77);
      expect(call!['status'], 'Pending');
      expect(call!['outcome'], 'Postponed');
      expect(call!['cashCollected'], 12.34);
      expect(call!['debtPaid'], 0.005);
      expect(jsonDecode(call!['cartItemsJson'] as String), cart);
      expect(jsonDecode(call!['returnsJson'] as String), returns);
      expect(call!['notes'], 'unchanged');
      expect(call!['cartItems'], cart);
      expect(call!['returnItems'], returns);
    });

    test('invalid Visit identity fails before local finalization', () async {
      var finalizations = 0;
      final replay = adapter(
        send: (path, {required data}) async => Response<dynamic>(
          requestOptions: RequestOptions(path: path),
          statusCode: 200,
        ),
        finalize: ({
          required commandRecordId,
          required visitId,
          required status,
          required outcome,
          required cashCollected,
          required debtPaid,
          cartItemsJson,
          returnsJson,
          notes,
          required cartItems,
          returnItems,
        }) async {
          finalizations++;
        },
      );

      await expectLater(
        replay.finalizeLocalState(
          commandRecordId: 91,
          payload: <String, dynamic>{'visitId': 0},
        ),
        throwsA(isA<StateError>()),
      );
      expect(finalizations, 0);
    });
  });

  test('SyncRepository owns queue policy while Visit adapter owns Visit mechanics',
      () async {
    final sync =
        await File('lib/repositories/sync_repository.dart').readAsString();
    final visitAdapter = await File(
      'lib/features/visits/data/local_visit_replay_adapter.dart',
    ).readAsString();

    expect(sync, contains('await _visitReplay.dispatch(payload);'));
    expect(sync, contains('await _visitReplay.finalizeLocalState('));
    expect(sync, contains('owner.requireRows(pending);'));
    expect(sync, contains('await _db.markPendingSyncInFlight(recordId);'));
    expect(sync, contains('await _db.deletePendingSync(recordId);'));
    expect(sync, contains('case DurableCommandType.transferResponse:'));
    expect(
      sync,
      contains("await _api.put('/driver/transfers/\$tId/respond', data: body);"),
    );
    expect(sync, isNot(contains("await _api.put('/visits/\$visitId'")));

    expect(visitAdapter, contains("await _send('/visits/\$visitId', data: body);"));
    expect(visitAdapter, contains('db.finalizeVisitCommandLocalState('));
    expect(visitAdapter, isNot(contains('deletePendingSync')));
    expect(visitAdapter, isNot(contains('markPendingSyncPending')));
    expect(visitAdapter, isNot(contains('markPendingSyncBlocked')));
    expect(visitAdapter, isNot(contains('transfer_response')));
  });
}
