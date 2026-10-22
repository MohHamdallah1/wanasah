import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'app_theme.dart';
import 'app_tokens.dart';

class AppSystemUi extends StatelessWidget {
  const AppSystemUi({
    required this.child,
    super.key,
  });

  final Widget child;

  static const SystemUiOverlayStyle overlayStyle =
      SystemUiOverlayStyle(
        statusBarColor: Colors.transparent,
        statusBarIconBrightness: Brightness.dark,
        systemNavigationBarColor: Colors.white,
        systemNavigationBarIconBrightness: Brightness.dark,
        systemNavigationBarDividerColor: Colors.transparent,
      );

  @override
  Widget build(BuildContext context) {
    return AnnotatedRegion<SystemUiOverlayStyle>(
      value: overlayStyle,
      child: SafeArea(
        top: false,
        bottom: true,
        child: Material(
          color: AppTokens.systemSurface,
          child: Stack(
            children: [
              const Positioned.fill(
                child: DecoratedBox(
                  decoration: BoxDecoration(
                    gradient: AppTheme.backgroundGradient,
                  ),
                ),
              ),
              child,
            ],
          ),
        ),
      ),
    );
  }
}
