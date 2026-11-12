import 'package:flutter_secure_storage/flutter_secure_storage.dart';

import '../../../core/network/api_client.dart';
import '../../auth/data/secure_auth_identity_store.dart';
import '../../work_session/data/field_execution_reader.dart';
import '../../work_session/data/signed_field_execution_authority.dart';

/// The Visit/offline feature owns secured cache persistence, not WorkSession
/// authorization. Server response remains the only source of current truth.
SignedFieldExecutionAuthority signedVisitExecutionAuthority(ApiClient client) {
  const storage = FlutterSecureStorage();
  final identities = SecureAuthIdentityStore();
  return SignedFieldExecutionAuthority(
    readRemote: FieldExecutionReader.withApiClient(client).read,
    ownerKey: () async {
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
