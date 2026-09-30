# D7-S independent mixed workload driver — Issue #38

Implementation only. D7-S remains OPEN. No acceptance run, real traffic, test,
database mutation, worker, migration, server, commit or deployment was performed
while implementing this tool. The owner performs independent review and acceptance.

The driver consists of two new standard-library modules under `wa_backend/scripts`.
Use Python 3.11 or newer for whole-request asyncio timeouts. They do not import the application, its configuration, SQLAlchemy, auth overrides,
D1/D7-L runners or worker runtime. Live mixed mode lazily imports HTTPX and Psycopg 3.
Copy only these modules, preserving the `scripts/` directory, to an independent
generator host; invoke from its parent with
`python -m scripts.staging_d7s_mixed_load`. Provision those client dependencies
independently of the application. This document does not authorize execution.

## Source-first contract and boundaries

The canonical architecture, .rules, AGENTS.md, workflow protection rule, root V1
plan D7-S, and release runbook govern this implementation. The main plan and
business code are unchanged.

| Workload | Actual HTTP / contract | Durable authority and driver behavior |
| --- | --- | --- |
| Sale / COGS | `PUT /visits/{visit_id}`, 200; `VisitUpdateRequest`: UUID `request_id`, `outcome=Sale`, canonical cart product IDs, carton/base-pack quantities and cash | `api/driver.py:update_visit` uses `DRIVER_UPDATE_VISIT` idempotency, driver-owned active authorized WorkSession, tenant/shop/visit locks, route commercial context, backend pricing, FEFO and financial cost engine. Commit precedes response. Response has a message/balance, not ledger IDs. Preserve the same UUID/body; reconcile actual frozen visit/item evidence and physical movements paired with COGS. Never send a price or select a batch. |
| Supplier inbound | `POST /warehouse/inbound`, 201; `UpgradedInboundRequest`: UUID, exact warehouse, items with product, purchase quantity, UOM, actual unit cost and batch number | `api/warehouse/inbound.py:warehouse_inbound` uses `WAREHOUSE_INBOUND`; exact location authorization, warehouse guards, immutable purchase input, cost policy and atomic ledger commit. Response is `INBOUND_POSTED`, not movement IDs. Driver creates deterministic references/batches and verifies purchase evidence and destination. |
| Route launch | `POST /dispatch/route`, 201; `DispatchRouteRequest`: zone, driver, vehicle, source warehouse and carton inventory targets; **no request UUID field** | `api/dispatch.py:dispatch_route`: driver/vehicle/zone/location guards, no active/unsettled session, reconciled vehicle custody, unique active route, FEFO transfer, immutable commercial lock. It also creates/reuses zone visits. Commit occurs before broadcast/response. Exactly one POST attempt; never replay on 429, timeout, crash or lost response. An attempted route without independently proven outcome blocks resumed traffic. A saved pristine baseline plus exclusive fixture tuple is required for reconciliation. |
| Product import | `POST /simple-products/imports`, 202; multipart UUID, file and explicit tracking defaults | `domains/simple_products/imports/api/router.py`, `application/api_service.py`, `queue.py:enqueue_new_import`: tenant/request uniqueness with actor, filename, size, SHA and tracking-default replay checks; SourceStore and queue admission are durable. 202 means admitted, not imported. Stable UTF-8 bytes, filename, defaults and UUID are reproduced for replay. Own-job GET polling and independent SQL must confirm terminal state, lineage, prices, ProductPublished audit/outbox pairs. |
| Catalog / status / isolation | `GET /simple-products?limit=10`; `GET /simple-products/imports/{job_id}`; foreign existing tenant job must return 404 | Catalog requires `catalog.read`; import submission also requires manage/publish/pricing permissions. Status is company scoped. Preflight checks each own job before foreign probes so a nonexistent fixture cannot fake isolation. No unpaginated company-wide route list is used. |

Additional source anchors:
- `api/dependencies.py:get_current_driver` verifies real HS256 access JWT signature,
  expiry, blacklist, active actor and tenant identity. `token_identity.py` requires
  language-neutral access identity. Local JWT parsing only checks fixture consistency;
  it is **not** signature verification. No login, refresh, locally minted token,
  authorization override or fake identity header is used.
- `database.py` / tenant RLS use `app.current_tenant`. The independent observer
  sets it transaction-locally, requires a non-superuser/non-BYPASSRLS role and
  FORCE RLS on every observed business table. It does not disable RLS.
- `main.py` applies the real 1000/minute IP limiter and the 10MiB body ceiling;
  middleware generates a new `X-Request-Id` per attempt. HTTP correlation IDs and
  stable business operation UUIDs are different evidence. `X-D7S-Run-Id` is a
  nonsecret collector tag only, never an identity or limiter bypass.
- `application/source_service.py` sets `started_at` on entering PARSING after
  source read/verification. `created_to_parsing_ms` includes both scheduling and
  source-read overhead; it must not be renamed exact worker claim/queue lag.
  Precise claim lag requires independent queue observation.
- `application/worker.py` parses, validates and automatically executes valid
  generated rows. The driver does not submit mapping/correction/cancellation
  mutations or start a worker.
- Inbound may lazily create a ProductLocation and a paired ProductLocationAssigned
  audit/outbox. Before/after assignment evidence is reconciled for the exact
  requested warehouse/variant pairs, including concurrent first receipt calls.
  Sale/Route do not have a universal ProductPublished-style outbox contract;
  the driver does not invent one.
- `models.py` and `product_lifecycle.py:record_domain_event` define frozen sale
  evidence v4, separate physical/cost ledgers and paired ProductPublished/outbox
  records. Import batch UUIDs derive from job + row identities, not the admission
  UUID. The observer pairs audit/outbox by their actual event request IDs.
- `scripts/product_import_d7_burst_child.py` uses ASGITransport and synthetic auth
  dependencies against disposable local data. Its 1000 arrivals and semaphore
  slots do not prove TLS ingress concurrency. Its fixture/bootstrap/worker helpers
  are deliberately not imported.
- Existing `scripts/staging_load_guard.py` and `locustfile.py` are GET-only,
  real-JWT tools; they remain unchanged. Neither proves the mixed D7-S gate.

No business workflow, costing/pricing authority, permissions, FEFO selection,
request hash, transaction boundary, SourceStore, cancellation or replay contract
is modified. Inbound profile restrictions are generator safety restrictions,
not changes to the API. A missing prerequisite is a blocker, never silently repaired.

## Operator configuration

All inputs come from explicitly named environment variables; no dotenv, developer
DATABASE_URL, secrets file, application settings, default fixture IDs or guessed
target. Secrets are excluded from representations/reports/journals. Server bodies,
error messages, catalog contents, raw import rows, names and connection exception
strings are not logged.

Required planning inputs:
- `WANASAH_D7S_URL` and `WANASAH_D7S_APPROVED_URL`: the same exact HTTPS origin.
  No path, query, credentials, redirect, loopback, link-local, .local/.localhost
  target. Live DNS/peer checks also reject local addresses. Private external
  staging addresses are permitted; independent isolation remains operator-owned.
- `WANASAH_D7S_CONFIG_JSON`: strict bounded JSON manifest below. Duplicate keys
  and nonfinite JSON fail closed.
- At live execution only, `WANASAH_D7S_ACK=I_ACK_EXTERNAL_ISOLATED_SYNTHETIC_STAGING`.
- At live mutation execution additionally,
  `WANASAH_D7S_MUTATIONS_ACK=I_ACK_BOUNDED_SYNTHETIC_MUTATIONS`.
- Per tenant key, `WANASAH_D7S_<KEY>_ADMIN_TOKEN` and
  `WANASAH_D7S_<KEY>_DRIVER_TOKEN`: distinct real access JWTs, exact company/actor
  identity, expiry beyond the full bounded run plus 120s. Never put them in CLI
  arguments, source, manifest, shell transcript or evidence files.
- At live mutations or readonly reconciliation, `WANASAH_D7S_READONLY_DSN` and
  `WANASAH_D7S_APPROVED_READONLY_DSN`: identical dedicated staging PostgreSQL
  URI, explicit matching database name, TLS `sslmode=verify-full`. Supply the
  observer role out of band with only necessary read grants; never grant superuser,
  BYPASSRLS or write privileges for this driver. The tool also enforces READ ONLY
  transactions. There is no fallback developer connection.

Manifest shape (placeholder values intentionally fail validation until the owner
replaces them with existing synthetic fixture IDs and approved facts):

```json
{
  "schema": 1,
  "run_id": "<fresh UUID; retain it on lost-response recovery>",
  "staging": {
    "isolated_synthetic": true,
    "generator_external": true,
    "fixtures_exclusive": true,
    "web_workers": 4,
    "release_sha": "<actual 40-character deployed git SHA>",
    "database_name": "<dedicated staging database>",
    "forbidden_origins": ["https://<development-host>", "https://<production-host>"]
  },
  "slo": {
    "read_p95_ms": "<approved integer>",
    "write_p95_ms": "<approved integer>",
    "write_p99_ms": "<approved integer>"
  },
  "tenants": [
    {"key": "A", "company_id": "<integer>", "admin_id": "<integer>",
     "driver_id": "<integer>", "status_job_id": "<existing own-job UUID>"},
    {"key": "B", "company_id": "<different integer>", "admin_id": "<integer>",
     "driver_id": "<integer>", "status_job_id": "<different existing own-job UUID>"}
  ],
  "limits": {},
  "operations": [
    {"key": "CATALOG_A", "tenant": "A", "kind": "catalog"},
    {"key": "STATUS_A", "tenant": "A", "kind": "owned_status"},
    {"key": "FOREIGN_A", "tenant": "A", "kind": "foreign_status"},
    {"key": "SALE_A", "tenant": "A", "kind": "sale",
     "fixture": {"visit_id": "<pending driver-owned visit integer>",
       "cash_collected": "<nonnegative decimal string, at most 3 places>",
       "cart_items": [{"product_variant_id": "<integer>", "quantity": 0,
                       "packs_quantity": "<positive integer>"}]},
     "expected": {"final_amount_due": "<known pinned-price/tax fixture value>",
                  "base_units": "<expected total stock exit including any bonuses>"}},
    {"key": "INBOUND_A", "tenant": "A", "kind": "inbound",
     "fixture": {"location_id": "<authorized warehouse integer>",
       "items": [{"product_variant_id": "<active integer>", "quantity": "<decimal string>",
                 "uom_id": "<that variant base UOM integer>", "unit_cost": "<actual cost string>"}]},
     "expected": {"base_units": "<sum of input base-unit quantities>"}},
    {"key": "ROUTE_A", "tenant": "A", "kind": "route",
     "fixture": {"zone_id": "<fresh synthetic zone integer>",
       "driver_id": "<different driver without active/unsettled session>",
       "vehicle_id": "<fresh reconciled vehicle integer>",
       "source_location_id": "<authorized warehouse integer>",
       "inventory": {"<active variant ID as canonical string>": "<positive carton integer>"}}},
    {"key": "IMPORT_A", "tenant": "A", "kind": "import",
     "fixture": {"rows": "<1..50000 integer>", "unit_price": "<positive decimal string>"}}
  ]
}
```

Use 2..8 distinct synthetic companies. Operation keys are unique uppercase identifiers;
tenant keys are uppercase identifiers. Expand a finite manifest to exactly 1000
submissions for that gate; bounded read operations can have separate keys while
each business mutation has its own explicitly supplied fresh fixture. Do not
repeat visits, route driver/vehicle/zone IDs or mutation identities to invent
business throughput. Give each company an appropriate mixed workload; actual
worker fairness still requires server/DB observation.

Generated CSV contains ten canonical neutral import headers, Arabic synthetic
names, explicit unit price, no outer package/barcodes, tracking NONE. It does not
claim coverage of XLSX parsing, localized header mapping, complex packaging or
arbitrary purchase-UOM conversions. Those profiles need separate real staging
acceptance evidence; extending backend behavior is outside this issue.

Supply existing active variants, authorized ordinary warehouses, appropriately
costed stock and an already explicitly selected/active costing policy. The
observer confirms IDs, active state, base-UOM inbound profile, scoped warehouse,
driver session authorization, fresh visits/requests/routes, initially empty route vehicle stock, RLS and quantity
bounds before any mutation. Route zones have bounded synthetic shop counts.
Server dependencies retain the final authority for vehicle custody, zone,
catalog manage/publish, purchase inputs and exact warehouse grants. Do not let
another generator/operator mutate these exclusive fixture sets during a run.

## Bounds and failure policy

| Resource | Default | Maximum accepted configuration |
| --- | ---: | ---: |
| Submission manifest | finite supplied operations | 1000 |
| HTTP attempts across workload/preflight/poll, including rejected/replayed attempts | 300 | 6000 |
| Submission/preflight duration | 60s | 300s |
| Additional import completion window | 120s | 600s |
| Whole HTTP attempt timeout (including streamed response) | 15s | 30s |
| Per operation attempts, retained across journal resume | 2 | 3; Route always 1 |
| HTTP / tenant concurrent in-flight requests | 16 / 8 | 1000 / 1000 |
| Endpoint concurrent requests | catalog 16, own/foreign status 4, Sale/Inbound 2, Route/Import 1 | 1000 each; Route fixed 1 |
| Arrival rate | 10/s | 1000/s; real IP limiter still applies |
| Import rows | 50000 cumulative | 100000 cumulative; 50000/job |
| Cumulative generated upload bytes | 20MiB | 64MiB |
| Single generated source | at most 9MiB UTF-8 | fixed; leaves multipart headroom below 10MiB ingress |
| Synthetic value budget (expected Sale + actual input receipts + imported rows × unit price) | 10000 | at most 100000000 explicit decimal |
| Expected physical quantity budget including route base-unit transfers | 100000 base units | at most 100000000 explicit decimal |
| Shops affected by one route zone | 50 | 200 |
| Import polling interval | 10s | 10..60s |
| Readonly tenant snapshot | 30s between bounded statements | 60s; last statement at most 5s, connection at most 5s |
| Raw authenticated connection profile | 100 connections held 10s | 1000, hold at most 60s within duration |
| Response / config / journal bytes | 1MiB / 2MiB / 8MiB | fixed |

A valid 50000-row generated source is supported when its **explicit aggregate
price/row/byte budget** fits. The tool never changes application admission budgets,
pool size, web/worker count or global settings. Configuring 1000 clients doesn't
alter connection facts.

429 honors the full numeric/date Retry-After; invalid/missing header waits the
actual global limiter's full 60s window. No truncated backoff, IP/header spoofing
or rate-limit bypass. If backoff exceeds the remaining budget, stop. Connection
mode stops admissions on its first 429. Rate rejections are counted, not erased.
4xx permission/validation, unexpected response/redirect, 5xx, transport ambiguity,
resource exhaustion, accounting mismatch and malformed success stop new traffic.
Already dispatched requests can still commit. No cancellations, deletes, reversal,
fixture cleanup, retry with a new UUID or destructive recovery is attempted.

Bounded async slots separate client admission wait from time awaiting HTTP.
A 1000-element operation list is a **planned** submission count; released
submissions, actual HTTP attempts, expected HTTP acknowledgments, durable queue
admissions and fully reconciled business completions are reported separately.
The report includes endpoint/tenant p50/p95/p99, errors/statuses, arrival lag and
client in-flight peak. Workload HTTP latency includes errors and rejections and
is not import completion latency. Baseline/preflight/poll attempts have separate
phases and consume the same HTTP budget. Completion time and the accurately
named created-to-parsing proxy come from server timestamps, not client clocks.

## Recovery and independent evidence

Default command performs static validation/planning only, with zero network,
journal creation or mutations:

```text
python -m scripts.staging_d7s_mixed_load
```

Only after owner authorization on independent isolated staging:
- live mixed writes require `--execute --allow-mutations --journal <private-local-path>`
  and both environment acknowledgments, exact targets, real JWTs, readonly DSN;
- read-only mixed mode requires `--execute` and contains only read operations;
- the separate raw HTTP/1.1 keepalive profile uses `--mode connections --execute`,
  a read-only manifest and no mutation opt-in; it opens real verified TLS sockets,
  separates budget reservations, socket write attempts, drained writes and actual
  HTTP response statuses; sends one authenticated catalog GET per socket, drains bounded responses and
  observes EOF/keepalive closure. HTTP/2 is disabled so streams cannot masquerade
  as separate connections.

For a 1000-connection attempt, concurrency, per-tenant allocation, catalog slots,
arrival rate, duration and request budget must explicitly accommodate all 1000.
The actual ingress may close idle sockets or throttle; record that result. Local
authenticated socket peaks **still do not prove** 1000 ingress connections.

Mixed mutation intent is appended and fsynced before every send; HTTP budget
reservations and acknowledged synthetic IDs are recorded without payloads/JWTs.
The journal is exclusively created and leased locally; an existing lease blocks
a second generator. Resume uses the same manifest/run UUID/fingerprint and
`--resume`. It preserves baseline evidence and attempt/request budgets; never
resubmit a confirmed mutation. Admitted imports resume only status observation.
A previous Route attempt with unknown outcome prevents any resumed workload.
Use `--mode reconcile --execute --journal <existing-private-journal>` with the
staging acknowledgment and approved readonly DSN to collect another bounded
snapshot without any HTTP or business mutation. This mode requires the saved
baseline, obtains the exclusive local lease, appends safe accounting evidence,
and does not require the mutation acknowledgment. It never retries a Route.
An incomplete/torn journal is an explicit review blocker. After force crash,
the operator must prove the previous generator is dead before removing its stale
**local lease**; the driver never does that automatically. Keep the journal on
durable private generator storage. Resume elapsed-time budgets are new bounded
observation windows; cumulative attempt budgets remain tied to the same journal.

Independent readonly SQL snapshots are before/after traffic, not high-frequency
load queries. They use tenant-scoped, ID/fixture-bounded SELECTs, 5s statement and
500ms lock timeout, local RLS, no locks, no business writes. Imported row
price/audit/outbox checks use batch aggregates, not HTTP/SQL queries per row.
They verify row-number/identity/product uniqueness, published base-UOM prices,
source clearing, immutable event pairs, conditional inbound assignment event pairs,
actual sale/COGS and inbound receipt
costs, route transfers without COGS, and physical/valuation conservation for
the touched variant set. A read role unable to see required records blocks;
lack of visibility is never interpreted as an empty successful run.

Optional `--ingress-evidence <collector-json>` reads a bounded **independently
collected** file. Its schema is:

```json
{
  "schema": 1,
  "run_id": "<same run UUID>",
  "origin": "https://<exact approved staging origin>",
  "metric": "active_authenticated_http1_connections",
  "includes_generator_only": true,
  "collector_external_to_generator": true,
  "samples": [
    {"at": "<timezone-aware ISO UTC timestamp>", "active_connections": 1000}
  ]
}
```

The collector must actually measure established authenticated connections at
TLS ingress, scoped to the generator/run tag, not requests, virtual users,
historical totals, DB sessions or HTTP/2 streams. Samples must be chronological
and inside the reported run window. The tool labels these as operator-supplied
evidence; file consistency is not proof of its authenticity. If collecting
after a run, independently compare the saved report/run window with the same
schema; never rerun mixed writes merely to attach evidence.

Gate output always stays OPEN for independent review. Missing independent
ingress/deployment/production-cardinality/CPU/memory/DB blocking and WorkSession
fairness/precise queue claim lag are explicit prerequisites or blockers. HTTP
cannot prove four deployed workers or production-like data. Reconciliation
failure cannot manufacture a PASS. Exit 2 means a blocker; exit 0 only means
bounded observations collected, not D7-S accepted. The report has no pass flag.

The focused owned test file specifies configuration guards, stable CSV/payload
identity, lost-response/journal behavior, Route non-replay, real Retry-After,
ACK-vs-commit and ingress proof separation. These tests were written and **not
executed**. HTTP TLS, SQL/RLS schema/grants, queue workers, real accounting,
1000 submissions/connections, hardware/cardinality/SLO and force-crash recovery
still require the owner's independent staging acceptance.

Client API references: [HTTPX async streaming](https://www.python-httpx.org/async/),
[HTTPX resource limits](https://www.python-httpx.org/advanced/resource-limits/),
[Psycopg transaction management](https://www.psycopg.org/psycopg3/docs/basic/transactions.html).
