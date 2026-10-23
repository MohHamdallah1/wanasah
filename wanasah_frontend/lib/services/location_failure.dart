/// Device-location evidence only; never business authorization authority.
enum LocationFailureKind {
  serviceDisabled,
  permissionDenied,
  permissionDeniedForever,
  timeout,
  mockedLocation,
  unexpected,
}

class LocationFailure implements Exception {
  const LocationFailure(this.kind, {this.cause, this.causeStackTrace});

  final LocationFailureKind kind;
  /// Retained locally for diagnostics. Not interpreted, rendered or sent as
  /// telemetry context by this contract.
  final Object? cause;
  final StackTrace? causeStackTrace;

  String get code => switch (kind) {
    LocationFailureKind.serviceDisabled => 'GPS_DISABLED',
    LocationFailureKind.permissionDenied => 'GPS_DENIED',
    LocationFailureKind.permissionDeniedForever => 'GPS_DENIED_FOREVER',
    LocationFailureKind.timeout => 'GPS_TIMEOUT',
    LocationFailureKind.mockedLocation => 'FAKE_GPS_DETECTED',
    LocationFailureKind.unexpected => 'GPS_UNEXPECTED',
  };

  @override
  String toString() => 'LocationFailure($code)';
}
