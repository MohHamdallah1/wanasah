import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/l10n/generated/app_localizations.dart';
import 'package:wanasah_frontend/app/shell/field_app_shell.dart';
import 'package:wanasah_frontend/app/theme/field_theme.dart';

void main() {
  Widget app({
    Locale locale = const Locale('ar'),
    double scale = 1,
    VoidCallback? logout,
    VoidCallback? refresh,
  }) => MaterialApp(
    locale: locale,
    supportedLocales: AppLocalizations.supportedLocales,
    localizationsDelegates: AppLocalizations.localizationsDelegates,
    builder:
        (context, child) => MediaQuery(
          data: MediaQuery.of(
            context,
          ).copyWith(textScaler: TextScaler.linear(scale)),
          child: child!,
        ),
    home: FieldAppShell(
      accountName: 'Representative',
      homeBuilder: (context) => const SizedBox.shrink(),
      routeBuilder: (_) => const _RouteProbe(),
      custody: const Center(child: Text('Custody evidence')),
      statusUtility: TextButton(
        onPressed: () {},
        child: const Text('Pending: 2'),
      ),
      onRefresh: refresh ?? () {},
      onLogout: logout ?? () {},
      onDestinationChanged: (_) {},
    ),
  );

  testWidgets(
    'three labeled persistent destinations, selection semantics and state',
    (tester) async {
      final semantics = tester.ensureSemantics();
      await tester.pumpWidget(app());
      expect(find.text('الرئيسية'), findsOneWidget);
      expect(find.text('خط السير'), findsOneWidget);
      expect(find.text('العهدة'), findsOneWidget);
      expect(find.byType(_RouteProbe), findsNothing);
      expect(
        tester.getSemantics(find.bySemanticsLabel('الرئيسية')),
        matchesSemantics(
          label: 'الرئيسية',
          isButton: true,
          isSelected: true,
          hasTapAction: true,
        ),
      );

      await tester.tap(find.byKey(const ValueKey('shell-tab-route')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Increment'));
      await tester.pump();
      expect(find.text('Route 1'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('shell-tab-custody')));
      await tester.pumpAndSettle();
      expect(find.text('Custody evidence'), findsOneWidget);
      await tester.tap(find.byKey(const ValueKey('shell-tab-route')));
      await tester.pumpAndSettle();
      expect(find.text('Route 1'), findsOneWidget);
      expect(find.text('Pending: 2'), findsOneWidget);
      semantics.dispose();
    },
  );

  testWidgets('deep actions hide shell; back restores route then Home', (
    tester,
  ) async {
    final semantics = tester.ensureSemantics();
    await tester.pumpWidget(app());
    await tester.tap(find.byKey(const ValueKey('shell-tab-route')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Deep action'));
    await tester.pumpAndSettle();
    expect(find.text('Protected draft'), findsOneWidget);
    expect(find.byKey(const ValueKey('shell-tab-home')), findsNothing);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(find.text('Route 0'), findsOneWidget);
    await tester.binding.handlePopRoute();
    await tester.pumpAndSettle();
    expect(
      tester.getSemantics(find.bySemanticsLabel('الرئيسية')),
      matchesSemantics(
        label: 'الرئيسية',
        isButton: true,
        isSelected: true,
        hasTapAction: true,
      ),
    );
    semantics.dispose();
  });

  testWidgets(
    'global secondary account actions retain refresh/logout callbacks',
    (tester) async {
      var logouts = 0;
      var refreshes = 0;
      await tester.pumpWidget(
        app(logout: () => logouts++, refresh: () => refreshes++),
      );
      await tester.tap(find.byKey(const ValueKey('shell-account')));
      await tester.pumpAndSettle();
      expect(find.text('Representative'), findsOneWidget);
      await tester.tap(find.text('تحديث البيانات'));
      await tester.pumpAndSettle();
      expect(refreshes, 1);
      await tester.tap(find.byKey(const ValueKey('shell-account')));
      await tester.pumpAndSettle();
      await tester.tap(find.text('تسجيل الخروج'));
      await tester.pumpAndSettle();
      expect(logouts, 1);
    },
  );

  for (final locale in [const Locale('ar'), const Locale('en')]) {
    for (final width in [320.0, 412.0]) {
      testWidgets(
        'navigation fits ${locale.languageCode} at width $width and 2x text',
        (tester) async {
          tester.view.physicalSize = Size(width, 780);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          await tester.pumpWidget(app(locale: locale, scale: 2));
          await tester.pumpAndSettle();
          expect(tester.takeException(), isNull);
          final home = find.byKey(const ValueKey('shell-tab-home'));
          final custody = find.byKey(const ValueKey('shell-tab-custody'));
          expect(tester.getSize(home).height, greaterThanOrEqualTo(48));
          expect(tester.getSize(home).width, greaterThanOrEqualTo(48));
          final route = find.byKey(const ValueKey('shell-tab-route'));
          final homeX = tester.getCenter(home).dx;
          final routeX = tester.getCenter(route).dx;
          final custodyX = tester.getCenter(custody).dx;
          if (locale.languageCode == 'ar') {
            expect(routeX, greaterThan(homeX));
            expect(homeX, greaterThan(custodyX));
          } else {
            expect(routeX, lessThan(homeX));
            expect(homeX, lessThan(custodyX));
          }
          await tester.tap(custody);
          await tester.pumpAndSettle();
          expect(find.text('Custody evidence'), findsOneWidget);
          expect(tester.takeException(), isNull);
        },
      );
    }
  }

  test(
    'semantic theme supports contrast, comfortable controls and both modes',
    () {
      for (final brightness in Brightness.values) {
        final theme = FieldTheme.data(brightness: brightness);
        final colors = theme.colorScheme;
        double contrast(Color a, Color b) {
          final x = a.computeLuminance();
          final y = b.computeLuminance();
          return x > y ? (x + .05) / (y + .05) : (y + .05) / (x + .05);
        }

        expect(contrast(colors.onSurface, colors.surface), greaterThan(7));
        expect(contrast(colors.primary, colors.surface), greaterThan(4.5));
        expect(contrast(colors.onPrimary, colors.primary), greaterThan(4.5));
        expect(theme.materialTapTargetSize, MaterialTapTargetSize.padded);
      }
    },
  );

  test('shell has no persistence, network, replay or business authority', () {
    final shell = File('lib/app/shell/field_app_shell.dart').readAsStringSync();
    for (final forbidden in [
      'LocalDatabase',
      'SyncRepository',
      'ApiClient',
      'VisitBloc',
      'AuthBloc(',
      'command_id',
      'batch_id',
      'is_admin',
    ]) {
      expect(shell, isNot(contains(forbidden)));
    }
    final dashboard =
        File('lib/screens/dashboard_screen.dart').readAsStringSync();
    expect(dashboard, contains('FieldAppShell('));
    expect(dashboard, contains('HomeOverview('));
    expect(dashboard, contains('WorkSessionControls('));
    expect(dashboard, contains('VehicleInventorySection('));
    expect(dashboard, contains('showPendingTransferDialog('));
    expect(
      dashboard,
      contains('RespondToBatchTransfer(decisions: result.decisions)'),
    );
    final route = File('lib/screens/visit_list_screen.dart').readAsStringSync();
    expect(route, contains('_allowAction(VisitRouteAction.openVisit)'));
    expect(route, contains('_allowAction(VisitRouteAction.addShop)'));
  });

  testWidgets('Home does not duplicate primary bottom destinations', (
    tester,
  ) async {
    await tester.pumpWidget(app());
    expect(find.byKey(const ValueKey('shell-tab-route')), findsOneWidget);
    expect(find.byKey(const ValueKey('shell-tab-custody')), findsOneWidget);
    expect(find.text('عرض قائمة زيارات اليوم'), findsNothing);
    expect(find.text('عرض العهدة'), findsNothing);
  });

  testWidgets('persistent dock reserves space above route actions', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(390, 844);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    await tester.pumpWidget(app());
    await tester.tap(find.byKey(const ValueKey('shell-tab-route')));
    await tester.pumpAndSettle();

    final fab = find.byKey(const ValueKey('route-probe-fab'));
    final dockHome = find.byKey(const ValueKey('shell-tab-home'));
    expect(fab, findsOneWidget);
    expect(
      tester.getRect(fab).bottom,
      lessThanOrEqualTo(tester.getRect(dockHome).top),
    );
  });

  testWidgets('shell labels are locale resources', (tester) async {
    await tester.pumpWidget(app(locale: const Locale('en')));
    expect(find.text('Route'), findsOneWidget);
    expect(find.text('Home'), findsOneWidget);
    expect(find.text('Custody'), findsOneWidget);
  });
}

class _RouteProbe extends StatefulWidget {
  const _RouteProbe();
  @override
  State<_RouteProbe> createState() => _RouteProbeState();
}

class _RouteProbeState extends State<_RouteProbe> {
  int count = 0;
  @override
  Widget build(BuildContext context) => Scaffold(
    body: ListView(
      children: [
        Text('Route $count'),
        TextButton(
          onPressed: () => setState(() => count++),
          child: const Text('Increment'),
        ),
        TextButton(
          onPressed:
              () => Navigator.of(context).push(
                MaterialPageRoute<void>(
                  builder: (_) => const Scaffold(body: Text('Protected draft')),
                ),
              ),
          child: const Text('Deep action'),
        ),
      ],
    ),
    floatingActionButton: FloatingActionButton(
      key: const ValueKey('route-probe-fab'),
      onPressed: () {},
      child: const Icon(Icons.add),
    ),
  );
}
