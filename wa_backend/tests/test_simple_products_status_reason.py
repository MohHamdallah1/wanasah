from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from domains.simple_products.status_reason import load_current_product_status_reasons


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Db:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Rows(self.rows)


def _variant(variant_id, revision, hold="SALES_HOLD"):
    return SimpleNamespace(
        id=variant_id,
        lifecycle_revision=revision,
        operational_hold=hold,
    )


@pytest.mark.asyncio
async def test_current_status_reasons_are_loaded_in_one_bounded_read():
    db = _Db([
        ("101", "مراجعة التسعير", 9),
        ("101", "سبب أقدم", 8),
        ("102", None, 7),
    ])
    result = await load_current_product_status_reasons(
        db,
        company_id=1,
        variants=[_variant(101, 4), _variant(102, 6)],
    )
    assert result == {101: "مراجعة التسعير", 102: None}
    assert len(db.statements) == 1

    sql = str(
        db.statements[0].compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "domain_audit_events.company_id = 1" in sql
    assert "domain_audit_events.entity_type = 'ProductVariant'" in sql
    assert "lifecycle_revision" in sql
    assert "ProductSalesHoldPlaced" in sql
    assert "ProductRecallIssued" in sql
    assert "FOR UPDATE" not in sql


@pytest.mark.asyncio
async def test_status_reason_scope_is_empty_safe_and_page_bounded():
    db = _Db([])
    assert await load_current_product_status_reasons(
        db,
        company_id=1,
        variants=[],
    ) == {}
    assert db.statements == []

    with pytest.raises(ValueError):
        await load_current_product_status_reasons(
            db,
            company_id=1,
            variants=[_variant(index, 1) for index in range(1, 202)],
        )
    assert db.statements == []
