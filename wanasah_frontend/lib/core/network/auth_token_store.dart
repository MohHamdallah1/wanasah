import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract interface class AuthTokenStore {
  Future<String?> readAccessToken();

  Future<String?> readRefreshToken();

  Future<void> persistReplacement({
    required String accessToken,
    required String refreshToken,
  });

  Future<void> clear();
}

class SecureAuthTokenStore implements AuthTokenStore {
  SecureAuthTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  @override
  Future<String?> readAccessToken() {
    return _storage.read(key: 'auth_token');
  }

  @override
  Future<String?> readRefreshToken() {
    return _storage.read(key: 'refresh_token');
  }

  @override
  Future<void> persistReplacement({
    required String accessToken,
    required String refreshToken,
  }) async {
    // The storage plugin has no multi-key transaction. Persist the successor
    // refresh credential first so an interruption between writes remains
    // recoverable by another refresh instead of stranding a new access token
    // beside an already-rotated predecessor refresh token.
    await _storage.write(
      key: 'refresh_token',
      value: refreshToken,
    );
    await _storage.write(
      key: 'auth_token',
      value: accessToken,
    );
  }

  @override
  Future<void> clear() async {
    await _storage.delete(key: 'auth_token');
    await _storage.delete(key: 'refresh_token');
  }
}
