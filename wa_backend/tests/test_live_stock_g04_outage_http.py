from __future__ import annotations

import asyncio
import json
import os
import subprocess

import httpx
import pytest

from tests.live_stock_g04_outage_support import (
    fingerprint,
    restore_reader_warehouse,
    revoke_reader_warehouse,
)


API = os.environ.get("WANASAH_G04_API", "http://127.0.0.1:4174")
CONTAINER = os.environ.get("WANASAH_G04_DB_CONTAINER", "live-stock-g04-pg")
STATE_PATH = os.environ["WANASAH_OPERATIONAL_BROWSER_STATE"]


def _state() -> dict:
    with open(STATE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _docker(*args: str) -> None:
    subprocess.run(["docker", *args], check=True, capture_output=True, text=True)


def _stop_db() -> None:
    _docker("stop", "-t", "1", CONTAINER)


def _start_db() -> None:
    _docker("start", CONTAINER)
    for _ in range(50):
        probe = subprocess.run(
            ["docker", "exec", CONTAINER, "pg_isready", "-U", "g04_admin",
             "-d", "wanasah_no_lot_contract_test", "-p", "55439"],
            capture_output=True,
            text=True,
        )
        if probe.returncode == 0:
            return
        import time
        time.sleep(0.2)
    raise AssertionError("PostgreSQL16 did not recover")


async def _login(client: httpx.AsyncClient, actor: str, state: dict) -> str:
    response = await client.post("/login", json={
        "company_code": state["credentials"][actor]["code"],
        "username": state["credentials"][actor]["username"],
        "password": state["credentials"][actor]["password"],
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["channel"] == "DASHBOARD"
    assert payload["principal_type"] == "BACKOFFICE"
    return payload["token"]


async def _get(client: httpx.AsyncClient, token: str, path: str) -> httpx.Response:
    return await client.get(path, headers={"Authorization": f"Bearer {token}"})


def _main_row(response: httpx.Response, variant_id: int) -> dict:
    assert response.status_code == 200, response.text
    return next(row for row in response.json()["items"] if int(row["id"]) == variant_id)


def _assert_outage_response(response: httpx.Response, state: dict) -> None:
    assert 500 <= response.status_code <= 599, (response.status_code, response.text)
    payload = response.json()
    rendered = json.dumps(payload, sort_keys=True)
    assert state["mainName"] not in rendered
    assert state["expected"]["value"] not in rendered
    assert "items" not in payload
    request_id = response.headers.get("x-request-id") or payload.get("request_id")
    assert isinstance(request_id, str) and request_id and request_id != "N/A"


async def _wait_ready(client: httpx.AsyncClient) -> None:
    for _ in range(60):
        try:
            response = await client.get("/ready")
            if response.status_code == 200:
                return
        except httpx.HTTPError:
            pass
        await asyncio.sleep(0.25)
    raise AssertionError("FastAPI did not regain fresh database readiness")


@pytest.mark.asyncio
async def test_g04_real_pg16_outage_revocation_and_recovery_fail_closed():
    assert os.environ.get("WANASAH_G04_GATE") == "1"
    state = _state()
    before = fingerprint()
    revoked = False

    async with httpx.AsyncClient(base_url=API, timeout=12.0) as client:
        owner_token = await _login(client, "owner", state)
        reader_token = await _login(client, "reader", state)

        owner = _main_row(
            await _get(
                client,
                owner_token,
                f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
            ),
            state["mainId"],
        )
        reader = _main_row(
            await _get(
                client,
                reader_token,
                f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
            ),
            state["mainId"],
        )
        assert owner["total_quantity"] == reader["total_quantity"] == "968"
        assert owner["total_quantity_scope"] == reader["total_quantity_scope"] == "WAREHOUSE_PHYSICAL"
        assert owner["vehicle_quantity"] == reader["vehicle_quantity"] == "32"
        assert owner["vehicle_quantity_scope"] == "COMPANY_WIDE"
        assert reader["vehicle_quantity_scope"] == "AUTHORIZED_LOCATIONS"

        batch_path = (
            f"/warehouse/inventory/{state['mainId']}/batches"
            f"?location_id={state['warehouse']}"
        )
        source_path = (
            f"/warehouse/inventory/{state['mainId']}/batches/{state['firstBatch']}/source"
            f"?location_id={state['warehouse']}"
        )
        baseline_batch = await _get(client, reader_token, batch_path)
        baseline_source = await _get(client, reader_token, source_path)
        assert baseline_batch.status_code == baseline_source.status_code == 200

        try:
            _stop_db()
            health = await client.get("/health")
            assert health.status_code == 200 and health.json() == {"status": "alive"}

            ready = await client.get("/ready")
            assert ready.status_code == 503
            for path in (
                f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
                f"/warehouse/inventory/summary?location_id={state['warehouse']}",
                batch_path,
                source_path,
            ):
                _assert_outage_response(await _get(client, reader_token, path), state)
        finally:
            _start_db()
        await _wait_ready(client)

        recovered = _main_row(
            await _get(
                client,
                reader_token,
                f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
            ),
            state["mainId"],
        )
        assert recovered == reader

        revoke_reader_warehouse()
        revoked = True
        for path in (
            f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
            batch_path,
            source_path,
        ):
            denied = await _get(client, reader_token, path)
            assert denied.status_code == 403, denied.text
            rendered = denied.text
            assert state["mainName"] not in rendered
            assert state["expected"]["value"] not in rendered

        try:
            _stop_db()
            denied_during_outage = await _get(
                client,
                reader_token,
                f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
            )
            _assert_outage_response(denied_during_outage, state)
        finally:
            _start_db()
        await _wait_ready(client)

        for path in (
            f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
            batch_path,
            source_path,
        ):
            denied_after_restore = await _get(client, reader_token, path)
            assert denied_after_restore.status_code == 403, denied_after_restore.text

        owner_after = _main_row(
            await _get(
                client,
                owner_token,
                f"/warehouse/inventory/cursor?location_id={state['warehouse']}&search=OP-MULTI",
            ),
            state["mainId"],
        )
        assert owner_after == owner

    if revoked:
        restore_reader_warehouse()
    after = fingerprint()
    assert after == before
    print("G04_REAL_PG16_OUTAGE PASS stock_cost_idempotency_unchanged=1")
