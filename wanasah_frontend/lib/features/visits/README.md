# Visits FIELD contracts

Backend contract: d2498f46aeba050f5d6cb43ca6d0d568fb39e585.
Functional acceptance baseline: 3ebc5d9eec54c8f98d33265a6976d170c7c5ea15.

Import visit_field_contracts.dart and construct VisitFieldClient.withApiClient
with the existing authenticated ApiClient. This client owns only return
resolution, commercial readiness, invoice preview and frozen invoice reads.

- domain/returns owns human ReturnEvidence, ReturnAmbiguity and opaque signed
  FieldReturnResolution. Preserve token and original request quantities exactly.
  toVisitReturnJson produces one canonical return line for later durable visit
  wiring; the existing command UUID/body must remain stable on retry. No Batch
  locator, FEFO choice or offline token manufacture becomes client authority.
- Return ambiguity classification, including the returnAmbiguity exception
  extension, stays in domain/returns/return_ambiguity.dart. It reads the existing
  ApiFailure code/status/context; display text never determines business state.
- domain/commercial owns tax readiness. READY means tax setup only; preserve
  actionable Backoffice completion without guessing jurisdiction.
- domain/invoice owns exact money, preview requests/results and frozen/committed
  invoice evidence. Legacy missing invoice, explicit invoice:null and committed
  evidence remain distinct. No client calculation or price input is added.

The two genuinely shared technical dependencies are:
- core/serialization/json_contract.dart: JSON shape/decimal-text readers also
  used by Custody, with no domain decisions.
- core/errors/api_failure_exception.dart: an exception carrier for the existing
  ApiFailure, also used by Custody. It imports no feature and classifies no
  return ambiguity.

Dio failures preserve ApiFailure through ApiFailureException. Malformed success
payloads remain FormatException. No retries, queue, auth policy, screen/BLoC or
local database wiring is added. Labels/locale formatting belong to presentation.

Focused gate: flutter test test/features/visits
