import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:wanasah_frontend/l10n/generated/app_localizations.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_bloc.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_event.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_state.dart';
import 'package:wanasah_frontend/features/custody/domain/non_sellable_custody.dart';
import 'package:wanasah_frontend/features/custody/domain/pending_return_custody.dart';
import 'package:wanasah_frontend/features/custody/domain/stock_disclosure.dart';
import 'package:wanasah_frontend/features/custody/presentation/vehicle_inventory_section.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_reader.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_sync_coordinator.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_data_source.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_sync_executor.dart';
import 'package:wanasah_frontend/features/work_session/presentation/work_session_controls.dart';
import 'package:wanasah_frontend/models/visit_model.dart';
import 'package:wanasah_frontend/features/visits/list/presentation/visit_route_tabs.dart';
import 'package:wanasah_frontend/features/visits/list/presentation/visit_list_strings.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_read_model.dart';
import 'package:wanasah_frontend/features/visits/list/application/visit_list_filter.dart';
import 'package:wanasah_frontend/models/product_model.dart';
import 'package:wanasah_frontend/screens/dashboard_screen.dart';

void main() {
  setUpAll(() async {
    await initializeDateFormatting('ar');
    if (Platform.environment['FIELD_SHELL_CAPTURE'] == '1') {
      final bytes =
          File(
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
          ).readAsBytesSync();
      for (final family in ['Roboto', 'Ahem']) {
        final loader = FontLoader(family)
          ..addFont(Future.value(ByteData.sublistView(bytes)));
        await loader.load();
      }
      final icons = FontLoader('MaterialIcons')
        ..addFont(rootBundle.load('fonts/MaterialIcons-Regular.otf'));
      await icons.load();
    }
  });

  testWidgets(
    'real Home evidence and custody stay reachable in the shared shell',
    (tester) async {
      // Ahem does not shape Arabic. The ordinary suite checks composition at
      // its wide fixture size; the CI render gate checks 390px with real fonts.
      tester.view.physicalSize = Size(
        Platform.environment['FIELD_SHELL_CAPTURE'] == '1' ? 390 : 800,
        844,
      );
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final bloc = _Dashboard(_loaded());
      addTearDown(bloc.close);
      final source = _Source();
      final executor = _Executor();
      final boundary = GlobalKey();

      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('ar'),
          supportedLocales: AppLocalizations.supportedLocales,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          home: BlocProvider<DashboardBloc>.value(
            value: bloc,
            child: RepaintBoundary(
              key: boundary,
              child: DashboardScreen(
                driverId: 17,
                recoveryCoordinator: RecoverySyncCoordinator(
                  reader: RecoveryReader(dataSource: source),
                  executor: executor,
                ),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(bloc.events.whereType<LoadDashboardData>(), hasLength(1));
      expect(bloc.events.whereType<FetchDashboardData>(), hasLength(1));
      expect(find.byType(WorkSessionControls), findsOneWidget);
      expect(find.byKey(const ValueKey('work-session-start')), findsOneWidget);
      expect(find.byType(VehicleInventorySection), findsNothing);
      expect(find.textContaining('أحمد'), findsNothing);
      await tester.tap(find.byKey(const ValueKey('shell-account')));
      await tester.pumpAndSettle();
      expect(find.textContaining('أحمد'), findsOneWidget);
      await tester.tapAt(const Offset(10, 200));
      await tester.pumpAndSettle();
      expect(find.text('جولة اليوم'), findsOneWidget);
      expect(find.text('تحصيل ذمم'), findsOneWidget);
      expect(find.text('إجمالي الكاش المستلم'), findsOneWidget);
      await _capture(tester, boundary, 'home-rtl');

      await tester.tap(find.byKey(const ValueKey('shell-tab-custody')));
      await tester.pumpAndSettle();
      expect(find.byType(VehicleInventorySection), findsOneWidget);
      expect(find.text('مرتجعات محلية بانتظار الحسم:'), findsOneWidget);
      expect(find.text('عهدة غير قابلة للبيع:'), findsOneWidget);
      expect(find.text('مياه شرب'), findsOneWidget);
      expect(executor.calls, 0);
      await _capture(tester, boundary, 'custody-rtl');
      await tester.tap(find.byKey(const ValueKey('shell-tab-home')));
      await tester.pumpAndSettle();
      expect(find.byType(WorkSessionControls), findsOneWidget);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('polished Route surface renders at field width', (tester) async {
    tester.view.physicalSize = Size(
      Platform.environment['FIELD_SHELL_CAPTURE'] == '1' ? 390 : 800,
      844,
    );
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final boundary = GlobalKey();
    final model = _routeModel();

    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ar'),
        supportedLocales: AppLocalizations.supportedLocales,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        home: DefaultTabController(
          length: 2,
          child: Builder(
            builder: (context) {
              final controller = DefaultTabController.of(context);
              return RepaintBoundary(
                key: boundary,
                child: Scaffold(
                  appBar: AppBar(
                    toolbarHeight: 64,
                    titleSpacing: 12,
                    title: VisitRouteTabBar(
                      controller: controller,
                      emergencyCount: model.emergencyCount,
                    ),
                    actions: const [
                      Padding(
                        padding: EdgeInsetsDirectional.only(end: 6),
                        child: IconButton.filledTonal(
                          onPressed: null,
                          icon: Icon(Icons.refresh_rounded),
                        ),
                      ),
                    ],
                  ),
                  floatingActionButtonLocation:
                      FloatingActionButtonLocation.startFloat,
                  floatingActionButton: FloatingActionButton.extended(
                    onPressed: () {},
                    icon: const Icon(Icons.add_business_outlined),
                    label: Text(
                      visitListString(
                        VisitListStringKey.addShopTooltip,
                        localeCode: 'ar',
                      ),
                    ),
                  ),
                  body: VisitRouteTabs(
                    controller: controller,
                    model: model,
                    activeRoute: VisitRouteKind.normal,
                    onFilterChanged: (_) {},
                    onRefresh: () async {},
                    onOpenVisit: (_) {},
                    onOpenMap: (_) {},
                  ),
                ),
              );
            },
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();

    expect(find.text('التالي'), findsOneWidget);
    expect(find.text('14 زيارة • 6 مكتملة • 8 متبقية'), findsOneWidget);
    expect(find.text('إضافة محل'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await _capture(tester, boundary, 'route-rtl');
  });

  testWidgets(
    'service failure keeps cached evidence and distinct top utility',
    (tester) async {
      final bloc = _Dashboard(
        _loaded().copyWith(
          refreshIssue: const DashboardRefreshIssue(
            kind: DashboardRefreshIssueKind.service,
            statusCode: 503,
            requestId: 'synthetic',
          ),
        ),
      );
      addTearDown(bloc.close);
      await tester.pumpWidget(
        MaterialApp(
          locale: const Locale('en'),
          supportedLocales: AppLocalizations.supportedLocales,
          localizationsDelegates: AppLocalizations.localizationsDelegates,
          home: BlocProvider<DashboardBloc>.value(
            value: bloc,
            child: DashboardScreen(
              driverId: 17,
              recoveryCoordinator: RecoverySyncCoordinator(
                reader: RecoveryReader(dataSource: _Source()),
                executor: _Executor(),
              ),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Service refresh failed'), findsOneWidget);
      expect(find.byType(WorkSessionControls), findsOneWidget);
      expect(find.textContaining('internet'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}

Future<void> _capture(WidgetTester tester, GlobalKey key, String name) async {
  if (Platform.environment['FIELD_SHELL_CAPTURE'] != '1') return;
  final boundary =
      key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  await tester.runAsync(() async {
    final image = await boundary.toImage(pixelRatio: 1.5);
    try {
      final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
      final directory = Directory('build/shell-review')
        ..createSync(recursive: true);
      File(
        '${directory.path}/$name.png',
      ).writeAsBytesSync(bytes!.buffer.asUint8List());
    } finally {
      image.dispose();
    }
  });
}

VisitListReadModel _routeModel() {
  const names = <String>[
    'بقالة الندى',
    'سوبر ماركت الأمل',
    'تموينات الياسمين',
    'متجر الروابي',
    'أسواق الصفوة',
    'تموينات النخيل',
    'ميني ماركت الريان',
    'أسواق البركة',
    'تموينات الوفاء',
    'سوبر ماركت الشروق',
    'متجر المدينة',
    'أسواق الوادي',
    'بقالة الخير',
    'تموينات الشرق',
  ];
  final rows = <VisitListRow>[
    _routeRow(1, 1, names[0], 42.5, 'Pending'),
    for (var index = 1; index <= 6; index++)
      _routeRow(
        index + 1,
        index + 1,
        names[index],
        index.isEven ? 0 : 12.5,
        'Completed',
      ),
    for (var index = 7; index < names.length; index++)
      _routeRow(
        index + 1,
        index + 1,
        names[index],
        5.0 + index,
        'Pending',
        outcome: index == 9 ? 'Postponed' : '',
      ),
  ];
  return VisitListReadModel(
    orderedRows: List<VisitListRow>.unmodifiable(rows),
    filter: VisitListFilter.all,
  );
}

VisitListRow _routeRow(
  int id,
  int sequence,
  String shopName,
  double balance,
  String status, {
  String outcome = '',
}) {
  final presentation =
      status.toLowerCase() == 'completed'
          ? VisitExecutionPresentation.completed
          : outcome.toLowerCase() == 'postponed'
          ? VisitExecutionPresentation.postponed
          : VisitExecutionPresentation.pending;
  return VisitListRow(
    visit: VisitModel(
      id: id,
      shopId: 500 + id,
      shopName: shopName,
      shopBalance: balance,
      maxDebtLimit: 100,
      status: status,
      outcome: outcome,
      sequence: sequence,
      isEmergency: false,
    ),
    routeKind: VisitRouteKind.normal,
    presentation: presentation,
  );
}

DashboardLoaded _loaded() => DashboardLoaded(
  visits: const [],
  totalVisits: 14,
  completedVisits: 6,
  pendingVisits: 8,
  offlineVisits: 0,
  salesInCompleted: 4,
  driverName: 'أحمد',
  assignedRegion: 'عمّان الغربية',
  totalSalesCash: 128.5,
  totalDebtPaid: 32,
  totalCashOverall: 160.5,
  debtPaymentsCount: 2,
  sellableStockDisclosure: StockDisclosure.verified,
  nonSellableStockDisclosure: StockDisclosure.verified,
  products: const [
    ProductModel(
      id: 1,
      name: 'مياه شرب',
      pricePerCarton: 0,
      pricePerPack: 0,
      packsPerCarton: 12,
      startingCartons: 20,
      soldCartons: 6,
      currentCartons: 14,
    ),
  ],
  nonSellableCustody: [
    NonSellableCustodyItem.fromJson({
      'product_variant_id': 2,
      'product_name': 'عصير برتقال',
      'stock_status': 'DAMAGED',
      'uom_code': 'PACK',
      'quantity': '2.000',
    }),
  ],
  pendingReturnCustody: const [
    PendingReturnCustodyItem(
      productVariantId: 3,
      productName: 'حليب طويل الأجل',
      reason: PendingReturnReason.expired,
      evidenceState: PendingCustodyEvidenceState.pending,
      cartons: 1,
      packs: 0,
      commandCount: 1,
    ),
  ],
);

class _Dashboard extends Cubit<DashboardState> implements DashboardBloc {
  _Dashboard(super.initialState);
  final List<DashboardEvent> events = [];
  @override
  void add(DashboardEvent event) => events.add(event);
  @override
  dynamic noSuchMethod(Invocation invocation) => super.noSuchMethod(invocation);
}

class _Source implements RecoveryDataSource {
  @override
  Future<List<Map<String, dynamic>>> readUnresolvedRows() async => [];
}

class _Executor implements RecoverySyncExecutor {
  int calls = 0;
  @override
  Future<bool> synchronize() async {
    calls++;
    return true;
  }
}
