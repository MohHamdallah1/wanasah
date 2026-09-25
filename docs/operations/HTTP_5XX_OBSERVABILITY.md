# HTTP 5xx observability

## Purpose

Every HTTP server failure must be traceable from the request id shown to the client to exactly one centralized server incident record.

The API response remains safe for clients. Internal exception messages and tracebacks are never returned to the dashboard/mobile client.

## error.log contract

`error.log` is the centralized HTTP **5xx incident** file.

Each record contains one structured JSON event with:

- `event=http_server_error`;
- `request_id`;
- HTTP `status_code`;
- stable `error_code`;
- HTTP method and path (query string/body/headers are not logged);
- client IP;
- whether the error was a handled HTTP exception;
- root-cause exception type/message;
- sanitized traceback.

Normal 4xx responses are intentionally not written to this file.

The existing rotation contract remains 1 MiB with 5 backups. Production deployment may forward these structured records to a centralized log platform later; the request-id contract does not change.

## Find an incident by tracking number

From the repository root:

```powershell
Select-String -Path .\wa_backend\error.log -Pattern "<request-id>"
```

If the backend is launched from another working directory, set `WANASAH_ERROR_LOG_PATH` explicitly in the deployment environment and search that configured file.

The request id in:

- the `X-Request-Id` response header;
- the top-level response `request_id`;
- `error.request_id`;
- the centralized 5xx log event

must be identical.

## Safety

- HTTP 5xx logging is centralized; route-local log calls do not create extra `error.log` incident records.
- PostgreSQL URLs and common named secrets are redacted before persistence.
- Logging failure never replaces the original API response.
- A chained or implicit exception cause is captured server-side when available.
- Client bodies, authorization headers, cookies, and query strings are not written to the incident record.
