import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/blocs/visit/visit_bloc.dart';
import 'package:wanasah_frontend/features/visits/application/visit_event.dart'
    as extracted_event;
import 'package:wanasah_frontend/features/visits/application/visit_state.dart'
    as extracted_state;

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
}
