# FIELD seam client adapters

Frozen Backend contract: d2498f46aeba050f5d6cb43ca6d0d568fb39e585.
Client base: 6e6c488a1858f033029acbb184d283511c794f1f.

Import field_contracts.dart. Construct FieldSeamsClient.withApiClient with the
existing authenticated ApiClient. The adapter does not initialize credentials,
change Network retry policy, queue work, or update a local projection.

- resolveReturn sends the read-only POST /visits/{id}/return-resolution.
  FieldReturnResolution retains the exact original request and opaque token.
  toVisitReturnJson emits one canonical resolved return line for the future
  visit serializer integration. Keep that whole line and its existing durable
  visit UUID/body stable across retry. Never decode/display the token as Batch
  identity, infer FEFO, or manufacture a token when offline.
- FieldSeamFailure carries the existing ApiFailure unchanged. code, context and
  requestId preserve Network authority; returnAmbiguity maps only the exact
  FIELD_RETURN_EVIDENCE_REQUIRED refusal to supported human evidence fields.
  Unsupported/malformed evidence stays a failure, never a technical input.
- commercialState reads GET /visits/{id}/commercial-state. The readiness model
  also parses the commercial_readiness object in POST /shops responses.
  READY covers tax setup only, not final sale authorization. Preserve the
  server's requiredAction; Flutter never chooses a tax jurisdiction.
- previewInvoice sends only sold product quantities to the existing read-only
  POST preview. Invoice money and reward quantities remain exact strings.
  commitRequired remains true; no client calculation becomes acceptance.
- readInvoice consumes frozen COMMITTED evidence. fromVisitResult parses the
  invoice field of an existing visit mutation result without sending a write.
  legacyResponse means an old replay omitted evidence, none means explicit
  invoice:null, and available carries authoritative evidence. Do not treat
  missing old evidence as a confirmed non-sale.
- custody reads one bounded page from GET /driver/custody. Status/UOM codes are
  language-neutral. Keep quantity and cursor strings exact. Restart pagination
  after mutation/reconciliation; do not merge this into AVAILABLE or local DB
  projection in this slice.

Successful malformed payloads throw FormatException with a field diagnostic;
they are never mislabeled as a Backend business rejection with an invented
code or request ID. Dio failures throw FieldSeamFailure. Presentation must use
translation keys and locale-aware formatting; this layer defines no UI labels.

No screen, Bloc, persistence, auth, Network or Backend wiring is included.

Focused gate:
flutter test test/core/field
flutter analyze
