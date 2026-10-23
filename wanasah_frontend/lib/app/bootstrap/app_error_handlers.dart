import 'dart:async';
import 'dart:ui' as ui;

import 'package:flutter/foundation.dart';
import 'package:flutter/material.dart';
import '../../core/observability/app_observability.dart';
import '../../core/observability/safe_sentry_context.dart';
import 'app_error_strings.dart';

class AppErrorHandlers {
  const AppErrorHandlers._();

  static AppExceptionReporter _reporter = AppObservability.captureException;

  static void install({AppExceptionReporter? reporter}) {
    _reporter = reporter ?? AppObservability.captureException;
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
    unawaited(
      _reporter(
        error,
        stack,
        SafeSentryMetadata.uncaught(
          ObservabilityOperation.platformAsync,
        ),
      ),
    );
  }

  static void _onFlutterError(FlutterErrorDetails details) {
    debugPrint('═══════════════ FLUTTER FRAMEWORK CRASH ═══════════════');
    debugPrint('EXCEPTION: ${details.exception}');
    debugPrint('STACK: ${details.stack}');
    if (details.library != null) {
      debugPrint('LIBRARY: ${details.library}');
    }
    debugPrint('════════════════════════════════════════════════════════');
    unawaited(
      _reporter(
        details.exception,
        details.stack,
        SafeSentryMetadata.uncaught(
          ObservabilityOperation.flutterFramework,
        ),
      ),
    );
    if (kDebugMode) {
      FlutterError.presentError(details);
    }
  }
}
