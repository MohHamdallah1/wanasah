"""Short-lived, tamper-evident two-actor custody handshake."""
from __future__ import annotations
import base64
import hashlib
import hmac
import json
from time import time
from config import Config

MAX_PROOF_AGE_SECONDS = 900

class CustodyRejected(ValueError):
    def __init__(self, code: str, status: int = 409):
        self.code = code
        self.status = status
        super().__init__(code)

def digest(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False, default=str,
    ).encode("utf-8")).hexdigest()

def signed(kind: str, data: dict, *, issued_at: int | None = None) -> str:
    # Reconstruct server-side proofs from persisted non-secret evidence only.
    timestamp = int(time()) if issued_at is None else issued_at
    if type(timestamp) is not int or timestamp <= 0:
        raise CustodyRejected("CUSTODY_PROOF_INVALID", 422)
    payload = dict(data, purpose=f"CUSTODY_{kind}", issued_at=timestamp)
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).rstrip(b"=")
    mac = hmac.new(
        Config.SECRET_KEY.encode(), b"wanasah-custody-v1:" + body,
        hashlib.sha256,
    ).hexdigest()
    return body.decode() + "." + mac

def verify(kind: str, token: str) -> dict:
    if not token or len(token) > 2048:
        raise CustodyRejected("CUSTODY_PROOF_INVALID", 422)
    try:
        encoded, claimed_mac = token.split(".")
        body = encoded.encode("ascii")
        expected = hmac.new(
            Config.SECRET_KEY.encode(), b"wanasah-custody-v1:" + body,
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(expected, claimed_mac):
            raise ValueError("signature")
        raw = base64.urlsafe_b64decode(body + b"=" * (-len(body) % 4))
        data = json.loads(raw)
        issued = data["issued_at"]
        if (data.get("purpose") != f"CUSTODY_{kind}" or
                type(issued) is not int or
                issued > int(time()) + 5 or
                int(time()) - issued > MAX_PROOF_AGE_SECONDS):
            raise ValueError("expired or wrong purpose")
        return data
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise CustodyRejected("CUSTODY_PROOF_INVALID_OR_EXPIRED", 409) from exc
