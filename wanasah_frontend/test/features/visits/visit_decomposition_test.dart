import 'dart:convert';
import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/blocs/visit/visit_bloc.dart';
import 'package:wanasah_frontend/features/visits/application/visit_event.dart'
    as extracted_event;
import 'package:wanasah_frontend/features/visits/application/visit_state.dart'
    as extracted_state;
import 'package:wanasah_frontend/features/visits/data/visit_durable_evidence_source.dart';

void main() {
  test('legacy visit_bloc import keeps event/state compatibility exports', () {
    const legacyEvent = LoadVisitCatalog(12.5);
    const directEvent = extracted_event.LoadVisitCatalog(12.5);

    expect(legacyEvent.props, directEvent.props);
    expect(VisitLoading(), isA<VisitState>());
    expect(extracted_state.VisitLoading(), isA<extracted_state.VisitState>());
  });

  test('visit catalog presentation is mechanically extracted from screen', () async {
    final screen = await File('lib/screens/visit_screen.dart').readAsString();
    final catalog =
        await File('lib/features/visits/presentation/visit_catalog.dart')
            .readAsString();

    expect(screen, contains("features/visits/presentation/visit_catalog.dart"));
    expect(screen, contains('VisitCatalog('));
    expect(screen, isNot(contains('class _SearchableCatalog')));
    expect(screen, isNot(contains('class _AccordionProductCard')));

    expect(catalog, contains('class VisitCatalog extends StatefulWidget'));
    expect(catalog, contains('class _AccordionProductCard'));
    expect(catalog, contains('AddOrUpdateCartItem(updatedItem)'));
  });

  test('visit bloc retains orchestration while declarations live in feature files',
      () async {
    final bloc = await File('lib/blocs/visit/visit_bloc.dart').readAsString();
    final events =
        await File('lib/features/visits/application/visit_event.dart')
            .readAsString();
    final states =
        await File('lib/features/visits/application/visit_state.dart')
            .readAsString();

    expect(bloc, contains('class VisitBloc extends Bloc<VisitEvent, VisitState>'));
    expect(bloc, contains("export '../../features/visits/application/visit_event.dart';"));
    expect(bloc, contains("export '../../features/visits/application/visit_state.dart';"));
    expect(bloc, isNot(contains('abstract class VisitEvent')));
    expect(bloc, isNot(contains('abstract class VisitState')));

    expect(events, contains('abstract class VisitEvent'));
    expect(states, contains('abstract class VisitState'));
    expect(states, contains('class VisitReady'));
  });

  test('Visit durable read model restores the newest matching submit_sale draft',
      () async {
    final source = LocalVisitDurableEvidenceSource(
      pendingRows: () async => <Map<String, dynamic>>[
        <String, dynamic>{
          'type': 'submit_sale',
          'state': 'pending',
          'payload': jsonEncode(<String, dynamic>{
            'visitId': 11,
            'cash_collected': '1.250',
            'debt_paid': '2.500',
            'notes': 'older',
            'cart_items': <Map<String, dynamic>>[
              <String, dynamic>{'product_variant_id': 7, 'quantity': 1},
            ],
          }),
        },
        <String, dynamic>{
          'type': 'submit_sale',
          'state': 'blocked',
          'payload': jsonEncode(<String, dynamic>{
            'visit_id': '11',
            'cash_collected': '9.125000',
            'debt_paid': '0.001',
            'no_sale_reason': 'newest',
            'returns': <Map<String, dynamic>>[
              <String, dynamic>{
                'product_variant_id': 7,
                'return_type': 'Damaged',
                'quantity': 1,
              },
            ],
          }),
        },
      ],
    );

    final readModel = await source.readForVisit(11);
    final draft = readModel.latestDraft;

    expect(readModel.hasUnresolvedDraft, isTrue);
    expect(draft, isNotNull);
    expect(draft!.cashCollected, '9.125000');
    expect(draft.debtPaid, '0.001');
    expect(draft.notes, 'newest');
    expect(draft.cartItemsJson, isNull);
    expect(jsonDecode(draft.returnsJson!), isA<List<dynamic>>());
  });

  test('Visit durable adapter ignores unrelated and malformed raw rows',
      () async {
    final source = LocalVisitDurableEvidenceSource(
      pendingRows: () async => <Map<String, dynamic>>[
        <String, dynamic>{
          'type': 'submit_sale',
          'payload': '{',
        },
        <String, dynamic>{
          'type': 'submit_sale',
          'payload': jsonEncode(<String, dynamic>{'visitId': 12}),
        },
        <String, dynamic>{
          'type': 'transfer_response',
          'payload': jsonEncode(<String, dynamic>{'visitId': 11}),
        },
        <String, dynamic>{
          'type': 'quarantined_submit_sale',
          'payload': jsonEncode(<String, dynamic>{'visitId': 11}),
        },
      ],
    );

    final readModel = await source.readForVisit(11);

    expect(readModel.hasUnresolvedDraft, isFalse);
    expect(readModel.latestDraft, isNull);
  });

  test('VisitScreen consumes typed durable evidence without raw command parsing',
      () async {
    final screen = await File('lib/screens/visit_screen.dart').readAsString();
    final source = await File(
      'lib/features/visits/data/visit_durable_evidence_source.dart',
    ).readAsString();

    expect(
      screen,
      contains('LocalVisitDurableEvidenceSource.withDatabase()'),
    );
    expect(screen, contains('durableEvidence.latestDraft'));
    expect(screen, isNot(contains('getPendingSyncs')));
    expect(screen, isNot(contains('jsonDecode(')));
    expect(screen, isNot(contains('jsonEncode(')));

    expect(source, contains('db.getPendingSyncs'));
    expect(source, contains('DurableCommandType.submitSale'));
    expect(source, contains('for (final row in rows.reversed)'));
    expect(source, isNot(contains('deletePendingSync')));
    expect(source, isNot(contains('markPendingSync')));
    expect(source, isNot(contains('updatePendingSync')));
  });

}
