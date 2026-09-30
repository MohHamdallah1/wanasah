# WebSocket authentication and logging — D5

## Scope and protocol
Both existing read-only dashboard WebSockets are covered:
- `/ws/dispatch` (company admin only).
- `/simple-products/imports/{job_id}/ws` (active actor, catalog.read and exact tenant-owned job).

The browser opens a **query-free** `wss://` URL (localhost development may use `ws://`) and immediately sends its existing access JWT as the FIRST text frame:
```json
{"type":"auth","token":"<existing access JWT>"}
```
The server validates `Origin` against the shared explicit CORS allowlist before accepting, permits 128 pending handshakes per web process, waits at most 5 seconds for the first frame, enforces 8192-character frame and 4096-character bearer ceilings, and uses the existing JWT expiry, blacklist, actor status and tenant permissions. The server sends `{"event":"WS_AUTHENTICATED"}` only after final scope authorization. Product Import keeps HTTP polling until this ACK is received. On expiration or after at most five minutes, the connection closes and the browser reconnects with its CURRENT access token, bounding stale-revocation exposure. WebSocket frames grant **no mutating business permissions**.

No access JWT, refresh token, session token or random UUID belongs in URL query arguments or the `Sec-WebSocket-Protocol` header. A request/correlation UUID already exists in the ASGI state for troubleshooting; it is NOT an authentication secret. Browsers cannot set an arbitrary `Authorization` header through the standard WebSocket constructor.

## Ingress and access logging
Every WebSocket handshake containing ANY query arguments is rejected before it reaches the router. The outer ASGI middleware clears `scope["query_string"]` before sending the refusal, so Uvicorn's protocol access logger sees the redacted path only. Both valid endpoints are query-free. The real Uvicorn (0.30.x) protocol/access-log gate `scripts/gate_websocket_d5_uvicorn_logs.py` checks that rejected legacy query canaries and invalid first-frame credential canaries NEVER appear in its emitted logs.

**Critical limit:** an upstream reverse proxy, API gateway, CDN or WAF receives the original URL *before* application middleware. At every production ingress layer, configure request logging to use the path-only URI (e.g. Nginx `$uri` rather than `$request_uri` for WebSocket access logging) or rigorously redact all credential query parameters, and disable sensitive header/frame payload capture. No claim about production-edge redaction is valid until the deployed ingress configuration and a synthetic-canary test are inspected. This is an explicit D8 deployment acceptance dependency.

## Operations and incident response
1. Deploy the backend and browser bundle as one coordinated protocol change. The old browser `?token=` URL is deliberately fail-closed. Do not roll back to a bearer-in-URL implementation; use authorized HTTP polling where available during maintenance.
2. Configure `--ws-max-size 8192` (or stricter, provided the real signed JWT still fits) on the serving Uvicorn protocol. Verify the effective setting on EVERY web process. Ensure production uses TLS/WSS at the ingress. Origin allowlisting is not a substitute for JWT/RLS.
3. Search prior local, proxy, CDN and application logs for `/ws/dispatch?token=`, `/imports/*/ws?token=` and related bearer query names without displaying or forwarding the tokens into a new log. Limit the review to authorized incident-response personnel; record only counts, time windows, affected identities by non-secret references, and actions.
4. Treat a previously logged **access** JWT as disclosed while valid. Existing access JWTs expire after 15 minutes in the current auth implementation; verify expiry from the issuance time before concluding exposure ended. Revoke still-valid exposed access tokens via the existing blacklist/logout workflow, and rotate/revoke refresh credentials separately ONLY if those were actually exposed. Do not mass-revoke unrelated customers without evidence/owner-approved incident response.
5. Restrict/delete previously exposed log artifacts according to retention and incident policy, confirm downstream log exporters no longer contain live secrets, and verify production Uvicorn AND edge proxy logs with synthetic canaries.
6. Monitor repeated policy-violation and unauthenticated handshakes by redacted route, HTTP 403 / WS close code and request ID only. Never record the first authentication frame body or JWT itself.

## Reproducible gates
From `wa_backend`: `python -m unittest tests.test_websocket_d5_security` and `python -m scripts.gate_websocket_d5_uvicorn_logs`. From `dashboard`: `vitest run src/test/websocket-d5-security.test.ts src/test/products-p9-4-import.test.ts`, followed by `vite build`. Production reverse-proxy inspection remains a separate D8 gate.
