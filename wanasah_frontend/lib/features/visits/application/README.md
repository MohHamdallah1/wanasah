# Visit FIELD application

Base and accepted adapters: e9f42b32ea9f02d8a37eca8b590da1df49e71b0e.
This layer adds read orchestration above those adapters without changing them.

Use-cases:
- returns/ReturnResolutionCoordinator.resolve(visitId, request): requests one
  Backend resolution from the existing business ReturnResolutionRequest.
  Carton/base-pack quantities remain the Backend's current mobile UOM contract;
  the application does not calculate conversions or accept technical Batch IDs.
- ReturnResolutionCoordinator.submitEvidence(pending, discriminator): requires
  exactly the human evidence fields requested by the typed Backend ambiguity.
  It preserves the pending visit/product/quantities/return type and earlier evidence,
  then obtains a fresh canonical response. It never selects a candidate, infers
  identity or silently retries. A further ambiguity remains explicit.
- invoice/PreviewVisitInvoice.execute(visitId, request): returns authoritative
  preview evidence with commitRequired intact. No arithmetic or price inputs.
- invoice/ReadCommittedVisitInvoice.execute(visitId): returns the frozen read
  result; explicit non-sale/null remains separate from committed evidence.
- commercial/ReadCommercialReadiness.execute(visitId): returns CommercialReady
  or CommercialActionRequired from canonical state only. taxSetupReady covers
  this prerequisite, not stock/credit/authorization or final sale acceptance.
  It stays false for failures and malformed responses.

Each coordinator has a typed callable dependency matching one existing data
operation and a fromClient factory for VisitFieldClient. Tests can inject that
narrow port without widgets, BLoC or persistence. No service locator or combined
Visit application mega-client is introduced.

Each capability owns its explicit sealed outcomes. ApiFailureException is
unwrapped to the SAME ApiFailure object, preserving kind/status/code/context/
requestId. No localized message text drives decisions. Human return prompts
use only ReturnAmbiguity's whitelisted business evidence, never raw failure
context. Unknown/malformed ambiguity stays an ordinary structured refusal.

Malformed success payloads become a capability-specific InvalidResponse outcome:
there is no authoritative ApiFailure for that case, so no Backend code/context/
requestId is fabricated. Invalid local follow-up evidence similarly remains a
separate ReturnEvidenceNotAccepted result with a typed issue. Unexpected
programming errors are not relabeled as business rejections.

Resolved values, tokens, money strings, currency, rounding, tax and timestamps
pass through untouched. No submission body, durable command, SQLite state,
screen, BLoC, Auth, Custody, Shops or Backend workflow is wired in this slice.
The presentation layer will own translations and locale formatting.

Validation uses the existing FIELD workflow:
- flutter analyze
- flutter test test/features/visits (new application plus accepted adapters)
- flutter test test/offline_owner_guard_test.dart test/offline_durable_command_test.dart

The application boundary test permits only own feature domain/data/application
imports and existing structured failure types. It rejects Flutter/BLoC,
database/sync, peer-feature imports, raw Batch fields and float conversions.
