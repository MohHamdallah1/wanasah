import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/application/custody_coordinator.dart';
import 'package:wanasah_frontend/features/custody/data/custody_client.dart';
import 'package:wanasah_frontend/features/custody/data/pending_transfer_source.dart';
import 'package:wanasah_frontend/features/custody/data/transfer_response_gateway.dart';
import 'package:wanasah_frontend/features/custody/domain/stock_disclosure.dart';
import 'package:wanasah_frontend/features/custody/domain/non_sellable_custody.dart';
import 'package:wanasah_frontend/features/custody/domain/pending_transfer.dart';
import 'package:wanasah_frontend/features/custody/domain/pending_return_custody.dart';
import 'package:wanasah_frontend/features/custody/presentation/vehicle_inventory_section.dart';
import 'package:wanasah_frontend/l10n/generated/app_localizations.dart';
import 'package:wanasah_frontend/models/product_model.dart';
import 'package:wanasah_frontend/blocs/visit/visit_bloc.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_bloc.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_event.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_state.dart';
import 'package:wanasah_frontend/repositories/dashboard_repository.dart';
import 'package:wanasah_frontend/repositories/sync_repository.dart';
import 'package:wanasah_frontend/core/db/local_database.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_reader.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_snapshot.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_coordinator.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_outcome.dart';
import 'package:wanasah_frontend/features/work_session/data/work_session_snapshot.dart';
import 'package:wanasah_frontend/features/visits/presentation/visit_catalog.dart';

Map<String, dynamic> _product({Object? cartons = 0, Object? packs = 0}) => {
  'id': 17,
  'name': 'Physical stock',
  'packs_per_carton': 8,
  'current_cartons': cartons,
  'current_packs': packs,
};

Map<String, dynamic> _custodyItem(int id) => {
  'product_variant_id': id,
  'product_name': 'Variant $id',
  'stock_status': 'DAMAGED',
  'uom_code': 'EACH',
  'quantity': '1.000',
};

CustodyCoordinator _coordinator(CustodyClient client) => CustodyCoordinator(
  custodyClient: client,
  pendingTransfers: PendingTransferSource(
    remoteFetch: () async => [],
    localFetch: () async => <Map<String, dynamic>>[],
  ),
  transferGateway: _UnusedTransferGateway(),
);

Widget _stockWidget(Locale locale, StockDisclosure disclosure, {
  List<ProductModel> products = const [],
}) => MaterialApp(
  locale: locale,
  supportedLocales: AppLocalizations.supportedLocales,
  localizationsDelegates: AppLocalizations.localizationsDelegates,
  home: Scaffold(
    body: SingleChildScrollView(
      child: VehicleInventorySection(
        products: products,
        sellableDisclosure: disclosure,
        nonSellableCustody: const [],
        nonSellableDisclosure: StockDisclosure.verified,
      ),
    ),
  ),
);

class _UnusedTransferGateway extends Fake implements TransferDispatchGateway {}
class _UnusedVisitBloc extends Fake implements VisitBloc {}
class _UnusedSyncRepository extends Fake implements SyncRepository {}

class _NoSyncRepository extends Fake implements SyncRepository {
  @override
  Future<bool> syncDown() async => false;
}

class _StockLocalDb extends Fake implements LocalDatabase {
  @override
  Future<List<Map<String, dynamic>>> getVisits() async => [];
  @override
  Future<List<Map<String, dynamic>>> getProducts() async =>
      [_product(cartons: 4, packs: 1)];
}

class _EmptyRecoveryReader extends Fake implements RecoveryReader {
  @override
  Future<RecoverySnapshot> read() async => const RecoverySnapshot.empty();
}

class _LiveOrFailedDashboardRepo extends Fake implements DashboardRepository {
  int? failureStatus;

  @override
  Future<Response> fetchDashboardRaw() async {
    final request = RequestOptions(path: '/driver/dashboard');
    if (failureStatus != 200) {
      throw DioException(
        requestOptions: request,
        type: failureStatus == null
            ? DioExceptionType.connectionError : DioExceptionType.badResponse,
        response: failureStatus == null ? null
            : Response(requestOptions: request, statusCode: failureStatus),
      );
    }
    return Response(requestOptions: request, statusCode: 200, data: {
      'driver_name': 'Representative',
      'active_session': {
        'session_id': 17,
        'start_time': '2026-10-31T07:00:00Z',
        'is_authorized_to_sell': true,
        'inventory': [_product(cartons: 8, packs: 2)],
      },
      'financials': <String, dynamic>{},
      'counts': <String, dynamic>{},
    });
  }

  @override
  Future<Map<String, String>> getAllCachedData() async => {};

  @override
  Future<void> cacheDashboardData(Map<String, String> data) async {}
}
class _UnusedCustodyCoordinator extends Fake implements CustodyCoordinator {}

/// Controlled production DashboardBloc custody path: request begins before
/// HTTP denial and is released only after the denied state was emitted.
class _BlockedCustodyCoordinator extends Fake implements CustodyCoordinator {
  final started = Completer<void>();
  final releasedThroughLocalRead = Completer<void>();
  final inFlight = Completer<List<NonSellableCustodyItem>>();

  @override
  Future<PendingTransferBatch?> loadPendingTransfers() async => null;

  @override
  Future<List<NonSellableCustodyItem>> loadNonSellableCustody({int? expectedSessionId}) {
    if (!started.isCompleted) started.complete();
    return inFlight.future;
  }

  @override
  Future<List<PendingReturnCustodyItem>> loadPendingReturnCustody() async {
    if (!releasedThroughLocalRead.isCompleted) {
      releasedThroughLocalRead.complete();
    }
    return const <PendingReturnCustodyItem>[];
  }
}

class _DeniedDashboardRepo extends Fake implements DashboardRepository {
  _DeniedDashboardRepo(this.status);
  final int status;

  @override
  Future<Response> fetchDashboardRaw() async {
    final request = RequestOptions(path: '/driver/dashboard');
    throw DioException(
      requestOptions: request,
      response: Response(requestOptions: request, statusCode: status),
      type: DioExceptionType.badResponse,
    );
  }
}

class _InactiveWorkSession extends Fake implements WorkSessionCoordinator {
  @override
  Future<WorkSessionRecoveryResult> recoverActiveSession() async =>
      WorkSessionRecoveryResult.success(const WorkSessionSnapshot.inactive());
}

// Seed only presentation state; the production refresh handler runs unchanged.
class _SeededDashboardBloc extends DashboardBloc {
  _SeededDashboardBloc({
    required DashboardRepository repository,
    required WorkSessionCoordinator session,
    CustodyCoordinator? custody,
    LocalDatabase? db,
    RecoveryReader? recovery,
    SyncRepository? sync,
  }) : super(
    dashboardRepo: repository,
    workSessionCoordinator: session,
    syncRepository: sync ?? _UnusedSyncRepository(),
    db: db,
    recoveryReader: recovery,
    custodyCoordinator: custody ?? _UnusedCustodyCoordinator(),
  );

  void seed(DashboardLoaded value) => emit(value);
}

void main() {
  test('zero is valid but omitted/null/malformed/negative custody never becomes zero', () {
    final zero = ProductModel.fromJson(_product());
    expect(zero.currentCartons, 0);
    expect(zero.currentPacks, 0);
    expect(ProductModel.fromJson(_product(cartons: 2, packs: 3)).currentPacks, 3);
    for (final value in [null, 'unavailable', -1, 1.5]) {
      expect(() => ProductModel.fromJson(_product(cartons: value)),
          throwsFormatException, reason: 'cartons=$value');
      expect(() => ProductModel.fromJson(_product(packs: value)),
          throwsFormatException, reason: 'packs=$value');
    }
    final missingCartons = _product()..remove('current_cartons');
    final missingPacks = _product()..remove('current_packs');
    expect(() => ProductModel.fromJson(missingCartons), throwsFormatException);
    expect(() => ProductModel.fromJson(missingPacks), throwsFormatException);
    expect(ProductModel.fromJson({
      'id': 17, 'remaining_cartons': 0, 'remaining_packs': 0,
    }).currentCartons, 0);
  });

  for (final status in const [401, 403]) {
    test('DashboardBloc denied $status refresh clears previously verified custody', () async {
      final bloc = _SeededDashboardBloc(
        repository: _DeniedDashboardRepo(status),
        session: _InactiveWorkSession(),
      );
      addTearDown(bloc.close);
      bloc.seed(DashboardLoaded(
        visits: const [],
        products: [ProductModel.fromJson(_product(cartons: 4, packs: 1))],
        totalVisits: 0,
        completedVisits: 0,
        pendingVisits: 0,
        offlineVisits: 0,
        sellableStockDisclosure: StockDisclosure.verified,
        nonSellableStockDisclosure: StockDisclosure.verified,
      ));

      bloc.add(FetchDashboardData(driverId: 17));
      final latest = await bloc.stream.firstWhere(
        (state) => state is DashboardLoaded &&
          state.sellableStockDisclosure == StockDisclosure.denied,
      ) as DashboardLoaded;
      expect(latest.products, isEmpty);
      expect(latest.nonSellableCustody, isEmpty);
      expect(latest.nonSellableStockDisclosure, StockDisclosure.denied);
    });
  }

  for (final status in const [401, 403]) {
    test('in-flight custody cannot revive verified stock after $status', () async {
      final custody = _BlockedCustodyCoordinator();
      final bloc = _SeededDashboardBloc(
        repository: _DeniedDashboardRepo(status),
        session: _InactiveWorkSession(),
        custody: custody,
      );
      addTearDown(bloc.close);
      bloc.seed(DashboardLoaded(
        visits: const [],
        products: [ProductModel.fromJson(_product(cartons: 9))],
        totalVisits: 0,
        completedVisits: 0,
        pendingVisits: 0,
        offlineVisits: 0,
        sellableStockDisclosure: StockDisclosure.verified,
        nonSellableStockDisclosure: StockDisclosure.verified,
      ));

      bloc.add(CheckPendingTransfers());
      await custody.started.future; // Request actually in flight before denial.
      final deniedState = bloc.stream.firstWhere((state) =>
          state is DashboardLoaded &&
          state.sellableStockDisclosure == StockDisclosure.denied);
      bloc.add(FetchDashboardData(driverId: 17));
      await deniedState;
      custody.inFlight.complete([
        NonSellableCustodyItem.fromJson(_custodyItem(555)),
      ]);
      await custody.releasedThroughLocalRead.future;
      await Future<void>.delayed(Duration.zero);

      final current = bloc.state as DashboardLoaded;
      expect(current.sellableStockDisclosure, StockDisclosure.denied);
      expect(current.nonSellableStockDisclosure, StockDisclosure.denied);
      expect(current.products, isEmpty);
      expect(current.nonSellableCustody, isEmpty);
    });
  }

  test('bounded custody aggregation is complete at 5000 and rejects overflow',
      () async {
    for (final overflow in const [false, true]) {
      var requests = 0;
      final client = CustodyClient(get: (_, {queryParameters}) async {
        requests++;
        final start = (requests - 1) * 100;
        final continuing = requests < CustodyCoordinator.maximumCustodyPages ||
            overflow;
        return {
          'session_id': 17,
          'items': List.generate(100, (i) => _custodyItem(start + i + 1)),
          'next_cursor': continuing ? 'page-$requests' : null,
        };
      });
      final read = _coordinator(client).loadNonSellableCustody();
      if (overflow) {
        await expectLater(read, throwsFormatException);
      } else {
        final items = await read;
        expect(items.length, CustodyCoordinator.maximumCustodyRows);
        expect(items.last.productVariantId, 5000);
      }
      expect(requests, CustodyCoordinator.maximumCustodyPages);
    }
  });

  test('connectivity fallback shows local stock only as stale, not live',
      () async {
    final repo = _LiveOrFailedDashboardRepo()..failureStatus = null;
    final bloc = _SeededDashboardBloc(
      repository: repo,
      session: _InactiveWorkSession(),
      db: _StockLocalDb(),
      recovery: _EmptyRecoveryReader(),
      sync: _NoSyncRepository(),
    );
    addTearDown(bloc.close);
    final next = bloc.stream.firstWhere((state) =>
        state is DashboardLoaded &&
        state.refreshIssue?.kind == DashboardRefreshIssueKind.connectivity);
    bloc.add(FetchDashboardData(driverId: 17));
    final offline = await next as DashboardLoaded;
    expect(offline.products.single.currentCartons, 4);
    expect(offline.sellableStockDisclosure, StockDisclosure.stale);
    expect(offline.isOffline, isTrue);
  });

  test('fresh authorized response restores verified stock after 403 denial',
      () async {
    final repo = _LiveOrFailedDashboardRepo()..failureStatus = 403;
    final bloc = _SeededDashboardBloc(
      repository: repo,
      session: _InactiveWorkSession(),
      db: _StockLocalDb(),
      recovery: _EmptyRecoveryReader(),
      sync: _NoSyncRepository(),
    );
    addTearDown(bloc.close);
    final denied = bloc.stream.firstWhere((state) =>
        state is DashboardError ||
        state is DashboardLoaded &&
            state.sellableStockDisclosure == StockDisclosure.denied);
    bloc.add(FetchDashboardData(driverId: 17));
    await denied;
    repo.failureStatus = 200;
    final authorized = bloc.stream.firstWhere((state) =>
        state is DashboardLoaded &&
            state.sellableStockDisclosure == StockDisclosure.verified);
    bloc.add(FetchDashboardData(driverId: 17));
    final restored = await authorized as DashboardLoaded;
    expect(restored.products.single.currentCartons, 8);
    expect(restored.products.single.currentPacks, 2);
    expect(restored.sellableStockDisclosure, StockDisclosure.verified);
  });

  test('revoked data stays denied; transient data becomes visibly stale', () {
    expect(stockDisclosureAfterFailure(StockDisclosure.verified, denied: false),
        StockDisclosure.stale);
    expect(stockDisclosureAfterFailure(StockDisclosure.stale, denied: false),
        StockDisclosure.stale);
    expect(stockDisclosureAfterFailure(StockDisclosure.unavailable, denied: false),
        StockDisclosure.unavailable);
    expect(stockDisclosureAfterFailure(StockDisclosure.verified, denied: true),
        StockDisclosure.denied);
    expect(stockDisclosureAfterFailure(StockDisclosure.denied, denied: false),
        StockDisclosure.denied);
  });

  test('101 custody records require cursor and keep exact session', () async {
    final calls = <Map<String, dynamic>>[];
    final items = await _coordinator(CustodyClient(get: (path, {queryParameters}) async {
      expect(path, '/driver/custody');
      calls.add(Map<String, dynamic>.from(queryParameters!));
      if (queryParameters['cursor'] == null) {
        return {
          'session_id': 42,
          'items': List.generate(100, (i) => _custodyItem(i + 1)),
          'next_cursor': 'opaque-session-cursor',
        };
      }
      expect(queryParameters['cursor'], 'opaque-session-cursor');
      return {
        'session_id': 42,
        'items': [_custodyItem(101)],
        'next_cursor': null,
      };
    })).loadNonSellableCustody();
    expect(items.length, 101);
    expect(items.first.productVariantId, 1);
    expect(items.last.productVariantId, 101);
    expect(calls, [
      {'limit': 100}, {'limit': 100, 'cursor': 'opaque-session-cursor'},
    ]);
    expect(() => items.removeLast(), throwsUnsupportedError);
  });

  test('custody page from a different authorized session fails closed', () async {
    final client = CustodyClient(get: (_, {queryParameters}) async => {
      'session_id': 88,
      'items': [_custodyItem(5)],
      'next_cursor': null,
    });
    await expectLater(_coordinator(client)
        .loadNonSellableCustody(expectedSessionId: 87),
        throwsFormatException);
    final matching = await _coordinator(client)
        .loadNonSellableCustody(expectedSessionId: 88);
    expect(matching.single.productVariantId, 5);
  });

  test('cross-session page and repeated cursor fail closed', () async {
    for (final mode in ['session', 'cursor']) {
      final client = CustodyClient(get: (_, {queryParameters}) async => {
        'session_id': queryParameters?['cursor'] == null ? 7 : (mode == 'session' ? 8 : 7),
        'items': [_custodyItem(1)],
        'next_cursor': 'same-cursor',
      });
      await expectLater(_coordinator(client).loadNonSellableCustody(),
          throwsFormatException);
    }
  });

  test('denied second page cannot return incomplete first page', () async {
    var pages = 0;
    final client = CustodyClient(get: (path, {queryParameters}) async {
      pages++;
      if (pages == 1) {
        return {
          'session_id': 11,
          'items': List.generate(100, (i) => _custodyItem(i + 1)),
          'next_cursor': 'cursor-page-2',
        };
      }
      final request = RequestOptions(path: path);
      throw DioException(
        requestOptions: request,
        response: Response(requestOptions: request, statusCode: 403),
        type: DioExceptionType.badResponse,
      );
    });
    await expectLater(_coordinator(client).loadNonSellableCustody(), throwsException);
    expect(pages, 2);
  });

  for (final locale in const [Locale('ar'), Locale('en')]) {
    testWidgets('visit catalog AR/EN stock amounts stay unchanged: ${locale.languageCode}', (tester) async {
      final bloc = _UnusedVisitBloc();
      await tester.pumpWidget(MaterialApp(
        locale: locale,
        supportedLocales: AppLocalizations.supportedLocales,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        home: Scaffold(
          body: Column(children: [
            VisitCatalog(
              catalog: [ProductModel.fromJson(_product(cartons: 4, packs: 2))],
              cart: const [],
              visitBloc: bloc,
              onCartUpdated: () {},
              onClose: () {},
            ),
          ]),
        ),
      ));
      expect(find.text('Physical stock'), findsOneWidget);
      expect(find.textContaining(locale.languageCode == 'ar'
          ? 'المتوفر محلياً (غير مؤكد حالياً): 4'
          : 'Locally available (not currently verified): 4'), findsOneWidget);
      expect(find.text(locale.languageCode == 'ar'
          ? 'اعتماد الكميات والعودة للفاتورة'
          : 'Confirm quantities and return to invoice'), findsOneWidget);
    });
  }

  for (final locale in const [Locale('ar'), Locale('en')]) {
    testWidgets('verified zero and AR/EN stock labels: ${locale.languageCode}', (tester) async {
      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.verified));
      expect(find.text(locale.languageCode == 'ar'
          ? 'لا يوجد مخزون متاح للبيع في السيارة حالياً.'
          : 'No sellable stock is currently in the vehicle.'), findsOneWidget);
      expect(find.textContaining('balance is unknown'), findsNothing);

      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.verified,
        products: [ProductModel.fromJson(_product())]));
      expect(find.text('Physical stock'), findsOneWidget);
      expect(find.textContaining(locale.languageCode == 'ar' ? 'المتبقي: 0' : 'Remaining: 0'), findsOneWidget);
    });

    testWidgets('denial hides quantities; transient stale is explicit: ${locale.languageCode}', (tester) async {
      final product = ProductModel.fromJson(_product(cartons: 4, packs: 1));
      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.denied,
        products: [product]));
      expect(find.text('Physical stock'), findsNothing);
      expect(find.text(locale.languageCode == 'ar'
          ? 'لا توجد صلاحية لعرض العهدة الحالية.'
          : 'You do not have access to current custody.'), findsOneWidget);

      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.unavailable,
        products: [product]));
      expect(find.text('Physical stock'), findsNothing);
      expect(find.text(locale.languageCode == 'ar'
          ? 'تعذر التحقق من مخزون السيارة؛ الرصيد غير معروف.'
          : 'Vehicle stock could not be verified; balance is unknown.'), findsOneWidget);

      await tester.pumpWidget(_stockWidget(locale, StockDisclosure.stale,
        products: [product]));
      expect(find.text('Physical stock'), findsOneWidget);
      expect(find.text(locale.languageCode == 'ar'
          ? 'مخزون محفوظ للاستخدام دون اتصال؛ ليس رصيداً حالياً مؤكداً.'
          : 'Saved offline stock; not a verified current balance.'), findsOneWidget);
    });
  }
}
