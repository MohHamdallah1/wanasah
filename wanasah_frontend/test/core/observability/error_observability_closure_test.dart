// ignore_for_file: deprecated_member_use

import 'dart:io';

import 'package:dio/dio.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:sentry_flutter/sentry_flutter.dart';
import 'package:wanasah_frontend/core/network/api_failure.dart';
import 'package:wanasah_frontend/core/observability/safe_sentry_context.dart';
import 'package:wanasah_frontend/core/observability/sentry_privacy_policy.dart';
import 'package:wanasah_frontend/features/auth/application/auth_failure_policy.dart';
import 'package:wanasah_frontend/features/recovery/application/recovery_sync_coordinator.dart';
import 'package:wanasah_frontend/features/recovery/presentation/recovery_strings.dart';
import 'package:wanasah_frontend/features/shops/domain/shop_creation.dart';
import 'package:wanasah_frontend/features/shops/presentation/shop_creation_failure_message.dart';
import 'package:wanasah_frontend/features/visits/presentation/visit_field_failure.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_action_issue.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_failure.dart';
import 'package:wanasah_frontend/features/work_session/application/work_session_outcome.dart';

void main() {
  group('user-facing typed failure categories', () {
    test('connectivity and timeout remain distinct without message parsing', () {
      final request = RequestOptions(path: '/typed');

      final connectionApi = DioException(
        requestOptions: request,
        type: DioExceptionType.connectionError,
        message: 'timeout timeout انتهاء المهلة',
      ).apiFailure;
      final timeoutApi = DioException(
        requestOptions: request,
        type: DioExceptionType.receiveTimeout,
        message: 'connection refused اتصال',
      ).apiFailure;

      expect(connectionApi.kind, ApiFailureKind.connection);
      expect(timeoutApi.kind, ApiFailureKind.timeout);

      final authConnection = AuthLoginFailure.fromDioException(
        DioException(
          requestOptions: request,
          type: DioExceptionType.connectionError,
          message: 'timeout',
        ),
      );
      final authTimeout = AuthLoginFailure.fromDioException(
        DioException(
          requestOptions: request,
          type: DioExceptionType.receiveTimeout,
          message: 'connection',
        ),
      );

      expect(authConnection.kind, AuthLoginFailureKind.connectivity);
      expect(authTimeout.kind, AuthLoginFailureKind.timeout);

      expect(
        visitFailureCategory(connectionApi),
        VisitFailureCategory.connectivity,
      );
      expect(
        visitFailureCategory(timeoutApi),
        VisitFailureCategory.timeout,
      );
    });

    test('401/403 and deterministic 4xx remain distinct categories', () {
      final authFailure = _apiResponse(
        status: 401,
        code: 'AUTH_REQUIRED',
        message: 'business rejection translated text',
      );
      final businessFailure = _apiResponse(
        status: 409,
        code: 'VISIT_CONFLICT',
        message: 'session expired translated text',
      );

      expect(
        visitFailureCategory(authFailure),
        VisitFailureCategory.authorization,
      );
      expect(
        visitFailureCategory(businessFailure),
        VisitFailureCategory.business,
      );

      final metadata = SafeSentryMetadata.fromApiFailure(
        operation: ObservabilityOperation.visitField,
        failure: businessFailure,
      );
      expect(
        metadata.failureKind,
        ObservabilityFailureKind.businessRejection,
      );
      expect(metadata.shouldCapture, isFalse);
    });

    test('5xx remains temporary/server rather than connectivity', () {
      final failure = _apiResponse(
        status: 503,
        code: 'SERVICE_UNAVAILABLE',
        message: 'offline-looking display text',
      );

      expect(
        visitFailureCategory(failure),
        VisitFailureCategory.temporary,
      );

      final metadata = SafeSentryMetadata.fromApiFailure(
        operation: ObservabilityOperation.visitField,
        failure: failure,
      );
      expect(metadata.failureKind, ObservabilityFailureKind.server);
      expect(metadata.shouldCapture, isTrue);
    });

    test('Work Session exposes connectivity and timeout separately', () {
      const connectionResult = WorkSessionOperationResult(
        operation: WorkSessionOperation.start,
        disposition: WorkSessionDisposition.unresolved,
        failure: WorkSessionFailure(
          kind: WorkSessionFailureKind.connectivity,
          status: null,
          code: null,
          context: <String, dynamic>{},
          requestId: null,
          displayFallback: null,
        ),
      );
      const timeoutResult = WorkSessionOperationResult(
        operation: WorkSessionOperation.start,
        disposition: WorkSessionDisposition.unresolved,
        failure: WorkSessionFailure(
          kind: WorkSessionFailureKind.timeout,
          status: null,
          code: null,
          context: <String, dynamic>{},
          requestId: null,
          displayFallback: null,
        ),
      );

      expect(
        WorkSessionActionIssue.fromResult(connectionResult).kind,
        WorkSessionActionIssueKind.connectivity,
      );
      expect(
        WorkSessionActionIssue.fromResult(timeoutResult).kind,
        WorkSessionActionIssueKind.timeout,
      );
    });

    test('local recovery remains distinct from transport feedback', () {
      expect(
        recoveryString(
          RecoveryStringKey.syncRecoveryRequired,
          localeCode: 'ar',
        ),
        isNot(
          recoveryString(
            RecoveryStringKey.syncConnectivityUnresolved,
            localeCode: 'ar',
          ),
        ),
      );
      expect(
        recoveryString(
          RecoveryStringKey.syncTimedOut,
          localeCode: 'ar',
        ),
        isNot(
          recoveryString(
            RecoveryStringKey.syncRecoveryRequired,
            localeCode: 'ar',
          ),
        ),
      );

      expect(
        RecoverySyncExecution.timedOut,
        isNot(RecoverySyncExecution.transportAmbiguous),
      );
    });

    test('Shop presentation distinguishes typed failure states', () {
      const connection = ShopCreateFailure(
        kind: ShopCreateFailureKind.connectivity,
        ambiguous: true,
        status: null,
        code: null,
        context: <String, dynamic>{},
        requestId: null,
        displayFallback: 'timeout fake text',
      );
      const timeout = ShopCreateFailure(
        kind: ShopCreateFailureKind.timeout,
        ambiguous: true,
        status: null,
        code: null,
        context: <String, dynamic>{},
        requestId: null,
        displayFallback: 'connection fake text',
      );
      const authorization = ShopCreateFailure(
        kind: ShopCreateFailureKind.authorization,
        ambiguous: false,
        status: 403,
        code: 'HTTP_403',
        context: <String, dynamic>{},
        requestId: 'req-auth',
        displayFallback: 'business fake text',
      );
      const business = ShopCreateFailure(
        kind: ShopCreateFailureKind.businessRejected,
        ambiguous: false,
        status: 409,
        code: 'SHOP_CONFLICT',
        context: <String, dynamic>{},
        requestId: 'req-business',
        displayFallback: 'رفض تجاري واضح',
      );

      expect(
        shopCreationFailureMessage(connection),
        isNot(shopCreationFailureMessage(timeout)),
      );
      expect(
        shopCreationFailureMessage(authorization),
        isNot(shopCreationFailureMessage(business)),
      );
      expect(
        shopCreationFailureMessage(business),
        'رفض تجاري واضح',
      );
    });
  });

  group('safe Sentry metadata allowlist', () {
    test('only stable operation kind code status and request ID are exported', () {
      const failure = ApiFailure(
        kind: ApiFailureKind.serverResponse,
        status: 503,
        code: 'SERVICE_UNAVAILABLE',
        message: 'customer=Alice password=secret',
        context: <String, dynamic>{
          'Authorization': 'Bearer token-secret',
          'password': 'secret',
          'payload': <String, dynamic>{'shop': 'Customer Shop'},
          'latitude': 31.95,
          'longitude': 35.91,
          'driver_id': 42,
        },
        requestId: 'req-1234',
        displayFallback: 'phone=0790000000',
      );

      final metadata = SafeSentryMetadata.fromApiFailure(
        operation: ObservabilityOperation.visitField,
        failure: failure,
      );
      final tags = metadata.toTags();

      expect(
        tags,
        <String, String>{
          'wanasah.operation': 'visitField',
          'wanasah.failure_kind': 'server',
          'wanasah.failure_code': 'SERVICE_UNAVAILABLE',
          'wanasah.http_status': '503',
          'wanasah.request_id': 'req-1234',
        },
      );

      final serialized = tags.toString();
      expect(serialized, isNot(contains('Authorization')));
      expect(serialized, isNot(contains('token-secret')));
      expect(serialized, isNot(contains('password')));
      expect(serialized, isNot(contains('Customer Shop')));
      expect(serialized, isNot(contains('31.95')));
      expect(serialized, isNot(contains('35.91')));
      expect(serialized, isNot(contains('0790000000')));
      expect(serialized, isNot(contains('driver_id')));
    });

    test('unsafe code/request values are omitted instead of attached', () {
      const metadata = SafeSentryMetadata(
        operation: ObservabilityOperation.localPersistence,
        failureKind: ObservabilityFailureKind.localPersistence,
        code: 'password=secret token',
        requestId: 'customer@example.com',
        durableState: ObservabilityDurableState.blocked,
      );

      expect(
        metadata.toTags(),
        <String, String>{
          'wanasah.operation': 'localPersistence',
          'wanasah.failure_kind': 'localPersistence',
          'wanasah.durable_state': 'blocked',
        },
      );
    });

    test('expected auth/business failures are not captured as crashes', () {
      const auth = SafeSentryMetadata(
        operation: ObservabilityOperation.authLogin,
        failureKind: ObservabilityFailureKind.authorization,
        status: 401,
        code: 'AUTH_REQUIRED',
      );
      const business = SafeSentryMetadata(
        operation: ObservabilityOperation.shopCreate,
        failureKind: ObservabilityFailureKind.businessRejection,
        status: 409,
        code: 'SHOP_CONFLICT',
      );
      const server = SafeSentryMetadata(
        operation: ObservabilityOperation.recoverySync,
        failureKind: ObservabilityFailureKind.server,
        status: 503,
        code: 'SERVICE_UNAVAILABLE',
      );

      expect(auth.shouldCapture, isFalse);
      expect(business.shouldCapture, isFalse);
      expect(server.shouldCapture, isTrue);
    });
  });

  group('Sentry redaction policy', () {
    test('SDK collection settings are privacy-first', () {
      final options = SentryFlutterOptions();
      SentryPrivacyPolicy.configure(options);

      expect(options.sendDefaultPii, isFalse);
      expect(options.attachScreenshot, isFalse);
      expect(options.attachViewHierarchy, isFalse);
      expect(options.captureFailedRequests, isFalse);
      expect(options.captureNativeFailedRequests, isFalse);
      expect(options.recordHttpBreadcrumbs, isFalse);
      expect(options.enablePrintBreadcrumbs, isFalse);
      expect(options.enableUserInteractionBreadcrumbs, isFalse);
      expect(options.enableAutoNativeBreadcrumbs, isFalse);
      expect(options.enableLogs, isFalse);
      expect(options.beforeBreadcrumb, isNotNull);
      expect(options.beforeSend, isNotNull);
      expect(options.beforeSendTransaction, isNotNull);
    });

    test('sanitizer strips deliberately attached sensitive application data', () {
      final throwable = StateError(
        'Authorization: Bearer access-token password=1234 '
        'customer=Alice phone=0790000000 lat=31.95 lng=35.91',
      );

      final event = SentryEvent(
        tags: <String, String>{
          'wanasah.operation': 'shopCreate',
          'wanasah.failure_kind': 'server',
          'wanasah.failure_code': 'HTTP_500',
          'wanasah.http_status': '500',
          'wanasah.request_id': 'req-safe',
          'secret': 'Bearer token-secret',
        },
        extra: <String, dynamic>{
          'password': '1234',
          'payload': <String, dynamic>{'customer': 'Alice'},
          'coordinates': <double>[31.95, 35.91],
        },
        breadcrumbs: <Breadcrumb>[
          Breadcrumb(
            message: 'phone=0790000000',
            data: <String, dynamic>{
              'Authorization': 'Bearer token-secret',
            },
          ),
        ],
        user: SentryUser(
          id: 'driver-42',
          username: 'customer-name',
          email: 'customer@example.com',
          ipAddress: '127.0.0.1',
        ),
        request: SentryRequest(
          url: 'https://example.test/shops?customer=Alice',
          method: 'POST',
          data: <String, dynamic>{
            'password': '1234',
            'latitude': 31.95,
            'longitude': 35.91,
          },
          headers: <String, String>{
            'Authorization': 'Bearer token-secret',
          },
        ),
        transaction: '/shops/Alice',
        fingerprint: <String>['customer@example.com'],
        exceptions: <SentryException>[
          SentryException(
            type: 'StateError',
            value: throwable.toString(),
            throwable: throwable,
          ),
        ],
      );
      event.contexts['customer'] = <String, dynamic>{
        'name': 'Alice',
        'phone': '0790000000',
      };

      final sanitized = SentryPrivacyPolicy.sanitizeEvent(event);

      expect(sanitized.request, isNull);
      expect(sanitized.user, isNull);
      expect(sanitized.toJson()['extra'], anyOf(isNull, isEmpty));
      expect(sanitized.breadcrumbs, isEmpty);
      expect(sanitized.contexts, isEmpty);
      expect(sanitized.transaction, isNull);
      expect(sanitized.fingerprint, isNull);
      expect(
        sanitized.tags,
        <String, String>{
          'wanasah.operation': 'shopCreate',
          'wanasah.failure_kind': 'server',
          'wanasah.failure_code': 'HTTP_500',
          'wanasah.http_status': '500',
          'wanasah.request_id': 'req-safe',
        },
      );

      final exception = sanitized.exceptions!.single;
      expect(exception.type, 'StateError');
      expect(exception.value, '[redacted]');
      expect(exception.throwable, isNull);

      final json = sanitized.toJson().toString();
      for (final forbidden in <String>[
        'Bearer token-secret',
        'password',
        '1234',
        'Alice',
        '0790000000',
        '31.95',
        '35.91',
        'customer@example.com',
        'driver-42',
      ]) {
        expect(json, isNot(contains(forbidden)), reason: forbidden);
      }
    });

    test('sanitizer drops unsafe values even on allowlisted tag keys', () {
      final event = SentryEvent(
        tags: <String, String>{
          'wanasah.operation': 'visitField',
          'wanasah.request_id': 'customer@example.com',
          'wanasah.failure_code': 'PASSWORD SECRET',
        },
      );

      final sanitized = SentryPrivacyPolicy.sanitizeEvent(event);

      expect(
        sanitized.tags,
        <String, String>{
          'wanasah.operation': 'visitField',
        },
      );
    });

    test('observability boundary has no generic context/payload input', () async {
      final source = await File(
        'lib/core/observability/safe_sentry_context.dart',
      ).readAsString();
      final reporter = await File(
        'lib/core/observability/app_observability.dart',
      ).readAsString();

      expect(source, isNot(contains('failure.context')));
      expect(source, isNot(contains('displayFallback')));
      expect(source, isNot(contains('latitude')));
      expect(source, isNot(contains('longitude')));
      expect(source, isNot(contains('password')));
      expect(reporter, isNot(contains('setExtra')));
      expect(reporter, isNot(contains('setContexts')));
      expect(reporter, isNot(contains('addBreadcrumb')));
    });
  });
}

ApiFailure _apiResponse({
  required int status,
  required String code,
  required String message,
}) {
  final options = RequestOptions(path: '/typed');
  return DioException(
    requestOptions: options,
    type: DioExceptionType.badResponse,
    response: Response<dynamic>(
      requestOptions: options,
      statusCode: status,
      data: <String, dynamic>{
        'request_id': 'req-$status',
        'error': <String, dynamic>{
          'code': code,
          'message': message,
          'context': <String, dynamic>{
            'customer': 'never classify this',
          },
          'request_id': 'req-$status',
        },
      },
    ),
  ).apiFailure;
}
