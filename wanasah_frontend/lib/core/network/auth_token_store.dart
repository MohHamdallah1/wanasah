import 'dart:async';
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


Future<void> _credentialWriteTail = Future<void>.value();

/// Serialize the existing credential keys with login metadata replacement.
Future<T> withAuthCredentialWrite<T>(Future<T> Function() write) async {
  final previous = _credentialWriteTail;
  final done = Completer<void>();
  _credentialWriteTail = done.future;
  try {
    await previous;
    return await write();
  } finally {
    done.complete();
  }
}

extension AuthTokenReplacementBinding on AuthTokenStore {
  Future<bool> persistReplacementIfCurrent({
    required String expectedRefreshToken,
    required String accessToken,
    required String refreshToken,
  }) => withAuthCredentialWrite(() async {
    if (await readRefreshToken() != expectedRefreshToken) return false;
    await persistReplacement(accessToken: accessToken, refreshToken: refreshToken);
    return true;
  });

  Future<bool> clearIfCurrent(String expectedRefreshToken) =>
      withAuthCredentialWrite(() async {
        if (await readRefreshToken() != expectedRefreshToken) return false;
        await clear();
        return true;
      });
}
