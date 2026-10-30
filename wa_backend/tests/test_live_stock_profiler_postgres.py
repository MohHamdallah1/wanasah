"""Focused PostgreSQL acceptance for the N1 Live Stock profiler repair."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from sqlalchemy import text

from scripts import profile_live_stock_explain as profiler
from tests.test_cp7_live_stock_postgres import _prepare_cp7
from tests.test_inbound_no_lot_frozen_postgres import pg  # noqa: F401


pytestmark = pytest.mark.asyncio(loop_scope="function")


def _plan_has_buffer_metrics(node: dict) -> bool:
    if any(
        key in node
        for key in (
            "Shared Hit Blocks",
            "Shared Read Blocks",
            "Temp Read Blocks",
            "Temp Written Blocks",
        )
    ):
        return True
    return any(_plan_has_buffer_metrics(child) for child in node.get("Plans", []) or [])


async def test_n1_profiler_uses_real_scoped_backoffice_and_explain(pg):
    case = await _prepare_cp7(pg)
    tenant = case.a
    foreign = case.b

    source = Path(profiler.__file__).read_text(encoding="utf-8")
    assert "current_admin=" not in source
    assert "from models import Driver" not in source
    assert "--driver-id" not in source
    assert "--backoffice-user-id" in source

    async with pg.session() as db:
        runtime_identity = (
            await db.execute(
                text(
                    "SELECT current_user, r.rolsuper, r.rolbypassrls "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                )
            )
        ).one()
        assert tuple(runtime_identity) == ("wanasah_app", False, False)

        access, context = await profiler.load_backoffice_access(
            db,
            company_id=tenant.company_id,
            backoffice_user_id=tenant.ordinary.context.backoffice_user_id,
            location_id=tenant.location_id,
        )
        assert context.company_id == tenant.company_id
        assert context.backoffice_user_id == tenant.ordinary.context.backoffice_user_id
        assert context.principal_id == tenant.ordinary.context.principal_id
        assert context.is_company_owner is False
        assert access.company_id == tenant.company_id

        with pytest.raises(RuntimeError, match="lacks inventory.read"):
            await profiler.load_backoffice_access(
                db,
                company_id=tenant.company_id,
                backoffice_user_id=tenant.ordinary.context.backoffice_user_id,
                location_id=tenant.other_location_id,
            )

        with pytest.raises(RuntimeError, match="identity not found"):
            await profiler.load_backoffice_access(
                db,
                company_id=tenant.company_id,
                backoffice_user_id=foreign.ordinary.context.backoffice_user_id,
                location_id=tenant.location_id,
            )

        evidence = {
            "method": pg.method,
            "company_id": tenant.company_id,
            "backoffice_user_id": context.backoffice_user_id,
            "principal_id": context.principal_id,
            "warehouse_id": tenant.location_id,
            "runtime_role": runtime_identity[0],
            "scenarios": {},
        }
        for scenario in ("live", "alerts", "summary", "only-alerts", "search"):
            result = await profiler.profile_scenario(
                db=db,
                capture_engine=pg.runtime_engine,
                access=access,
                scenario=scenario,
                location_id=tenant.location_id,
                limit=50,
                search="No-lot",
                cursor_page=1,
                top=3,
            )
            assert result["endpoint_ms"] >= 0
            assert result["sql_statement_count"] > 0
            assert result["captured_sql"]
            assert all(item["statement"] for item in result["captured_sql"])
            assert result["explanations"]
            assert all("plan_error" not in item for item in result["explanations"])
            for item in result["explanations"]:
                assert item["execution_time_ms"] >= 0
                assert item["planning_time_ms"] >= 0
                assert item["plan"]["Plan"]
                assert _plan_has_buffer_metrics(item["plan"]["Plan"])

            evidence["scenarios"][scenario] = {
                "endpoint_ms": round(float(result["endpoint_ms"]), 3),
                "sql_statement_count": result["sql_statement_count"],
                "payload_items": result["payload_items"],
                "explain": [
                    {
                        "rank": item["rank"],
                        "original_duration_ms": round(
                            float(item["original_duration_ms"]), 3
                        ),
                        "planning_time_ms": round(
                            float(item["planning_time_ms"]), 3
                        ),
                        "execution_time_ms": round(
                            float(item["execution_time_ms"]), 3
                        ),
                        "statement": item["statement"],
                    }
                    for item in result["explanations"]
                ],
            }

    evidence_dir = os.getenv("N1_PROFILER_EVIDENCE_DIR")
    if evidence_dir:
        path = Path(evidence_dir)
        path.mkdir(parents=True, exist_ok=True)
        (path / f"n1-profiler-{pg.method.lower()}.json").write_text(
            json.dumps(evidence, indent=2, default=str),
            encoding="utf-8",
        )
    print("N1_PROFILER_EVIDENCE " + json.dumps(evidence, default=str, sort_keys=True))
