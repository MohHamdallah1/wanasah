"""Focused read-only summary contracts; compile statements, never connect to a DB."""
import ast
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError
from sqlalchemy.dialects import postgresql

from domains.simple_products.catalog_summary import CatalogSummaryResponse, load_catalog_summary


COUNTS = dict(total=1234, families=82, available=1000, retiring=120, archived=100, sales_restricted=14)


@pytest.mark.asyncio
async def test_one_tenant_aggregate_without_pagination_or_mutations():
    result = MagicMock()
    result.mappings.return_value.one.return_value = COUNTS
    db = SimpleNamespace(execute=AsyncMock(return_value=result))
    summary = await load_catalog_summary(db, company_id=38)
    assert summary.model_dump() == dict(schema_version=1, company_id=38, **COUNTS)
    db.execute.assert_awaited_once()
    statement = db.execute.call_args.args[0]
    sql = str(statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))
    assert "WHERE product_variants.company_id = 38" in sql
    assert "FROM products" in sql and "products.company_id = 38" in sql
    assert "FILTER (WHERE product_variants.lifecycle_status = 'ACTIVE' AND product_variants.operational_hold = 'NONE')" in sql
    assert "FILTER (WHERE product_variants.lifecycle_status = 'RETIRING')" in sql
    assert "FILTER (WHERE product_variants.lifecycle_status = 'ARCHIVED')" in sql
    assert "FILTER (WHERE product_variants.operational_hold IN ('SALES_HOLD', 'RECALL'))" in sql
    assert sql.count("count(*)") == 6
    assert all(word not in sql for word in ("JOIN", "LIMIT", "OFFSET", "UPDATE", "INSERT", "FOR UPDATE"))


@pytest.mark.asyncio
async def test_empty_catalog_preserves_zero_counts():
    row_result = MagicMock()
    row_result.mappings.return_value.one.return_value = {key: 0 for key in COUNTS}
    db = SimpleNamespace(execute=AsyncMock(return_value=row_result))
    result = await load_catalog_summary(db, company_id=38)
    assert result.total == result.available == result.sales_restricted == 0


@pytest.mark.parametrize("invalid", [dict(total=-1), dict(available="5"), dict(retiring=None), dict(schema_version=2)])
def test_summary_contract_rejects_invalid_counts(invalid):
    with pytest.raises(ValidationError):
        CatalogSummaryResponse(company_id=38, **(dict(COUNTS, **invalid)))


def route_under_test():
    """Execute the actual route body without initializing the application/database."""
    source = Path(__file__).resolve().parents[1] / "api" / "simple_products.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "catalog_summary")
    decorator = function.decorator_list[0]
    assert decorator.func.attr == "get" and decorator.args[0].value == "/summary"
    assert next(item.value.id for item in decorator.keywords if item.arg == "response_model") == "CatalogSummaryResponse"
    function.decorator_list = []
    namespace = {"Depends": lambda dependency: dependency, "get_db": object(), "get_current_driver": object(),
                 "AsyncSession": object, "Driver": object,
                 "_require": AsyncMock(), "load_catalog_summary": AsyncMock()}
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    return namespace


@pytest.mark.asyncio
async def test_route_uses_existing_catalog_permission_before_actor_scoped_read():
    route = route_under_test()
    db, actor = object(), SimpleNamespace(company_id=38)
    async def authorized_read(session, *, company_id):
        route["_require"].assert_awaited_once_with(db, actor, "catalog.read")
        assert session is db and company_id == 38
        return "summary"
    route["load_catalog_summary"].side_effect = authorized_read
    assert await route["catalog_summary"](db=db, actor=actor) == "summary"


@pytest.mark.asyncio
async def test_permission_denial_never_runs_summary_query():
    route = route_under_test()
    route["_require"].side_effect = PermissionError("denied")
    with pytest.raises(PermissionError):
        await route["catalog_summary"](db=object(), actor=SimpleNamespace(company_id=38))
    route["load_catalog_summary"].assert_not_awaited()
