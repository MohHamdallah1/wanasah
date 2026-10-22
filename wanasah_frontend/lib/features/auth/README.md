# Canonical FIELD identity and durable ownership

Pinned Backend contract: main 0b06f17406222cc4c2e1e4160d32bcd478c23fb8.

Mounted /driver/login uses api/authentication/login_transport_routes.py and
FieldLoginTransportResponse, which extends the canonical FieldPrincipalLoginResponse.
The credential root principal_id, FIELD profile representative_id and company_id
are independent positive identifiers. channel is FIELD and principal_type is
FIELD_REPRESENTATIVE. They classify the credential/access channel; Backend
persisted capability/scope checks remain the only authorization authority.

The bounded transport also supplies legacy_driver_id and driver_id, with
driver_id explicitly copied from the mapped legacy Driver locator. Neither is
a principal or profile ID. Backend field_subject.py resolves that bridge using
company + principal + representative; Flutter never reconstructs it.

FieldPrincipalIdentity records these meanings explicitly. StoredAuthIdentity
pairs that metadata with access and refresh credentials. Login rejects missing
canonical fields, fractional/coerced IDs, channel/type mismatch or conflicting
legacy aliases. Input company codes, role/admin flags, display names/messages
and JWT decoding never repair missing identity.

SecureAuthIdentityStore persists one canonical metadata snapshot. Existing
auth_token / refresh_token remain the sole credential pair; token refresh
continues through SecureAuthTokenStore. Login invalidates the previous pair
before replacing metadata and writes the new refresh credential before access.
Refresh returns only token + refresh_token, with canonical principal/company/
channel revalidated server-side; the stored profile/bridge metadata remains
unchanged. Restart reads the snapshot and current pair and runs the owner guard.
Legacy-only storage requires a fresh canonical login; it is not guessed from a
JWT subject or silently upgraded.

Existing owner_driver_id columns retain their original operational Driver
locator meaning: the Backend-mapped legacy_driver_id, paired with
owner_company_code. The column is NOT reinterpreted as principal_id or
representative_id; old rows are never relabeled. This is a compatibility locator
for evidence, not legacy Driver authentication/authorization.

New Visit and Transfer call sites require the complete authenticated identity
and matching active DB tenant before passing ownerDriverId to existing DB
facades. PendingCommandStore rejects new replayable commands without a positive
owner ID and captures/checks the tenant around DB acquisition. The SQLite
schema and LocalDatabase are unchanged.

Login/restart/replay require each unresolved row to carry matching owner columns.
A matching secure marker never claims an unattributed legacy row. Blocked and
quarantined rows protect ownership. The original recovery evidence/body/UUID is
not rewritten to make attribution succeed. Replay checks ownership before
legacy UUID repair or dispatch. A live marker remains while unresolved rows
exist; stale marker cleanup still requires an empty inspected queue.

Confirmed refresh 401/403 may clear credentials and notify auth logout even if
pending work prevents cache cleanup. Connectivity, timeout, 5xx, malformed
success and unexpected refresh failure preserve the session/evidence. Last
canonical metadata remains available for logout owner-marker capture after
credentials are cleared; it cannot create a new command without tokens.

The identity closure does not change transfer decisions/exact replay, Visit
payload/commercial/return/invoice semantics or local projection.
