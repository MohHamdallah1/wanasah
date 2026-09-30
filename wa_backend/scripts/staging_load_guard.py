"""Fail-closed credentials/target guard for external READ-ONLY staging load.

Does not import Locust. Keep test secrets outside git and stdout.
"""
from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlsplit, urlunsplit
from uuid import UUID


ACK = "I_ACK_ISOLATED_SYNTHETIC_STAGING"


@dataclass(frozen=True, slots=True)
class StagingLoadConfig:
    base_url: str
    token_a: str
    token_b: str | None
    job_a: str | None
    job_b: str | None


def _canonical_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    url = urlsplit(value)
    if (
        url.scheme not in {"http", "https"}
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.path not in {"", "/"}
        or url.query or url.fragment
        or url.hostname.endswith(".")
    ):
        raise ValueError(
            "Staging load URL must be a scheme + host[:port], "
            "without credentials, paths, queries or fragments."
        )
    try:
        port = url.port
    except ValueError as exc:
        raise ValueError("Invalid staging load URL port") from exc
    if not 0 <= (port or 0) <= 65535:
        raise ValueError("Invalid staging load URL port")
    if url.scheme != "https" and url.hostname not in {
        "127.0.0.1", "::1", "localhost"
    }:
        raise ValueError("Non-loopback staging load requires HTTPS")
    return urlunsplit((
        url.scheme, url.netloc.lower(), "", "", ""
    ))


def _job_id(name: str) -> str | None:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return None
    try:
        return str(UUID(raw))
    except ValueError as exc:
        raise ValueError(f"{name} must be a canonical UUID") from exc


def read_staging_load_config() -> StagingLoadConfig:
    if os.environ.get("WANASAH_LOAD_TEST_ACK") != ACK:
        raise RuntimeError(
            "Read-only load requires explicit isolated staging acknowledgement."
        )
    target = _canonical_url(
        os.environ.get("WANASAH_LOAD_STAGING_URL", "")
    )
    allowed = _canonical_url(
        os.environ.get("WANASAH_LOAD_APPROVED_URL", "")
    )
    if target != allowed:
        raise RuntimeError("Requested load host is not the approved staging host")

    token_a = os.environ.get("WANASAH_LOAD_TOKEN_COMPANY_A", "").strip()
    token_b = os.environ.get("WANASAH_LOAD_TOKEN_COMPANY_B", "").strip() or None
    if not token_a:
        raise RuntimeError("Synthetic company A JWT is required")
    if token_b == token_a:
        raise RuntimeError("Test tenants must use distinct JWTs")

    job_a = _job_id("WANASAH_LOAD_JOB_COMPANY_A")
    job_b = _job_id("WANASAH_LOAD_JOB_COMPANY_B")
    if job_b and not token_b:
        raise RuntimeError("Company B import status requires company B JWT")
    if job_b and not job_a:
        raise RuntimeError("Company B job needs company A job for cross-scope proof")
    return StagingLoadConfig(
        base_url=target,
        token_a=token_a,
        token_b=token_b,
        job_a=job_a,
        job_b=job_b,
    )


def assert_actual_target(host: str, config: StagingLoadConfig) -> None:
    if _canonical_url(host) != config.base_url:
        raise RuntimeError(
            "Locust effective target differs from the approved staging URL"
        )
