"""Wanasah independent D7-S staging mixed-load driver. Importing does no IO or application boot.

Default invocation is a static plan. Network and synthetic mutations require
separate explicit opt-ins. This tool never seeds fixtures or starts workers.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import csv
from datetime import datetime, timezone
from decimal import Decimal
from email.utils import parsedate_to_datetime
import hashlib
import io
import json
import math
import os
from pathlib import Path
import socket
import ssl
import time
from urllib.parse import urlsplit
from uuid import UUID

from tools.staging_load.wanasah_d7s_mixed_load_config import (
    Blocker, Config, KINDS, MUTATIONS, Operation, Tenant, money, read_config, require,
)

MAX_RESPONSE_BYTES = 1024 * 1024
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
HEADERS = (
    "Name", "Family", "Outer Package Type", "Base Units per Outer Package",
    "Outer Package Price", "Unit Price", "Unit Barcode", "Outer Package Barcode",
    "Lot Tracking", "Expiry Tracking",
)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def percentile(values: list[float], quantile: float):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * quantile) - 1)], 3)


def distribution(values):
    return {"count": len(values), "p50_ms": percentile(values, .5),
            "p95_ms": percentile(values, .95), "p99_ms": percentile(values, .99)}


def retry_delay(raw: str | None, now: float | None = None) -> float:
    """Missing/invalid Retry-After uses the real global limiter's full 60s window."""
    if raw:
        try:
            value = float(raw)
            if math.isfinite(value) and value >= 0:
                return max(1., value)
        except ValueError:
            try:
                when = parsedate_to_datetime(raw)
                if when.tzinfo is not None:
                    return max(1., when.timestamp() - (time.time() if now is None else now))
            except (TypeError, ValueError, OverflowError):
                pass
    return 60.


def source_bytes(config: Config, op: Operation) -> bytes:
    """Reproducible UTF-8 CSV; exact bytes/name/defaults are retained on replay."""
    output = io.StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(HEADERS)
    tag = UUID(op.request_id).hex
    for row in range(op.fixture["rows"]):
        writer.writerow((f"صناعي D7S {tag} {row + 1}", "", "No outer package",
                         "", "", op.fixture["unit_price"], "", "", "NONE", "NONE"))
        # A single upload must leave multipart headroom under ingress 10MiB.
        require(output.tell() <= 9 * 1024 * 1024, "SOURCE_UPLOAD_LIMIT")
    data = output.getvalue().encode("utf-8")
    require(len(data) <= 9 * 1024 * 1024, "SOURCE_UPLOAD_LIMIT")
    return data


def request_spec(config: Config, op: Operation) -> tuple[str, str, dict]:
    f = op.fixture
    if op.kind == "sale":
        return "PUT", f"/visits/{f['visit_id']}", {"json": {
            "request_id": op.request_id, "outcome": "Sale",
            "cash_collected": f["cash_collected"], "cart_items": f["cart_items"],
        }}
    if op.kind == "inbound":
        items = []
        for index, item in enumerate(f["items"]):
            items.append({**item, "batch_number": f"D7S-{UUID(op.request_id).hex}-{index}"})
        return "POST", "/warehouse/inbound", {"json": {
            "request_id": op.request_id, "location_id": f["location_id"],
            "reference_id": f"D7S-IN-{UUID(op.request_id).hex}", "items": items,
        }}
    if op.kind == "route":
        # No server idempotency contract. NEVER add a fictional request_id.
        return "POST", "/dispatch/route", {"json": dict(f)}
    if op.kind == "import":
        return "POST", "/simple-products/imports", {
            "data": {"request_id": op.request_id, "default_lot_control_mode": "NONE",
                     "default_expiry_control_mode": "NONE"},
            "files": {"file": (f"d7s-{op.request_id}.csv", source_bytes(config, op), "text/csv")},
        }
    tenant = next(t for t in config.tenants if t.key == op.tenant)
    if op.kind == "catalog":
        return "GET", "/simple-products?limit=10", {}
    job = tenant.status_job_id
    if op.kind == "foreign_status":
        job = next(t.status_job_id for t in config.tenants if t.key != op.tenant)
    return "GET", f"/simple-products/imports/{job}", {}


def payload_hash(config: Config, op: Operation) -> str:
    method, path, kwargs = request_spec(config, op)
    if op.kind == "import":
        body = {"data": kwargs["data"], "name": kwargs["files"]["file"][0],
                "source_sha256": hashlib.sha256(kwargs["files"]["file"][1]).hexdigest()}
    else:
        body = kwargs
    return hashlib.sha256(canonical([method, path, body]).encode()).hexdigest()


class Journal:
    """Exclusive process lease + fsynced intent; never stores tokens or payloads.

    A stale lock is intentionally not auto-deleted. The operator must establish
    the old generator is dead before removing its LOCAL lock (not DB fixtures).
    """
    def __init__(self, path: Path, config: Config, *, resume=False):
        self.path = path
        self.lock = Path(str(path) + ".lock")
        self.events = []
        self.closed = False
        require(path.parent.is_dir(), "JOURNAL_DIRECTORY_REQUIRED")
        require(not path.is_symlink() and not self.lock.is_symlink(), "JOURNAL_SYMLINK_DENIED")
        try:
            lease = os.open(self.lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            raise Blocker("GENERATOR_LEASE_EXISTS") from None
        os.close(lease)
        try:
            if resume:
                require(path.is_file() and path.stat().st_size <= MAX_JOURNAL_BYTES, "JOURNAL_REQUIRED")
                raw = path.read_bytes()
                require(raw.endswith(b"\n"), "TORN_JOURNAL_REQUIRES_REVIEW")
                self.events = [json.loads(line) for line in raw.splitlines()]
                require(bool(self.events) and self.events[0] == {
                    "event": "header", "run_id": config.run_id, "fingerprint": config.fingerprint},
                    "RESUME_INPUT_CHANGED")
                self.file = path.open("ab", buffering=0)
            else:
                descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                self.file = os.fdopen(descriptor, "ab", buffering=0)
                self.append({"event": "header", "run_id": config.run_id, "fingerprint": config.fingerprint})
        except BaseException:
            self.lock.unlink(missing_ok=True)
            raise

    def append(self, event: dict) -> None:
        data = (canonical(event) + "\n").encode()
        require(self.path.stat().st_size + len(data) <= MAX_JOURNAL_BYTES, "JOURNAL_BUDGET")
        require(self.file.write(data) == len(data), "JOURNAL_INCOMPLETE_WRITE")
        os.fsync(self.file.fileno())
        self.events.append(event)

    def attempts(self, op: Operation) -> int:
        return sum(e.get("event") == "intent" and e.get("operation") == op.key for e in self.events)

    def latest(self, event: str):
        return next((e for e in reversed(self.events) if e.get("event") == event), None)

    def close(self):
        if not self.closed:
            self.file.close()
            self.lock.unlink(missing_ok=True)
            self.closed = True


class Metrics:
    def __init__(self):
        self.attempts = []
        self.results = {}
        self.active = 0
        self.peak = 0
        self.submissions_started = 0

    def record(self, *, op, phase, status, elapsed, wait, correlation=None):
        self.attempts.append({"operation": op.key, "tenant": op.tenant, "kind": op.kind,
                              "phase": phase, "status": status, "http_ms": round(elapsed, 3),
                              "client_wait_ms": round(wait, 3), "request_id": correlation})

    def report(self):
        groups = {}
        for kind in sorted(KINDS):
            records = [a for a in self.attempts if a["kind"] == kind and a["phase"] == "workload"]
            groups[kind] = {
                "attempts": len(records), "http_latency": distribution([a["http_ms"] for a in records]),
                "client_admission_wait": distribution([a["client_wait_ms"] for a in records]),
                "statuses": dict(Counter(str(a["status"]) for a in records)),
                "accepted_unique_operations": sum(r.get("accepted", False) and r["kind"] == kind
                                                  for r in self.results.values()),
            }
        tenants = {}
        for tenant in {a["tenant"] for a in self.attempts}:
            records = [a for a in self.attempts if a["tenant"] == tenant and a["phase"] == "workload"]
            tenants[tenant] = {"attempts": len(records),
                               "http_latency": distribution([a["http_ms"] for a in records]),
                               "client_wait": distribution([a["client_wait_ms"] for a in records]),
                               "statuses": dict(Counter(str(a["status"]) for a in records))}
        return {"by_tenant": tenants, "submissions_started": self.submissions_started,
                "http_attempts_all_phases": len(self.attempts), "client_peak_inflight_http": self.peak,
                "by_endpoint": groups, "operations": self.results, "attempts": self.attempts}


class Transport:
    def __init__(self, config, client, journal, metrics):
        self.config, self.client, self.journal, self.metrics = config, client, journal, metrics
        self.stop = asyncio.Event()
        self.blockers = set()
        self.deadline = time.monotonic() + config.limits.duration_seconds
        self.hard_deadline = self.deadline + config.limits.completion_seconds
        self.cooldown_until = 0.
        self.sent = sum(e.get("event") == "http_intent" for e in journal.events) if journal else 0
        self.global_slots = asyncio.Semaphore(config.limits.concurrency)
        self.tenant_slots = {t.key: asyncio.Semaphore(config.limits.per_tenant) for t in config.tenants}
        self.endpoint_slots = {k: asyncio.Semaphore(v) for k, v in config.limits.endpoint_concurrency.items()}

    def fatal(self, code):
        self.blockers.add(code)
        self.stop.set()

    async def exchange(self, op, *, phase="workload", path_override=None):
        """One attempt only. Caller handles safe replay with the identical spec."""
        waiting = time.monotonic()
        async with self.global_slots, self.tenant_slots[op.tenant], self.endpoint_slots[op.kind]:
            deadline = self.hard_deadline if phase == "poll" else self.deadline
            while self.cooldown_until > time.monotonic():
                delay = self.cooldown_until - time.monotonic()
                if time.monotonic() + delay >= deadline:
                    self.fatal("RATE_LIMIT_OUTLASTS_BUDGET")
                    return None
                try:
                    await asyncio.wait_for(self.stop.wait(), timeout=delay)
                except asyncio.TimeoutError:
                    pass
                if self.stop.is_set():
                    return None
            if self.stop.is_set() or time.monotonic() >= deadline:
                if not self.stop.is_set():
                    self.fatal("DURATION_BUDGET")
                return None
            if self.sent >= self.config.limits.max_requests:
                self.fatal("HTTP_REQUEST_BUDGET")
                return None
            tenant = next(t for t in self.config.tenants if t.key == op.tenant)
            token = tenant.driver_token if op.kind == "sale" else tenant.admin_token
            method, path, kwargs = request_spec(self.config, op)
            if path_override is not None:
                method, path, kwargs = "GET", path_override, {}
            if method != "GET":
                self.journal.append({"event": "intent", "operation": op.key,
                                     "request_id": op.request_id,
                                     "payload_hash": payload_hash(self.config, op), "at": utc()})
            if self.journal:
                self.journal.append({"event": "http_intent", "operation": op.key, "phase": phase, "at": utc()})
            # No await between budget reservation and dispatch; one event loop owns it.
            self.sent += 1
            self.metrics.active += 1
            self.metrics.peak = max(self.metrics.peak, self.metrics.active)
            start = time.monotonic()
            status, correlation, body, retry = "transport_unknown", None, {}, None
            try:
                async with asyncio.timeout(self.config.limits.timeout_seconds):
                    async with self.client.stream(method, self.config.origin + path,
                                                  headers={"Authorization": "Bearer " + token, "X-D7S-Run-Id": self.config.run_id}, **kwargs) as response:
                        status = response.status_code
                        correlation = response.headers.get("x-request-id")
                        # Never reflect arbitrary headers or server bodies into a report.
                        if correlation:
                            try:
                                correlation = str(UUID(correlation))
                            except (ValueError, TypeError):
                                correlation = None
                        retry = response.headers.get("retry-after")
                        buffer = bytearray()
                        async for chunk in response.aiter_bytes():
                            buffer.extend(chunk)
                            require(len(buffer) <= MAX_RESPONSE_BYTES, "RESPONSE_BYTE_BUDGET")
                        if buffer:
                            try:
                                decoded = json.loads(buffer)
                                if isinstance(decoded, dict):
                                    body = decoded
                                elif op.kind != "catalog" and 200 <= status < 300:
                                    raise Blocker("INVALID_SUCCESS_SHAPE")
                            except (ValueError, UnicodeError):
                                if 200 <= status < 300:
                                    raise Blocker("INVALID_SUCCESS_JSON")
                    if status == 429:
                        self.cooldown_until = max(self.cooldown_until, time.monotonic() + retry_delay(retry))
                    elif status >= 500:
                        self.fatal("SERVER_FAILURE_UNKNOWN_OUTCOME")
                    elif status not in {200, 201, 202, 404}:
                        self.fatal("HTTP_REJECTED_OR_REDIRECTED")
            except Blocker as error:
                status, body = "response_invalid", {}
                self.fatal(error.code)
            except Exception:
                # Exception strings may include URLs/tokens/DB details: never log them.
                status, body = "transport_unknown", {}
                self.fatal("TRANSPORT_UNKNOWN_OUTCOME")
            finally:
                self.metrics.active -= 1
                self.metrics.record(op=op, phase=phase, status=status,
                                    elapsed=(time.monotonic() - start) * 1000,
                                    wait=(start - waiting) * 1000, correlation=correlation)
            expected = 404 if op.kind == "foreign_status" else (
                202 if op.kind == "import" and phase != "poll" else
                201 if op.kind in {"inbound", "route"} and phase != "poll" else 200)
            if status != expected and status != 429:
                self.fatal("UNEXPECTED_HTTP_STATUS")
            if isinstance(status, int) and not correlation:
                self.fatal("CORRELATION_ID_MISSING")
            return status, body


def read_only_connection(config):
    """Lazy optional dependency. One independent observer; no application pool."""
    try:
        import psycopg
        from psycopg.rows import dict_row
    except ImportError:
        raise Blocker("READONLY_OBSERVER_DEPENDENCY_REQUIRED") from None
    return psycopg.connect(config.db_dsn, connect_timeout=5, row_factory=dict_row)


class BudgetCursor:
    def __init__(self, cursor, seconds):
        self.cursor, self.deadline = cursor, time.monotonic() + seconds

    def execute(self, sql, params=None):
        require(time.monotonic() < self.deadline, "READONLY_SNAPSHOT_TIME_BUDGET")
        return self.cursor.execute(sql, params)

    def fetchone(self):
        return self.cursor.fetchone()

    def fetchall(self):
        return self.cursor.fetchall()


class Observer:
    TABLES = (
        "drivers", "visits", "visit_items", "shops", "product_locations", "inventory_locations", "inventory_balances",
        "inventory_movements", "inventory_cost_events", "inventory_cost_states",
        "inventory_cost_policies", "work_sessions", "dispatch_routes", "route_commercial_contexts",
        "product_import_jobs", "product_import_rows", "product_variants",
        "price_book_entries", "domain_audit_events", "transactional_outbox", "operation_idempotency",
    )

    def __init__(self, config):
        self.config = config

    def snapshot(self):
        """Bounded parameterized SELECTs in a READ ONLY, tenant-local transaction.

        No payload/PII/secret columns are selected. Snapshot cannot mint authority:
        role/RLS/environment facts are prerequisites, and HTTP uses real JWTs.
        """
        result = {"tenants": {}, "captured_at": utc()}
        try:
            with read_only_connection(self.config) as conn:
                with conn.cursor() as cursor:
                    cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
                    cursor.execute("SET LOCAL search_path = public, pg_catalog")
                    cursor.execute("SET LOCAL statement_timeout = '5s'")
                    cursor.execute("SET LOCAL lock_timeout = '500ms'")
                    cursor = BudgetCursor(cursor, self.config.limits.observer_seconds)
                    cursor.execute("SELECT current_database() AS db, r.rolsuper, r.rolbypassrls "
                                   "FROM pg_roles r WHERE r.rolname=current_user")
                    role = cursor.fetchone()
                    require(role["db"] == self.config.database_name and not role["rolsuper"]
                            and not role["rolbypassrls"], "OBSERVER_ROLE_OR_DATABASE_UNSAFE")
                    cursor.execute("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                                   "WHERE oid = ANY(SELECT to_regclass(x) FROM unnest(%s::text[]) AS x)",
                                   (list(self.TABLES),))
                    rows = cursor.fetchall()
                    require(len(rows) == len(self.TABLES)
                            and all(r["relrowsecurity"] and r["relforcerowsecurity"] for r in rows),
                            "REQUIRED_FORCE_RLS_MISSING")
                    for tenant in self.config.tenants:
                        cursor.execute("SELECT set_config('app.current_tenant', %s, true)", (str(tenant.company_id),))
                        result["tenants"][tenant.key] = self._tenant(cursor, tenant)
        except Blocker:
            raise
        except Exception:
            raise Blocker("READONLY_OBSERVER_UNAVAILABLE") from None
        return result

    def _tenant(self, c, tenant):
        company = tenant.company_id
        ops = [o for o in self.config.operations if o.tenant == tenant.key]
        fixtures = [{"key": o.key, "kind": o.kind, "request_id": o.request_id,
                     "visit_id": o.fixture.get("visit_id"),
                     "zone_id": o.fixture.get("zone_id"), "driver_id": o.fixture.get("driver_id"),
                     "vehicle_id": o.fixture.get("vehicle_id"),
                     "source_location_id": o.fixture.get("source_location_id"),
                     "location_id": o.fixture.get("location_id"),
                     "unit_price": o.fixture.get("unit_price"),
                     "reference_id": "D7S-IN-" + UUID(o.request_id).hex} for o in ops]
        plan = canonical(fixtures)
        variants = sorted({item["product_variant_id"] for o in ops if o.kind in {"sale", "inbound"}
                           for item in o.fixture.get("items", o.fixture.get("cart_items", []))}
                          | {int(k) for o in ops if o.kind == "route" for k in o.fixture["inventory"]})
        driver_ids = sorted({tenant.admin_id, tenant.driver_id}
                            | {o.fixture["driver_id"] for o in ops if o.kind == "route"})
        c.execute("SELECT id,is_active FROM drivers WHERE company_id=%s AND id=ANY(%s)", (company, driver_ids))
        actors = c.fetchall()
        require(len(actors) == len(driver_ids) and all(a["is_active"] for a in actors), "FIXTURE_ACTOR_NOT_ACTIVE")
        c.execute("SELECT count(*) AS n FROM product_import_jobs WHERE company_id=%s AND id=%s::uuid",
                  (company, tenant.status_job_id))
        require(c.fetchone()["n"] == 1, "OWNED_STATUS_FIXTURE_MISSING")
        foreign_jobs = [t.status_job_id for t in self.config.tenants if t.key != tenant.key]
        c.execute("SELECT count(*) AS n FROM product_import_jobs WHERE company_id<>%s AND id=ANY(%s::uuid[])",
                  (company, foreign_jobs))
        require(c.fetchone()["n"] == 0, "TENANT_RLS_LEAK")
        c.execute("SELECT id,lifecycle_status,packs_per_carton,base_uom_id FROM product_variants "
                  "WHERE company_id=%s AND id=ANY(%s)", (company, variants))
        products = c.fetchall()
        require(len(products) == len(variants) and all(p["lifecycle_status"] == "ACTIVE" for p in products),
                "ACTIVE_VARIANT_FIXTURES_REQUIRED")
        product_map = {p["id"]: p for p in products}
        for op in (o for o in ops if o.kind == "sale"):
            actual = sum(item["quantity"] * product_map[item["product_variant_id"]]["packs_per_carton"]
                         + item["packs_quantity"] for item in op.fixture["cart_items"])
            require(Decimal(str(actual)) <= money(op.expected["base_units"]), "SALE_QUANTITY_EXPECTATION")
        # The bounded D7S inbound profile uses base UOM only. Arbitrary conversions
        # remain backend authority; the generator does not reproduce that engine.
        for op in (o for o in ops if o.kind == "inbound"):
            require(all(item["uom_id"] == product_map[item["product_variant_id"]]["base_uom_id"]
                        for item in op.fixture["items"]), "BASE_UOM_INBOUND_PROFILE_REQUIRED")
            require(sum(money(item["quantity"]) for item in op.fixture["items"])
                    == money(op.expected["base_units"]), "INBOUND_QUANTITY_EXPECTATION")
        locations = sorted({o.fixture["location_id"] for o in ops if o.kind == "inbound"}
                           | {o.fixture["source_location_id"] for o in ops if o.kind == "route"})
        c.execute("SELECT id FROM inventory_locations WHERE company_id=%s AND id=ANY(%s) "
                  "AND is_active IS TRUE AND location_type='WAREHOUSE' AND is_system_managed IS FALSE",
                  (company, locations))
        require(len(c.fetchall()) == len(locations), "WAREHOUSE_FIXTURE_SCOPE")
        inbound_pairs = sorted({(o.fixture["location_id"], item["product_variant_id"])
                                for o in ops if o.kind == "inbound" for item in o.fixture["items"]})
        c.execute("""
            WITH pairs AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
              AS x(location_id int,product_variant_id int))
            SELECT p.location_id,p.product_variant_id,l.id,
              count(DISTINCT d.id) AS audits,count(DISTINCT o.id) AS outboxes
            FROM pairs p LEFT JOIN product_locations l ON l.company_id=%s
              AND l.location_id=p.location_id AND l.product_variant_id=p.product_variant_id
            LEFT JOIN domain_audit_events d ON d.company_id=l.company_id
              AND d.entity_type='ProductLocation' AND d.entity_id=l.id::text
              AND d.event_type='ProductLocationAssigned' AND d.actor_user_id=%s
              AND d.request_id=ANY(%s::uuid[])
            LEFT JOIN transactional_outbox o ON o.company_id=d.company_id
              AND o.aggregate_type='ProductLocation' AND o.aggregate_id=d.entity_id
              AND o.event_type=d.event_type AND o.payload->>'request_id'=d.request_id::text
            GROUP BY p.location_id,p.product_variant_id,l.id
        """, (canonical([{"location_id": loc,"product_variant_id": pid} for loc,pid in inbound_pairs]),
              company, tenant.admin_id, [o.request_id for o in ops if o.kind == "inbound"]))
        assignments = {f"{r['location_id']}:{r['product_variant_id']}": r for r in c.fetchall()}

        c.execute("SELECT id,driver_id,is_authorized_to_sell,is_settled,commercial_context_id FROM work_sessions "
                  "WHERE company_id=%s AND driver_id=ANY(%s) AND end_time IS NULL", (company, driver_ids))
        sessions = c.fetchall()
        if any(o.kind == "sale" for o in ops):
            require(any(r["driver_id"] == tenant.driver_id and r["is_authorized_to_sell"]
                        and not r["is_settled"] and r["commercial_context_id"] is not None for r in sessions),
                    "SALE_ACTIVE_AUTHORIZED_SESSION_REQUIRED")
        route_drivers = {o.fixture["driver_id"] for o in ops if o.kind == "route"}
        require(not any(r["driver_id"] in route_drivers for r in sessions), "ROUTE_DRIVER_ACTIVE_SESSION")
        zone_ids = sorted({o.fixture["zone_id"] for o in ops if o.kind == "route"})
        c.execute("SELECT zone_id,count(*) AS n FROM shops WHERE company_id=%s AND zone_id=ANY(%s) "
                  "GROUP BY zone_id", (company, zone_ids))
        require(all(r["n"] <= self.config.limits.max_route_shops for r in c.fetchall()), "ROUTE_SHOP_BUDGET")
        route_units = sum(q * product_map[int(pid)]["packs_per_carton"]
                          for o in ops if o.kind == "route" for pid,q in o.fixture["inventory"].items())
        require(route_units <= money(self.config.limits.max_base_units), "ROUTE_QUANTITY_BUDGET")
        vehicle_ids = sorted({o.fixture["vehicle_id"] for o in ops if o.kind == "route"})
        c.execute("SELECT l.vehicle_id,COALESCE(sum(b.on_hand_quantity),0) AS quantity "
                  "FROM inventory_locations l LEFT JOIN inventory_balances b "
                  "ON b.company_id=l.company_id AND b.location_id=l.id "
                  "WHERE l.company_id=%s AND l.vehicle_id=ANY(%s) AND l.is_active IS TRUE "
                  "GROUP BY l.vehicle_id", (company, vehicle_ids))
        vehicle_stock = {r["vehicle_id"]: r["quantity"] for r in c.fetchall()}
        require(len(vehicle_stock) == len(vehicle_ids), "VEHICLE_LOCATION_FIXTURE_REQUIRED")
        c.execute("SELECT COALESCE(sum(on_hand_quantity),0) AS physical, "
                  "count(*) FILTER (WHERE on_hand_quantity<0 OR reserved_quantity>on_hand_quantity) AS invalid "
                  "FROM inventory_balances WHERE company_id=%s AND product_variant_id=ANY(%s)", (company, variants))
        stock = c.fetchone()
        c.execute("SELECT COALESCE(sum(quantity),0) AS quantity, COALESCE(sum(inventory_value),0) AS value "
                  "FROM inventory_cost_states WHERE company_id=%s AND product_variant_id=ANY(%s)", (company, variants))
        valuation = c.fetchone()
        c.execute("SELECT method, is_active, selected_at, locked_at FROM inventory_cost_policies WHERE company_id=%s", (company,))
        policy = c.fetchone()
        if any(o.kind in {"sale", "inbound"} for o in ops):
            require(policy is not None and policy["method"] in {"MOVING_AVERAGE", "FIFO"}
                    and policy["is_active"] and policy["selected_at"] is not None
                    and policy["locked_at"] is not None, "ACTIVE_COSTING_FIXTURE_REQUIRED")
        # One batch per category, not per candidate/row. All joins include company.
        c.execute("""
            WITH p AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
              AS x(key text,kind text,request_id text,visit_id int))
            SELECT p.key, v.id, v.driver_id, v.status, v.outcome, v.final_amount_due,
              v.financial_evidence_version, i.completed_at IS NOT NULL AS durable,
              COALESCE(lines.n,0) AS lines, COALESCE(lines.frozen,0) AS frozen_lines,
              COALESCE(m.n,0) AS movements, COALESCE(m.qty,0) AS quantity,
              COALESCE(m.costs,0) AS cost_events, COALESCE(m.cost,0) AS cost
            FROM p LEFT JOIN visits v ON v.company_id=%s AND v.id=p.visit_id
            LEFT JOIN operation_idempotency i ON i.company_id=%s
              AND i.operation='DRIVER_UPDATE_VISIT' AND i.request_id=p.request_id AND i.created_by=%s
            LEFT JOIN LATERAL (
              SELECT count(*) AS n,count(*) FILTER (WHERE vi.financial_evidence_version=4
                AND vi.financial_evidence_frozen_at IS NOT NULL AND vi.selected_price_entry_id IS NOT NULL
                AND vi.commercial_context_id=v.commercial_context_id
                AND vi.sales_revision_id=v.current_sales_revision_id) AS frozen
              FROM visit_items vi WHERE vi.company_id=v.company_id AND vi.visit_id=v.id AND NOT vi.is_cancelled
            ) lines ON true
            LEFT JOIN LATERAL (
              SELECT count(*) AS n,sum(m.quantity) AS qty,count(e.id) AS costs,sum(e.total_cost) AS cost
              FROM inventory_movements m LEFT JOIN inventory_cost_events e
                ON e.company_id=m.company_id AND e.inventory_movement_id=m.id AND e.event_type='OUTBOUND'
              WHERE m.company_id=%s AND m.reference_type='VISIT_ITEM_OUT'
                AND m.reference_id=p.visit_id::text
            ) m ON true WHERE p.kind='sale'
        """, (plan, company, company, tenant.driver_id, company))
        sales = {r["key"]: r for r in c.fetchall()}
        c.execute("""
            WITH p AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
              AS x(key text,kind text,request_id text,reference_id text,location_id int))
            SELECT p.key, i.completed_at IS NOT NULL AS durable, count(m.id) AS movements,
              COALESCE(sum(m.quantity),0) AS quantity, count(e.id) AS cost_events,
              COALESCE(sum(e.total_cost),0) AS cost,
              count(m.id) FILTER (WHERE m.destination_location_id<>p.location_id
                OR m.source_location_id IS NOT NULL OR m.performed_by<>%s) AS wrong_scope,
              count(e.id) FILTER (WHERE e.input_uom_id IS NULL OR e.input_quantity IS NULL
                OR e.input_unit_cost IS NULL) AS missing_purchase_input
            FROM p LEFT JOIN operation_idempotency i ON i.company_id=%s
              AND i.operation='WAREHOUSE_INBOUND' AND i.request_id=p.request_id AND i.created_by=%s
            LEFT JOIN inventory_movements m ON m.company_id=%s
              AND m.reference_type='INBOUND_SUPPLIER' AND m.reference_id=p.reference_id
            LEFT JOIN inventory_cost_events e ON e.company_id=m.company_id
              AND e.inventory_movement_id=m.id AND e.event_type='PURCHASE_IN'
              AND e.cost_basis='PURCHASE_ACTUAL'
            WHERE p.kind='inbound' GROUP BY p.key, i.completed_at
        """, (plan, tenant.admin_id, company, tenant.admin_id, company))
        inbounds = {r["key"]: r for r in c.fetchall()}
        c.execute("""
            WITH p AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
              AS x(key text,kind text,zone_id int,driver_id int,vehicle_id int,source_location_id int))
            SELECT p.key,count(r.id) AS routes,min(r.id) AS route_id,count(ctx.id) AS contexts,
              COALESCE(sum(m.qty),0) AS transferred,COALESCE(sum(m.costs),0) AS cost_events
            FROM p LEFT JOIN dispatch_routes r ON r.company_id=%s AND r.zone_id=p.zone_id
              AND r.driver_id=p.driver_id AND r.vehicle_id=p.vehicle_id
              AND r.source_location_id=p.source_location_id
            LEFT JOIN route_commercial_contexts ctx ON ctx.company_id=r.company_id AND ctx.dispatch_route_id=r.id
            LEFT JOIN LATERAL (
              SELECT sum(m.quantity) AS qty,count(e.id) AS costs
              FROM inventory_movements m LEFT JOIN inventory_cost_events e
                ON e.company_id=m.company_id AND e.inventory_movement_id=m.id
              WHERE m.company_id=r.company_id AND m.reference_id=r.id::text
                AND m.reference_type IN ('DISPATCH_LOAD','DISPATCH_UNLOAD')
            ) m ON true WHERE p.kind='route' GROUP BY p.key
        """, (plan, company))
        routes = {r["key"]: r for r in c.fetchall()}
        for op in (o for o in ops if o.kind == "route"):
            routes[op.key]["expected_transfer"] = sum(q * product_map[int(pid)]["packs_per_carton"]
                                                      for pid,q in op.fixture["inventory"].items())
        c.execute("""
            WITH p AS (SELECT * FROM jsonb_to_recordset(%s::jsonb)
              AS x(key text,kind text,request_id text,unit_price numeric)),
            jobs AS MATERIALIZED (
              SELECT p.key,p.unit_price,j.*
              FROM p LEFT JOIN product_import_jobs j ON j.company_id=%s
                AND j.request_id=p.request_id::uuid AND j.created_by=%s WHERE p.kind='import'
            ), rs AS MATERIALIZED (
              SELECT r.id AS row_id,r.company_id,r.job_id,r.row_number,r.row_identity,r.status,
                r.product_variant_id,v.lifecycle_status,v.base_uom_id,j.unit_price,j.created_by
              FROM jobs j JOIN product_import_rows r ON r.company_id=j.company_id AND r.job_id=j.id
              LEFT JOIN product_variants v ON v.company_id=r.company_id AND v.id=r.product_variant_id
            ), prices AS (
              SELECT r.row_id,count(b.id) AS n FROM rs r LEFT JOIN price_book_entries b
                ON b.company_id=r.company_id AND b.product_variant_id=r.product_variant_id
                AND b.uom_id=r.base_uom_id AND b.amount=r.unit_price AND b.is_published IS TRUE
              GROUP BY r.row_id
            ), audits AS (
              SELECT r.row_id,count(d.id) AS n,min(d.request_id::text) AS event_request
              FROM rs r LEFT JOIN domain_audit_events d ON d.company_id=r.company_id
                AND d.entity_type='ProductVariant' AND d.entity_id=r.product_variant_id::text
                AND d.event_type='ProductPublished' AND d.actor_user_id=r.created_by
              GROUP BY r.row_id
            ), outboxes AS (
              SELECT r.row_id,count(o.id) AS n,min(o.payload->>'request_id') AS event_request
              FROM rs r LEFT JOIN transactional_outbox o ON o.company_id=r.company_id
                AND o.aggregate_type='ProductVariant' AND o.aggregate_id=r.product_variant_id::text
                AND o.event_type='ProductPublished' GROUP BY r.row_id
            ), evidence AS (
              SELECT r.job_id,count(*) AS rows,count(DISTINCT r.row_identity) AS identities,
                min(r.row_number) AS min_row,max(r.row_number) AS max_row,
                count(*) FILTER (WHERE r.status='IMPORTED') AS imported,
                count(DISTINCT r.product_variant_id) AS variants,
                count(*) FILTER (WHERE r.lifecycle_status='ACTIVE') AS active,
                count(*) FILTER (WHERE b.n=1) AS priced,
                count(*) FILTER (WHERE d.n=1) AS audited,
                count(*) FILTER (WHERE o.n=1 AND o.event_request=d.event_request) AS outboxed
              FROM rs r JOIN prices b ON b.row_id=r.row_id JOIN audits d ON d.row_id=r.row_id
                JOIN outboxes o ON o.row_id=r.row_id GROUP BY r.job_id
            )
            SELECT j.key,j.id::text AS job_id,j.status,j.total_rows,j.processed_rows,j.failed_rows,
              j.source_payload_cleared_at IS NOT NULL AS source_cleared,
              EXTRACT(EPOCH FROM (j.started_at-j.created_at))*1000 AS created_to_parsing_ms,
              EXTRACT(EPOCH FROM (j.finished_at-j.created_at))*1000 AS created_to_terminal_ms,
              COALESCE(a.rows,0) AS rows,COALESCE(a.identities,0) AS identities,
              a.min_row,a.max_row,COALESCE(a.imported,0) AS imported,COALESCE(a.variants,0) AS variants,
              COALESCE(a.active,0) AS active,COALESCE(a.priced,0) AS priced,
              COALESCE(a.audited,0) AS audited,COALESCE(a.outboxed,0) AS outboxed
            FROM jobs j LEFT JOIN evidence a ON a.job_id=j.id
        """, (plan, company, tenant.admin_id))
        imports = {r["key"]: r for r in c.fetchall()}
        return {"stock": stock, "valuation": valuation, "sales": sales, "inbounds": inbounds,
                "routes": routes, "imports": imports, "vehicle_stock": vehicle_stock,
                "assignments": assignments}


def validate_baseline(config, snapshot):
    total = sum(money(o.expected["base_units"]) for o in config.operations if o.kind in {"sale", "inbound"})
    total += sum(Decimal(str(r["expected_transfer"])) for data in snapshot["tenants"].values()
                 for r in data["routes"].values())
    require(total <= money(config.limits.max_base_units), "TOTAL_BASE_UNIT_BUDGET")
    for tenant in config.tenants:
        data = snapshot["tenants"][tenant.key]
        require(data["stock"]["invalid"] == 0, "INVALID_BASELINE_STOCK")
        for op in (o for o in config.operations if o.tenant == tenant.key):
            if op.kind == "sale":
                row = data["sales"][op.key]
                require(row["id"] == op.fixture["visit_id"] and row["driver_id"] == tenant.driver_id
                        and row["status"] == "Pending" and not row["durable"] and row["movements"] == 0,
                        "SALE_FIXTURE_NOT_FRESH")
            elif op.kind == "inbound":
                row = data["inbounds"][op.key]
                require(not row["durable"] and row["movements"] == 0, "INBOUND_FIXTURE_NOT_FRESH")
            elif op.kind == "route":
                require(Decimal(str(data["vehicle_stock"][op.fixture["vehicle_id"]])) == 0,
                        "ROUTE_VEHICLE_MUST_START_EMPTY")
                require(data["routes"][op.key]["routes"] == 0, "ROUTE_FIXTURE_NOT_FRESH")
            elif op.kind == "import":
                require(data["imports"][op.key]["job_id"] is None, "IMPORT_REQUEST_NOT_FRESH")


def outcome(op, row):
    """ACK is never used as the accounting oracle."""
    if op.kind == "sale":
        return bool(row["durable"] and row["status"] == "Completed" and row["outcome"] == "Sale"
                    and row["financial_evidence_version"] == 4 and row["lines"] > 0
                    and row["frozen_lines"] == row["lines"]
                    and Decimal(str(row["final_amount_due"])) == money(op.expected["final_amount_due"])
                    and row["movements"] > 0 and row["cost_events"] == row["movements"]
                    and Decimal(str(row["quantity"])) == money(op.expected["base_units"]))
    if op.kind == "inbound":
        cost = sum(money(i["quantity"]) * money(i["unit_cost"]) for i in op.fixture["items"])
        return bool(row["durable"] and row["movements"] > 0 and row["cost_events"] == row["movements"]
                    and row["wrong_scope"] == row["missing_purchase_input"] == 0
                    and Decimal(str(row["quantity"])) == money(op.expected["base_units"])
                    and abs(Decimal(str(row["cost"])) - cost) <= Decimal(".000001") * len(op.fixture["items"]))
    if op.kind == "route":
        return (row["routes"] == row["contexts"] == 1 and row["cost_events"] == 0
                and Decimal(str(row["transferred"])) == Decimal(str(row["expected_transfer"])))
    if op.kind == "import":
        n = op.fixture["rows"]
        return bool(row["status"] == "COMPLETED" and row["source_cleared"]
                    and row["total_rows"] == row["processed_rows"] == n and row["failed_rows"] == 0
                    and all(row[k] == n for k in ("rows", "identities", "imported", "variants",
                                                  "active", "priced", "audited", "outboxed"))
                    and row["min_row"] == 2 and row["max_row"] == n + 1
                    and row["created_to_parsing_ms"] is not None and row["created_to_terminal_ms"] is not None
                    and 0 <= row["created_to_parsing_ms"] <= row["created_to_terminal_ms"])
    return False


def ack_matches(op, row, ack):
    field = "job_id" if op.kind == "import" else "route_id" if op.kind == "route" else None
    return field is None or ack.get(field) is None or ack[field] == row[field]


def assignment_delta_valid(previous, current):
    expected_events = 1 if previous["id"] is None else 0
    return (current["id"] is not None
            and (previous["id"] is None or previous["id"] == current["id"])
            and current["audits"] - previous["audits"] == expected_events
            and current["outboxes"] - previous["outboxes"] == expected_events)


def reconcile(config, before, after, metrics):
    committed = Counter()
    mismatches = []
    evidence = {}
    for tenant in config.tenants:
        old, new = before["tenants"][tenant.key], after["tenants"][tenant.key]
        incoming, outgoing, receipt_value, cogs = Decimal(0), Decimal(0), Decimal(0), Decimal(0)
        for op in (o for o in config.operations if o.tenant == tenant.key and o.kind in MUTATIONS):
            group = {"sale": "sales", "inbound": "inbounds", "route": "routes", "import": "imports"}[op.kind]
            row = new[group][op.key]
            confirmed = outcome(op, row) and ack_matches(op, row, metrics.results.get(op.key, {}))
            evidence[op.key] = {"kind": op.kind, "tenant": op.tenant, "committed": confirmed, "observed": row}
            if confirmed:
                committed[op.kind] += 1
            else:
                mismatches.append(op.key)
            # Include actual durable ledger quantities, including partially observed/unknown effects.
            if op.kind == "sale":
                outgoing += Decimal(str(row["quantity"]))
                cogs += Decimal(str(row["cost"]))
            elif op.kind == "inbound":
                incoming += Decimal(str(row["quantity"]))
                receipt_value += Decimal(str(row["cost"]))
        for identity, previous in old["assignments"].items():
            assignment = new["assignments"][identity]
            if not assignment_delta_valid(previous, assignment):
                mismatches.append(tenant.key + ":product_location:" + identity)
        for field_name, expected in (
            ("physical", incoming - outgoing),
            ("quantity", incoming - outgoing),
            ("value", receipt_value - cogs),
        ):
            group = "stock" if field_name == "physical" else "valuation"
            actual = Decimal(str(new[group][field_name])) - Decimal(str(old[group][field_name]))
            if abs(actual - expected) > Decimal(".000001"):
                mismatches.append(tenant.key + ":" + field_name)
        if new["stock"]["invalid"]:
            mismatches.append(tenant.key + ":invalid_stock")
    return {"committed_business_operations": dict(committed),
            "durably_admitted_import_jobs": sum(r["job_id"] is not None for d in after["tenants"].values()
                                                  for r in d["imports"].values()), "mismatches": mismatches,
            "import_timing": {
                "created_to_parsing": distribution([float(r["created_to_parsing_ms"])
                    for d in after["tenants"].values() for r in d["imports"].values()
                    if r["created_to_parsing_ms"] is not None]),
                "created_to_terminal": distribution([float(r["created_to_terminal_ms"])
                    for d in after["tenants"].values() for r in d["imports"].values()
                    if r["created_to_terminal_ms"] is not None]),
                "created_to_parsing_includes_source_read_and_verification": True,
                "precise_queue_claim_lag_requires_independent_queue_collector": True,
            }, "operations": evidence, "before": before, "after": after}


async def preflight(config, transport):
    """Small real-auth read path, both HTTP and SQL tenant isolation evidence."""
    for tenant in config.tenants:
        for kind in ("catalog", "owned_status", "foreign_status"):
            op = Operation("PREFLIGHT_" + kind.upper(), tenant.key, kind, config.run_id, {}, {})
            result = await transport.exchange(op, phase="preflight")
            require(result is not None and result[0] == (404 if kind == "foreign_status" else 200),
                    "AUTH_OR_ISOLATION_PREFLIGHT_FAILED")
            if kind == "owned_status":
                require(result[1].get("job_id") == tenant.status_job_id, "OWNED_STATUS_RESPONSE_MISMATCH")
        sale = next((o for o in config.operations if o.tenant == tenant.key and o.kind == "sale"), None)
        if sale:
            result = await transport.exchange(sale, phase="preflight",
                                              path_override=f"/visits/{sale.fixture['visit_id']}")
            require(result is not None and result[0] == 200
                    and result[1].get("visit_id") == sale.fixture["visit_id"]
                    and result[1].get("driver_id") == tenant.driver_id, "DRIVER_AUTH_PREFLIGHT_FAILED")
    require(not transport.stop.is_set(), "PREFLIGHT_STOPPED")


def safe_result(op, accepted=False, **fields):
    return {"kind": op.kind, "tenant": op.tenant, "operation_id": op.request_id,
            "accepted": accepted, **fields}


async def submit(config, transport, op, index, started, current):
    # Open-loop arrivals with finite total submissions; queued tasks are not sockets.
    arrival = started + index / config.limits.arrival_rate
    delay = arrival - time.monotonic()
    if delay > 0:
        try:
            await asyncio.wait_for(transport.stop.wait(), timeout=delay)
        except asyncio.TimeoutError:
            pass
    if transport.stop.is_set():
        return
    if time.monotonic() >= transport.deadline:
        transport.fatal("DURATION_BUDGET")
        return
    transport.metrics.submissions_started += 1
    result = safe_result(op, arrival_lag_ms=round(max(0., time.monotonic() - arrival) * 1000, 3))
    transport.metrics.results[op.key] = result
    prior_attempts = transport.journal.attempts(op) if transport.journal and op.kind in MUTATIONS else 0
    if prior_attempts:
        group = {"sale": "sales", "inbound": "inbounds", "route": "routes", "import": "imports"}[op.kind]
        row = current["tenants"][op.tenant][group][op.key]
        ack = next((e for e in reversed(transport.journal.events)
                    if e.get("event") == "ack" and e.get("operation") == op.key), {})
        result["accepted"] = bool(ack)
        result.update({k: ack[k] for k in ("job_id", "route_id") if k in ack})
        if not ack_matches(op, row, result):
            transport.fatal("ACK_RECONCILIATION_ID_MISMATCH")
            return
        if outcome(op, row):
            result["reconciled_without_replay"] = True
            return
        if op.kind == "route":
            result["unknown_outcome"] = True
            transport.fatal("ROUTE_PREVIOUS_ATTEMPT_UNRESOLVED_NO_REPLAY")
            return
        if op.kind == "import" and row["job_id"] is not None:
            result["job_id"] = row["job_id"]
            result["admission_reconciled"] = True
            return
    attempts = config.limits.max_attempts if op.replay_safe else 1
    for _ in range(prior_attempts, attempts):
        response = await transport.exchange(op)
        if response is None:
            return
        status, body = response
        if status == 429:
            if not op.replay_safe:
                # The route has no durable replay envelope, even after 429.
                transport.fatal("ROUTE_REJECTED_NO_REPLAY")
                result["unknown_outcome"] = True
                return
            continue
        expected = 404 if op.kind == "foreign_status" else (202 if op.kind == "import" else
                   201 if op.kind in {"route", "inbound"} else 200)
        if status != expected:
            if op.kind in MUTATIONS:
                result["unknown_outcome"] = True
            return
        if op.kind == "owned_status":
            tenant = next(t for t in config.tenants if t.key == op.tenant)
            if body.get("job_id") != tenant.status_job_id:
                transport.fatal("OWNED_STATUS_RESPONSE_MISMATCH")
                return
        result["accepted"] = True
        if op.kind == "import":
            try:
                result["job_id"] = str(UUID(body["job_id"]))
            except (KeyError, ValueError, TypeError):
                transport.fatal("IMPORT_ACK_SHAPE")
                return
            result["admitted_only"] = True
        elif op.kind == "route":
            if type(body.get("route_id")) is not int or body["route_id"] <= 0:
                transport.fatal("ROUTE_ACK_SHAPE")
                return
            result["route_id"] = body["route_id"]
        if op.kind in MUTATIONS:
            transport.journal.append({"event": "ack", "operation": op.key,
                                      **{k: result[k] for k in ("job_id", "route_id") if k in result}, "at": utc()})
        return
    result["attempt_budget_exhausted"] = True
    transport.fatal("ATTEMPT_BUDGET_EXHAUSTED")


async def guarded_submit(config, transport, op, index, started, current):
    try:
        return await submit(config, transport, op, index, started, current)
    except asyncio.CancelledError:
        transport.fatal("GENERATOR_CANCELLED_UNKNOWN_OUTCOME")
        raise
    except Exception as error:
        transport.fatal(error.code if isinstance(error, Blocker) else "SUBMISSION_FATAL_UNKNOWN_OUTCOME")


async def poll_imports(config, transport):
    outstanding = {o.key: o for o in config.operations if o.kind == "import"
                   and transport.metrics.results.get(o.key, {}).get("job_id")}
    terminal = {"COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED", "CANCELLED",
                "VALIDATION_FAILED", "NEEDS_MAPPING"}
    while outstanding and not transport.stop.is_set() and time.monotonic() < transport.hard_deadline:
        for key, op in list(outstanding.items()):
            job = transport.metrics.results[key]["job_id"]
            probe = Operation(op.key, op.tenant, "owned_status", op.request_id, {}, {})
            response = await transport.exchange(probe, phase="poll", path_override=f"/simple-products/imports/{job}")
            if response is None:
                return
            status, body = response
            if status == 429:
                continue
            if status != 200 or body.get("job_id") != job:
                transport.fatal("IMPORT_STATUS_SCOPE")
                return
            state = body.get("status")
            # Allow-listed enum and numeric counts only; raw rows/errors never logged.
            if state not in {"QUEUED", "PARSING", "VALIDATING", "IMPORTING", "RETRYING"} | terminal:
                transport.fatal("IMPORT_STATUS_SHAPE")
                return
            result = transport.metrics.results[key]
            result["terminal_status"] = state
            if state in terminal:
                outstanding.pop(key)
                if state != "COMPLETED":
                    transport.fatal("IMPORT_NOT_FULLY_COMPLETED")
                    return
        if outstanding:
            try:
                await asyncio.wait_for(transport.stop.wait(), timeout=config.limits.poll_seconds)
            except asyncio.TimeoutError:
                pass
    if outstanding:
        transport.blockers.add("IMPORT_COMPLETION_UNOBSERVED")


def target_addresses(config):
    u = urlsplit(config.origin)
    addresses = socket.getaddrinfo(u.hostname, u.port or 443, type=socket.SOCK_STREAM)
    import ipaddress
    require(bool(addresses), "TARGET_DNS_EMPTY")
    for row in addresses:
        address = ipaddress.ip_address(row[4][0])
        require(not (address.is_loopback or address.is_link_local or address.is_unspecified
                     or address.is_multicast), "TARGET_DNS_LOCAL_DENIED")


def ingress_evidence(path: Path | None, config, start: str, end: str):
    """Independent ingress samples are supplied by the operator, never fabricated.

    Validation checks scope/time/definition, not authenticity of an external file.
    Raw metric labels and arbitrary strings are not copied to the report.
    """
    if path is None:
        return {"reported_1000_at_ingress": False, "blocker": "INGRESS_EVIDENCE_REQUIRED"}
    try:
        require(path.stat().st_size <= 1024 * 1024, "INGRESS_EVIDENCE_BUDGET")
        data = json.loads(path.read_bytes())
        require(data["schema"] == 1 and data["run_id"] == config.run_id
                and data["origin"] == config.origin
                and data["metric"] == "active_authenticated_http1_connections"
                and data["includes_generator_only"] is True
                and data["collector_external_to_generator"] is True, "INGRESS_EVIDENCE_SCOPE")
        begin, finish = datetime.fromisoformat(start), datetime.fromisoformat(end)
        require(begin.tzinfo is not None and finish.tzinfo is not None, "INGRESS_TIMESTAMP")
        samples = data["samples"]
        require(isinstance(samples, list) and 1 <= len(samples) <= 10000, "INGRESS_SAMPLES")
        eligible = []
        previous = None
        for sample in samples:
            at = datetime.fromisoformat(sample["at"])
            count = sample["active_connections"]
            require(at.tzinfo is not None and type(count) is int and 0 <= count <= 100000
                    and (previous is None or at > previous), "INGRESS_SAMPLE_SHAPE")
            previous = at
            if begin <= at <= finish:
                eligible.append(count)
        require(bool(eligible), "INGRESS_WINDOW_NOT_OBSERVED")
        peak = max(eligible)
        return {"reported_1000_at_ingress": peak >= 1000, "peak_observed_at_ingress": peak,
                "samples_in_run_window": len(eligible), "source": "operator_external_collector",
                "authenticity_requires_independent_review": True}
    except Exception:
        return {"reported_1000_at_ingress": False, "blocker": "INGRESS_EVIDENCE_INVALID"}


async def http1_body(reader, headers, timeout):
    """Drain one bounded HTTP/1 response, then keep that socket open."""
    require(headers.get("content-encoding", "identity") == "identity", "CONNECTION_PROBE_ENCODING")
    if headers.get("transfer-encoding", "").lower() == "chunked":
        total = 0
        while True:
            raw = await asyncio.wait_for(reader.readline(), timeout)
            require(len(raw) <= 128 and raw.endswith(b"\r\n"), "HTTP_CHUNK_SHAPE")
            size = int(raw.split(b";", 1)[0], 16)
            total += size
            require(0 <= total <= MAX_RESPONSE_BYTES, "CONNECTION_RESPONSE_BUDGET")
            if size == 0:
                trailer_size = 0
                while True:
                    line = await asyncio.wait_for(reader.readline(), timeout)
                    trailer_size += len(line)
                    require(trailer_size <= 8192 and line.endswith(b"\r\n"), "HTTP_TRAILER_SHAPE")
                    if line == b"\r\n":
                        return
            await asyncio.wait_for(reader.readexactly(size + 2), timeout)
    else:
        require("content-length" in headers, "HTTP_LENGTH_REQUIRED_FOR_KEEPALIVE")
        size = int(headers["content-length"])
        require(0 <= size <= MAX_RESPONSE_BYTES, "CONNECTION_RESPONSE_BUDGET")
        await asyncio.wait_for(reader.readexactly(size), timeout)


async def connection_probe(config):
    """Actual TLS sockets with one authenticated GET each; NOT ingress proof.

    No load clients, fake JWTs, HTTP/2 multiplexing, or mutating requests.
    Connections close on server EOF/error; idle keepalive failure is evidence.
    """
    require(not any(o.kind in MUTATIONS for o in config.operations), "CONNECTION_MODE_READS_ONLY")
    target_addresses(config)
    u = urlsplit(config.origin)
    context = ssl.create_default_context()
    context.set_alpn_protocols(["http/1.1"])
    active, peak, opened, authenticated = 0, 0, 0, 0
    samples, errors, latencies = [], Counter(), []
    stop = asyncio.Event()
    cooldown = 0.
    reserved, http_writes, drained = 0, 0, 0
    statuses = Counter()
    start = time.monotonic()
    deadline = start + config.limits.duration_seconds
    global_slots = asyncio.Semaphore(config.limits.concurrency)
    tenant_slots = {t.key: asyncio.Semaphore(config.limits.per_tenant) for t in config.tenants}
    endpoint_slots = asyncio.Semaphore(config.limits.endpoint_concurrency["catalog"])

    async def one(index):
        nonlocal active, peak, opened, authenticated, cooldown, reserved, http_writes, drained
        tenant = config.tenants[index % len(config.tenants)]
        writer = None
        counted = False
        delay = start + index / config.limits.arrival_rate - time.monotonic()
        if delay > 0:
            try:
                await asyncio.wait_for(stop.wait(), timeout=delay)
            except asyncio.TimeoutError:
                pass
        async with global_slots, tenant_slots[tenant.key], endpoint_slots:
            if stop.is_set():
                return
            if time.monotonic() >= deadline:
                errors["duration_budget"] += 1
                stop.set()
                return
            if cooldown > time.monotonic():
                errors["rate_limit_stop"] += 1
                stop.set()
                return
            if reserved >= config.limits.max_requests:
                errors["request_budget"] += 1
                stop.set()
                return
            reserved += 1
            try:
                async with asyncio.timeout(config.limits.timeout_seconds):
                    reader, writer = await asyncio.wait_for(asyncio.open_connection(
                        u.hostname, u.port or 443, ssl=context, server_hostname=u.hostname,
                        limit=65536), config.limits.timeout_seconds)
                    opened += 1
                    peer = writer.get_extra_info("peername")
                    import ipaddress
                    addr = ipaddress.ip_address(peer[0])
                    require(not (addr.is_loopback or addr.is_link_local or addr.is_unspecified
                                 or addr.is_multicast), "CONNECTION_PEER_LOCAL_DENIED")
                    require(time.monotonic() < deadline, "CONNECTION_DURATION_BUDGET")
                    host = u.netloc
                    request_start = time.monotonic()
                    http_writes += 1
                    writer.write(("GET /simple-products?limit=10 HTTP/1.1\r\nHost: " + host +
                                  "\r\nAuthorization: Bearer " + tenant.admin_token +
                                  "\r\nX-D7S-Run-Id: " + config.run_id +
                                  "\r\nAccept-Encoding: identity\r\nConnection: keep-alive\r\n\r\n").encode("ascii"))
                    await asyncio.wait_for(writer.drain(), config.limits.timeout_seconds)
                    drained += 1
                    head = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), config.limits.timeout_seconds)
                    require(len(head) <= 65536, "HTTP_HEADERS_BUDGET")
                    lines = head.decode("iso-8859-1").split("\r\n")
                    status = int(lines[0].split()[1])
                    statuses[str(status)] += 1
                    headers = {}
                    for line in lines[1:]:
                        if line:
                            k, v = line.split(":", 1)
                            require(k.lower() not in headers, "DUPLICATE_HTTP_HEADER")
                            headers[k.lower()] = v.strip()
                    if status == 429:
                        cooldown = time.monotonic() + retry_delay(headers.get("retry-after"))
                        errors["429"] += 1
                        stop.set()  # No further admissions; never bypass the real IP limiter.
                        return
                    require(status == 200 and headers.get("connection", "").lower() != "close",
                            "CONNECTION_GET_REJECTED")
                    await http1_body(reader, headers, config.limits.timeout_seconds)
                latencies.append((time.monotonic() - request_start) * 1000)
                authenticated += 1
                active += 1
                counted = True
                peak = max(peak, active)
                hold = min(config.limits.hold_seconds, max(0., deadline - time.monotonic()))
                try:
                    # EOF means the ingress closed it; don't count a dead idle socket.
                    tail = await asyncio.wait_for(reader.read(1), timeout=hold)
                    errors["unexpected_data" if tail else "server_closed_keepalive"] += 1
                    stop.set()
                except asyncio.TimeoutError:
                    samples.append({"held_seconds": round(hold, 3)})
            except Exception:
                errors["connection_failure"] += 1
                stop.set()
            finally:
                if counted:
                    active -= 1
                if writer:
                    writer.close()
                    try:
                        await asyncio.wait_for(writer.wait_closed(), timeout=2)
                    except Exception:
                        pass

    await asyncio.gather(*(one(i) for i in range(config.limits.connections)))
    return {"configured_connection_attempts": config.limits.connections,
            "request_budget_reserved": reserved, "http_write_attempts": http_writes,
            "http_writes_drained_to_socket": drained, "received_http_statuses": dict(statuses),
            "tls_connections_opened_total": opened,
            "authenticated_keepalive_total": authenticated,
            "client_peak_locally_open_authenticated_sockets": peak,
            "client_hold_observations": samples, "errors": dict(errors),
            "authenticated_get_latency": distribution(latencies),
            "client_counts_are_not_ingress_proof": True}


def coverage(config):
    present = {o.kind for o in config.operations}
    blockers = []
    if not KINDS <= present:
        blockers.append("MIXED_ENDPOINT_COVERAGE_INCOMPLETE")
    if len(config.operations) != 1000:
        blockers.append("NOT_1000_PLANNED_SUBMISSIONS")
    if {o.tenant for o in config.operations} != {t.key for t in config.tenants}:
        blockers.append("TENANT_WORKLOAD_COVERAGE_INCOMPLETE")
    return blockers


async def mixed_run(config, journal, *, mutations):
    require(mutations or not any(o.kind in MUTATIONS for o in config.operations), "MUTATIONS_OPT_IN_REQUIRED")
    target_addresses(config)
    try:
        import httpx
    except ImportError:
        raise Blocker("HTTP_CLIENT_DEPENDENCY_REQUIRED") from None
    metrics = Metrics()
    observer = Observer(config) if mutations else None
    before = None
    current = None
    if observer:
        current = await asyncio.to_thread(observer.snapshot)
        saved = journal.latest("baseline")
        if saved:
            before = saved["snapshot"]
            journal.append({"event": "recovery_snapshot", "snapshot": current})
            for op in (o for o in config.operations if o.kind in MUTATIONS):
                if op.kind == "route" and journal.attempts(op):
                    require(outcome(op, current["tenants"][op.tenant]["routes"][op.key]),
                            "ROUTE_PREVIOUS_ATTEMPT_UNRESOLVED_NO_REPLAY")
        else:
            validate_baseline(config, current)
            before = current
            journal.append({"event": "baseline", "snapshot": before})
    async with httpx.AsyncClient(http2=False, verify=True, trust_env=False, follow_redirects=False,
                                 timeout=config.limits.timeout_seconds,
                                 limits=httpx.Limits(max_connections=config.limits.concurrency,
                                                     max_keepalive_connections=config.limits.concurrency)) as client:
        transport = Transport(config, client, journal, metrics)
        try:
            await preflight(config, transport)
            started = time.monotonic()
            results = await asyncio.gather(*(guarded_submit(config, transport, op, i, started, current)
                                            for i, op in enumerate(config.operations)), return_exceptions=True)
            for result in results:
                if isinstance(result, BaseException):
                    transport.fatal(result.code if isinstance(result, Blocker) else "SUBMISSION_FATAL_UNKNOWN_OUTCOME")
            await poll_imports(config, transport)
        except Blocker as error:
            transport.fatal(error.code)
        except asyncio.CancelledError:
            transport.fatal("GENERATOR_CANCELLED_UNKNOWN_OUTCOME")
            # Dispatched HTTP may still commit. Local journal is the recovery authority.
        except Exception:
            transport.fatal("GENERATOR_FATAL_UNKNOWN_OUTCOME")
    evidence = None
    if observer:
        try:
            after = await asyncio.to_thread(observer.snapshot)
            evidence = reconcile(config, before, after, metrics)
            if evidence["mismatches"]:
                transport.blockers.add("ACCOUNTING_OR_COMPLETION_MISMATCH")
            journal.append({"event": "reconciliation", "evidence": evidence})
        except Blocker as error:
            transport.blockers.add(error.code)
    report = metrics.report()
    report["planned_submissions"] = len(config.operations)
    report["http_budget_used_logical_run"] = transport.sent
    report["metrics_scope"] = "HTTP and arrivals: current process; accounting and acceptance: logical journal run"
    report["reconciliation"] = evidence
    blockers = sorted(transport.blockers | set(coverage(config)))
    report["blockers"] = blockers
    report["slo"] = slo_result(config, metrics)
    # Driver cannot attest hardware, 4 worker deployment, fairness or DB locks from HTTP.
    report["gate"] = "OPEN_REQUIRES_INDEPENDENT_STAGING_REVIEW"
    report["blockers"] += ["DEPLOYMENT_FACTS_REQUIRE_INDEPENDENT_REVIEW",
                           "CARDINALITY_REQUIRES_INDEPENDENT_REVIEW",
                           "SERVER_RESOURCE_DB_WAIT_FAIRNESS_EVIDENCE_REQUIRED",
                           "PRECISE_QUEUE_CLAIM_LAG_EVIDENCE_REQUIRED"]
    report["independent_evidence_required"] = [
        "REAL_TLS_INGRESS_CONNECTIONS", "DEPLOYED_SHA_AND_FOUR_WORKERS",
        "PRODUCTION_LIKE_CARDINALITY", "CPU_MEMORY_DB_WAIT_WORK_SESSION_FAIRNESS",
        "PRECISE_QUEUE_CLAIM_LAG",
    ]
    return report


async def collect_reconciliation(config, journal):
    require(journal.latest("baseline") is not None, "RECONCILIATION_BASELINE_REQUIRED")
    snapshot = await asyncio.to_thread(Observer(config).snapshot)
    metrics = Metrics()
    for event in journal.events:
        if event.get("event") == "ack":
            metrics.results[event["operation"]] = event
    evidence = reconcile(config, journal.latest("baseline")["snapshot"], snapshot, metrics)
    journal.append({"event": "reconciliation", "evidence": evidence})
    return {"profile": "READONLY_RECONCILIATION", "http_requests": 0, "business_mutations": 0,
            "reconciliation": evidence, "gate": "OPEN_REQUIRES_INDEPENDENT_STAGING_REVIEW",
            "blockers": (["ACCOUNTING_OR_COMPLETION_MISMATCH"] if evidence["mismatches"] else [])
                        + ["DEPLOYMENT_RESOURCE_CARDINALITY_FAIRNESS_EVIDENCE_REQUIRES_REVIEW"]}


def slo_result(config, metrics):
    reads = [r["http_ms"] for r in metrics.attempts if r["phase"] == "workload" and r["kind"] not in MUTATIONS]
    writes = [r["http_ms"] for r in metrics.attempts if r["phase"] == "workload" and r["kind"] in MUTATIONS]
    observed = {"read_p95_ms": percentile(reads, .95),
                "write_p95_ms": percentile(writes, .95), "write_p99_ms": percentile(writes, .99)}
    return {"approved": config.slo, "observed": observed,
            "within": {k: observed[k] is not None and observed[k] <= v for k, v in config.slo.items()},
            "latency_includes_rejections_and_errors": True}


def dry_plan(config, mode):
    total_bytes = sum(len(source_bytes(config, o)) for o in config.operations if o.kind == "import")
    require(total_bytes <= config.limits.max_source_bytes, "CUMULATIVE_SOURCE_BYTE_BUDGET")
    return {"mode": "DRY_RUN", "network_requests": 0, "mutations": 0,
            "origin": config.origin, "run_id": config.run_id, "release_sha": config.release_sha,
            "planned_submissions": len(config.operations), "profile": mode,
            "by_kind": dict(Counter(o.kind for o in config.operations)),
            "planned_source_bytes": total_bytes, "limits": config.limits.__dict__,
            "blockers_for_mixed_gate": coverage(config),
            "gate": "OPEN_REQUIRES_REAL_STAGING_EVIDENCE"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("mixed", "connections", "reconcile"), default="mixed")
    parser.add_argument("--execute", action="store_true", help="Opt in to external staging HTTP")
    parser.add_argument("--allow-mutations", action="store_true", help="Separate synthetic writes opt-in")
    parser.add_argument("--journal", type=Path, help="Private local journal; required for live mixed mutations")
    parser.add_argument("--resume", action="store_true", help="Replay only supported durable contracts")
    parser.add_argument("--ingress-evidence", type=Path, help="Independent ingress samples after the run")
    args = parser.parse_args(argv)
    journal = None
    start = utc()
    try:
        require(not args.allow_mutations or args.execute, "MUTATIONS_REQUIRE_EXECUTE")
        require(not args.resume or args.journal is not None, "RESUME_JOURNAL_REQUIRED")
        config = read_config(execute=args.execute, mutations=args.allow_mutations,
                             observe=args.mode == "reconcile")
        plan = dry_plan(config, args.mode)
        if not args.execute:
            print(canonical(plan))
            return 0
        if args.mode == "reconcile":
            require(not args.allow_mutations and args.journal is not None, "RECONCILE_READONLY_JOURNAL_REQUIRED")
            journal = Journal(args.journal, config, resume=True)
            report = asyncio.run(collect_reconciliation(config, journal))
        elif args.mode == "connections":
            require(not args.allow_mutations, "CONNECTION_MODE_NO_MUTATIONS")
            report = asyncio.run(connection_probe(config))
            report["gate"] = "OPEN_REQUIRES_INDEPENDENT_STAGING_REVIEW"
            report["blockers"] = ["CONNECTION_PROBE_ERRORS"] if report["errors"] else []
        else:
            if args.allow_mutations:
                require(args.journal is not None, "DURABLE_JOURNAL_REQUIRED")
                journal = Journal(args.journal, config, resume=args.resume)
            report = asyncio.run(mixed_run(config, journal, mutations=args.allow_mutations))
        end = utc()
        report.update({"origin": config.origin, "run_id": config.run_id,
                       "release_sha": config.release_sha, "started_at": start, "finished_at": end})
        report["ingress"] = ingress_evidence(args.ingress_evidence, config, start, end)
        if not report["ingress"]["reported_1000_at_ingress"]:
            report["blockers"].append(report["ingress"].get("blocker", "INGRESS_BELOW_1000"))
        print(canonical(report))
        # A zero exit means only bounded observations collected, never gate PASS.
        return 2 if report["blockers"] else 0
    except Blocker as error:
        print(canonical({"gate": "BLOCKED", "blockers": [error.code]}))
        return 2
    except KeyboardInterrupt:
        print(canonical({"gate": "BLOCKED", "blockers": ["INTERRUPTED_RECONCILE_FROM_JOURNAL"]}))
        return 2
    except Exception:
        print(canonical({"gate": "BLOCKED", "blockers": ["SAFE_DRIVER_FAILURE_REVIEW_JOURNAL"]}))
        return 2
    finally:
        if journal:
            journal.close()


if __name__ == "__main__":
    raise SystemExit(main())
