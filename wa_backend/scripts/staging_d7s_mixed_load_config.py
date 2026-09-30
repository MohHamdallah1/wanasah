"""Pure, fail-closed configuration for the independent D7-S generator.

No dotenv, application, database or networking imports. Secrets come only from
explicit D7S environment names and are excluded from dataclass representations.
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
import hashlib
import ipaddress
import json
import os
import re
import time
from urllib.parse import parse_qs, urlsplit
from uuid import UUID, uuid5

ACK = "I_ACK_EXTERNAL_ISOLATED_SYNTHETIC_STAGING"
MUTATION_ACK = "I_ACK_BOUNDED_SYNTHETIC_MUTATIONS"
KINDS = frozenset({"catalog", "owned_status", "foreign_status", "sale", "inbound", "route", "import"})
MUTATIONS = frozenset({"sale", "inbound", "route", "import"})
SAFE_KEY = re.compile(r"^[A-Z][A-Z0-9_]{0,23}$")
MAX_CONFIG_BYTES = 2 * 1024 * 1024


class Blocker(ValueError):
    """Only fixed safe codes may be exposed by the CLI."""
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise Blocker(code)


def integer(value, low: int, high: int, code="INVALID_INTEGER") -> int:
    require(type(value) is int and low <= value <= high, code)
    return value


def money(value, *, positive=False) -> Decimal:
    require(isinstance(value, (str, int)) and not isinstance(value, bool), "INVALID_DECIMAL")
    try:
        number = Decimal(str(value))
    except InvalidOperation:
        raise Blocker("INVALID_DECIMAL") from None
    require(number.is_finite() and (number > 0 if positive else number >= 0)
            and number <= Decimal("100000000"), "INVALID_DECIMAL")
    require(number.as_tuple().exponent >= -6, "EXCESS_DECIMAL_PRECISION")
    return number


def canonical_origin(raw: str) -> str:
    require(isinstance(raw, str) and not any(c.isspace() for c in raw), "INVALID_ORIGIN")
    try:
        u = urlsplit(raw)
        port = u.port
    except ValueError:
        raise Blocker("INVALID_ORIGIN") from None
    require(u.scheme == "https" and bool(u.hostname) and u.username is None
            and u.password is None and u.path in ("", "/") and not u.query
            and not u.fragment and (port is None or 1 <= port <= 65535), "HTTPS_EXACT_ORIGIN_REQUIRED")
    host = u.hostname.lower()
    require(not host.endswith((".", ".localhost", ".local")) and host != "localhost", "LOCAL_TARGET_DENIED")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address:
        require(not (address.is_loopback or address.is_link_local or address.is_unspecified
                     or address.is_multicast), "LOCAL_TARGET_DENIED")
    authority = f"[{host}]" if ":" in host else host
    return f"https://{authority}" + (f":{port}" if port not in (None, 443) else "")


def json_object(raw: str) -> dict:
    require(isinstance(raw, str) and len(raw.encode()) <= MAX_CONFIG_BYTES, "CONFIG_TOO_LARGE")
    try:
        def unique(pairs):
            result = {}
            for key, value in pairs:
                require(key not in result, "DUPLICATE_JSON_KEY")
                result[key] = value
            return result
        value = json.loads(raw, object_pairs_hook=unique,
                           parse_constant=lambda _: (_ for _ in ()).throw(Blocker("NONFINITE_JSON")))
    except (ValueError, TypeError):
        raise Blocker("INVALID_CONFIG_JSON") from None
    require(isinstance(value, dict), "CONFIG_OBJECT_REQUIRED")
    return value


def token_for(env: dict, name: str, company: int, actor: int, end_time: float) -> str:
    token = env.get(name, "")
    require(isinstance(token, str) and 0 < len(token) <= 8192
            and not any(c.isspace() for c in token), "TOKEN_REQUIRED")
    try:
        parts = token.split(".")
        require(len(parts) == 3, "TOKEN_SHAPE")
        payload = json_object(base64.urlsafe_b64decode(parts[1] + "=" * (-len(parts[1]) % 4)).decode())
        require(payload.get("type") == "access"
                and str(payload.get("company_id")) == str(company)
                and str(payload.get("sub")) == str(actor), "TOKEN_FIXTURE_IDENTITY_MISMATCH")
        require(isinstance(payload.get("exp"), (int, float)) and payload["exp"] > end_time, "TOKEN_EXPIRES_DURING_RUN")
    except (ValueError, UnicodeError):
        raise Blocker("TOKEN_SHAPE") from None
    # This is an untrusted-claim consistency check, NOT signature verification.
    # The real server dependency verifies signature, expiry, blacklist and actor.
    return token


@dataclass(frozen=True)
class Tenant:
    key: str
    company_id: int
    admin_id: int
    driver_id: int
    status_job_id: str
    admin_token: str = field(repr=False)
    driver_token: str = field(repr=False)


@dataclass(frozen=True)
class Operation:
    key: str
    tenant: str
    kind: str
    request_id: str
    fixture: dict = field(repr=False)
    expected: dict = field(repr=False)

    @property
    def replay_safe(self) -> bool:
        return self.kind != "route"


@dataclass(frozen=True)
class Limits:
    duration_seconds: int = 60
    completion_seconds: int = 120
    timeout_seconds: int = 15
    max_requests: int = 300
    max_attempts: int = 2
    max_rows: int = 50000
    max_source_bytes: int = 20 * 1024 * 1024
    max_value: str = "10000"
    max_base_units: str = "100000"
    max_route_shops: int = 50
    observer_seconds: int = 30
    concurrency: int = 16
    per_tenant: int = 8
    arrival_rate: int = 10
    poll_seconds: int = 10
    connections: int = 100
    hold_seconds: int = 10
    endpoint_concurrency: dict = field(default_factory=lambda: {
        "catalog": 16, "owned_status": 4, "foreign_status": 4,
        "sale": 2, "inbound": 2, "route": 1, "import": 1,
    })


@dataclass(frozen=True)
class Config:
    origin: str
    run_id: str
    tenants: tuple[Tenant, ...]
    operations: tuple[Operation, ...]
    limits: Limits
    fingerprint: str
    database_name: str
    release_sha: str
    slo: dict
    db_dsn: str = field(repr=False)
    environment: dict = field(repr=False, compare=False)


def validate_fixture(kind: str, data: dict, expected: dict) -> tuple[int, Decimal]:
    """Narrow synthetic profile. Business validation remains server-owned."""
    require(isinstance(data, dict) and isinstance(expected, dict), "INVALID_FIXTURE")
    rows, value = 0, Decimal(0)
    if kind == "sale":
        require(set(data) == {"visit_id", "cart_items", "cash_collected"}, "SALE_FIXTURE_FIELDS")
        integer(data["visit_id"], 1, 2147483647)
        items = data["cart_items"]
        require(isinstance(items, list) and 1 <= len(items) <= 20, "SALE_ITEMS_LIMIT")
        seen = set()
        for item in items:
            require(isinstance(item, dict), "ITEM_OBJECT_REQUIRED")
            require(set(item) == {"product_variant_id", "quantity", "packs_quantity"}, "SALE_ITEM_FIELDS")
            pid = integer(item["product_variant_id"], 1, 2147483647)
            require(pid not in seen, "DUPLICATE_PRODUCT")
            seen.add(pid)
            q = integer(item["quantity"], 0, 10000)
            p = integer(item["packs_quantity"], 0, 10000)
            require(q + p > 0, "ZERO_SALE")
        require(money(data["cash_collected"]).as_tuple().exponent >= -3, "CASH_PRECISION")
        value = money(expected.get("final_amount_due"), positive=True)
        money(expected.get("base_units"), positive=True)
    elif kind == "inbound":
        require(set(data) == {"location_id", "items"}, "INBOUND_FIXTURE_FIELDS")
        integer(data["location_id"], 1, 2147483647)
        require(isinstance(data["items"], list) and 1 <= len(data["items"]) <= 20, "INBOUND_ITEMS_LIMIT")
        for item in data["items"]:
            require(isinstance(item, dict), "ITEM_OBJECT_REQUIRED")
            require(set(item) <= {"product_variant_id", "quantity", "uom_id", "unit_cost",
                                  "production_date", "expiry_date"}
                    and {"product_variant_id", "quantity", "uom_id", "unit_cost"} <= set(item), "INBOUND_ITEM_FIELDS")
            integer(item["product_variant_id"], 1, 2147483647)
            integer(item["uom_id"], 1, 2147483647)
            require(money(item["quantity"], positive=True) <= 10000, "INBOUND_QUANTITY_LIMIT")
            value += money(item["quantity"], positive=True) * money(item["unit_cost"])
            for field_name in ("production_date", "expiry_date"):
                if item.get(field_name) is not None:
                    from datetime import date
                    try:
                        date.fromisoformat(item[field_name])
                    except (ValueError, TypeError):
                        raise Blocker("INVALID_FIXTURE_DATE") from None
        money(expected.get("base_units"), positive=True)
    elif kind == "route":
        require(set(data) == {"zone_id", "driver_id", "vehicle_id", "source_location_id", "inventory"}, "ROUTE_FIXTURE_FIELDS")
        for key in ("zone_id", "driver_id", "vehicle_id", "source_location_id"):
            integer(data[key], 1, 2147483647)
        require(isinstance(data["inventory"], dict) and 1 <= len(data["inventory"]) <= 20, "ROUTE_ITEMS_LIMIT")
        for pid, quantity in data["inventory"].items():
            require(isinstance(pid, str) and pid.isascii() and pid.isdecimal()
                    and str(int(pid)) == pid, "ROUTE_PRODUCT_ID")
            integer(int(pid), 1, 2147483647)
            integer(quantity, 1, 10000)
    elif kind == "import":
        require(set(data) == {"rows", "unit_price"}, "IMPORT_FIXTURE_FIELDS")
        rows = integer(data["rows"], 1, 50000)
        value = money(data["unit_price"], positive=True) * rows
    else:
        require(not data and not expected, "READ_FIXTURE_MUST_BE_EMPTY")
    return rows, value


def read_config(env: dict | None = None, *, execute=False, mutations=False, observe=False) -> Config:
    env = dict(os.environ if env is None else env)
    raw = env.get("WANASAH_D7S_CONFIG_JSON", "")
    require(bool(raw), "CONFIG_REQUIRED")
    manifest = json_object(raw)
    require(manifest.get("schema") == 1, "CONFIG_SCHEMA")
    origin = canonical_origin(env.get("WANASAH_D7S_URL", ""))
    require(origin == canonical_origin(env.get("WANASAH_D7S_APPROVED_URL", "")), "TARGET_MISMATCH")
    facts = manifest.get("staging", {})
    require(isinstance(facts, dict), "STAGING_OBJECT_REQUIRED")
    require(facts.get("isolated_synthetic") is True and facts.get("generator_external") is True
            and facts.get("web_workers") == 4 and facts.get("fixtures_exclusive") is True,
            "STAGING_ATTESTATION_REQUIRED")
    require(origin not in {canonical_origin(x) for x in facts.get("forbidden_origins", [])}
            and len(facts.get("forbidden_origins", [])) >= 2, "DEVELOPMENT_PRODUCTION_DENYLIST_REQUIRED")
    require(re.fullmatch(r"[0-9a-f]{40}", facts.get("release_sha", "")) is not None, "RELEASE_SHA_REQUIRED")
    database = facts.get("database_name", "")
    require(re.fullmatch(r"[A-Za-z0-9_]{1,63}", database) is not None, "STAGING_DATABASE_REQUIRED")
    try:
        run_id = str(UUID(manifest["run_id"]))
    except (KeyError, ValueError, TypeError):
        raise Blocker("RUN_UUID_REQUIRED") from None
    settings = manifest.get("limits", {})
    require(isinstance(settings, dict) and set(settings) <= set(Limits.__dataclass_fields__), "LIMIT_FIELDS")
    try:
        limits = Limits(**settings)
    except TypeError:
        raise Blocker("INVALID_LIMITS") from None
    for name, low, high in (
        ("duration_seconds", 1, 300), ("completion_seconds", 1, 600),
        ("timeout_seconds", 1, 30), ("max_requests", 1, 6000),
        ("max_attempts", 1, 3), ("max_rows", 1, 100000),
        ("max_source_bytes", 1, 64 * 1024 * 1024), ("concurrency", 1, 1000),
        ("per_tenant", 1, 1000), ("arrival_rate", 1, 1000),
        ("observer_seconds", 1, 60), ("max_route_shops", 1, 200), ("poll_seconds", 10, 60), ("connections", 1, 1000), ("hold_seconds", 1, 60),
    ):
        integer(getattr(limits, name), low, high, "LIMIT_OUT_OF_RANGE")
    require(isinstance(limits.endpoint_concurrency, dict) and set(limits.endpoint_concurrency) == KINDS, "ENDPOINT_LIMITS_REQUIRED")
    for count in limits.endpoint_concurrency.values():
        integer(count, 1, 1000, "ENDPOINT_LIMIT_OUT_OF_RANGE")
    require(limits.endpoint_concurrency["route"] == 1, "ROUTE_CONCURRENCY_MUST_BE_ONE")
    money(limits.max_value, positive=True)
    money(limits.max_base_units, positive=True)
    slo = manifest.get("slo", {})
    require(isinstance(slo, dict) and set(slo) == {"read_p95_ms", "write_p95_ms", "write_p99_ms"}, "APPROVED_SLO_REQUIRED")
    for value in slo.values():
        integer(value, 1, 120000, "INVALID_SLO")
    if execute:
        require(env.get("WANASAH_D7S_ACK") == ACK, "EXTERNAL_STAGING_ACK_REQUIRED")
        if mutations:
            require(env.get("WANASAH_D7S_MUTATIONS_ACK") == MUTATION_ACK, "MUTATIONS_ACK_REQUIRED")
    tenants, tokens = [], set()
    end_time = time.time() + limits.duration_seconds + limits.completion_seconds + 120
    for entry in manifest.get("tenants", []):
        require(isinstance(entry, dict), "TENANT_OBJECT_REQUIRED")
        key = entry.get("key", "")
        require(SAFE_KEY.fullmatch(key) is not None, "TENANT_KEY")
        ids = [integer(entry.get(k), 1, 2147483647) for k in ("company_id", "admin_id", "driver_id")]
        try:
            job = str(UUID(entry["status_job_id"]))
        except (KeyError, ValueError, TypeError):
            raise Blocker("OWNED_STATUS_JOB_REQUIRED") from None
        admin = token_for(env, f"WANASAH_D7S_{key}_ADMIN_TOKEN", ids[0], ids[1], end_time) if execute else ""
        driver = token_for(env, f"WANASAH_D7S_{key}_DRIVER_TOKEN", ids[0], ids[2], end_time) if execute else ""
        if execute:
            require(admin != driver and admin not in tokens and driver not in tokens, "DISTINCT_TOKENS_REQUIRED")
            tokens.update((admin, driver))
        tenants.append(Tenant(key, *ids, job, admin, driver))
    require(2 <= len(tenants) <= 8 and len({t.key for t in tenants}) == len(tenants)
            and len({t.company_id for t in tenants}) == len(tenants)
            and len({t.status_job_id for t in tenants}) == len(tenants), "DISTINCT_SYNTHETIC_TENANTS_REQUIRED")
    keys = {t.key for t in tenants}
    operations, seen, visits, routes = [], set(), set(), set()
    row_total, value_total, units_total = 0, Decimal(0), Decimal(0)
    entries = manifest.get("operations", [])
    require(isinstance(entries, list) and 1 <= len(entries) <= 1000, "SUBMISSIONS_LIMIT")
    for entry in entries:
        require(isinstance(entry, dict), "OPERATION_OBJECT_REQUIRED")
        key, kind, tenant = entry.get("key", ""), entry.get("kind"), entry.get("tenant")
        require(SAFE_KEY.fullmatch(key) is not None and key not in seen, "OPERATION_KEY")
        require(kind in KINDS and tenant in keys, "OPERATION_SCOPE")
        seen.add(key)
        fixture, expected = entry.get("fixture", {}), entry.get("expected", {})
        rows, value = validate_fixture(kind, fixture, expected)
        if kind in {"sale", "inbound"}:
            units_total += money(expected["base_units"], positive=True)
        row_total += rows
        value_total += value
        if kind == "sale":
            identity = (tenant, fixture["visit_id"])
            require(identity not in visits, "VISIT_REUSED")
            visits.add(identity)
        if kind == "route":
            for column in ("driver_id", "vehicle_id", "zone_id"):
                identity = (tenant, column, fixture[column])
                require(identity not in routes, "ROUTE_FIXTURE_REUSED")
                routes.add(identity)
            own = next(t for t in tenants if t.key == tenant)
            require(fixture["driver_id"] != own.driver_id, "ROUTE_DRIVER_HAS_SALE_SESSION")
        request_id = str(uuid5(UUID(run_id), tenant + ":" + key))
        operations.append(Operation(key, tenant, kind, request_id, fixture, expected))
    require(row_total <= limits.max_rows and value_total <= money(limits.max_value)
            and units_total <= money(limits.max_base_units), "ROWS_OR_VALUE_BUDGET")
    dsn = ""
    if execute and (mutations or observe):
        dsn = env.get("WANASAH_D7S_READONLY_DSN", "")
        require(bool(dsn) and dsn == env.get("WANASAH_D7S_APPROVED_READONLY_DSN"), "READONLY_OBSERVER_REQUIRED")
        try:
            u = urlsplit(dsn)
            require(u.scheme in {"postgres", "postgresql"} and u.hostname
                    and u.path == "/" + database and parse_qs(u.query).get("sslmode") == ["verify-full"],
                    "READONLY_DSN_SCOPE_TLS")
            canonical_origin("https://" + u.hostname + (":" + str(u.port) if u.port else ""))
        except ValueError:
            raise Blocker("READONLY_DSN_SCOPE_TLS") from None
    fingerprint = hashlib.sha256((origin + json.dumps(manifest, sort_keys=True, separators=(",", ":"))).encode()).hexdigest()
    return Config(origin, run_id, tuple(tenants), tuple(operations), limits,
                  fingerprint, database, facts["release_sha"], slo, dsn, env)
