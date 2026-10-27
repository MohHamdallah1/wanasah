import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/core/errors/api_failure_exception.dart';
import 'package:wanasah_frontend/features/custody/data/pending_transfer_source.dart';
import 'package:wanasah_frontend/features/custody/domain/non_sellable_custody.dart';
import 'package:wanasah_frontend/features/custody/domain/transfer_decision.dart';
import 'package:wanasah_frontend/features/custody/presentation/vehicle_inventory_section.dart';

void main() {
  group('transfer decision contract', () {
    test('accepted decision carries no rejection reason', () {
      final decision = TransferDecision(
        transferId: 9,
        status: TransferDecisionStatus.accepted,
        reason: 'ignored',
      );

      expect(decision.reason, isNull);
      expect(decision.status.wireValue, 'accepted');
    });

    test('rejected decision requires an auditable reason', () {
      expect(
        () => TransferDecision(
          transferId: 9,
          status: TransferDecisionStatus.rejected,
        ),
        throwsArgumentError,
      );

      final decision = TransferDecision(
        transferId: 9,
        status: TransferDecisionStatus.rejected,
        reason: '  الكمية لا تطابق التحويل  ',
      );
      expect(decision.reason, 'الكمية لا تطابق التحويل');
      expect(decision.status.wireValue, 'rejected');
    });
  });

  group('pending transfer source', () {
    test('parses canonical server batch into typed model', () async {
      final source = PendingTransferSource(
        remoteFetch: () async => <Object?>[
          <String, Object?>{
            'transfer_id': 'batch-1',
            'created_at': '2026-10-22T00:00:00',
            'items': <Object?>[
              <String, Object?>{
                'real_transfer_id': 17,
                'product_name': 'منتج',
                'delta_cartons': -2,
                'delta_packs': 3,
              },
            ],
          },
        ],
        localFetch: () async => const <Map<String, dynamic>>[],
      );

      final batch = await source.load();

      expect(batch, isNotNull);
      expect(batch!.fromLocalCache, isFalse);
      expect(batch.items.single.transferId, 17);
      expect(batch.items.single.deltaCartons, -2);
      expect(batch.items.single.deltaPacks, 3);
    });

    test('ambiguous network failure falls back to typed local evidence',
        () async {
      final request = RequestOptions(path: '/driver/transfers/pending');
      final source = PendingTransferSource(
        remoteFetch: () async {
          throw DioException(
            requestOptions: request,
            type: DioExceptionType.connectionError,
            error: 'offline',
          );
        },
        localFetch: () async => <Map<String, dynamic>>[
          <String, dynamic>{
            'transfer_id': 22,
            'product_name': 'محلي',
            'delta_cartons': 1,
            'delta_packs': 0,
          },
        ],
      );

      final batch = await source.load();

      expect(batch, isNotNull);
      expect(batch!.fromLocalCache, isTrue);
      expect(batch.items.single.transferId, 22);
    });

    test('confirmed auth rejection does not masquerade as local fallback',
        () async {
      final request = RequestOptions(path: '/driver/transfers/pending');
      final source = PendingTransferSource(
        remoteFetch: () async {
          throw DioException(
            requestOptions: request,
            response: Response<Object?>(
              requestOptions: request,
              statusCode: 401,
              data: <String, dynamic>{
                'error': <String, dynamic>{'code': 'AUTH_REQUIRED'},
              },
            ),
            type: DioExceptionType.badResponse,
          );
        },
        localFetch: () async => <Map<String, dynamic>>[
          <String, dynamic>{
            'transfer_id': 99,
            'product_name': 'لا يجب استخدامه',
            'delta_cartons': 1,
            'delta_packs': 0,
          },
        ],
      );

      await expectLater(source.load(), throwsA(isA<ApiFailureException>()));
    });
  });

  test('Dashboard and transfer dialog use typed Custody models', () async {
    final bloc =
        await File('lib/blocs/dashboard/dashboard_bloc.dart').readAsString();
    final state =
        await File('lib/blocs/dashboard/dashboard_state.dart').readAsString();
    final dialog = await File(
      'lib/features/custody/presentation/pending_transfer_dialog.dart',
    ).readAsString();

    expect(bloc, contains('CustodyCoordinator'));
    expect(
      bloc,
      isNot(contains("part '../../features/custody/application/custody_handlers.dart';")),
    );
    expect(state, contains('PendingTransferBatch? pendingTransfer'));
    expect(state, contains('List<NonSellableCustodyItem> nonSellableCustody'));
    expect(dialog, contains('PendingTransferBatch batch'));
    expect(dialog, contains('List<TransferDecision> decisions'));
    expect(dialog, contains("labelText: strings.t('reason')"));
    expect(dialog, isNot(contains('detailedResponses')));
  });

  testWidgets('non-sellable custody displays Backend exact quantity',
      (tester) async {
    final item = NonSellableCustodyItem.fromJson(
      <String, dynamic>{
        'product_variant_id': 7,
        'product_name': 'تالف اختبار',
        'stock_status': 'DAMAGED',
        'uom_code': 'PACK',
        'quantity': '12.500',
      },
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: VehicleInventorySection(
            products: const [],
            nonSellableCustody: <NonSellableCustodyItem>[item],
          ),
        ),
      ),
    );

    expect(find.text('عهدة غير قابلة للبيع:'), findsOneWidget);
    expect(find.text('تالف اختبار'), findsOneWidget);
    expect(find.text('تالف'), findsOneWidget);
    expect(find.text('12.500 PACK'), findsOneWidget);
  });
}
