import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/presentation/vehicle_inventory_section.dart';
import 'package:wanasah_frontend/features/work_session/presentation/work_session_controls.dart';
import 'package:wanasah_frontend/models/product_model.dart';

void main() {
  group('mechanical architecture boundaries', () {
    test(
        'dashboard composes feature-owned work session boundary and custody seam',
        () async {
      final bloc =
          await File('lib/blocs/dashboard/dashboard_bloc.dart').readAsString();
      final coordinator = await File(
        'lib/features/work_session/application/work_session_coordinator.dart',
      ).readAsString();
      final remote = await File(
        'lib/features/work_session/data/work_session_remote_data_source.dart',
      ).readAsString();
      final custody = await File(
        'lib/features/custody/application/custody_handlers.dart',
      ).readAsString();

      expect(
        bloc,
        isNot(
          contains(
            "part '../../features/work_session/application/work_session_handlers.dart';",
          ),
        ),
      );
      expect(bloc, contains('WorkSessionCoordinator'));
      expect(bloc, contains('recoverActiveSession()'));
      expect(bloc, isNot(contains('_dashboardRepo.startSession(')));
      expect(bloc, isNot(contains('_dashboardRepo.endSession(')));
      expect(bloc, isNot(contains('_dashboardRepo.toggleBreak(')));

      expect(coordinator, contains('_remote.startSession('));
      expect(coordinator, contains('_remote.endSession()'));
      expect(coordinator, contains('_remote.toggleBreak('));
      expect(coordinator, contains('recoverActiveSession()'));
      expect(coordinator, isNot(contains('package:flutter/material.dart')));

      expect(remote, contains("'/driver/sessions/start'"));
      expect(remote, contains("'/driver/sessions/end'"));
      expect(remote, contains("'/driver/sessions/break'"));
      expect(remote, contains("'/driver/sessions/active'"));

      expect(
        bloc,
        contains(
          "part '../../features/custody/application/custody_handlers.dart';",
        ),
      );
      expect(bloc, isNot(contains('Future<void> _onRespondToTransfer')));
      expect(
        bloc,
        isNot(contains('Future<void> _onRespondToBatchTransfer')),
      );

      expect(custody, contains('checkPendingTransfersRaw()'));
      expect(custody, contains('getIncomingTransfers()'));
      expect(custody, contains('respondToTransfer('));
      expect(
        custody,
        contains(
          'تم حفظ ردك. سيتم إرساله تلقائياً عند عودة الإنترنت 📡',
        ),
      );
      expect(custody, isNot(contains('package:flutter/material.dart')));
    });

    test('dashboard screen is a shell over extracted feature presentation',
        () async {
      final screen =
          await File('lib/screens/dashboard_screen.dart').readAsString();
      final session = await File(
        'lib/features/work_session/presentation/work_session_controls.dart',
      ).readAsString();
      final transfer = await File(
        'lib/features/custody/presentation/pending_transfer_dialog.dart',
      ).readAsString();
      final inventory = await File(
        'lib/features/custody/presentation/vehicle_inventory_section.dart',
      ).readAsString();

      expect(screen, contains('WorkSessionControls('));
      expect(screen, contains('showPendingTransferDialog('));
      expect(screen, contains('VehicleInventorySection('));
      expect(screen, isNot(contains("DateFormat('hh:mm a')")));
      expect(screen, isNot(contains("'تحديث عهدة من الإدارة'")));
      expect(screen, isNot(contains("'مخزون سيارة المندوب:'")));

      expect(session, contains("DateFormat('hh:mm a')"));
      expect(session, contains("'يجب إنهاء الاستراحة أولاً!'"));
      expect(transfer, contains("'تحديث عهدة من الإدارة'"));
      expect(
        transfer,
        contains("'يجب الرد على جميع الأصناف بالقبول أو الرفض'"),
      );
      expect(inventory, contains("'مخزون سيارة المندوب:'"));
      expect(inventory, contains("'لا يوجد بضاعة في السيارة حالياً.'"));
    });
  });

  group('work session presentation characterization', () {
    testWidgets('inactive session preserves start confirmation flow',
        (tester) async {
      var actionStarted = 0;
      var starts = 0;
      var ends = 0;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: WorkSessionControls(
              isActiveSession: false,
              activeSessionStartTime: null,
              isOnBreak: false,
              isActionInProgress: false,
              onActionStarted: () => actionStarted++,
              onStart: () => starts++,
              onEnd: () => ends++,
              onToggleBreak: (_) {},
            ),
          ),
        ),
      );

      expect(find.text('اضغط لبدء العمل'), findsOneWidget);
      await tester.tap(find.text('بدء العمل'));
      await tester.pumpAndSettle();

      expect(find.text('بدء العمل؟'), findsOneWidget);
      expect(find.text('هل تريد بدء جلسة عمل جديدة؟'), findsOneWidget);

      await tester.tap(find.text('نعم، تأكيد'));
      await tester.pumpAndSettle();

      expect(actionStarted, 1);
      expect(starts, 1);
      expect(ends, 0);
    });

    testWidgets('active break still blocks end-session action',
        (tester) async {
      var actionStarted = 0;
      var ends = 0;

      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: WorkSessionControls(
              isActiveSession: true,
              activeSessionStartTime: '2026-10-21T08:30:00',
              isOnBreak: true,
              isActionInProgress: false,
              onActionStarted: () => actionStarted++,
              onStart: () {},
              onEnd: () => ends++,
              onToggleBreak: (_) {},
            ),
          ),
        ),
      );

      await tester.tap(find.text('إنهاء العمل'));
      await tester.pump();

      expect(find.text('يجب إنهاء الاستراحة أولاً!'), findsOneWidget);
      expect(actionStarted, 0);
      expect(ends, 0);
    });
  });

  testWidgets('vehicle inventory keeps existing field quantities and labels',
      (tester) async {
    const product = ProductModel(
      id: 7,
      name: 'منتج اختبار',
      pricePerCarton: 1,
      pricePerPack: 1,
      packsPerCarton: 12,
      startingCartons: 10,
      startingPacks: 3,
      soldCartons: 2,
      soldPacks: 4,
      currentCartons: 8,
      currentPacks: 11,
    );

    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: VehicleInventorySection(
            products: <ProductModel>[product],
          ),
        ),
      ),
    );

    expect(find.text('مخزون سيارة المندوب:'), findsOneWidget);
    expect(find.text('منتج اختبار'), findsOneWidget);
    expect(find.text('الاستلام: 10 كرتونة و 3 حبة'), findsOneWidget);
    expect(find.text('المباع: 2 كرتونة، 4 حبة'), findsOneWidget);
    expect(find.text('المتبقي: 8 كرتونة، 11 باكيت'), findsOneWidget);
  });
}
