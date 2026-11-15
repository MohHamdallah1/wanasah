import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/data/current_vehicle_stock_reader.dart';
import 'package:wanasah_frontend/features/custody/domain/vehicle_route_authority.dart';
import 'package:wanasah_frontend/features/custody/presentation/current_vehicle_stock_section.dart';
import 'package:wanasah_frontend/l10n/generated/app_localizations.dart';

const active = VehicleRouteAuthority.active(routeId: 71, vehicleId: 17);
const otherCar = VehicleRouteAuthority.active(routeId: 72, vehicleId: 21);

Map<String, Object?> stockPage({
  int car = 17,
  String stock = '8',
  String fingerprint = 'signed-snapshot-1',
  String? cursor,
  bool empty = false,
}) => {
  'status': 'VERIFIED',
  'source': 'INVENTORY_BALANCE',
  'vehicle_id': car,
  'vehicle_location_id': 81,
  'custody_epoch_id': 12,
  'context_revision': 3,
  'stock_snapshot': fingerprint,
  'sellable_items':
      empty
          ? []
          : [
            {
              'product_variant_id': 7,
              'product_name': 'Chips',
              'stock_status': 'AVAILABLE',
              'uom_code': 'EACH',
              'quantity': stock,
              'packs_per_carton': 50,
            },
          ],
  'non_sellable_items': [],
  'next_cursor': cursor,
};

Widget harness(
  VehicleRouteAuthority route,
  CurrentVehicleStockReader reader, {
  int nonce = 0,
}) => MaterialApp(
  locale: const Locale('ar'),
  supportedLocales: AppLocalizations.supportedLocales,
  localizationsDelegates: AppLocalizations.localizationsDelegates,
  home: Scaffold(
    body: SingleChildScrollView(
      child: CurrentVehicleStockSection(
        route: route,
        reader: reader,
        refreshNonce: nonce,
      ),
    ),
  ),
);

void main() {
  test('route state comes exclusively from signed current dashboard read', () {
    expect(
      VehicleRouteAuthority.fromDashboard({}).kind,
      VehicleRouteKind.unverified,
    );
    expect(
      VehicleRouteAuthority.fromDashboard({'active_route_vehicle': null}).kind,
      VehicleRouteKind.noActiveRoute,
    );
    expect(
      VehicleRouteAuthority.fromDashboard({
        'active_route_vehicle': {'route_id': 71, 'vehicle_id': 17},
        'execution_context': {'route_id': 71, 'vehicle_id': 17},
      }),
      active,
    );
    expect(
      () => VehicleRouteAuthority.fromDashboard({
        'active_route_vehicle': {'route_id': 71, 'vehicle_id': 17},
        'execution_context': {'route_id': 72, 'vehicle_id': 17},
      }),
      throwsFormatException,
    );
    expect(
      () => VehicleRouteAuthority.fromDashboard({
        'active_route_vehicle': {'route_id': 71, 'vehicle_id': null},
      }),
      throwsFormatException,
    );
  });

  test(
    'real exact-car physical balance verified, never invented starting or sold',
    () async {
      final reader = CurrentVehicleStockReader(
        fetch: (limit, cursor) async {
          expect(limit, 100);
          expect(cursor, isNull);
          return stockPage();
        },
      );
      final result = await reader.read(active);
      expect(result.vehicleId, 17);
      expect(result.sellable.single.quantity, '8');
      expect(result.sellable.single.baseUomCode, 'EACH');
      expect(result.nonSellable, isEmpty);
    },
  );

  test('no route never triggers a stock request and no fake empty', () async {
    var reads = 0;
    final reader = CurrentVehicleStockReader(
      fetch: (limit, cursor) async {
        reads++;
        return stockPage();
      },
    );
    await expectLater(
      reader.read(const VehicleRouteAuthority.noActiveRoute()),
      throwsStateError,
    );
    expect(reads, 0);
  });

  test('foreign vehicle or invalid physical quantity fails closed', () async {
    for (final invalid in [stockPage(car: 99), stockPage(stock: '0')]) {
      final reader = CurrentVehicleStockReader(
        fetch: (limit, cursor) async => invalid,
      );
      await expectLater(reader.read(active), throwsFormatException);
    }
  });

  test(
    'changed current vehicle fingerprint between cursor pages fails closed',
    () async {
      var calls = 0;
      final reader = CurrentVehicleStockReader(
        fetch: (limit, cursor) async {
          calls++;
          if (calls == 1) return stockPage(cursor: 'opaque-cursor');
          expect(cursor, 'opaque-cursor');
          return stockPage(fingerprint: 'another-snapshot', empty: true);
        },
      );
      await expectLater(reader.read(active), throwsFormatException);
      expect(calls, 2);
    },
  );

  testWidgets(
    'verified no active route displays neutral state, never stock-error copy',
    (tester) async {
      var reads = 0;
      final reader = CurrentVehicleStockReader(
        fetch: (limit, cursor) async {
          reads++;
          return stockPage();
        },
      );
      await tester.pumpWidget(
        harness(const VehicleRouteAuthority.noActiveRoute(), reader),
      );
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('field-no-active-route')),
        findsOneWidget,
      );
      expect(
        find.text(
          AppLocalizations.of(
            tester.element(find.byType(CurrentVehicleStockSection)),
          ).stockUnavailable,
        ),
        findsNothing,
      );
      expect(reads, 0);
    },
  );

  testWidgets('active signed route shows only actual physical current stock', (
    tester,
  ) async {
    final reader = CurrentVehicleStockReader(
      fetch: (limit, cursor) async => stockPage(),
    );
    await tester.pumpWidget(harness(active, reader));
    await tester.pumpAndSettle();
    expect(find.text('8 EACH'), findsOneWidget);
    expect(find.text('Chips'), findsOneWidget);
    expect(
      find.text(
        AppLocalizations.of(
          tester.element(find.byType(CurrentVehicleStockSection)),
        ).stockUnavailable,
      ),
      findsNothing,
    );
  });

  testWidgets(
    'failed signed active vehicle read remains an error, not no route',
    (tester) async {
      final reader = CurrentVehicleStockReader(
        fetch: (limit, cursor) async => stockPage(car: 99),
      );
      await tester.pumpWidget(harness(active, reader));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('field-no-active-route')), findsNothing);
      expect(
        find.text(
          AppLocalizations.of(
            tester.element(find.byType(CurrentVehicleStockSection)),
          ).stockUnavailable,
        ),
        findsOneWidget,
      );
    },
  );

  testWidgets(
    'vehicle switch revokes earlier request even if old HTTP returns later',
    (tester) async {
      final pending = Completer<Object?>();
      final reader = CurrentVehicleStockReader(
        fetch: (limit, cursor) async {
          return pending.future;
        },
      );
      await tester.pumpWidget(harness(active, reader));
      await tester.pump();
      await tester.pumpWidget(
        harness(const VehicleRouteAuthority.noActiveRoute(), reader),
      );
      pending.complete(stockPage());
      await tester.pumpAndSettle();
      expect(
        find.byKey(const ValueKey('field-no-active-route')),
        findsOneWidget,
      );
      expect(find.text('8 EACH'), findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
