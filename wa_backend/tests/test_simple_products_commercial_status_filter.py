from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects import postgresql

from domains.simple_products.catalog_summary import stopped_product_predicate
from models import ProductVariant


ROOT = Path(__file__).resolve().parents[1]
API_SOURCE = (ROOT / "api" / "simple_products.py").read_text(encoding="utf-8")
SUMMARY_SOURCE = (
    ROOT / "domains" / "simple_products" / "catalog_summary.py"
).read_text(encoding="utf-8")


def test_stopped_filter_shares_the_catalog_summary_predicate():
    sql = str(
        select(ProductVariant.id)
        .where(stopped_product_predicate())
        .compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "product_variants.lifecycle_status != 'ARCHIVED'" in sql
    assert "product_variants.lifecycle_status != 'ACTIVE'" in sql
    assert "product_variants.operational_hold != 'NONE'" in sql
    assert "stopped_predicate = stopped_product_predicate()" in SUMMARY_SOURCE


def test_simple_products_exposes_bounded_stopped_commercial_filter_with_cursor_scope():
    assert 'commercial_status: str | None = None' in API_SOURCE
    assert '_PRODUCT_COMMERCIAL_STATUSES = {"STOPPED"}' in API_SOURCE
    assert 'field="commercial_status"' in API_SOURCE
    assert 'if commercial_status_value == "STOPPED":' in API_SOURCE
    assert 'stmt = stmt.where(stopped_product_predicate())' in API_SOURCE
    assert '"commercial_status": commercial_status' in API_SOURCE
    assert API_SOURCE.count("commercial_status=commercial_status") >= 2
