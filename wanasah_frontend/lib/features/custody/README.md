# Non-sellable custody contracts

Backend contract: d2498f46aeba050f5d6cb43ca6d0d568fb39e585.
Functional acceptance baseline: 3ebc5d9eec54c8f98d33265a6976d170c7c5ea15.

Import custody_contracts.dart and construct CustodyClient.withApiClient with the
existing authenticated ApiClient. Its only operation is the bounded
GET /driver/custody read; it has no Visits dependency or POST transport.

domain/non_sellable_custody.dart owns status/UOM codes, exact quantity strings
and opaque page cursors. Preserve all five non-sellable statuses and restart
pagination after mutation/reconciliation. Do not invent Batch identity or merge
this read into AVAILABLE stock or a local database projection.

The client reuses only technical core infrastructure: existing ApiClient and
ApiFailure, the ApiFailureException carrier, and JsonContract shape readers.
Return ambiguity classification belongs exclusively to Visits/Returns.

No retries, screen/BLoC, auth or persistence wiring is introduced. Display
labels and locale formatting remain presentation responsibilities.

Focused gate: flutter test test/features/custody
