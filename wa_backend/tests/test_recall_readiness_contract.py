import ast
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from domains.authorization.backoffice_access import BackofficeCapabilityAccess
from domains.authorization.backoffice_subject import BackofficeAuthorizationSubject
from models import ProductVariant


class FakeSession:
    def __init__(self, row):
        self.row = row

    async def scalar(self, statement):
        # This contract isolates completion evidence; the optional inventory
        # summary has no grant in this fixture and remains absent.
        entity = statement.column_descriptions[0].get("entity")
        return self.row if entity is ProductVariant else False


def access(db):
    return BackofficeCapabilityAccess(
        db, BackofficeAuthorizationSubject(101, 202, 1, False, 303),
    )


async def allow(*_args, **_kwargs):
    return None


def endpoint(blockers):
    path = Path(__file__).parents[1] / "api/catalog.py"
    node = next(
        n for n in ast.parse(path.read_text(encoding="utf-8")).body
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "variant_recall_readiness"
    )
    node.decorator_list = []
    node.args.defaults = []
    for arg in node.args.args:
        arg.annotation = None

    async def read_blockers(_db, _company_id, _variant_id):
        return blockers

    namespace = {
        "_require": allow,
        "select": select,
        "ProductVariant": ProductVariant,
        "recall_completion_blockers": read_blockers,
        "_error": lambda *args, **kwargs: RuntimeError(args),
    }
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(path), "exec"), namespace)
    return namespace["variant_recall_readiness"]


@pytest.mark.asyncio
async def test_recall_readiness_uses_backend_completion_evidence():
    row = SimpleNamespace(version=7, operational_hold="RECALL")
    db = FakeSession(row)
    blocked = await endpoint([
        {"code": "INVENTORY_BALANCE", "count": 2, "sample_id": 4}
    ])(101, db, access(db))
    assert blocked["ready_to_resume_sales"] is False
    assert blocked["blockers"][0]["code"] == "INVENTORY_BALANCE"

    ready = await endpoint([])(101, db, access(db))
    assert ready["ready_to_resume_sales"] is True
    assert ready["blockers"] == []


@pytest.mark.asyncio
async def test_recall_readiness_never_claims_ready_without_active_hold():
    row = SimpleNamespace(version=8, operational_hold="NONE")
    db = FakeSession(row)
    result = await endpoint([])(101, db, access(db))
    assert result["ready_to_resume_sales"] is False
    assert result["blockers"] == []
