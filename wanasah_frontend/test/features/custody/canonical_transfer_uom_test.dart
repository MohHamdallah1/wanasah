import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/domain/pending_transfer.dart';
import 'package:wanasah_frontend/features/custody/domain/transfer_decision.dart';
import 'package:wanasah_frontend/features/custody/domain/transfer_decision_command.dart';
import 'package:wanasah_frontend/features/custody/presentation/pending_transfer_dialog.dart';
import 'package:wanasah_frontend/features/custody/presentation/pending_transfer_quantity_formatter.dart';
import 'canonical_transfer_fixture.dart';

void main() {
  test('canonical integer range is not limited by legacy negative carton counters', () {
    final item = PendingTransferItem.fromServerJson(canonicalTransfer(quantity: '-3000000000'));
    expect(item.canonicalQuantity!.signedBaseQuantity, '-3000000000');
    expect(item.isAddition, isFalse);
  });
  test(
    'canonical evidence remains exact and compatibility fields do not set direction',
    () {
      final item = PendingTransferItem.fromServerJson(
        canonicalTransfer(quantity: '-5')
          ..['delta_cartons'] = 999
          ..['delta_packs'] = 999,
      );
      expect(item.isAddition, isFalse);
      expect(item.canonicalQuantity!.signedBaseQuantity, '-5');
      expect(item.canonicalQuantity!.baseUomCode, 'EACH');
    },
  );
  test('marked malformed or incomplete evidence fails closed', () {
    for (final field in [
      'signed_base_quantity',
      'base_uom_id',
      'base_uom_code',
      'base_uom_name',
      'quantity_scale',
      'quantity_step',
      'display_uom_name',
      'display_factor_to_base',
    ]) {
      expect(
        () => PendingTransferItem.fromServerJson(
          canonicalTransfer()..remove(field),
        ),
        throwsFormatException,
      );
    }
    for (final invalid
        in <String, Object?>{
          'quantity_contract': 'UNKNOWN',
          'signed_base_quantity': '0.5',
          'base_uom_id': 0,
          'quantity_scale': 7,
          'quantity_step': '0',
          'display_factor_to_base': '0',
        }.entries) {
      expect(
        () => PendingTransferItem.fromServerJson(
          canonicalTransfer()..[invalid.key] = invalid.value,
        ),
        throwsFormatException,
      );
    }
    expect(
      () => PendingTransferItem.fromLocalRow(
        canonicalTransfer()..remove('base_uom_name'),
      ),
      throwsFormatException,
    );
  });
  for (final example
      in {
        '8': '1 باكيت',
        '5': '5 حبة',
        '25': '3 باكيت + 1 حبة',
        '-5': '5 حبة',
      }.entries) {
    test(
      'canonical ${example.key} uses exact PACK/base presentation despite carton conflict',
      () {
        final item = PendingTransferItem.fromServerJson(
          canonicalTransfer(quantity: example.key),
        );
        expect(
          formatPendingTransferQuantity(item, locale: 'en'),
          example.value,
        );
        expect(formatPendingTransferQuantity(item), isNot(contains('كرتونة')));
      },
    );
  }
  test('no unique commercial UOM uses true non-EACH base name', () {
    final item = PendingTransferItem.fromServerJson(
      canonicalTransfer(quantity: '5')
        ..['base_uom_code'] = 'KG'
        ..['base_uom_name'] = 'كجم'
        ..['display_uom_name'] = null
        ..['display_factor_to_base'] = null,
    );
    expect(formatPendingTransferQuantity(item, locale: 'en'), '5 كجم');
    expect(formatPendingTransferQuantity(item), isNot(contains('حبة')));
  });
  test('unmarked historical rows retain carton/piece semantics', () {
    final item = PendingTransferItem.fromLocalRow({
      'transfer_id': 9,
      'product_name': 'قديم',
      'delta_cartons': -2,
      'delta_packs': -3,
    });
    expect(item.canonicalQuantity, isNull);
    expect(item.isAddition, isFalse);
    expect(
      formatPendingTransferQuantity(item, locale: 'en'),
      '2 cartons, 3 pieces',
    );
    expect(formatPendingTransferQuantity(item), contains('كرتونة'));
  });
  test(
    'durable decision retains canonical context but no quantity becomes decision authority',
    () {
      final item = PendingTransferItem.fromServerJson(canonicalTransfer());
      final payload = TransferDecisionCommand.toPayload(
        TransferDecision(
          transferId: 17,
          status: TransferDecisionStatus.accepted,
        ),
        canonicalQuantity: item.canonicalQuantity,
        deltaCartons: 0,
        deltaPacks: 8,
      );
      expect(payload['context_quantity_contract'], 'CANONICAL_BASE_V1');
      expect(payload['context_signed_base_quantity'], '8');
      expect(payload['context_base_uom_name'], 'حبة');
      expect(payload.containsKey('context_delta_cartons'), isFalse);
      expect(TransferDecisionCommand.fromPayload(payload).transferId, 17);
      expect(
        TransferDecisionCommand.fromPayload(payload).status,
        TransferDecisionStatus.accepted,
      );
    },
  );
  for (final action in ['Accept', 'Reject', 'Defer (close)']) {
    testWidgets(
      'canonical dialog $action preserves existing decision/defer behavior',
      (tester) async {
        PendingTransferDialogResult? result;
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: Builder(
                builder:
                    (context) => TextButton(
                      onPressed: () async {
                        result = await showPendingTransferDialog(
                          context,
                          PendingTransferBatch(
                            batchId: 'b',
                            items: [
                              PendingTransferItem.fromServerJson(
                                canonicalTransfer(quantity: '-5'),
                              ),
                            ],
                          ),
                        );
                      },
                      child: const Text('Open'),
                    ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('Open'));
        await tester.pumpAndSettle();
        expect(find.text('5 حبة'), findsOneWidget);
        expect(find.text('Removal from vehicle'), findsOneWidget);
        expect(find.textContaining('cartons'), findsNothing);
        if (action == 'Defer (close)') {
          await tester.tap(find.text(action));
        } else {
          await tester.tap(find.byTooltip(action));
          await tester.pumpAndSettle();
          if (action == 'Reject') {
            await tester.tap(find.text('Send response'));
            await tester.pump();
            expect(
              find.text('Every rejected movement needs a reason.'),
              findsOneWidget,
            );
            await tester.enterText(find.byType(TextField), 'Mismatch');
          }
          await tester.tap(find.text('Send response'));
        }
        await tester.pumpAndSettle();
        expect(result, isNotNull);
        expect(
          result!.disposition,
          action == 'Defer (close)'
              ? PendingTransferDialogDisposition.deferred
              : PendingTransferDialogDisposition.submitted,
        );
        if (action != 'Defer (close)') {
          expect(result!.decisions.single.transferId, 17);
          expect(
            result!.decisions.single.status,
            action == 'Accept'
                ? TransferDecisionStatus.accepted
                : TransferDecisionStatus.rejected,
          );
        }
      },
    );
  }
}
