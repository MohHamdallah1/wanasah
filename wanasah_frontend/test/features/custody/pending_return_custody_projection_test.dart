import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/data/pending_return_custody_source.dart';
import 'package:wanasah_frontend/features/custody/domain/pending_return_custody.dart';

Map<String, dynamic> _command({
  required String id,
  required String state,
  required int localEffectApplied,
  required List<Map<String, dynamic>> returns,
  String type = 'submit_sale',
}) {
  return <String, dynamic>{
    'id': int.parse(id),
    'type': type,
    'state': state,
    'command_id': 'cmd-$id',
    'local_effect_applied': localEffectApplied,
    'payload': jsonEncode(<String, dynamic>{
      'visitId': 11,
      'returns': returns,
    }),
  };
}

Map<String, dynamic> _return({
  required int variantId,
  required String reason,
  int cartons = 0,
  int packs = 0,
}) {
  return <String, dynamic>{
    'product_variant_id': variantId,
    'return_type': reason,
    'quantity': cartons,
    'packs_quantity': packs,
  };
}

void main() {
  group('pending local return custody projection', () {
    test('projects all canonical return reasons as pending DAMAGED evidence', () async {
      final source = LocalPendingReturnCustodySource(
        pendingRows: () async => <Map<String, dynamic>>[
          _command(
            id: '1',
            state: 'pending',
            localEffectApplied: 1,
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'Damaged',
                cartons: 1,
                packs: 2,
              ),
              _return(
                variantId: 8,
                reason: 'Expired',
                cartons: 2,
              ),
              _return(
                variantId: 9,
                reason: 'Factory_Defect',
                packs: 4,
              ),
            ],
          ),
        ],
        productRows: () async => <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': 'A'},
          <String, dynamic>{'id': 8, 'name': 'B'},
          <String, dynamic>{'id': 9, 'name': 'C'},
        ],
      );

      final result = await source.read();

      expect(result, hasLength(3));
      expect(
        result.map((item) => item.reason).toSet(),
        <PendingReturnReason>{
          PendingReturnReason.damaged,
          PendingReturnReason.expired,
          PendingReturnReason.factoryDefect,
        },
      );
      expect(result.every((item) => item.stockStatus == 'DAMAGED'), isTrue);
      expect(
        result.every(
          (item) => item.evidenceState == PendingCustodyEvidenceState.pending,
        ),
        isTrue,
      );
    });

    test('aggregates only equal variant/reason/state evidence', () async {
      final source = LocalPendingReturnCustodySource(
        pendingRows: () async => <Map<String, dynamic>>[
          _command(
            id: '1',
            state: 'pending',
            localEffectApplied: 1,
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'Damaged',
                cartons: 1,
                packs: 2,
              ),
            ],
          ),
          _command(
            id: '2',
            state: 'pending',
            localEffectApplied: 1,
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'Damaged',
                cartons: 2,
                packs: 3,
              ),
            ],
          ),
          _command(
            id: '3',
            state: 'blocked',
            localEffectApplied: 1,
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'Damaged',
                packs: 1,
              ),
            ],
          ),
        ],
        productRows: () async => <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': 'Product'},
        ],
      );

      final result = await source.read();

      expect(result, hasLength(2));
      final pending = result.singleWhere(
        (item) => item.evidenceState == PendingCustodyEvidenceState.pending,
      );
      expect(pending.cartons, 3);
      expect(pending.packs, 5);
      expect(pending.commandCount, 2);

      final blocked = result.singleWhere(
        (item) => item.evidenceState == PendingCustodyEvidenceState.blocked,
      );
      expect(blocked.cartons, 0);
      expect(blocked.packs, 1);
      expect(blocked.commandCount, 1);
    });

    test('strict rejected command with no local effect is not projected', () async {
      final source = LocalPendingReturnCustodySource(
        pendingRows: () async => <Map<String, dynamic>>[
          _command(
            id: '1',
            state: 'blocked',
            localEffectApplied: 0,
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'Damaged',
                cartons: 1,
              ),
            ],
          ),
        ],
        productRows: () async => <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': 'Product'},
        ],
      );

      expect(await source.read(), isEmpty);
    });

    test('unsupported reason and unrelated durable command fail closed', () async {
      final source = LocalPendingReturnCustodySource(
        pendingRows: () async => <Map<String, dynamic>>[
          _command(
            id: '1',
            state: 'pending',
            localEffectApplied: 1,
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'SomethingElse',
                cartons: 1,
              ),
            ],
          ),
          _command(
            id: '2',
            state: 'pending',
            localEffectApplied: 1,
            type: 'transfer_response',
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'Damaged',
                cartons: 5,
              ),
            ],
          ),
        ],
        productRows: () async => <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': 'Product'},
        ],
      );

      expect(await source.read(), isEmpty);
    });

    test('legacy quarantined draft sale normalizes without losing blocked evidence', () async {
      final source = LocalPendingReturnCustodySource(
        pendingRows: () async => <Map<String, dynamic>>[
          _command(
            id: '1',
            state: 'blocked',
            localEffectApplied: 1,
            type: 'quarantined_draft_sale',
            returns: <Map<String, dynamic>>[
              _return(
                variantId: 7,
                reason: 'Expired',
                cartons: 1,
              ),
            ],
          ),
        ],
        productRows: () async => <Map<String, dynamic>>[
          <String, dynamic>{'id': 7, 'name': 'Product'},
        ],
      );

      final result = await source.read();

      expect(result, hasLength(1));
      expect(result.single.reason, PendingReturnReason.expired);
      expect(
        result.single.evidenceState,
        PendingCustodyEvidenceState.blocked,
      );
    });
  });

  test('vehicle inventory UI keeps local pending evidence separate from authority', () async {
    final source = await File(
      'lib/features/custody/presentation/vehicle_inventory_section.dart',
    ).readAsString();

    expect(source, contains('مرتجعات محلية بانتظار الحسم'));
    expect(
      source,
      contains('ليست رصيد العهدة النهائي من السيرفر'),
    );
    expect(source, contains('nonSellableCustody'));
    expect(source, contains('pendingReturnCustody'));
  });

  test('dashboard local recovery reloads pending return evidence', () async {
    final source =
        await File('lib/blocs/dashboard/dashboard_bloc.dart').readAsString();

    expect(
      source,
      contains('await _custodyCoordinator.loadPendingReturnCustody()'),
    );
    expect(
      source,
      contains('pendingReturnCustody: pendingReturnCustody'),
    );
  });
}
