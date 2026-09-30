"""Focused contracts for independent review. Do not execute during implementation.

No application/database imports, real sockets, jobs, servers or workers.
"""
from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone
from email.utils import format_datetime
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from uuid import UUID

from scripts import staging_d7s_mixed_load as driver
from scripts import staging_d7s_mixed_load_config as config


def manifest():
    return {
        "schema": 1, "run_id": "f85d996d-c77a-43ed-9ac2-5c5ec7be15a7",
        "staging": {"isolated_synthetic": True, "generator_external": True,
                    "fixtures_exclusive": True, "web_workers": 4,
                    "release_sha": "a" * 40, "database_name": "d7s_synthetic",
                    "forbidden_origins": ["https://dev.example.invalid", "https://prod.example.invalid"]},
        "slo": {"read_p95_ms": 1000, "write_p95_ms": 2000, "write_p99_ms": 3000},
        "tenants": [
            {"key": "A", "company_id": 101, "admin_id": 201, "driver_id": 301,
             "status_job_id": "4f4a1d67-de74-416f-bd9d-7dc60526be62"},
            {"key": "B", "company_id": 102, "admin_id": 202, "driver_id": 302,
             "status_job_id": "6b0a9a31-ea46-4f92-ac74-566ec0d058c8"},
        ],
        "operations": [
            {"key": "READ_A", "tenant": "A", "kind": "catalog"},
            {"key": "READ_B", "tenant": "B", "kind": "catalog"},
        ],
    }


def env_for(value=None):
    return {"WANASAH_D7S_URL": "https://stage.example.invalid",
            "WANASAH_D7S_APPROVED_URL": "https://stage.example.invalid",
            "WANASAH_D7S_CONFIG_JSON": json.dumps(manifest() if value is None else value)}


def load(value=None):
    return config.read_config(env_for(value))


def op(kind, fixture, expected=None):
    value = manifest()
    value["operations"].append({"key": "WRITE_A", "tenant": "A", "kind": kind,
                                "fixture": fixture, "expected": expected or {}})
    result = load(value)
    return result, result.operations[-1]


def sale():
    return op("sale", {"visit_id": 401, "cash_collected": "2.000",
                      "cart_items": [{"product_variant_id": 501, "quantity": 0, "packs_quantity": 2}]},
              {"final_amount_due": "2.000", "base_units": "2"})


class ConfigContracts(unittest.TestCase):
    def test_dry_run_never_enters_network_or_creates_journal(self):
        with patch.dict("os.environ", env_for(), clear=True), patch.object(driver.asyncio, "run") as run, \
                patch("builtins.print") as output:
            self.assertEqual(driver.main([]), 0)
        run.assert_not_called()
        report = json.loads(output.call_args.args[0])
        self.assertEqual((report["network_requests"], report["mutations"]), (0, 0))
        self.assertIn("REAL_STAGING", report["gate"])

    def test_exact_target_and_https_are_required(self):
        for target in ("http://stage.example.invalid", "https://localhost", "https://127.0.0.1",
                       "https://stage.example.invalid/private", "https://stage.example.invalid?x=1",
                       "https://user:password@stage.example.invalid", "https://other.example.invalid"):
            with self.subTest(target=target), self.assertRaises(config.Blocker):
                env = env_for()
                env["WANASAH_D7S_URL"] = target
                config.read_config(env)

    def test_duplicate_json_and_nonfinite_values_fail_closed(self):
        for raw in ('{"a":1,"a":2}', '{"a":NaN}', '[]'):
            with self.assertRaises(config.Blocker):
                config.json_object(raw)

    def test_live_requires_explicit_staging_ack(self):
        with self.assertRaises(config.Blocker) as error:
            config.read_config(env_for(), execute=True)
        self.assertEqual(error.exception.code, "EXTERNAL_STAGING_ACK_REQUIRED")

    def test_separate_mutations_ack(self):
        env = env_for()
        env["WANASAH_D7S_ACK"] = config.ACK
        with self.assertRaises(config.Blocker) as error:
            config.read_config(env, execute=True, mutations=True)
        self.assertEqual(error.exception.code, "MUTATIONS_ACK_REQUIRED")

    def test_tenant_ids_are_distinct_and_operator_supplied(self):
        value = manifest()
        value["tenants"][1]["company_id"] = 101
        with self.assertRaises(config.Blocker):
            load(value)
        value = manifest()
        del value["tenants"][0]["driver_id"]
        with self.assertRaises(config.Blocker):
            load(value)

    def test_resource_rows_cost_and_concurrency_caps(self):
        value = manifest()
        value["limits"] = {"concurrency": 1001}
        with self.assertRaises(config.Blocker):
            load(value)
        with self.assertRaises(config.Blocker):
            op("import", {"rows": 50001, "unit_price": "1"})
        with self.assertRaises(config.Blocker):
            op("import", {"rows": 50000, "unit_price": "100"})

    def test_route_single_attempt_and_fresh_driver(self):
        c, route = op("route", {"zone_id": 601, "driver_id": 303, "vehicle_id": 701,
                               "source_location_id": 801, "inventory": {"501": 1}})
        method, path, body = driver.request_spec(c, route)
        self.assertEqual((method, path), ("POST", "/dispatch/route"))
        self.assertNotIn("request_id", body["json"])
        self.assertFalse(route.replay_safe)
        with self.assertRaises(config.Blocker):
            op("route", {"zone_id": 601, "driver_id": 301, "vehicle_id": 701,
                         "source_location_id": 801, "inventory": {"501": 1}})

    def test_stable_identity_rejects_changed_input_on_resume(self):
        c, operation = sale()
        again, repeated = sale()
        self.assertEqual(operation.request_id, repeated.request_id)
        self.assertEqual(driver.payload_hash(c, operation), driver.payload_hash(again, repeated))
        changed = replace(operation, fixture={**operation.fixture, "cash_collected": "1.000"})
        self.assertNotEqual(driver.payload_hash(c, operation), driver.payload_hash(c, changed))

    def test_no_arbitrary_payload_or_admin_operation_fields(self):
        with self.assertRaises(config.Blocker):
            op("sale", {"visit_id": 401, "cash_collected": "2", "cart_items": [],
                        "price": "1"}, {"final_amount_due": "2", "base_units": "2"})

    def test_import_exact_utf8_bytes_defaults_and_metadata_on_replay(self):
        c, operation = op("import", {"rows": 3, "unit_price": "1"})
        first = driver.request_spec(c, operation)
        second = driver.request_spec(c, operation)
        self.assertEqual(first, second)
        data = first[2]["files"]["file"][1]
        self.assertIn("صناعي".encode("utf-8"), data)
        self.assertNotIn(b"\\u0635", data)
        self.assertEqual(first[2]["data"]["request_id"], operation.request_id)
        self.assertEqual(first[2]["data"]["default_lot_control_mode"], "NONE")
        self.assertEqual(len(data.decode().splitlines()), 4)

    def test_inbound_preserves_actual_cost_uom_and_stable_batches(self):
        c, operation = op("inbound", {"location_id": 801, "items": [
            {"product_variant_id": 501, "quantity": "2", "uom_id": 901, "unit_cost": "1.250"}]},
                          {"base_units": "2"})
        body = driver.request_spec(c, operation)[2]["json"]
        self.assertEqual(body["items"][0]["unit_cost"], "1.250")
        self.assertEqual(body["items"][0]["uom_id"], 901)
        self.assertTrue(body["reference_id"].startswith("D7S-IN-"))
        self.assertEqual(body, driver.request_spec(c, operation)[2]["json"])

    def test_secret_values_are_excluded_from_config_repr(self):
        c = replace(load(), db_dsn="password=SECRET", environment={"JWT": "SECRET"})
        self.assertNotIn("SECRET", repr(c))


class EvidenceContracts(unittest.TestCase):
    def test_real_retry_after_and_global_limiter_fallback(self):
        self.assertEqual(driver.retry_delay(None), 60)
        self.assertEqual(driver.retry_delay("garbage"), 60)
        self.assertEqual(driver.retry_delay("NaN"), 60)
        self.assertEqual(driver.retry_delay("120"), 120)
        date = format_datetime(datetime.fromtimestamp(1100, timezone.utc))
        self.assertEqual(driver.retry_delay(date, now=1000), 100)

    def test_quantiles_have_no_fake_empty_pass(self):
        self.assertIsNone(driver.percentile([], .95))
        self.assertEqual(driver.distribution([10., 20., 100.])["p95_ms"], 100.)

    def test_virtual_users_and_client_sockets_never_supply_ingress_evidence(self):
        c = load()
        report = driver.ingress_evidence(None, c, driver.utc(), driver.utc())
        self.assertFalse(report["reported_1000_at_ingress"])
        self.assertEqual(report["blocker"], "INGRESS_EVIDENCE_REQUIRED")

    def test_independent_ingress_requires_scope_definition_and_window(self):
        c = load()
        stamp = "2026-09-30T00:00:01+00:00"
        value = {"schema": 1, "run_id": c.run_id, "origin": c.origin,
                 "metric": "active_authenticated_http1_connections",
                 "includes_generator_only": True, "collector_external_to_generator": True,
                 "samples": [{"at": stamp, "active_connections": 1000}]}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evidence.json"
            path.write_text(json.dumps(value))
            report = driver.ingress_evidence(path, c, stamp, stamp)
            self.assertTrue(report["reported_1000_at_ingress"])
            self.assertTrue(report["authenticity_requires_independent_review"])
            value["metric"] = "virtual_users"
            path.write_text(json.dumps(value))
            self.assertFalse(driver.ingress_evidence(path, c, stamp, stamp)["reported_1000_at_ingress"])

    def test_http_ack_identifier_must_match_scoped_sql_outcome(self):
        _, operation = op("import", {"rows": 2, "unit_price": "1"})
        self.assertFalse(driver.ack_matches(operation, {"job_id": "own"}, {"job_id": "other"}))
        self.assertTrue(driver.ack_matches(operation, {"job_id": "own"}, {}))

    def test_import_202_does_not_count_as_committed(self):
        _, operation = op("import", {"rows": 2, "unit_price": "1"})
        row = {"status": "QUEUED", "source_cleared": False}
        self.assertFalse(driver.outcome(operation, row))

    def test_cogs_and_frozen_prices_required_for_sale(self):
        _, operation = sale()
        row = {"durable": True, "status": "Completed", "outcome": "Sale",
               "financial_evidence_version": 4, "lines": 1, "frozen_lines": 1,
               "final_amount_due": "2.000", "movements": 2, "cost_events": 2, "quantity": "2"}
        self.assertTrue(driver.outcome(operation, row))
        # FEFO may split a line; don't equate one sale with one cost event.
        row["cost_events"] = 1
        self.assertFalse(driver.outcome(operation, row))
        row["cost_events"] = 2
        row["frozen_lines"] = 0
        self.assertFalse(driver.outcome(operation, row))

    def test_first_inbound_assignment_requires_exact_audit_outbox_pair(self):
        before = {"id": None, "audits": 0, "outboxes": 0}
        after = {"id": 17, "audits": 1, "outboxes": 1}
        self.assertTrue(driver.assignment_delta_valid(before, after))
        self.assertFalse(driver.assignment_delta_valid(before, {**after, "outboxes": 0}))
        existing = {"id": 17, "audits": 0, "outboxes": 0}
        self.assertTrue(driver.assignment_delta_valid(existing, existing))
        self.assertFalse(driver.assignment_delta_valid(existing, {**existing, "id": 18}))

    def test_route_context_and_physical_transfer_without_cogs(self):
        _, operation = op("route", {"zone_id": 601, "driver_id": 303, "vehicle_id": 701,
                                   "source_location_id": 801, "inventory": {"501": 1}})
        row = {"routes": 1, "contexts": 1, "cost_events": 0, "transferred": "2", "expected_transfer": 2}
        self.assertTrue(driver.outcome(operation, row))
        row["cost_events"] = 1
        self.assertFalse(driver.outcome(operation, row))

    def test_import_requires_row_fidelity_price_audit_outbox(self):
        _, operation = op("import", {"rows": 2, "unit_price": "1"})
        row = {k: 2 for k in ("total_rows", "processed_rows", "rows", "identities", "imported",
                              "variants", "active", "priced", "audited", "outboxed")}
        row.update(status="COMPLETED", source_cleared=True, failed_rows=0, min_row=2, max_row=3,
                   created_to_parsing_ms=10, created_to_terminal_ms=20)
        self.assertTrue(driver.outcome(operation, row))
        row["identities"] = 1
        self.assertFalse(driver.outcome(operation, row))

    def test_journal_exclusive_lease_and_resume_input_guard(self):
        c, operation = sale()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            journal = driver.Journal(path, c)
            journal.append({"event": "intent", "operation": operation.key,
                            "request_id": operation.request_id, "payload_hash": driver.payload_hash(c, operation)})
            with self.assertRaises(config.Blocker):
                driver.Journal(path, c, resume=True)
            journal.close()
            resumed = driver.Journal(path, c, resume=True)
            self.assertEqual(resumed.attempts(operation), 1)
            resumed.close()
            with self.assertRaises(config.Blocker) as error:
                driver.Journal(path, replace(c, fingerprint="changed"), resume=True)
            self.assertEqual(error.exception.code, "RESUME_INPUT_CHANGED")

    def test_torn_intent_requires_review_not_silent_replay(self):
        c = load()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "journal.jsonl"
            path.write_bytes(b'{"event":')
            with self.assertRaises(config.Blocker):
                driver.Journal(path, c, resume=True)


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code = status
        self.headers = {"x-request-id": "30aad1b7-aee1-4db0-81f8-7f1eb18d73b4", **(headers or {})}
        self.body = body or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def aiter_bytes(self):
        yield json.dumps(self.body).encode()


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def stream(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return next(self.responses)


class TransportContracts(unittest.IsolatedAsyncioTestCase):
    async def test_route_429_is_not_reposted(self):
        c, operation = op("route", {"zone_id": 601, "driver_id": 303, "vehicle_id": 701,
                                   "source_location_id": 801, "inventory": {"501": 1}})
        client = FakeClient([FakeResponse(429, headers={"retry-after": "60"})])
        with tempfile.TemporaryDirectory() as directory:
            journal = driver.Journal(Path(directory) / "journal.jsonl", c)
            transport = driver.Transport(c, client, journal, driver.Metrics())
            try:
                await driver.submit(c, transport, operation, 0, time.monotonic(), None)
                self.assertEqual(len(client.calls), 1)
                self.assertEqual(journal.attempts(operation), 1)
                self.assertTrue(transport.stop.is_set())
                self.assertIn("ROUTE_REJECTED_NO_REPLAY", transport.blockers)
            finally:
                journal.close()

    async def test_previous_unknown_route_stops_without_network(self):
        c, operation = op("route", {"zone_id": 601, "driver_id": 303, "vehicle_id": 701,
                                   "source_location_id": 801, "inventory": {"501": 1}})
        client = FakeClient([])
        with tempfile.TemporaryDirectory() as directory:
            journal = driver.Journal(Path(directory) / "journal.jsonl", c)
            journal.append({"event": "intent", "operation": operation.key})
            transport = driver.Transport(c, client, journal, driver.Metrics())
            current = {"tenants": {"A": {"routes": {operation.key: {
                "routes": 0, "contexts": 0, "cost_events": 0, "transferred": 0, "expected_transfer": 1}}}}}
            try:
                await driver.submit(c, transport, operation, 0, time.monotonic(), current)
                self.assertEqual(client.calls, [])
                self.assertTrue(transport.stop.is_set())
            finally:
                journal.close()

    async def test_unknown_transport_stops_new_traffic_preserving_intent(self):
        c, operation = sale()
        client = FakeClient([])  # raises before any ACK; transport outcome is unknown.
        with tempfile.TemporaryDirectory() as directory:
            journal = driver.Journal(Path(directory) / "journal.jsonl", c)
            transport = driver.Transport(c, client, journal, driver.Metrics())
            try:
                await transport.exchange(operation)
                await transport.exchange(operation)
                self.assertEqual(journal.attempts(operation), 1)
                self.assertEqual(len(client.calls), 1)
                self.assertIn("TRANSPORT_UNKNOWN_OUTCOME", transport.blockers)
            finally:
                journal.close()

    async def test_success_headers_with_lost_body_are_not_an_ack(self):
        c, operation = sale()
        class LostBody(FakeResponse):
            async def aiter_bytes(self):
                raise OSError("synthetic disconnect")
                yield b""
        client = FakeClient([LostBody(200)])
        with tempfile.TemporaryDirectory() as directory:
            journal = driver.Journal(Path(directory) / "journal.jsonl", c)
            transport = driver.Transport(c, client, journal, driver.Metrics())
            try:
                await driver.submit(c, transport, operation, 0, time.monotonic(), None)
                self.assertFalse(transport.metrics.results[operation.key]["accepted"])
                self.assertFalse(any(e["event"] == "ack" for e in journal.events))
                self.assertTrue(transport.stop.is_set())
            finally:
                journal.close()

    async def test_retry_after_outlasting_deadline_is_not_shortened(self):
        c = load()
        client = FakeClient([FakeResponse(429, headers={"retry-after": "120"})])
        transport = driver.Transport(c, client, None, driver.Metrics())
        operation = c.operations[0]
        await transport.exchange(operation)
        result = await transport.exchange(operation)
        self.assertIsNone(result)
        self.assertEqual(len(client.calls), 1)
        self.assertIn("RATE_LIMIT_OUTLASTS_BUDGET", transport.blockers)

    async def test_readonly_reconciliation_never_enters_http_transport(self):
        c = load()
        class SavedJournal:
            events = []
            def latest(self, event):
                return {"snapshot": {}}
            def append(self, event):
                self.events.append(event)
        journal = SavedJournal()
        evidence = {"mismatches": []}
        with patch.object(driver.Observer, "snapshot", return_value={}), \
                patch.object(driver, "reconcile", return_value=evidence), \
                patch.object(driver.Transport, "exchange") as exchange:
            report = await driver.collect_reconciliation(c, journal)
        exchange.assert_not_called()
        self.assertEqual(report["business_mutations"], 0)
        self.assertEqual(report["http_requests"], 0)

    async def test_accepted_import_ack_is_separate_from_completion(self):
        c, operation = op("import", {"rows": 2, "unit_price": "1"})
        job = "7c6c3fd2-c459-4080-a41f-e4bbb4f6a20a"
        client = FakeClient([FakeResponse(202, {"job_id": job, "status": "QUEUED"})])
        with tempfile.TemporaryDirectory() as directory:
            journal = driver.Journal(Path(directory) / "journal.jsonl", c)
            metrics = driver.Metrics()
            transport = driver.Transport(c, client, journal, metrics)
            try:
                await driver.submit(c, transport, operation, 0, time.monotonic(), None)
                self.assertTrue(metrics.results[operation.key]["accepted"])
                self.assertTrue(metrics.results[operation.key]["admitted_only"])
                self.assertNotIn("committed", metrics.results[operation.key])
            finally:
                journal.close()


if __name__ == "__main__":
    unittest.main()
