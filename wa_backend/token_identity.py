"""Shared validation after JWT signature/expiry verification; no DB side effects."""
from typing import Mapping, Any


def _positive_id(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError('Invalid identity')
    result = int(value)
    if result <= 0 or str(result) != str(value) or result > 2_147_483_647:
        raise ValueError('Invalid identity')
    return result


def access_token_identity(payload: Mapping[str, Any]) -> tuple[int, int]:
    # This legacy decoder returns operational Driver ids. Canonical company-token
    # subjects are principal ids, even when their numeric values happen to coincide.
    # Realtime callers must migrate to persisted canonical context before accepting
    # those tokens; never silently reinterpret one identity family as the other.
    if any(key in payload for key in ('channel', 'principal_type', 'auth_revision')):
        raise ValueError('Canonical request context required')
    # A valid refresh signature must never authorize an HTTP/WebSocket operation.
    if payload.get('type') != 'access':
        raise ValueError('Access token required')
    return _positive_id(payload.get('sub')), _positive_id(payload.get('company_id'))
