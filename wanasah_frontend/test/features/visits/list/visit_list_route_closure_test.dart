import 'dart:async';
import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import 'package:flutter/services.dart';
import 'package:wanasah_frontend/blocs/visit_list/visit_list_bloc.dart';
import 'package:wanasah_frontend/blocs/visit_list/visit_list_event.dart';
import 'package:wanasah_frontend/blocs/visit_list/visit_list_state.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_filter.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_read_model.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_reader.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_refresh.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_map_target.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_route_action_gate.dart';
import 'package:wanasah_frontend/features/visits/list/data/visit_list_data_source.dart';
import 'package:wanasah_frontend/features/visits/list/data/visit_list_refresh_source.dart';
import 'package:wanasah_frontend/models/visit_model.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();
  group('Visit List read model', () {
    test('orders deterministically by sequence then visit id', () async {
      final model = await _reader(<VisitModel>[
        _visit(id: 30, sequence: 2, status: 'Completed'),
        _visit(
          id: 20,
          sequence: 1,
          status: 'Pending',
          emergency: true,
          outcome: 'NoSale',
        ),
        _visit(
          id: 10,
          sequence: 1,
          status: 'Pending',
          outcome: 'Postponed',
        ),
        _visit(
          id: 40,
          sequence: 3,
          status: 'Pending',
          emergency: true,
        ),
      ]).read();

      expect(
        model.orderedRows.map((row) => row.id).toList(),
        <int>[10, 20, 30, 40],
      );
    });

    test('splits normal route and emergency rows without changing order',
        () async {
      final model = await _sampleReader().read();

      expect(
        model.rowsFor(VisitRouteKind.normal).map((row) => row.id),
        <int>[10, 30],
      );
      expect(
        model.rowsFor(VisitRouteKind.emergency).map((row) => row.id),
        <int>[20, 40],
      );
      expect(model.emergencyCount, 2);
    });

    test('Completed stays completed and Postponed stays backend Pending',
        () async {
      final model = await _sampleReader().read();
      final completed =
          model.orderedRows.firstWhere((row) => row.id == 30);
      final postponed =
          model.orderedRows.firstWhere((row) => row.id == 10);

      expect(
        completed.presentation,
        VisitExecutionPresentation.completed,
      );
      expect(completed.backendStatus, 'Completed');

      expect(
        postponed.presentation,
        VisitExecutionPresentation.postponed,
      );
      expect(postponed.backendStatus, 'Pending');
      expect(postponed.backendOutcome, 'Postponed');
    });

    test('attempted Pending visit gets attempted presentation only', () async {
      final model = await _sampleReader().read();
      final attempted =
          model.orderedRows.firstWhere((row) => row.id == 20);

      expect(
        attempted.presentation,
        VisitExecutionPresentation.attempted,
      );
      expect(attempted.backendStatus, 'Pending');
      expect(attempted.backendOutcome, 'NoSale');
    });

    test('counts derive from backend status and route kind', () async {
      final model = await _sampleReader().read();

      final normal = model.countsFor(VisitRouteKind.normal);
      final emergency = model.countsFor(VisitRouteKind.emergency);

      expect(normal.total, 2);
      expect(normal.completed, 1);
      expect(normal.pending, 1);
      expect(emergency.total, 2);
      expect(emergency.completed, 0);
      expect(emergency.pending, 2);
    });

    test('pending filter includes postponed and attempted because status is Pending',
        () async {
      final model = await _sampleReader().read(
        filter: VisitListFilter.pending,
      );

      expect(
        model.rowsFor(VisitRouteKind.normal).map((row) => row.id),
        <int>[10],
      );
      expect(
        model.rowsFor(VisitRouteKind.emergency).map((row) => row.id),
        <int>[20, 40],
      );
    });

    test('filter is preserved across Bloc local reload', () async {
      final dataSource = _FakeVisitListDataSource(_sampleVisits());
      final reader = VisitListReader(dataSource: dataSource);
      final bloc = VisitListBloc(
        reader: reader,
        refreshCoordinator: VisitListRefreshCoordinator(
          source: _FakeRefreshSource(),
        ),
      );

      final firstLoaded = bloc.stream.firstWhere(
        (state) => state is VisitListLoaded,
      );
      bloc.add(const LoadVisitsEvent());
      await firstLoaded;

      final filtered = bloc.stream.firstWhere(
        (state) =>
            state is VisitListLoaded &&
            state.model.filter == VisitListFilter.pending,
      );
      bloc.add(const FilterVisitsEvent(VisitListFilter.pending));
      await filtered;

      dataSource.visits = <VisitModel>[
        ..._sampleVisits(),
        _visit(id: 50, sequence: 4, status: 'Completed'),
      ];

      final reloaded = bloc.stream.firstWhere(
        (state) =>
            state is VisitListLoaded &&
            state.model.filter == VisitListFilter.pending &&
            state.model.orderedRows.length == 5,
      );
      bloc.add(const LoadVisitsEvent());
      final state = await reloaded as VisitListLoaded;

      expect(state.model.filter, VisitListFilter.pending);
      await bloc.close();
    });
  });

  group('Visit List refresh classification', () {
    test('success is typed refreshed', () async {
      final result = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(syncResult: true),
      ).refresh();

      expect(result.outcome, VisitListRefreshOutcome.refreshed);
    });

    test('sync lock reports already syncing', () async {
      final result = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(syncResult: false),
      ).refresh();

      expect(
        result.outcome,
        VisitListRefreshOutcome.alreadySyncing,
      );
    });

    test('connection failure is transport ambiguous', () async {
      final result = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(
          error: DioException(
            requestOptions: RequestOptions(path: '/driver/visits'),
            type: DioExceptionType.connectionError,
            message: 'arbitrary text must not classify the failure',
          ),
        ),
      ).refresh();

      expect(
        result.outcome,
        VisitListRefreshOutcome.transportAmbiguous,
      );
    });

    test('deterministic 409 is deterministic failure', () async {
      final result = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(
          error: _dioResponse(
            status: 409,
            message: 'Any display fallback',
          ),
        ),
      ).refresh();

      expect(
        result.outcome,
        VisitListRefreshOutcome.deterministicFailure,
      );
    });

    test('free text does not change deterministic classification', () async {
      final first = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(
          error: _dioResponse(
            status: 409,
            message: 'رسالة عربية',
          ),
        ),
      ).refresh();
      final second = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(
          error: _dioResponse(
            status: 409,
            message: 'Completely unrelated English fallback',
          ),
        ),
      ).refresh();

      expect(first.outcome, second.outcome);
      expect(first.code, second.code);
      expect(first.displayFallback, isNot(second.displayFallback));
    });

    test('generic failure plus unresolved durable evidence is blocked', () async {
      final result = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(
          error: StateError('compatibility failure text'),
          unresolvedRows: <Map<String, dynamic>>[
            <String, dynamic>{
              'id': 91,
              'state': 'blocked',
              'type': 'submit_sale',
            },
          ],
        ),
      ).refresh();

      expect(
        result.outcome,
        VisitListRefreshOutcome.blockedByUnresolvedDurableWork,
      );
      expect(result.displayFallback, isNull);
    });

    test('generic failure without durable evidence fails closed deterministically',
        () async {
      final result = await VisitListRefreshCoordinator(
        source: _FakeRefreshSource(
          error: StateError('must not be parsed'),
        ),
      ).refresh();

      expect(
        result.outcome,
        VisitListRefreshOutcome.deterministicFailure,
      );
      expect(result.displayFallback, isNull);
    });

    test('refresh timeout is transport ambiguous outside the Widget', () async {
      final source = _HangingRefreshSource();
      final result = await VisitListRefreshCoordinator(
        source: source,
        waitLimit: const Duration(milliseconds: 1),
      ).refresh();

      expect(
        result.outcome,
        VisitListRefreshOutcome.transportAmbiguous,
      );
    });
  });

  group('Route action navigation is not authorization', () {
    test('stale cached active break does not block either form', () async {
      final gate = _gate(onBreak: 'true', authorized: 'true');
      for (final action in VisitRouteAction.values) {
        expect(await gate.evaluate(action), VisitRouteActionDecision.allowed);
      }
    });

    test('stale cached unauthorized does not block either form', () async {
      final gate = _gate(onBreak: 'false', authorized: 'false');
      for (final action in VisitRouteAction.values) {
        expect(await gate.evaluate(action), VisitRouteActionDecision.allowed);
      }
    });

    test('allowed cache opens forms without claiming mutation acceptance', () async {
      final gate = _gate(onBreak: 'false', authorized: 'true');
      for (final action in VisitRouteAction.values) {
        expect(await gate.evaluate(action), VisitRouteActionDecision.allowed);
      }
    });

    test('missing or malformed compatibility values do not deny navigation', () async {
      for (final gate in [
        _gate(onBreak: null, authorized: null),
        _gate(onBreak: 'invalid', authorized: 'yes'),
      ]) {
        for (final action in VisitRouteAction.values) {
          expect(await gate.evaluate(action), VisitRouteActionDecision.allowed);
        }
      }
    });

    test('storage failure cannot affect navigation because it is never read', () async {
      var reads = 0;
      const channel = MethodChannel('plugins.it_nomads.com/flutter_secure_storage');
      TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, (_) async {
        reads++;
        throw StateError('storage unavailable');
      });
      addTearDown(() => TestDefaultBinaryMessengerBinding.instance.defaultBinaryMessenger
          .setMockMethodCallHandler(channel, null));
      for (final action in VisitRouteAction.values) {
        expect(await const VisitRouteActionGate().evaluate(action),
          VisitRouteActionDecision.allowed);
      }
      expect(reads, 0);
    });
  });

  group('Map target safety', () {
    test('0,0 is never treated as a valid coordinate target', () {
      final target = VisitMapTarget.fromRow(
        _row(
          _visit(
            id: 70,
            sequence: 1,
            status: 'Pending',
            latitude: 0,
            longitude: 0,
          ),
        ),
      );

      expect(target.hasCoordinates, isFalse);
      expect(target.fallbackUri, isNull);
    });

    test('valid coordinates are preserved with a sanitized link fallback', () {
      final target = VisitMapTarget.fromRow(
        _row(
          _visit(
            id: 71,
            sequence: 1,
            status: 'Pending',
            latitude: 31.95,
            longitude: 35.91,
            locationLink: 'maps.google.com/?q=31.95,35.91',
          ),
        ),
      );

      expect(target.hasCoordinates, isTrue);
      expect(target.latitude, 31.95);
      expect(target.longitude, 35.91);
      expect(target.fallbackUri!.scheme, 'https');
    });

    test('zero on one axis remains a valid real coordinate', () {
      final target = VisitMapTarget.fromRow(
        _row(
          _visit(
            id: 72,
            sequence: 1,
            status: 'Pending',
            latitude: 0,
            longitude: 35,
          ),
        ),
      );

      expect(target.hasCoordinates, isTrue);
    });

    test('unsafe external schemes are rejected', () {
      final target = VisitMapTarget.fromRow(
        _row(
          _visit(
            id: 73,
            sequence: 1,
            status: 'Pending',
            locationLink: 'javascript:alert(1)',
          ),
        ),
      );

      expect(target.fallbackUri, isNull);
      expect(target.hasInvalidRawLink, isTrue);
    });
  });

  group('Visit List architecture invariants', () {
    test('screen no longer parses raw DB rows or owns machine classification',
        () async {
      final screen = await File(
        'lib/screens/visit_list_screen.dart',
      ).readAsString();

      expect(screen, isNot(contains('LocalDatabase')));
      expect(screen, isNot(contains('SyncRepository')));
      expect(screen, isNot(contains('FlutterSecureStorage')));
      expect(screen, isNot(contains('getVisits()')));
      expect(screen, isNot(contains('VisitModel.fromJson')));
      expect(screen, isNot(contains('message.contains(')));
      expect(screen, isNot(contains("read(key: 'is_on_break')")));
      expect(screen, isNot(contains("read(key: 'is_authorized')")));
      expect(screen, contains('VisitRouteActionGate'));
      expect(screen, contains('VisitRouteTabs'));
    });

    test('Bloc delegates raw reads, filtering and refresh classification',
        () async {
      final bloc = await File(
        'lib/blocs/visit_list/visit_list_bloc.dart',
      ).readAsString();

      expect(bloc, isNot(contains('LocalDatabase')));
      expect(bloc, isNot(contains('SyncRepository')));
      expect(bloc, isNot(contains('VisitModel.fromJson')));
      expect(bloc, isNot(contains('.sort(')));
      expect(bloc, isNot(contains('.where(')));
      expect(bloc, contains('VisitListReader'));
      expect(bloc, contains('VisitListRefreshCoordinator'));
    });

    test('extracted list widgets stay presentation-only', () async {
      for (final path in <String>[
        'lib/features/visits/list/presentation/visit_card.dart',
        'lib/features/visits/list/presentation/visit_route_tabs.dart',
        'lib/features/visits/list/presentation/visit_list_summary.dart',
        'lib/features/visits/list/presentation/visit_empty_state.dart',
      ]) {
        final source = await File(path).readAsString();
        expect(source, isNot(contains('LocalDatabase')), reason: path);
        expect(source, isNot(contains('SyncRepository')), reason: path);
        expect(source, isNot(contains('FlutterSecureStorage')), reason: path);
        expect(source, isNot(contains('DioException')), reason: path);
      }
    });
  });
}

VisitListReader _sampleReader() => _reader(_sampleVisits());

VisitListReader _reader(List<VisitModel> visits) {
  return VisitListReader(
    dataSource: _FakeVisitListDataSource(visits),
  );
}

List<VisitModel> _sampleVisits() {
  return <VisitModel>[
    _visit(
      id: 30,
      sequence: 2,
      status: 'Completed',
    ),
    _visit(
      id: 20,
      sequence: 1,
      status: 'Pending',
      emergency: true,
      outcome: 'NoSale',
    ),
    _visit(
      id: 10,
      sequence: 1,
      status: 'Pending',
      outcome: 'Postponed',
    ),
    _visit(
      id: 40,
      sequence: 3,
      status: 'Pending',
      emergency: true,
    ),
  ];
}

VisitModel _visit({
  required int id,
  required int sequence,
  required String status,
  bool emergency = false,
  String outcome = '',
  double? latitude,
  double? longitude,
  String? locationLink,
}) {
  return VisitModel(
    id: id,
    shopId: 1000 + id,
    shopName: 'Shop $id',
    shopBalance: 12.5,
    maxDebtLimit: 100,
    status: status,
    outcome: outcome,
    sequence: sequence,
    isEmergency: emergency,
    latitude: latitude,
    longitude: longitude,
    locationLink: locationLink,
  );
}

VisitListRow _row(VisitModel visit) {
  return VisitListRow(
    visit: visit,
    routeKind:
        visit.isEmergency
            ? VisitRouteKind.emergency
            : VisitRouteKind.normal,
    presentation: VisitExecutionPresentation.pending,
  );
}

VisitRouteActionGate _gate({
  required String? onBreak,
  required String? authorized,
}) {
  FlutterSecureStorage.setMockInitialValues({
    if (onBreak != null) 'is_on_break': onBreak,
    if (authorized != null) 'is_authorized': authorized,
  });
  return const VisitRouteActionGate();
}

DioException _dioResponse({
  required int status,
  required String message,
}) {
  final options = RequestOptions(path: '/driver/visits');
  return DioException(
    requestOptions: options,
    type: DioExceptionType.badResponse,
    response: Response<dynamic>(
      requestOptions: options,
      statusCode: status,
      data: <String, dynamic>{
        'request_id': 'req-$status',
        'error': <String, dynamic>{
          'code': 'HTTP_$status',
          'message': message,
          'context': <String, dynamic>{},
        },
      },
    ),
  );
}

class _FakeVisitListDataSource implements VisitListDataSource {
  _FakeVisitListDataSource(this.visits);

  List<VisitModel> visits;

  @override
  Future<List<VisitModel>> readVisits() async =>
      List<VisitModel>.from(visits);
}

class _FakeRefreshSource implements VisitListRefreshSource {
  _FakeRefreshSource({
    this.syncResult = true,
    this.error,
    this.unresolvedRows = const <Map<String, dynamic>>[],
  });

  final bool syncResult;
  final Object? error;
  final List<Map<String, dynamic>> unresolvedRows;

  @override
  Future<bool> syncDown() async {
    if (error case final value?) throw value;
    return syncResult;
  }

  @override
  Future<List<Map<String, dynamic>>> readUnresolvedCommands() async {
    return unresolvedRows;
  }
}

class _HangingRefreshSource implements VisitListRefreshSource {
  final Completer<bool> _completer = Completer<bool>();

  @override
  Future<bool> syncDown() => _completer.future;

  @override
  Future<List<Map<String, dynamic>>> readUnresolvedCommands() async {
    return const <Map<String, dynamic>>[];
  }
}

