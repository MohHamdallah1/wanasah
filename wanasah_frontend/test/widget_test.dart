import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:wanasah_frontend/main.dart';
import 'package:wanasah_frontend/screens/splash_screen.dart';

void main() {
  testWidgets('Wanasah app opens with Arabic-branded SplashScreen', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(const MyApp());

    // The real entry screen is the field app splash, not Flutter's counter
    // template. Do not pumpAndSettle: the loader is intentionally animated.
    expect(find.byType(MaterialApp), findsOneWidget);
    expect(find.byType(SplashScreen), findsOneWidget);
    expect(find.text('وناسة'), findsOneWidget);
    expect(find.byIcon(Icons.directions_car_filled_rounded), findsOneWidget);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);

    final splashContext = tester.element(find.byType(SplashScreen));
    expect(Localizations.localeOf(splashContext).languageCode, 'ar');
  });
}
