import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/features/custody/presentation/vehicle_inventory_section.dart';
import 'package:wanasah_frontend/features/custody/domain/stock_disclosure.dart';
import 'package:wanasah_frontend/l10n/generated/app_localizations.dart';

void main() {
  testWidgets('identical unavailable vehicle stock states display one notice', (
    tester,
  ) async {
    await tester.pumpWidget(
      MaterialApp(
        locale: const Locale('ar'),
        supportedLocales: AppLocalizations.supportedLocales,
        localizationsDelegates: AppLocalizations.localizationsDelegates,
        home: const Scaffold(
          body: SingleChildScrollView(
            child: VehicleInventorySection(
              products: [],
              nonSellableCustody: [],
              sellableDisclosure: StockDisclosure.unavailable,
              nonSellableDisclosure: StockDisclosure.unavailable,
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    final stockContext = tester.element(find.byType(VehicleInventorySection));
    final title = AppLocalizations.of(stockContext).stockVehicleTitle;
    final sectionColumn = tester.widget<Column>(
      find
          .descendant(
            of: find.byType(VehicleInventorySection),
            matching: find.byType(Column),
          )
          .first,
    );
    // No spacer or divider must precede the vehicle stock heading.
    expect(sectionColumn.children.first, isA<Text>());
    expect((sectionColumn.children.first as Text).data, title);
    expect(
      find.descendant(
        of: find.byType(VehicleInventorySection),
        matching: find.byType(Divider),
      ),
      findsNothing,
    );
    expect(
      find.text(AppLocalizations.of(stockContext).stockUnavailable),
      findsOneWidget,
    );
    expect(tester.takeException(), isNull);
  });
}
