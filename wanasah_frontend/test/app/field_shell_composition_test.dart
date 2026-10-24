import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_bloc/flutter_bloc.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:intl/date_symbol_data_local.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_bloc.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_event.dart';
import 'package:wanasah_frontend/blocs/dashboard/dashboard_state.dart';
import 'package:wanasah_frontend/features/custody/domain/non_sellable_custody.dart';
import 'package:wanasah_frontend/features/custody/domain/pending_return_custody.dart';
import 'package:wanasah_frontend/features/custody/presentation/vehicle_inventory_section.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_reader.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_sync_coordinator.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_data_source.dart';
import 'package:wanasah_frontend/features/recovery/data/recovery_sync_executor.dart';
import 'package:wanasah_frontend/features/work_session/presentation/work_session_controls.dart';
import 'package:wanasah_frontend/models/product_model.dart';
import 'package:wanasah_frontend/screens/dashboard_screen.dart';

void main() {
  setUpAll(() async {
    await initializeDateFormatting('ar');
    if (Platform.environment['FIELD_SHELL_CAPTURE'] == '1') {
      final bytes = File('/usr/share/fonts/truetype/noto/NotoSansArabic-Regular.ttf')
          .readAsBytesSync();
      final loader = FontLoader('Roboto')
        ..addFont(Future.value(ByteData.sublistView(bytes)));
      await loader.load();
    }
  });

  testWidgets('real Home evidence and custody stay reachable in the shared shell',
      (tester) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final bloc = _Dashboard(_loaded());
    addTearDown(bloc.close);
    final source = _Source();
    final executor = _Executor();
    final boundary = GlobalKey();

    await tester.pumpWidget(MaterialApp(
      locale: const Locale('ar'),
      supportedLocales: const [Locale('ar')],
      localizationsDelegates: const [
        GlobalMaterialLocalizations.delegate,
        GlobalWidgetsLocalizations.delegate,
        GlobalCupertinoLocalizations.delegate,
      ],
      home: BlocProvider<DashboardBloc>.value(
        value: bloc,
        child: RepaintBoundary(
          key: boundary,
          child: DashboardScreen(
            driverId: 17,
            recoveryCoordinator: RecoverySyncCoordinator(
              reader: RecoveryReader(dataSource: source), executor: executor,
            ),
          ),
        ),
      ),
    ));
    await tester.pumpAndSettle();
    expect(bloc.events.whereType<LoadDashboardData>(), hasLength(1));
    expect(bloc.events.whereType<FetchDashboardData>(), hasLength(1));
    expect(find.byType(WorkSessionControls), findsOneWidget);
    expect(find.byType(VehicleInventorySection), findsNothing);
    expect(find.textContaining('أحمد'), findsOneWidget);
    expect(find.textContaining('الذمم المحصلة'), findsOneWidget);
    expect(find.textContaining('الكاش المستلم'), findsOneWidget);
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
  });

  testWidgets('service failure keeps cached evidence and distinct top utility',
      (tester) async {
    final bloc = _Dashboard(_loaded().copyWith(
      refreshIssue: const DashboardRefreshIssue(
        kind: DashboardRefreshIssueKind.service, statusCode: 503, requestId: 'synthetic',
      ),
    ));
    addTearDown(bloc.close);
    await tester.pumpWidget(MaterialApp(
      home: BlocProvider<DashboardBloc>.value(
        value: bloc,
        child: DashboardScreen(driverId: 17, recoveryCoordinator: RecoverySyncCoordinator(
          reader: RecoveryReader(dataSource: _Source()), executor: _Executor(),
        )),
      ),
    ));
    await tester.pumpAndSettle();
    expect(find.text('Service refresh failed'), findsOneWidget);
    expect(find.byType(WorkSessionControls), findsOneWidget);
    expect(find.textContaining('internet'), findsNothing);
    expect(tester.takeException(), isNull);
  });
}

Future<void> _capture(WidgetTester tester, GlobalKey key, String name) async {
  if (Platform.environment['FIELD_SHELL_CAPTURE'] != '1') return;
  final boundary = key.currentContext!.findRenderObject()! as RenderRepaintBoundary;
  final image = await boundary.toImage(pixelRatio: 1.5);
  final bytes = await image.toByteData(format: ui.ImageByteFormat.png);
  await tester.runAsync(() async {
    final directory = Directory('build/shell-review')..createSync(recursive: true);
    File('${directory.path}/$name.png').writeAsBytesSync(bytes!.buffer.asUint8List());
  });
  image.dispose();
}

DashboardLoaded _loaded() => DashboardLoaded(
  visits: const [], totalVisits: 14, completedVisits: 6, pendingVisits: 8,
  offlineVisits: 0, salesInCompleted: 4,
  driverName: 'أحمد', assignedRegion: 'عمّان الغربية',
  totalSalesCash: 128.5, totalDebtPaid: 32, totalCashOverall: 160.5,
  debtPaymentsCount: 2,
  products: const [ProductModel(
    id: 1, name: 'مياه شرب', pricePerCarton: 0, pricePerPack: 0,
    packsPerCarton: 12, startingCartons: 20, soldCartons: 6, currentCartons: 14,
  )],
  nonSellableCustody: [NonSellableCustodyItem.fromJson({
    'product_variant_id': 2, 'product_name': 'عصير برتقال', 'stock_status': 'DAMAGED',
    'uom_code': 'PACK', 'quantity': '2.000',
  })],
  pendingReturnCustody: const [PendingReturnCustodyItem(
    productVariantId: 3, productName: 'حليب طويل الأجل',
    reason: PendingReturnReason.expired, evidenceState: PendingCustodyEvidenceState.pending,
    cartons: 1, packs: 0, commandCount: 1,
  )],
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
  Future<bool> synchronize() async { calls++; return true; }
}
