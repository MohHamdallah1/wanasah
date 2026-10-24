import 'package:flutter/material.dart';

/// Semantic foundation for the approved FIELD shell. Legacy/deep screens keep
/// their existing theme until their own polish slice adopts these tokens.
class FieldTheme {
  const FieldTheme._();

  static const double gutter = 20;
  static const double touchTarget = 48;
  static const double radius = 12;

  static ThemeData data({Brightness brightness = Brightness.light}) {
    final dark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF176454),
      brightness: brightness,
    ).copyWith(
      primary: dark ? const Color(0xFF8DD8C3) : const Color(0xFF145447),
      onPrimary: dark ? const Color(0xFF12372D) : Colors.white,
      surface: dark ? const Color(0xFF15201E) : const Color(0xFFF5F7F6),
      onSurface: dark ? const Color(0xFFE4EEE9) : const Color(0xFF192F2A),
      onSurfaceVariant: dark ? const Color(0xFFB9C9C2) : const Color(0xFF4D625A),
      outlineVariant: dark ? const Color(0xFF3F514A) : const Color(0xFFD2DED7),
    );
    final base = ThemeData(
      useMaterial3: true,
      colorScheme: scheme,
      scaffoldBackgroundColor: scheme.surface,
      visualDensity: VisualDensity.standard,
      materialTapTargetSize: MaterialTapTargetSize.padded,
    );
    return base.copyWith(
      textTheme: base.textTheme.copyWith(
        headlineSmall: base.textTheme.headlineSmall?.copyWith(
          fontSize: 24, fontWeight: FontWeight.w700, height: 1.4,
        ),
        titleLarge: base.textTheme.titleLarge?.copyWith(
          fontSize: 20, fontWeight: FontWeight.w700, height: 1.4,
        ),
        titleMedium: base.textTheme.titleMedium?.copyWith(
          fontSize: 16, fontWeight: FontWeight.w600, height: 1.4,
        ),
        bodyLarge: base.textTheme.bodyLarge?.copyWith(fontSize: 16, height: 1.5),
        bodyMedium: base.textTheme.bodyMedium?.copyWith(fontSize: 14, height: 1.5),
        labelLarge: base.textTheme.labelLarge?.copyWith(
          fontSize: 14, fontWeight: FontWeight.w700, letterSpacing: 0,
        ),
      ),
      appBarTheme: AppBarTheme(
        backgroundColor: scheme.surface,
        foregroundColor: scheme.onSurface,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
      ),
      dividerTheme: DividerThemeData(color: scheme.outlineVariant, thickness: 1),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          minimumSize: const Size(touchTarget, touchTarget),
          elevation: 0,
          backgroundColor: scheme.primary,
          foregroundColor: scheme.onPrimary,
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radius)),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          minimumSize: const Size(touchTarget, touchTarget),
          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radius)),
        ),
      ),
      textButtonTheme: TextButtonThemeData(
        style: TextButton.styleFrom(minimumSize: const Size(touchTarget, touchTarget)),
      ),
      iconButtonTheme: IconButtonThemeData(
        style: IconButton.styleFrom(minimumSize: const Size(touchTarget, touchTarget)),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: scheme.inverseSurface,
        contentTextStyle: TextStyle(color: scheme.onInverseSurface, fontSize: 16),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(radius)),
      ),
    );
  }
}
