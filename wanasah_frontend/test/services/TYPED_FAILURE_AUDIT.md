# Typed location and free-text failure audit

Exact audited base: 896963ffc04711acf5a518514576896531a86426.
All 150 Dart files under lib were read from that immutable GitHub tree.
Frozen V1 workflow: field location capture, Shop creation feedback, and preserving
a legacy transfer refusal without changing canonical Custody decision ownership.

## Findings and disposition

| Finding | Disposition |
| --- | --- |
| services/location_service.dart: generic GPS exceptions, fake-GPS toString().contains, wrapping arbitrary text | Fixed: typed LocationFailure; only Position.isMocked marks a mocked position, with explicit platform exception mapping. |
| screens/add_shop_screen.dart: five errStr.contains GPS branches | Fixed: kind-to-translation mapping in Shop presentation, with unexpected typed fallback. |
| repositories/sync_repository.dart respondToTransfer deterministic 4xx | Fixed: original DioException rethrown, preserving status/code/context/request ID and stack. |
| core/db/local_database.dart duplicate-column migration string check | Excluded: low-level schema compatibility, owned by persistence worker. Not modified and not claimed closed. |
| core/db/local_database.dart generic missing-tenant exception | Excluded owner; guard checks actual tenant presence, not exception text. |
| screens/dashboard_screen.dart actionSuccessMessage.contains cleanup emoji | Display-only SnackBar color, no business/retry/authorization decision. Preserved. |
| features/visits/presentation/visit_catalog.dart name.contains and sample reason list.contains | Catalog search / dropdown selection only. Preserved. |
| Visit action policy NUL/input/code membership checks; return evidence membership | Canonical input/code checks, not error-text classification. Preserved. |
| Add Shop locationText.startsWith('Lat:') and Visit map URL prefixes | Input representation / safe URL handling, not failure parsing. Preserved per task. |
| core/network/api_failure.dart message/displayFallback and repository display-error extraction | Display/diagnostics only; stable status/code drive decisions. Preserved. |
| Auth/Visit/Dashboard states and screens displaying message/toString | Display/log evidence only; no error-text machine decision found. Preserved. |
| core/sync/sync_reconciliation_failure.dart error.toString() | Diagnostic fallback after DatabaseException type classification; not parsed. Preserved. |
| core/sync durable type prefixes, Work Session VEHICLE_CUSTODY_ code prefix | Stable language-neutral protocol identifiers, not arbitrary failure text. Preserved. |
| app/bootstrap/app_environment.dart and services/api_constants.dart startup exceptions | Configuration guards; no text-based recovery/business classification. Preserved. |

No other exception-message substring, regex, equality or prefix business
classification was identified in the audited lib tree. This does not claim the
excluded SQLite migration check is resolved.

## Location contract

services/location_failure.dart is adjacent to the existing cross-feature device
service used by Shops and Work Session. It contains only device failure evidence,
not business authority, permissions cache or domain policy.

Kinds and stable codes:
- serviceDisabled / GPS_DISABLED
- permissionDenied / GPS_DENIED
- permissionDeniedForever / GPS_DENIED_FOREVER
- timeout / GPS_TIMEOUT
- mockedLocation / FAKE_GPS_DETECTED
- unexpected / GPS_UNEXPECTED

A typed LocationFailure is rethrown unchanged. TimeoutException,
LocationServiceDisabledException and PermissionDeniedException map explicitly,
including failures during initial service/permission checks. Unknown errors keep
their original object and stack locally, but expose only GPS_UNEXPECTED through
toString. Arbitrary StateError('FAKE_GPS_DETECTED') remains unexpected.

Existing order is preserved: service enabled; permission/request; last-known
position; mocked check; less-than-60-second cache; fresh high-accuracy lookup with
eight-second timeout; mocked check. Work Session retains its accepted optional
best-effort coordinates behavior. No new Backend/session authority added.

## Legacy transfer compatibility

Runtime audit found respondToTransfer defined only in SyncRepository, with no
current production caller. CustodyTransferGateway/TransferDecisionStore remain
the canonical production decision path and are unchanged.

Only the deterministic 400..499 branch excluding 408/429 changes: original
DioException is rethrown instead of replaced with a generic Arabic Exception.
It cannot fall into offline success. Connection/timeout/408/429/5xx and generic
unknown compatibility fallback retain the existing single queue/write path.
Response/reason, owner, context, command identity and removal order are unchanged.

The CI-only legacy test harness copies the exact method body from checked-out
production source and substitutes external dependencies only. It does not
reimplement the method or add a production dispatch/replay path. Owner/persistence
internals are covered by their existing regressions, not claimed tested by fakes.

## Sentry audit

app/bootstrap/app_error_handlers.dart captures uncaught exception + stack in
platform/framework handlers. app_bootstrap.dart initializes the DSN and trace
sample rate. No per-operation allowlisted typed context is currently added there.
A broader Sentry context/redaction review remains separate; no Sentry edits,
headers, tokens, payloads, coordinates or customer data were added by this wave.
The touched location diagnostic logs only the stable failure code.

## Ownership / validation

No LocalDatabase, local projection/persistence, Auth, Custody production,
TransferDecisionStore, Work Session, Backend, Dashboard web, design system/theme,
Sentry or closure-plan edits. Add Shop changes only GPS feedback selection;
coordinates/link validation, creation service/UUID/retry/readiness and accepted
route authority remain unchanged. No UI/UX visual redesign.

The dedicated exact-head GitHub workflow runs analyze; typed location and Shop
feedback tests; source-extracted legacy method tests; Shop reconciliation;
Visit route/List; Session; Offline owner/durable/correction; Transfer handshake;
Sync Recovery regressions and owned exception-text boundary checks.
