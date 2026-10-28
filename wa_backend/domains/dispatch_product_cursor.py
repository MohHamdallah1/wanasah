"""Signed, scope-bound immutable-ID seek cursors for Dispatch discovery."""
import base64
import hashlib
import hmac
import json
from config import Config


class DispatchProductCursorError(ValueError):
    code = "DISPATCH_PRODUCT_CURSOR_INVALID"
    message = "Search context changed or the continuation is invalid. Restart the search."


def _b64(raw):
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _decode(value):
    decoded = base64.b64decode(value.encode("ascii") + b"=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(decoded) != value:
        raise ValueError("noncanonical cursor")
    return decoded


def _scope(scope):
    return hashlib.sha256(json.dumps(scope, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _signature(raw):
    return hmac.new(Config.SECRET_KEY.encode(), raw, hashlib.sha256).digest()


def encode_product_cursor(after_id, *, scope):
    raw = json.dumps({"kind": "dispatch-products-v1", "scope": _scope(scope), "after_id": after_id}, sort_keys=True, separators=(",", ":")).encode()
    return f"{_b64(raw)}.{_b64(_signature(raw))}"


def decode_product_cursor(cursor, *, scope):
    if not cursor:
        return 0
    try:
        payload, signature = cursor.split(".")
        raw = _decode(payload)
        if not hmac.compare_digest(_signature(raw), _decode(signature)):
            raise ValueError("signature")
        data = json.loads(raw)
        if data["kind"] != "dispatch-products-v1" or data["scope"] != _scope(scope) or type(data["after_id"]) is not int or data["after_id"] <= 0:
            raise ValueError("scope")
        return data["after_id"]
    except (ValueError, KeyError, TypeError, UnicodeError) as exc:
        raise DispatchProductCursorError() from exc
