import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import 'package:sentry_flutter/sentry_flutter.dart';

import 'app_error_strings.dart';

class AppErrorHandlers {
  const AppErrorHandlers._();

  static void install() {
    ErrorWidget.builder = _buildErrorWidget;
    FlutterError.onError = _onFlutterError;
    ui.PlatformDispatcher.instance.onError = (error, stack) {
      _onPlatformError(error, stack);
      return true;
    };
  }

  static Widget _buildErrorWidget(FlutterErrorDetails details) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      home: Scaffold(
        body: Center(
          child: Text(
            appErrorString(
              AppErrorStringKey.criticalSystemError,
              localeCode: 'ar',
            ),
            textAlign: TextAlign.center,
            textDirection: TextDirection.rtl,
          ),
        ),
      ),
    );
  }

  static void _onPlatformError(Object error, StackTrace stack) {
    debugPrint('═══════════════ PLATFORM ASYNC CRASH ═══════════════');
    debugPrint('ERROR: $error');
    debugPrint('STACK: $stack');
    debugPrint('═══════════════════════════════════════════════════');
    Sentry.captureException(error, stackTrace: stack);
  }

  static void _onFlutterError(FlutterErrorDetails details) {
    debugPrint('═══════════════ FLUTTER FRAMEWORK CRASH ═══════════════');
    debugPrint('EXCEPTION: ${details.exception}');
    debugPrint('STACK: ${details.stack}');
    if (details.library != null) {
      debugPrint('LIBRARY: ${details.library}');
    }
    debugPrint('════════════════════════════════════════════════════════');
    Sentry.captureException(
      details.exception,
      stackTrace: details.stack,
    );
    if (kDebugMode) {
      FlutterError.presentError(details);
    }
  }
}
