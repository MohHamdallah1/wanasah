# Dashboard authentication session

## Session lifetime

Dashboard authentication uses two credentials:

- access token: 15 minutes;
- refresh token: 30 days.

The refresh token is rotated on successful refresh and the replacement receives a new 30-day expiry. An actively used dashboard session therefore remains signed in without periodic user interruption. A session that is not used for 30 days expires and requires login again.

Explicit logout, account disablement, company disablement, invalid/expired refresh credentials, or a real authentication failure can also end the session.

## Concurrent refresh safety

Refresh tokens remain single-use rotation credentials.

To prevent two browser contexts from racing on the same token:

1. the database row for the presented refresh token is locked;
2. the first request creates one successor and links the old token to it;
3. duplicate requests arriving within the 15-second concurrency grace receive that same successor;
4. after the grace window the old token is rejected with 401;
5. the dashboard also detects if another tab already advanced `localStorage` and will not let a stale 401 erase the newer session.

The grace window is only for concurrent delivery of the already-created successor. It does not create multiple active successors and it does not make the old token generally reusable.

## Security properties

- Access tokens remain short-lived.
- Refresh rotation remains enabled.
- A rotation creates exactly one successor.
- Explicit logout deletes the current refresh token.
- The self-reference uses `ON DELETE SET NULL`, so deleting the current token cannot leave a broken predecessor reference.
- Disabled users or companies cannot refresh.
- Refresh role context is preserved across rotation for Admin, Inventory, and Driver sessions.
