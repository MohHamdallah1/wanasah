import 'package:sentry_flutter/sentry_flutter.dart';

import 'safe_sentry_context.dart';

typedef AppExceptionReporter = Future<void> Function(
  Object error,
  StackTrace? stackTrace,
  SafeSentryMetadata metadata,
);

class AppObservability {
  const AppObservability._();

  static Future<void> captureException(
    Object error,
    StackTrace? stackTrace,
    SafeSentryMetadata metadata,
  ) async {
    if (!metadata.shouldCapture) return;

    await Sentry.captureException(
      error,
      stackTrace: stackTrace,
      withScope: (scope) async {
        for (final entry in metadata.toTags().entries) {
          await scope.setTag(entry.key, entry.value);
        }
      },
    );
  }
}
