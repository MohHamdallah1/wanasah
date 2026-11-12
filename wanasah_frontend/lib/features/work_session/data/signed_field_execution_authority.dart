import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../../core/network/api_client.dart';
import '../../auth/data/secure_auth_identity_store.dart';
import 'execution_context.dart';
import 'field_execution_reader.dart';

typedef ReadCurrentSignedExecution = Future<ExecutionContextProof?> Function();
typedef ReadExecutionOwnerKey = Future<String> Function();
typedef ReadSavedExecution = Future<String?> Function(String key);
typedef WriteSavedExecution = Future<void> Function(String key, String value);
typedef DeleteSavedExecution = Future<void> Function(String key);

/// Trusted signed period storage for offline FIELD commands. The server,
/// NEVER this cache, determines current route/vehicle authority on replay.
///
/// An offline capture retains the last proof as-is. A remote M02 A->B->A
/// change may make that proof stale: never patch a queued Visit to the new
/// period. The backend's period+revision+epoch CAS rejects that original
/// command with 409, preserving its durable UUID and unresolved evidence.
class SignedFieldExecutionAuthority {
  SignedFieldExecutionAuthority({
    required ReadCurrentSignedExecution readRemote,
    required ReadExecutionOwnerKey ownerKey,
    required ReadSavedExecution readSaved,
    required WriteSavedExecution writeSaved,
    required DeleteSavedExecution deleteSaved,
  }) : _remote = readRemote,
       _ownerKey = ownerKey,
       _readSaved = readSaved,
       _writeSaved = writeSaved,
       _deleteSaved = deleteSaved;

  factory SignedFieldExecutionAuthority.withApiClient(ApiClient client) {
    const storage = FlutterSecureStorage();
    final identities = SecureAuthIdentityStore();
    return SignedFieldExecutionAuthority(
      readRemote: FieldExecutionReader.withApiClient(client).read,
      ownerKey: () async {
        // Revalidate the complete canonical FIELD login on EVERY read/write.
        // Company code or an old legacy driver key ALONE never authorizes data.
        final identity = await identities.read();
        if (identity == null) {
          throw StateError('M05_FIELD_AUTH_REQUIRED');
        }
        return '${identity.companyId}:${identity.principalId}:'
            '${identity.representativeId}:${identity.legacyDriverId}';
      },
      readSaved: (key) => storage.read(key: key),
      writeSaved: (key, value) => storage.write(key: key, value: value),
      deleteSaved: (key) => storage.delete(key: key),
    );
  }

  final ReadCurrentSignedExecution _remote;
  final ReadExecutionOwnerKey _ownerKey;
  final ReadSavedExecution _readSaved;
  final WriteSavedExecution _writeSaved;
  final DeleteSavedExecution _deleteSaved;

  String _key(String owner) => 'm05_signed_field_execution:$owner';

  Future<void> _remember(
    String owner, ExecutionContextProof? proof,
  ) async {
    if (await _ownerKey() != owner) {
      throw StateError('M05_FIELD_OWNER_CHANGED');
    }
    final key = _key(owner);
    if (proof == null) {
      await _deleteSaved(key); // Explicit server legacy/no-period state.
    } else {
      await _writeSaved(key, jsonEncode(proof.toJson()));
    }
  }

  /// Cache immediately after a successful canonical FIELD Start Work so the
  /// first offline Visit can freeze the actual new S2 period without a GET.
  /// Caller must invoke only AFTER HTTP 201; failures here cannot turn an
  /// already committed Start Work into a fake failed/second POST.
  Future<void> captureSuccessfulStart(Object? response) async {
    final owner = await _ownerKey();
    if (response is! Map || response['execution_context'] == null) {
      await _remember(owner, null); // Rev1 legacy is never guessed as M03.
      return;
    }
    await _remember(owner, ExecutionContextProof.fromResponse(response));
  }

  Future<ExecutionContextProof?> read() async {
    final owner = await _ownerKey();
    try {
      final proof = await _remote();
      await _remember(owner, proof);
      return proof; // null only for explicit server-confirmed legacy V1.
    } on DioException catch (error) {
      // No cached fallback on 401/403/409, server 5xx, or unrecognized errors.
      // An unavailable network may stage an original, potentially stale
      // immutable period to be verified on the server on eventual replay.
      if (error.response != null ||
          !const <DioExceptionType>{
            DioExceptionType.connectionError,
            DioExceptionType.connectionTimeout,
            DioExceptionType.sendTimeout,
            DioExceptionType.receiveTimeout,
          }.contains(error.type)) {
        rethrow;
      }
      final raw = await _readSaved(_key(owner));
      if (await _ownerKey() != owner) {
        throw StateError('M05_FIELD_OWNER_CHANGED');
      }
      if (raw == null) rethrow;
      final decoded = jsonDecode(raw);
      if (decoded is! Map) {
        throw const FormatException('Invalid saved FIELD period');
      }
      return ExecutionContextProof.fromJson(Map<String, dynamic>.from(decoded));
    }
  }
}
