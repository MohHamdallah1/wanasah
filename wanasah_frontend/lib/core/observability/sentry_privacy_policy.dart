import 'package:sentry_flutter/sentry_flutter.dart';

import 'safe_sentry_context.dart';

class SentryPrivacyPolicy {
  const SentryPrivacyPolicy._();

  static void configure(SentryFlutterOptions options) {
    options.sendDefaultPii = false;
    options.attachScreenshot = false;
    options.attachViewHierarchy = false;
    options.captureFailedRequests = false;
    options.captureNativeFailedRequests = false;
    options.recordHttpBreadcrumbs = false;
    options.enablePrintBreadcrumbs = false;
    options.enableUserInteractionBreadcrumbs = false;
    options.enableAutoNativeBreadcrumbs = false;
    options.enableLogs = false;

    options.beforeBreadcrumb = (_, _) => null;
    options.beforeSend = (event, _) => sanitizeEvent(event);
  }

  static SentryEvent sanitizeEvent(SentryEvent event) {
    event.request = null;
    event.user = null;
    event.extra = <String, dynamic>{};
    event.breadcrumbs = <Breadcrumb>[];
    event.message = null;
    event.transaction = null;

    final safeTags = <String, String>{};
    for (final entry in (event.tags ?? const <String, String>{}).entries) {
      if (SafeSentryMetadata.allowedTagKeys.contains(entry.key) &&
          _isSafeTagValue(entry.value)) {
        safeTags[entry.key] = entry.value;
      }
    }
    event.tags = safeTags;

    event.contexts.clear();

    event.modules = null;
    event.logger = null;
    event.serverName = null;
    event.culprit = null;

    final exceptions = event.exceptions;
    if (exceptions != null) {
      for (final exception in exceptions) {
        exception.value = '[redacted]';
        exception.throwable = null;
      }
    }

    return event;
  }

  static bool _isSafeTagValue(String value) {
    if (value.isEmpty || value.length > 128) return false;
    return RegExp(r'^[A-Za-z0-9._:-]+
).hasMatch(value);
  }
}
