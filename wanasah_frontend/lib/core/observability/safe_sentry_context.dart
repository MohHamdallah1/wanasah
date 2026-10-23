import '../network/api_failure.dart';

enum ObservabilityOperation {
  flutterFramework,
  platformAsync,
  authLogin,
  workSession,
  visitField,
  shopCreate,
  recoverySync,
  localPersistence,
}

enum ObservabilityFailureKind {
  crash,
  connectivity,
  timeout,
  authorization,
  businessRejection,
  server,
  localPersistence,
  recovery,
  unexpected,
}

enum ObservabilityDurableState {
  pending,
  inFlight,
  blocked,
}

class SafeSentryMetadata {
  const SafeSentryMetadata({
    required this.operation,
    required this.failureKind,
    this.code,
    this.status,
    this.requestId,
    this.durableState,
  });

  final ObservabilityOperation operation;
  final ObservabilityFailureKind failureKind;
  final String? code;
  final int? status;
  final String? requestId;
  final ObservabilityDurableState? durableState;

  static const allowedTagKeys = <String>{
    'wanasah.operation',
    'wanasah.failure_kind',
    'wanasah.failure_code',
    'wanasah.http_status',
    'wanasah.request_id',
    'wanasah.durable_state',
  };

  factory SafeSentryMetadata.uncaught(ObservabilityOperation operation) {
    return SafeSentryMetadata(
      operation: operation,
      failureKind: ObservabilityFailureKind.crash,
    );
  }

  factory SafeSentryMetadata.fromApiFailure({
    required ObservabilityOperation operation,
    required ApiFailure failure,
  }) {
    final status = failure.status;
    final kind = switch (failure.kind) {
      ApiFailureKind.connection => ObservabilityFailureKind.connectivity,
      ApiFailureKind.timeout => ObservabilityFailureKind.timeout,
      ApiFailureKind.cancelled => ObservabilityFailureKind.unexpected,
      ApiFailureKind.unknown => ObservabilityFailureKind.unexpected,
      ApiFailureKind.serverResponse when status == 401 || status == 403 =>
        ObservabilityFailureKind.authorization,
      ApiFailureKind.serverResponse
          when status != null && status >= 400 && status < 500 =>
        ObservabilityFailureKind.businessRejection,
      ApiFailureKind.serverResponse when status != null && status >= 500 =>
        ObservabilityFailureKind.server,
      ApiFailureKind.serverResponse => ObservabilityFailureKind.unexpected,
    };

    return SafeSentryMetadata(
      operation: operation,
      failureKind: kind,
      code: _safeIdentifier(failure.code),
      status: status,
      requestId: _safeIdentifier(failure.requestId),
    );
  }

  bool get shouldCapture =>
      failureKind == ObservabilityFailureKind.crash ||
      failureKind == ObservabilityFailureKind.server ||
      failureKind == ObservabilityFailureKind.localPersistence ||
      failureKind == ObservabilityFailureKind.recovery ||
      failureKind == ObservabilityFailureKind.unexpected;

  Map<String, String> toTags() {
    final tags = <String, String>{
      'wanasah.operation': operation.name,
      'wanasah.failure_kind': failureKind.name,
    };

    final normalizedCode = _safeIdentifier(code);
    if (normalizedCode != null) {
      tags['wanasah.failure_code'] = normalizedCode;
    }

    if (status != null) {
      tags['wanasah.http_status'] = status.toString();
    }

    final normalizedRequestId = _safeIdentifier(requestId);
    if (normalizedRequestId != null) {
      tags['wanasah.request_id'] = normalizedRequestId;
    }

    if (durableState != null) {
      tags['wanasah.durable_state'] = durableState!.name;
    }

    return Map<String, String>.unmodifiable(tags);
  }

  static String? _safeIdentifier(String? value) {
    final trimmed = value?.trim();
    if (trimmed == null || trimmed.isEmpty || trimmed.length > 128) {
      return null;
    }

    if (!RegExp(r'^[A-Za-z0-9._:-]+$').hasMatch(trimmed)) {
      return null;
    }
    return trimmed;
  }
}
