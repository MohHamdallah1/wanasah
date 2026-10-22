import 'package:flutter/material.dart';

import 'app_tokens.dart';

class AppTheme {
  const AppTheme._();

  static ThemeData get data {
    return ThemeData(
      primarySwatch: AppTokens.primarySwatch,
      scaffoldBackgroundColor: AppTokens.scaffoldSurface,
      canvasColor: AppTokens.canvasSurface,
      visualDensity: VisualDensity.adaptivePlatformDensity,
      fontFamily: AppTokens.fontFamily,
      appBarTheme: const AppBarTheme(
        backgroundColor: AppTokens.appBarBackground,
        elevation: AppTokens.appBarElevation,
        centerTitle: true,
        iconTheme: IconThemeData(
          color: AppTokens.appBarForeground,
        ),
        titleTextStyle: TextStyle(
          color: AppTokens.appBarForeground,
          fontWeight: FontWeight.bold,
          fontSize: AppTokens.appBarTitleSize,
        ),
      ),
    );
  }

  static const LinearGradient backgroundGradient = LinearGradient(
    begin: Alignment.topLeft,
    end: Alignment.bottomRight,
    colors: AppTokens.backgroundGradientColors,
    stops: AppTokens.backgroundGradientStops,
  );
}
