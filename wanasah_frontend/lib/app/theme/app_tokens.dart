import 'package:flutter/material.dart';

class AppTokens {
  const AppTokens._();

  static const MaterialColor primarySwatch = Colors.teal;
  static const String fontFamily = 'Cairo';

  static const Color scaffoldSurface = Colors.transparent;
  static const Color canvasSurface = Colors.white;
  static const Color systemSurface = Colors.white;

  static const Color appBarBackground = Colors.transparent;
  static const Color appBarForeground = Colors.black87;
  static const double appBarElevation = 0;
  static const double appBarTitleSize = 18;

  static const Color backgroundGradientStart =
      Color.fromARGB(255, 194, 201, 173);
  static const Color backgroundGradientMiddle =
      Color.fromARGB(255, 117, 179, 97);
  static const Color backgroundGradientEnd =
      Color.fromARGB(255, 255, 255, 255);

  static const List<Color> backgroundGradientColors = <Color>[
    backgroundGradientStart,
    backgroundGradientMiddle,
    backgroundGradientEnd,
  ];

  static const List<double> backgroundGradientStops = <double>[
    0.0,
    0.3,
    0.8,
  ];
}
