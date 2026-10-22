import 'package:flutter_secure_storage/flutter_secure_storage.dart';

class VisitRouteCompatibilityState {
  const VisitRouteCompatibilityState({
    required this.isOnBreak,
    required this.isAuthorized,
  });

  final String? isOnBreak;
  final String? isAuthorized;
}

abstract interface class VisitRouteActionStateSource {
  Future<VisitRouteCompatibilityState> readCompatibilityState();
}

/// Historical last-known compatibility evidence only.
///
/// Retained for compatibility; Visit screens and route navigation no longer
/// consume this source. Missing/malformed values or read errors cannot decide
/// whether a Visit or Shop form opens or whether a mutation is authorized.
/// Dashboard/Work Session owns any writes; Backend owns current eligibility.
class SecureStorageVisitRouteActionStateSource
    implements VisitRouteActionStateSource {
  SecureStorageVisitRouteActionStateSource({
    FlutterSecureStorage storage = const FlutterSecureStorage(),
  }) : _storage = storage;

  final FlutterSecureStorage _storage;

  @override
  Future<VisitRouteCompatibilityState> readCompatibilityState() async {
    final values = await Future.wait<String?>([
      _storage.read(key: 'is_on_break'),
      _storage.read(key: 'is_authorized'),
    ]);

    return VisitRouteCompatibilityState(
      isOnBreak: values[0],
      isAuthorized: values[1],
    );
  }
}
