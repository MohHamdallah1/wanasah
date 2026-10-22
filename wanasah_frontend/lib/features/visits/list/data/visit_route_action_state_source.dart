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

/// Transitional V1 seam.
///
/// Dashboard/Work Session currently persists these two compatibility flags.
/// Missing or malformed values are intentionally handled fail-closed by the
/// application gate. This source is not an authorization authority.
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
